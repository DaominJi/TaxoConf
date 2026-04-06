"""
Context-aware session naming using taxonomy hierarchy.

Implements a bottom-up naming cascade:
1. Leaf sessions are named from their taxonomy path + paper titles
2. Parent/merged sessions are named from their path + child session names + papers

The taxonomy path (root > ... > current node) provides disambiguation context.
Child session names (already finalized) provide sub-topic awareness.
"""

import json
import logging
from typing import Optional

from models import Paper, TaxonomyNode, Session
from llm_client import LLMClient
from prompts.session_naming import (
    LEAF_SYSTEM_PROMPT,
    LEAF_USER_PROMPT,
    PARENT_SYSTEM_PROMPT,
    PARENT_USER_PROMPT,
)

logger = logging.getLogger(__name__)


def _build_node_map(root: TaxonomyNode) -> dict[str, TaxonomyNode]:
    """Build a flat map of node_id -> TaxonomyNode."""
    result = {}

    def walk(node):
        result[node.node_id] = node
        for child in node.children:
            walk(child)

    walk(root)
    return result


def _get_taxonomy_path(node_id: str, node_map: dict[str, TaxonomyNode]) -> list[str]:
    """Walk from a node up to root, return path as [root_name, ..., node_name]."""
    path = []
    current_id = node_id
    visited = set()
    while current_id and current_id in node_map and current_id not in visited:
        visited.add(current_id)
        node = node_map[current_id]
        path.append(node.name)
        current_id = node.parent_id
    path.reverse()
    return path


def _get_child_session_names(node_id: str, node_map: dict[str, TaxonomyNode],
                              session_names: dict[str, str]) -> list[tuple[str, int]]:
    """Get session names derived from children of this node.

    Returns list of (session_name, paper_count) for child nodes that have
    sessions named so far.
    """
    node = node_map.get(node_id)
    if not node:
        return []

    result = []

    def collect(n):
        # Check if any session was formed from this node
        if n.node_id in session_names:
            # Count papers — use the node's own papers or sum children
            count = len(n.paper_ids)
            if not count:
                count = sum(len(c.paper_ids) for c in n.children)
            result.append((session_names[n.node_id], count))
        else:
            for child in n.children:
                collect(child)

    for child in node.children:
        collect(child)

    return result


def _format_papers_short(paper_ids: list[str], papers_map: dict[str, Paper],
                          max_papers: int = 15) -> str:
    """Format paper list for the naming prompt (titles only, truncated)."""
    lines = []
    for pid in paper_ids[:max_papers]:
        p = papers_map.get(pid)
        if p:
            lines.append(f"- [{p.id}] {p.title}")
    if len(paper_ids) > max_papers:
        lines.append(f"- ... and {len(paper_ids) - max_papers} more papers")
    return "\n".join(lines) if lines else "(no papers)"


def _parse_naming_response(raw: str, fallback_name: str) -> tuple[str, str]:
    """Parse the LLM naming response, return (title, description)."""
    text = raw.strip()
    # Strip code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        result = json.loads(text)
        title = str(result.get("title", "")).strip()
        desc = str(result.get("description", "")).strip()
        if title:
            return title, desc
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: use raw text as title if it's short enough
    if len(text) < 80 and "\n" not in text:
        return text.strip('"'), ""

    return fallback_name, ""


def name_sessions(sessions: list[Session],
                  taxonomy_root: TaxonomyNode,
                  papers_map: dict[str, Paper],
                  llm: Optional[LLMClient] = None) -> list[Session]:
    """Rename all sessions using context-aware LLM naming.

    Implements a bottom-up cascade:
    1. Group sessions by their taxonomy node depth (deepest first)
    2. Name leaf-level sessions using taxonomy path + papers
    3. Name higher-level sessions using path + already-named child sessions + papers
    4. Return sessions with updated names and descriptions

    Parameters
    ----------
    sessions : list[Session]
        Sessions to rename (modified in-place).
    taxonomy_root : TaxonomyNode
        The taxonomy tree root.
    papers_map : dict[str, Paper]
        Paper ID -> Paper lookup.
    llm : LLMClient, optional
        LLM client. If None, creates a new one.

    Returns
    -------
    list[Session]
        The same sessions with updated names.
    """
    if not sessions:
        return sessions

    if llm is None:
        llm = LLMClient()

    node_map = _build_node_map(taxonomy_root)

    # Track which node_id has which session name (for child lookups)
    session_names: dict[str, str] = {}  # node_id -> session name

    # Group sessions by taxonomy depth (deeper = named first)
    def get_depth(s: Session) -> int:
        nid = s.taxonomy_node_id
        if nid and nid in node_map:
            return node_map[nid].depth
        return 0

    sessions_by_depth = sorted(sessions, key=get_depth, reverse=True)

    logger.info(f"Naming {len(sessions)} sessions (bottom-up cascade)...")

    for session in sessions_by_depth:
        nid = session.taxonomy_node_id
        if not nid or nid not in node_map:
            logger.warning(f"  Session '{session.session_id}' has no taxonomy node, skipping naming")
            continue

        # Build taxonomy path
        path = _get_taxonomy_path(nid, node_map)
        path_text = " > ".join(path) if path else "Conference"

        # Get child session names (already named in previous iterations)
        child_names = _get_child_session_names(nid, node_map, session_names)

        # Format papers
        papers_text = _format_papers_short(session.paper_ids, papers_map)

        # Choose prompt based on whether we have child session context
        if child_names:
            child_text = "\n".join(
                f"- \"{name}\" ({count} papers)" for name, count in child_names
            )
            prompt = PARENT_USER_PROMPT.format(
                taxonomy_path=path_text,
                child_sessions_text=child_text,
                papers_text=papers_text,
            )
            system = PARENT_SYSTEM_PROMPT
            label = f"name_parent:{session.session_id}"
        else:
            prompt = LEAF_USER_PROMPT.format(
                taxonomy_path=path_text,
                papers_text=papers_text,
            )
            system = LEAF_SYSTEM_PROMPT
            label = f"name_leaf:{session.session_id}"

        # Call LLM
        try:
            raw = llm.chat(system, prompt, call_label=label)
            title, desc = _parse_naming_response(raw, session.name)
            old_name = session.name
            session.name = title
            session.description = desc
            session_names[nid] = title
            logger.info(f"  {session.session_id}: \"{old_name}\" -> \"{title}\"")
        except Exception as e:
            logger.warning(f"  Failed to name session {session.session_id}: {e}")
            session_names[nid] = session.name  # Keep original name

    logger.info(f"Session naming complete: {len(session_names)} sessions named")
    return sessions
