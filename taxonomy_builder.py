"""
LLM-based iterative taxonomy builder (multi-threaded, multi-provider).

Algorithm:
  1. Start with root node containing all papers.
  2. For each non-leaf node, ask the LLM to propose child topics.
     - If total input length > TOKEN_THRESHOLD, send only titles.
     - Otherwise, send titles + abstracts.
     - LLM may return "CANNOT_SPLIT" if the node is already fine-grained.
  3. Ask the LLM to classify each paper into exactly one child topic.
  4. Recurse until MAX_DEPTH is reached or all leaves say CANNOT_SPLIT.

Parallelism:
  - After a node's children are created and papers classified, all sibling
    children are expanded in parallel using ThreadPoolExecutor.
  - The subdivision + classification of a single node is sequential (2 LLM
    calls), but sibling nodes at the same depth run concurrently.
  - Thread-safety: each node expansion only reads/writes its own subtree,
    so no locking is needed.

Multi-LLM support:
  - OpenAI (GPT-4o, GPT-4-turbo, etc.)
  - Google (Gemini 2.5 Pro / Flash, etc.)
  - Anthropic (Claude Sonnet 4, Opus 4, etc.)
  - xAI (Grok-3, Grok-3-mini, etc.)
  Provider is selected via config.LLM_PROVIDER (default: "openai").
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import config
from models import Paper, TaxonomyNode
from token_tracker import get_global_tracker

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Prompt templates
# ────────────────────────────────────────────────────────────────────

SUBDIVISION_SYSTEM_PROMPT = """\
You are an expert conference program chair organizing an academic conference.
Your task is to propose topically coherent sub-categories for a given set of
research papers. Each sub-category should be specific enough to form a
meaningful conference session, but broad enough to contain multiple papers.
"""

SUBDIVISION_USER_PROMPT = """\
I have a set of papers under the topic: "{node_name}"
Description: {node_description}

Here are the papers:
{papers_text}

Based on these papers, propose sub-categories that partition them into
coherent topical groups. Each sub-category should:
- Have a clear, concise name suitable as a conference session title
- Have a brief description (1-2 sentences)
- Be distinct from other sub-categories
- Cover at least {min_papers} papers

If the papers are already homogeneous enough that further subdivision would
be artificial (i.e., they naturally form a single coherent session), respond
with exactly: {{"status": "CANNOT_SPLIT"}}

Otherwise, respond with a JSON object:
{{
  "status": "OK",
  "categories": [
    {{
      "name": "Category Name",
      "description": "Brief description of what this category covers"
    }},
    ...
  ]
}}

Important:
- Propose at most {max_children} categories.
- Every paper should fit into exactly one category.
- Respond ONLY with the JSON object, no other text.
"""

CLASSIFICATION_SYSTEM_PROMPT = """\
You are an expert at categorizing academic papers into topical categories.
You must assign each paper to exactly one category based on its content.
"""

CLASSIFICATION_USER_PROMPT = """\
Classify each of the following papers into exactly one of the given categories.

Categories:
{categories_text}

Papers:
{papers_text}

Respond with a JSON object mapping paper IDs to category names:
{{
  "paper_id_1": "Category Name",
  "paper_id_2": "Category Name",
  ...
}}

Rules:
- Every paper must be assigned to exactly one category.
- Use the exact category names as provided above.
- If a paper fits multiple categories, choose the best fit.
- Respond ONLY with the JSON object, no other text.
"""


# ────────────────────────────────────────────────────────────────────
# Multi-provider LLM Client
# ────────────────────────────────────────────────────────────────────

class LLMClient:
    """Unified wrapper around OpenAI, Google Gemini, Anthropic Claude, and xAI Grok.

    Provider selection is based on config.LLM_PROVIDER:
      - "openai"    → uses the openai SDK
      - "google"    → uses the google-genai SDK
      - "anthropic" → uses the anthropic SDK
      - "xai"       → uses the openai SDK with xAI base URL

    All providers are accessed through a common `.chat(system, user)` interface
    and token usage is automatically tracked via the global TokenTracker.
    """

    def __init__(self, provider: str = None, model: str = None,
                 temperature: float = None, json_mode: bool = True):
        self.provider = (provider or getattr(config, "LLM_PROVIDER", "openai")).lower()
        self.model = model or config.LLM_MODEL
        self.temperature = temperature if temperature is not None else config.LLM_TEMPERATURE
        self.json_mode = json_mode
        self.tracker = get_global_tracker()

        self._init_client()

    def _init_client(self):
        """Initialize the appropriate SDK client."""
        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "google":
            self._init_google()
        elif self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "xai":
            self._init_xai()
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider!r}. "
                             f"Supported: openai, google, anthropic, xai")

    def _init_openai(self):
        """Initialize OpenAI client (uses OPENAI_API_KEY env var)."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required for OpenAI provider. "
                              "Install with: pip install openai")
        self.client = OpenAI()

    def _init_google(self):
        """Initialize Google Gemini client (uses GOOGLE_API_KEY env var)."""
        try:
            from google import genai
        except ImportError:
            raise ImportError("google-genai package required for Google provider. "
                              "Install with: pip install google-genai")
        import os
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable required")
        self.client = genai.Client(api_key=api_key)

    def _init_anthropic(self):
        """Initialize Anthropic Claude client (uses ANTHROPIC_API_KEY env var)."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required for Anthropic provider. "
                              "Install with: pip install anthropic")
        self.client = anthropic.Anthropic()

    def _init_xai(self):
        """Initialize xAI Grok client (OpenAI-compatible, uses XAI_API_KEY env var)."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required for xAI provider. "
                              "Install with: pip install openai")
        import os
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable required")
        self.client = OpenAI(api_key=api_key,
                             base_url="https://api.x.ai/v1")

    # ── Unified chat interface ─────────────────────────────────────

    def chat(self, system: str, user: str, call_label: str = "") -> str:
        """Send a chat completion request and return the text response.

        Automatically dispatches to the correct provider and records
        token usage in the global tracker.
        """
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                if self.provider == "openai" or self.provider == "xai":
                    return self._chat_openai(system, user, call_label)
                elif self.provider == "google":
                    return self._chat_google(system, user, call_label)
                elif self.provider == "anthropic":
                    return self._chat_anthropic(system, user, call_label)
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}/{config.LLM_MAX_RETRIES}): {e}")
                if attempt == config.LLM_MAX_RETRIES - 1:
                    raise
        return ""

    def _chat_openai(self, system: str, user: str, call_label: str) -> str:
        """OpenAI / xAI (OpenAI-compatible) chat completion."""
        kwargs = dict(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content.strip()

        # Track tokens
        usage = resp.usage
        if usage:
            self.tracker.record(
                provider=self.provider,
                model=self.model,
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                call_label=call_label,
            )

        return text

    def _chat_google(self, system: str, user: str, call_label: str) -> str:
        """Google Gemini chat completion via google-genai SDK."""
        from google.genai import types

        combined_prompt = f"{system}\n\n{user}"
        gen_config = types.GenerateContentConfig(
            temperature=self.temperature,
        )
        if self.json_mode:
            gen_config.response_mime_type = "application/json"
        response = self.client.models.generate_content(
            model=self.model,
            contents=combined_prompt,
            config=gen_config,
        )
        text = response.text.strip()

        # Track tokens from usage metadata
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.tracker.record(
                provider="google",
                model=self.model,
                prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                call_label=call_label,
            )

        return text

    def _chat_anthropic(self, system: str, user: str, call_label: str) -> str:
        """Anthropic Claude chat completion."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
        )

        # Extract text from Claude's content blocks
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()

        # Claude may wrap JSON in markdown code blocks — strip them
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines if they're code fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Track tokens
        usage = resp.usage
        if usage:
            self.tracker.record(
                provider="anthropic",
                model=self.model,
                prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
                completion_tokens=getattr(usage, "output_tokens", 0) or 0,
                call_label=call_label,
            )

        return text


# ────────────────────────────────────────────────────────────────────
# Taxonomy Builder
# ────────────────────────────────────────────────────────────────────

class TaxonomyBuilder:
    """Builds a topic taxonomy iteratively using LLM subdivision + classification.

    Parallelism: after a node is subdivided and papers are classified into
    children, all children at the same level are expanded concurrently via
    ThreadPoolExecutor. Each child expansion (subdivide + classify) involves
    sequential LLM calls, but sibling expansions run in parallel threads.
    """

    def __init__(self, papers: list[Paper], llm: Optional[LLMClient] = None,
                 max_workers: int = None):
        self.papers = {p.id: p for p in papers}
        self.llm = llm or LLMClient()
        self.max_workers = max_workers or config.LLM_MAX_WORKERS
        self._node_counter = 0

    # ── Public API ──────────────────────────────────────────────────

    def build(self) -> TaxonomyNode:
        """Build the full taxonomy and return the root node."""
        root = TaxonomyNode(
            node_id="0",
            name="All Papers",
            description="Root node containing all accepted papers",
            paper_ids=list(self.papers.keys()),
            depth=0,
        )
        logger.info(f"Starting taxonomy construction with {len(self.papers)} papers, "
                     f"max_depth={config.MAX_DEPTH}, max_workers={self.max_workers}")
        self._expand_node(root)
        return root

    # ── Core recursion ──────────────────────────────────────────────

    def _expand_node(self, node: TaxonomyNode):
        """Recursively expand a taxonomy node."""
        # Stop conditions
        if node.depth >= config.MAX_DEPTH:
            logger.info(f"  Node '{node.name}' hit max depth {config.MAX_DEPTH} → leaf")
            node.is_leaf = True
            return

        if len(node.paper_ids) < config.MIN_PAPERS_TO_SPLIT:
            logger.info(f"  Node '{node.name}' has only {len(node.paper_ids)} papers → leaf")
            node.is_leaf = True
            return

        # Step 1: Ask LLM to propose child categories
        children_spec = self._subdivide(node)
        if children_spec is None:
            logger.info(f"  Node '{node.name}' cannot be further split → leaf")
            node.is_leaf = True
            return

        # Step 2: Ask LLM to classify papers into children
        assignment = self._classify(node, children_spec)

        # Step 3: Create child nodes and assign papers
        node.is_leaf = False
        node.children = []

        for idx, cat in enumerate(children_spec):
            child_id = f"{node.node_id}.{idx}"
            child_paper_ids = [pid for pid, cname in assignment.items()
                               if cname == cat["name"]]

            # Handle papers that weren't assigned (fallback: keep in parent)
            child_node = TaxonomyNode(
                node_id=child_id,
                name=cat["name"],
                description=cat.get("description", ""),
                parent_id=node.node_id,
                paper_ids=child_paper_ids,
                depth=node.depth + 1,
            )
            node.children.append(child_node)
            logger.info(f"  Created child '{cat['name']}' with {len(child_paper_ids)} papers "
                        f"(depth={child_node.depth})")

        # Handle unassigned papers → put them in the best-matching child
        assigned_ids = set(assignment.keys())
        unassigned = [pid for pid in node.paper_ids if pid not in assigned_ids]
        if unassigned:
            logger.warning(f"  {len(unassigned)} papers unassigned at node '{node.name}', "
                           f"placing in largest child")
            largest_child = max(node.children, key=lambda c: len(c.paper_ids))
            largest_child.paper_ids.extend(unassigned)

        # Clear papers from the parent (they now live in children)
        node.paper_ids = []

        # Step 4: Expand children in parallel using ThreadPoolExecutor
        # Each child's subtree is independent, so no locking is needed.
        # The subdivision + classification LLM calls within a single child
        # are sequential, but sibling children run concurrently.
        if len(node.children) == 1 or self.max_workers <= 1:
            # Single child or single-threaded mode: expand sequentially
            for child in node.children:
                self._expand_node(child)
        else:
            with ThreadPoolExecutor(max_workers=min(self.max_workers,
                                                     len(node.children))) as executor:
                futures = {
                    executor.submit(self._expand_node, child): child
                    for child in node.children
                }
                for future in as_completed(futures):
                    child = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"  Error expanding child '{child.name}': {e}")
                        child.is_leaf = True

    # ── LLM: Subdivision ───────────────────────────────────────────

    def _subdivide(self, node: TaxonomyNode) -> Optional[list[dict]]:
        """Ask LLM to propose child categories for this node."""
        papers_text = self._format_papers(node.paper_ids, for_subdivision=True)

        prompt = SUBDIVISION_USER_PROMPT.format(
            node_name=node.name,
            node_description=node.description,
            papers_text=papers_text,
            min_papers=config.MIN_PAPERS_TO_SPLIT,
            max_children=config.MAX_CHILDREN,
        )

        raw = self.llm.chat(SUBDIVISION_SYSTEM_PROMPT, prompt,
                            call_label=f"subdivide:{node.name}")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"  Failed to parse subdivision response for '{node.name}'")
            return None

        if result.get("status") == "CANNOT_SPLIT":
            return None

        categories = result.get("categories", [])
        if len(categories) < 2:
            return None  # Need at least 2 children to subdivide

        return categories

    # ── LLM: Classification ────────────────────────────────────────

    def _classify(self, node: TaxonomyNode, categories: list[dict]) -> dict[str, str]:
        """Ask LLM to assign each paper in this node to one of the child categories."""
        # Build categories text
        categories_text = "\n".join(
            f"- {cat['name']}: {cat.get('description', '')}"
            for cat in categories
        )

        # Build papers text — for classification always include abstract if available
        papers_text = self._format_papers(node.paper_ids, for_subdivision=False)

        prompt = CLASSIFICATION_USER_PROMPT.format(
            categories_text=categories_text,
            papers_text=papers_text,
        )

        raw = self.llm.chat(CLASSIFICATION_SYSTEM_PROMPT, prompt,
                            call_label=f"classify:{node.name}")
        try:
            assignment = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"  Failed to parse classification for '{node.name}'")
            # Fallback: assign all to first category
            return {pid: categories[0]["name"] for pid in node.paper_ids}

        # Validate: ensure assigned category names are valid
        valid_names = {cat["name"] for cat in categories}
        valid_pids = set(node.paper_ids)
        cleaned = {}
        for raw_pid, cname in assignment.items():
            # The LLM may return IDs with brackets (e.g. "[63]" instead of "63")
            # because the prompt formats papers as "[63] Title".  Strip them.
            pid = raw_pid.strip().strip("[]").strip()
            if pid not in valid_pids:
                logger.warning(f"  LLM returned unknown paper ID '{raw_pid}' "
                               f"(cleaned: '{pid}'), skipping")
                continue

            if cname in valid_names:
                cleaned[pid] = cname
            else:
                # Fuzzy match: pick the closest valid name
                best = min(valid_names, key=lambda v: _edit_distance(v.lower(), cname.lower()))
                logger.warning(f"  Paper {pid} assigned to unknown category '{cname}', "
                               f"remapped to '{best}'")
                cleaned[pid] = best

        return cleaned

    # ── Formatting helpers ─────────────────────────────────────────

    def _format_papers(self, paper_ids: list[str], for_subdivision: bool) -> str:
        """Format papers for LLM input, respecting the token threshold."""
        papers = [self.papers[pid] for pid in paper_ids if pid in self.papers]

        if for_subdivision:
            # Check if titles+abstracts would exceed the token budget
            full_text = "\n".join(
                f"[{p.id}] {p.title}\n  Abstract: {p.abstract}"
                for p in papers
            )
            est_tokens = len(full_text) / config.TOKEN_EST_CHARS_PER_TOKEN

            if est_tokens > config.TOKEN_THRESHOLD:
                logger.info(f"  Input too long ({est_tokens:.0f} est. tokens), "
                            f"using titles only for subdivision")
                return "\n".join(f"[{p.id}] {p.title}" for p in papers)
            else:
                return full_text
        else:
            # For classification, include abstract for better accuracy
            # but still respect a reasonable limit
            full_text = "\n".join(
                f"[{p.id}] {p.title}\n  Abstract: {p.abstract}"
                for p in papers
            )
            est_tokens = len(full_text) / config.TOKEN_EST_CHARS_PER_TOKEN

            if est_tokens > config.TOKEN_THRESHOLD:
                return "\n".join(f"[{p.id}] {p.title}" for p in papers)
            return full_text


def _edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance for fuzzy matching."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


# ────────────────────────────────────────────────────────────────────
# Utility: collect all leaf nodes
# ────────────────────────────────────────────────────────────────────

def collect_leaves(node: TaxonomyNode) -> list[TaxonomyNode]:
    """Collect all leaf nodes of the taxonomy."""
    if node.is_leaf:
        return [node]
    leaves = []
    for child in node.children:
        leaves.extend(collect_leaves(child))
    return leaves


def print_taxonomy(node: TaxonomyNode, indent: int = 0):
    """Pretty-print the taxonomy tree to stdout."""
    prefix = "  " * indent
    marker = "📄" if node.is_leaf else "📁"
    print(f"{prefix}{marker} [{node.node_id}] {node.name} "
          f"({len(node.paper_ids)} papers)")
    if node.description and indent > 0:
        print(f"{prefix}   ↳ {node.description}")
    for child in node.children:
        print_taxonomy(child, indent + 1)


# ────────────────────────────────────────────────────────────────────
# Human-readable rendering (tree / markdown / indent)
# ────────────────────────────────────────────────────────────────────

def _count_papers(node: TaxonomyNode) -> int:
    """Recursively count all papers under a node."""
    if node.is_leaf:
        return len(node.paper_ids)
    total = len(node.paper_ids)  # papers directly on this node
    for child in node.children:
        total += _count_papers(child)
    return total


def _render_tree(node: TaxonomyNode, papers_map: dict = None,
                 prefix: str = "", is_last: bool = True, is_root: bool = False,
                 show_papers: bool = True) -> list[str]:
    """Render the taxonomy as an ASCII tree (like the `tree` command).

    Args:
        node: current taxonomy node
        papers_map: {paper_id: Paper} to resolve titles; if None, shows IDs only
        prefix: indentation prefix for child lines
        is_last: whether this node is the last sibling
        is_root: whether this is the root node
        show_papers: if True, list individual papers under leaf nodes
    """
    lines = []
    connector = "" if is_root else ("└── " if is_last else "├── ")
    n_papers = _count_papers(node)
    label = f"{node.name} ({n_papers} papers)"
    if node.description and not is_root:
        label += f"  — {node.description}"
    lines.append(f"{prefix}{connector}{label}")

    child_prefix = prefix + ("" if is_root else ("    " if is_last else "│   "))

    # List individual papers for leaf nodes
    if node.is_leaf and show_papers and node.paper_ids:
        for i, pid in enumerate(node.paper_ids):
            is_last_paper = (i == len(node.paper_ids) - 1) and not node.children
            paper_connector = "└── " if is_last_paper else "├── "
            if papers_map and pid in papers_map:
                title = papers_map[pid].title
                authors = ", ".join(papers_map[pid].authors[:3])
                if len(papers_map[pid].authors) > 3:
                    authors += " et al."
                lines.append(f"{child_prefix}{paper_connector}[{pid}] {title}")
                lines.append(f"{child_prefix}{'    ' if is_last_paper else '│   '}     {authors}")
            else:
                lines.append(f"{child_prefix}{paper_connector}[{pid}]")

    for i, child in enumerate(node.children):
        lines.extend(_render_tree(child, papers_map, child_prefix,
                                  is_last=(i == len(node.children) - 1),
                                  show_papers=show_papers))
    return lines


def _render_markdown(node: TaxonomyNode, papers_map: dict = None,
                     depth: int = 0, show_papers: bool = True) -> list[str]:
    """Render the taxonomy as Markdown with headings + bullet lists."""
    lines = []
    MAX_HEADING = 4
    n_papers = _count_papers(node)

    if depth < MAX_HEADING:
        heading = "#" * (depth + 1)
        desc = f"  \n*{node.description}*" if node.description and depth > 0 else ""
        lines.append(f"\n{heading} {node.name} ({n_papers} papers){desc}\n")
    else:
        bullet_indent = "  " * (depth - MAX_HEADING)
        lines.append(f"{bullet_indent}- **{node.name}** ({n_papers} papers)")

    # List papers for leaf nodes
    if node.is_leaf and show_papers and node.paper_ids:
        bullet_depth = max(depth - MAX_HEADING + 1, 0)
        indent = "  " * bullet_depth
        for pid in node.paper_ids:
            if papers_map and pid in papers_map:
                p = papers_map[pid]
                authors = ", ".join(p.authors[:3])
                if len(p.authors) > 3:
                    authors += " et al."
                lines.append(f"{indent}- **[{pid}]** {p.title}  ")
                lines.append(f"{indent}  *{authors}*")
            else:
                lines.append(f"{indent}- [{pid}]")

    for child in node.children:
        lines.extend(_render_markdown(child, papers_map, depth + 1,
                                      show_papers=show_papers))
    return lines


def _render_indent(node: TaxonomyNode, papers_map: dict = None,
                   depth: int = 0, show_papers: bool = True) -> list[str]:
    """Render as a numbered indented outline."""
    lines = []
    indent = "    " * depth
    n_papers = _count_papers(node)
    desc = f" — {node.description}" if node.description and depth > 0 else ""
    lines.append(f"{indent}{node.name} ({n_papers} papers){desc}")

    if node.is_leaf and show_papers and node.paper_ids:
        paper_indent = "    " * (depth + 1)
        for pid in node.paper_ids:
            if papers_map and pid in papers_map:
                p = papers_map[pid]
                authors = ", ".join(p.authors[:3])
                if len(p.authors) > 3:
                    authors += " et al."
                lines.append(f"{paper_indent}• [{pid}] {p.title}")
                lines.append(f"{paper_indent}        {authors}")
            else:
                lines.append(f"{paper_indent}• [{pid}]")

    for child in node.children:
        lines.extend(_render_indent(child, papers_map, depth + 1,
                                    show_papers=show_papers))
    return lines


def render_taxonomy(node: TaxonomyNode, papers_map: dict = None,
                    fmt: str = "tree", show_papers: bool = True) -> str:
    """Render a taxonomy tree as a human-readable string.

    Args:
        node: root TaxonomyNode
        papers_map: optional {paper_id: Paper} dict for resolving titles/authors
        fmt: "tree" (ASCII art), "markdown", or "indent" (outline)
        show_papers: whether to list individual papers under leaf nodes

    Returns:
        Formatted string.
    """
    if fmt == "tree":
        lines = _render_tree(node, papers_map, is_root=True, show_papers=show_papers)
    elif fmt == "markdown":
        lines = _render_markdown(node, papers_map, depth=0, show_papers=show_papers)
    elif fmt == "indent":
        lines = _render_indent(node, papers_map, depth=0, show_papers=show_papers)
    else:
        raise ValueError(f"Unknown format: {fmt!r}. Use 'tree', 'markdown', or 'indent'.")
    return "\n".join(lines) + "\n"


def export_taxonomy_readable(node: TaxonomyNode, path: str,
                             papers_map: dict = None, fmt: str = "tree",
                             show_papers: bool = True):
    """Render and write taxonomy to a text file."""
    text = render_taxonomy(node, papers_map, fmt=fmt, show_papers=show_papers)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"Human-readable taxonomy ({fmt}) saved to {path}")


# ────────────────────────────────────────────────────────────────────
# Interactive HTML rendering (collapsible tree)
# ────────────────────────────────────────────────────────────────────

def _taxonomy_to_html_json(node: TaxonomyNode, papers_map: dict = None) -> dict:
    """Convert taxonomy tree to a JSON-serialisable dict for the HTML viewer."""
    n_papers = _count_papers(node)
    d = {
        "id": node.node_id,
        "name": node.name,
        "description": node.description or "",
        "count": n_papers,
        "is_leaf": node.is_leaf,
    }
    if node.paper_ids:
        papers_list = []
        for pid in node.paper_ids:
            if papers_map and pid in papers_map:
                p = papers_map[pid]
                papers_list.append({
                    "id": pid,
                    "title": p.title,
                    "authors": ", ".join(p.authors),
                })
            else:
                papers_list.append({"id": pid, "title": pid, "authors": ""})
        d["papers"] = papers_list
    if node.children:
        d["children"] = [_taxonomy_to_html_json(c, papers_map) for c in node.children]
    return d


def export_taxonomy_html(node: TaxonomyNode, path: str,
                         papers_map: dict = None, title: str = "Taxonomy"):
    """Export the taxonomy as a self-contained interactive HTML with collapsible nodes."""
    import json as _json
    tree_data = _taxonomy_to_html_json(node, papers_map)
    tree_json = _json.dumps(tree_data, ensure_ascii=False)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@400;600;700&display=swap');

  :root {{
    --bg: #fafbfc;
    --card-bg: #ffffff;
    --border: #e2e6ea;
    --text: #1a2332;
    --text-muted: #5a6a7e;
    --accent: #2563eb;
    --accent-light: #dbeafe;
    --leaf-bg: #f0fdf4;
    --leaf-border: #86efac;
    --paper-bg: #f8fafc;
    --paper-border: #e2e8f0;
    --hover: #f1f5f9;
    --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.04);
    --shadow-lg: 0 4px 12px rgba(0,0,0,.1);
    --radius: 10px;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 0;
  }}

  header {{
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: #fff;
    padding: 2rem 2.5rem;
    font-family: 'Source Serif 4', Georgia, serif;
  }}
  header h1 {{ font-size: 1.75rem; font-weight: 700; }}
  header .subtitle {{
    font-family: 'Inter', sans-serif;
    font-size: .875rem;
    opacity: .85;
    margin-top: .35rem;
  }}

  .toolbar {{
    display: flex;
    gap: .5rem;
    padding: 1rem 2.5rem;
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .toolbar button {{
    font-family: 'Inter', sans-serif;
    font-size: .8rem;
    font-weight: 500;
    padding: .4rem .9rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card-bg);
    color: var(--text);
    cursor: pointer;
    transition: all .15s;
  }}
  .toolbar button:hover {{
    background: var(--accent-light);
    border-color: var(--accent);
    color: var(--accent);
  }}
  .toolbar .search-box {{
    flex: 1;
    max-width: 320px;
    margin-left: auto;
  }}
  .toolbar input {{
    width: 100%;
    font-family: 'Inter', sans-serif;
    font-size: .8rem;
    padding: .4rem .75rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    outline: none;
    transition: border-color .15s;
  }}
  .toolbar input:focus {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-light);
  }}

  .tree-container {{
    max-width: 1100px;
    margin: 1.5rem auto;
    padding: 0 1.5rem 3rem;
  }}

  .node {{
    margin-left: 1.25rem;
    border-left: 2px solid var(--border);
    padding-left: 0;
  }}
  .tree-container > .node {{
    margin-left: 0;
    border-left: none;
  }}

  .node-header {{
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .55rem .75rem;
    margin: 2px 0 2px 0;
    border-radius: var(--radius);
    cursor: pointer;
    transition: background .15s;
    user-select: none;
  }}
  .node-header:hover {{ background: var(--hover); }}
  .node-header.leaf {{ cursor: default; }}
  .node-header.leaf:hover {{ background: transparent; }}

  .toggle {{
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: .7rem;
    color: var(--text-muted);
    flex-shrink: 0;
    transition: transform .2s;
  }}
  .toggle.collapsed {{ transform: rotate(-90deg); }}
  .toggle.empty {{ visibility: hidden; }}

  .node-icon {{
    font-size: 1rem;
    flex-shrink: 0;
  }}

  .node-name {{
    font-weight: 600;
    font-size: .9rem;
  }}

  .node-badge {{
    font-size: .7rem;
    font-weight: 600;
    padding: .15rem .5rem;
    border-radius: 999px;
    background: var(--accent-light);
    color: var(--accent);
    flex-shrink: 0;
  }}

  .node-desc {{
    font-size: .78rem;
    color: var(--text-muted);
    margin-left: 2.6rem;
    padding: 0 .75rem .25rem;
    font-style: italic;
  }}

  .node-children {{
    overflow: hidden;
    transition: max-height .3s ease;
  }}
  .node-children.collapsed {{
    max-height: 0 !important;
  }}

  .paper-list {{
    margin: .25rem 0 .5rem 2.6rem;
    padding: 0 .75rem;
  }}

  .paper-card {{
    display: flex;
    align-items: flex-start;
    gap: .6rem;
    padding: .5rem .7rem;
    margin: 3px 0;
    background: var(--paper-bg);
    border: 1px solid var(--paper-border);
    border-radius: 8px;
    transition: box-shadow .15s;
  }}
  .paper-card:hover {{
    box-shadow: var(--shadow);
  }}

  .paper-id {{
    font-size: .7rem;
    font-weight: 600;
    color: var(--accent);
    background: var(--accent-light);
    padding: .1rem .4rem;
    border-radius: 4px;
    flex-shrink: 0;
    margin-top: 2px;
  }}

  .paper-info {{
    flex: 1;
    min-width: 0;
  }}
  .paper-title {{
    font-size: .82rem;
    font-weight: 500;
    line-height: 1.4;
  }}
  .paper-authors {{
    font-size: .73rem;
    color: var(--text-muted);
    margin-top: .15rem;
  }}

  .highlight {{
    background: #fef08a;
    border-radius: 2px;
    padding: 0 1px;
  }}

  .stats {{
    display: flex;
    gap: 1.5rem;
    margin-top: .5rem;
    font-size: .8rem;
    color: rgba(255,255,255,.9);
  }}
  .stats span {{ font-weight: 600; }}

  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<header>
  <h1>{title}</h1>
  <div class="stats" id="stats"></div>
</header>

<div class="toolbar">
  <button onclick="expandAll()">Expand All</button>
  <button onclick="collapseAll()">Collapse All</button>
  <button onclick="expandLevel(1)">Level 1</button>
  <button onclick="expandLevel(2)">Level 2</button>
  <div class="search-box">
    <input type="text" id="search" placeholder="Search papers or topics..." oninput="handleSearch(this.value)">
  </div>
</div>

<div class="tree-container" id="tree"></div>

<script>
const DATA = {tree_json};

// ── Build HTML ───────────────────────────────────────
function buildNode(node, depth) {{
  const div = document.createElement('div');
  div.className = 'node';
  div.dataset.depth = depth;
  div.dataset.nodeId = node.id;

  const hasChildren = node.children && node.children.length > 0;
  const hasPapers = node.papers && node.papers.length > 0;
  const isExpandable = hasChildren || hasPapers;

  // Header row
  const header = document.createElement('div');
  header.className = 'node-header' + (isExpandable ? '' : ' leaf');

  const toggle = document.createElement('span');
  toggle.className = 'toggle' + (isExpandable ? '' : ' empty');
  toggle.textContent = '▼';

  const icon = document.createElement('span');
  icon.className = 'node-icon';
  icon.textContent = node.is_leaf ? '📄' : '📁';

  const name = document.createElement('span');
  name.className = 'node-name';
  name.textContent = node.name;

  const badge = document.createElement('span');
  badge.className = 'node-badge';
  badge.textContent = node.count + ' paper' + (node.count !== 1 ? 's' : '');

  header.append(toggle, icon, name, badge);
  div.appendChild(header);

  // Description
  if (node.description && depth > 0) {{
    const desc = document.createElement('div');
    desc.className = 'node-desc';
    desc.textContent = node.description;
    div.appendChild(desc);
  }}

  // Children wrapper
  const childrenDiv = document.createElement('div');
  childrenDiv.className = 'node-children';

  // Papers (for leaf nodes)
  if (hasPapers) {{
    const paperList = document.createElement('div');
    paperList.className = 'paper-list';
    for (const p of node.papers) {{
      const card = document.createElement('div');
      card.className = 'paper-card';
      card.dataset.searchText = (p.id + ' ' + p.title + ' ' + p.authors).toLowerCase();

      const idSpan = document.createElement('span');
      idSpan.className = 'paper-id';
      idSpan.textContent = p.id;

      const info = document.createElement('div');
      info.className = 'paper-info';
      const titleEl = document.createElement('div');
      titleEl.className = 'paper-title';
      titleEl.textContent = p.title;
      const authorsEl = document.createElement('div');
      authorsEl.className = 'paper-authors';
      authorsEl.textContent = p.authors;
      info.append(titleEl, authorsEl);

      card.append(idSpan, info);
      paperList.appendChild(card);
    }}
    childrenDiv.appendChild(paperList);
  }}

  // Child nodes
  if (hasChildren) {{
    for (const child of node.children) {{
      childrenDiv.appendChild(buildNode(child, depth + 1));
    }}
  }}

  div.appendChild(childrenDiv);

  // Click to toggle
  if (isExpandable) {{
    header.addEventListener('click', () => {{
      const isCollapsed = childrenDiv.classList.toggle('collapsed');
      toggle.classList.toggle('collapsed', isCollapsed);
    }});
  }}

  return div;
}}

// ── Expand / Collapse helpers ────────────────────────
function expandAll() {{
  document.querySelectorAll('.node-children').forEach(el => {{
    el.classList.remove('collapsed');
  }});
  document.querySelectorAll('.toggle').forEach(el => {{
    el.classList.remove('collapsed');
  }});
}}

function collapseAll() {{
  document.querySelectorAll('.node-children').forEach(el => {{
    el.classList.add('collapsed');
  }});
  document.querySelectorAll('.toggle:not(.empty)').forEach(el => {{
    el.classList.add('collapsed');
  }});
  // Always expand root
  const root = document.querySelector('#tree > .node > .node-children');
  const rootToggle = document.querySelector('#tree > .node > .node-header .toggle');
  if (root) {{ root.classList.remove('collapsed'); }}
  if (rootToggle) {{ rootToggle.classList.remove('collapsed'); }}
}}

function expandLevel(level) {{
  collapseAll();
  document.querySelectorAll('.node').forEach(el => {{
    const d = parseInt(el.dataset.depth);
    if (d <= level) {{
      const ch = el.querySelector(':scope > .node-children');
      const tg = el.querySelector(':scope > .node-header .toggle');
      if (ch) ch.classList.remove('collapsed');
      if (tg) tg.classList.remove('collapsed');
    }}
  }});
}}

// ── Search ───────────────────────────────────────────
function handleSearch(query) {{
  const q = query.trim().toLowerCase();
  // Remove old highlights
  document.querySelectorAll('.highlight').forEach(el => {{
    el.replaceWith(el.textContent);
  }});

  if (!q) {{
    // Show everything, restore collapse state
    document.querySelectorAll('.node').forEach(n => n.classList.remove('hidden'));
    document.querySelectorAll('.paper-card').forEach(c => c.classList.remove('hidden'));
    return;
  }}

  // Hide all, then selectively show matches
  const allPapers = document.querySelectorAll('.paper-card');
  const allNodes = document.querySelectorAll('.node');

  allPapers.forEach(c => c.classList.add('hidden'));
  allNodes.forEach(n => n.classList.add('hidden'));

  // Find matching papers
  allPapers.forEach(card => {{
    if (card.dataset.searchText.includes(q)) {{
      card.classList.remove('hidden');
      // Expand + show ancestors
      let el = card.closest('.node');
      while (el) {{
        el.classList.remove('hidden');
        const ch = el.querySelector(':scope > .node-children');
        const tg = el.querySelector(':scope > .node-header .toggle');
        if (ch) ch.classList.remove('collapsed');
        if (tg) tg.classList.remove('collapsed');
        el = el.parentElement.closest('.node');
      }}
    }}
  }});

  // Also match on node names
  allNodes.forEach(node => {{
    const nameEl = node.querySelector(':scope > .node-header .node-name');
    const descEl = node.querySelector(':scope > .node-desc');
    const text = ((nameEl ? nameEl.textContent : '') + ' ' + (descEl ? descEl.textContent : '')).toLowerCase();
    if (text.includes(q)) {{
      node.classList.remove('hidden');
      // show all descendants
      node.querySelectorAll('.node').forEach(d => d.classList.remove('hidden'));
      node.querySelectorAll('.paper-card').forEach(c => c.classList.remove('hidden'));
      const ch = node.querySelector(':scope > .node-children');
      const tg = node.querySelector(':scope > .node-header .toggle');
      if (ch) ch.classList.remove('collapsed');
      if (tg) tg.classList.remove('collapsed');
      // show ancestors
      let el = node.parentElement.closest('.node');
      while (el) {{
        el.classList.remove('hidden');
        const ch2 = el.querySelector(':scope > .node-children');
        const tg2 = el.querySelector(':scope > .node-header .toggle');
        if (ch2) ch2.classList.remove('collapsed');
        if (tg2) tg2.classList.remove('collapsed');
        el = el.parentElement.closest('.node');
      }}
    }}
  }});
}}

// ── Init ─────────────────────────────────────────────
function countTotalPapers(node) {{
  let c = (node.papers || []).length;
  for (const ch of (node.children || [])) c += countTotalPapers(ch);
  return c;
}}
function countLeaves(node) {{
  if (node.is_leaf) return 1;
  let c = 0;
  for (const ch of (node.children || [])) c += countLeaves(ch);
  return c;
}}
function maxDepth(node, d) {{
  if (!node.children || node.children.length === 0) return d;
  let m = d;
  for (const ch of node.children) m = Math.max(m, maxDepth(ch, d + 1));
  return m;
}}

const tree = document.getElementById('tree');
tree.appendChild(buildNode(DATA, 0));

// Stats
const stats = document.getElementById('stats');
const totalPapers = countTotalPapers(DATA);
const totalLeaves = countLeaves(DATA);
const depth = maxDepth(DATA, 0);
stats.innerHTML = '<span>' + totalPapers + '</span> papers &middot; '
  + '<span>' + totalLeaves + '</span> leaf topics &middot; '
  + '<span>' + depth + '</span> levels deep';

// Default: expand level 1
expandLevel(1);
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Interactive taxonomy HTML saved to {path}")
