"""
Unified session organizer — two-stage architecture for both oral and poster.

Stage 1:   Paper → Session  (topical coherence + capacity)
  Method 1 ("greedy"):       Bottom-up greedy with last-mile LLM editing
  Method 2 ("optimization"): LCA-based optimization (ILP or heuristic)

Stage 1.5: Board Layout (poster only)
  TSP/spectral optimization per floor plan (line / circle / rectangle).

Stage 2:   Session → Slot   (conflict avoidance + audience diversity)
  Shared across both methods: ILP/heuristic graph-coloring scheduler.

Last-Mile Edit pass runs after both stages to handle edge cases
(unresolvable conflicts, LLM-flagged misfits, root orphans).
For poster sessions, Stage 1.5 is re-run for affected sessions.

Cross-type scheduling merges oral + poster conflict graphs when their
time slots overlap.
"""
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import networkx as nx

import config
from models import Paper, Session, TaxonomyNode
from taxonomy_builder import collect_leaves
from similarity import SimilarityEngine

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


# ════════════════════════════════════════════════════════════════════
# Session-type configuration
# ════════════════════════════════════════════════════════════════════

@dataclass
class SessionTypeConfig:
    """Encapsulates all parameters that differ between oral and poster."""
    session_type: str              # "oral" or "poster"
    min_papers: int
    max_papers: int
    num_slots: int
    num_parallel: int
    method: str                    # "greedy" or "optimization"
    solver: str                    # "ilp" or "heuristic"
    alpha: float                   # LCA vs embedding blend
    enable_conflict_avoidance: bool
    audience_sim_threshold: float
    ilp_time_limit: int
    ilp_mip_gap: float
    max_repair_iterations: int
    session_id_prefix: str = "S"   # "S" for oral, "PS" for poster

    @property
    def target_sessions(self) -> int:
        return self.num_slots * self.num_parallel

    @staticmethod
    def oral() -> "SessionTypeConfig":
        """Build config from oral globals."""
        return SessionTypeConfig(
            session_type="oral",
            min_papers=config.SESSION_MIN,
            max_papers=config.SESSION_MAX,
            num_slots=config.NUM_SLOTS,
            num_parallel=config.NUM_PARALLEL_TRACKS,
            method=config.ORAL_METHOD,
            solver=config.ORAL_SOLVER,
            alpha=config.ORAL_ALPHA,
            enable_conflict_avoidance=config.ENABLE_CONFLICT_AVOIDANCE,
            audience_sim_threshold=config.AUDIENCE_SIM_THRESHOLD,
            ilp_time_limit=config.ILP_TIME_LIMIT,
            ilp_mip_gap=config.ILP_MIP_GAP,
            max_repair_iterations=config.MAX_REPAIR_ITERATIONS,
            session_id_prefix="S",
        )

    @staticmethod
    def poster() -> "SessionTypeConfig":
        """Build config from poster globals."""
        return SessionTypeConfig(
            session_type="poster",
            min_papers=config.POSTER_SESSION_MIN,
            max_papers=config.POSTER_SESSION_MAX,
            num_slots=config.POSTER_NUM_SLOTS,
            num_parallel=config.POSTER_NUM_PARALLEL,
            method=config.POSTER_METHOD,
            solver=config.POSTER_SOLVER,
            alpha=config.POSTER_ALPHA,
            enable_conflict_avoidance=config.POSTER_ENABLE_CONFLICT_AVOIDANCE,
            audience_sim_threshold=config.AUDIENCE_SIM_THRESHOLD,
            ilp_time_limit=config.ILP_TIME_LIMIT,
            ilp_mip_gap=config.ILP_MIP_GAP,
            max_repair_iterations=config.MAX_REPAIR_ITERATIONS,
            session_id_prefix="PS",
        )


# ════════════════════════════════════════════════════════════════════
# Data structures for tracking
# ════════════════════════════════════════════════════════════════════

@dataclass
class LastMileEdit:
    paper_id: str
    source_session: Optional[str]
    target_session: Optional[str]
    reason: str

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "source_session": self.source_session,
            "target_session": self.target_session,
            "reason": self.reason,
        }


@dataclass
class OrganizationResult:
    """Full output from the session organizer (oral or poster)."""
    sessions: list[Session]
    session_type: str = "oral"
    last_mile_edits: list[LastMileEdit] = field(default_factory=list)
    capacity_report: list[dict] = field(default_factory=list)
    conflict_report: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════
# LLM helper
# ════════════════════════════════════════════════════════════════════

class _LLMHelper:
    """Thin wrapper for LLM calls used in session formation."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not _HAS_OPENAI:
                raise ImportError("openai package required. pip install openai")
            self._client = OpenAI()
        return self._client

    def chat_json(self, system: str, user: str) -> dict:
        """Send a chat request and return parsed JSON."""
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                resp = self.client.chat.completions.create(
                    model=config.LLM_MODEL,
                    temperature=config.LLM_TEMPERATURE,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content.strip())
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {e}")
                if attempt == config.LLM_MAX_RETRIES - 1:
                    raise
        return {}

    def name_sessions(self, node_name: str, node_desc: str,
                      session_papers: list[list[dict]], k: int,
                      session_type: str = "oral") -> list[str]:
        """Name k sessions split from a taxonomy node. (Appendix A.1)"""
        system = f"You are a conference program chair naming {session_type} sessions."
        papers_text = ""
        for i, papers in enumerate(session_papers, 1):
            papers_text += f"\nSession {i}:\n"
            for p in papers:
                papers_text += f"- {p['title']}\n"

        if k <= 2:
            specific = (f"These sessions could be named '{node_name} I', "
                        f"'{node_name} II', etc. Would that be appropriate, "
                        f"or do they need more distinctive names?")
        else:
            specific = ("Please provide a distinctive, descriptive name for each "
                        "session that captures its specific focus within the "
                        "broader topic.")

        poster_note = ""
        if session_type == "poster":
            poster_note = ("\nNote: Poster sessions are broader than oral sessions. "
                           "Session names should encompass the range of topics "
                           "in each group.")

        user = (f'I have split the topic "{node_name}" ({node_desc}) into '
                f'{k} {session_type} sessions. Here are the papers in each '
                f'session:\n{papers_text}\n{specific}{poster_note}\n\n'
                'Respond as JSON:\n'
                '{"sessions": [{"session_index": 1, "name": "Proposed Name"}, ...]}')

        try:
            result = self.chat_json(system, user)
            sessions = result.get("sessions", [])
            return [s.get("name", f"{node_name} Part {s.get('session_index', i)}")
                    for i, s in enumerate(sessions, 1)]
        except Exception:
            return [f"{node_name} (Part {i})" for i in range(1, k + 1)]

    def reassign_paper(self, paper: Paper, candidates: list[dict],
                       max_papers: int = 5) -> Optional[int]:
        """Ask LLM which session is best fit. (Appendix A.2)"""
        system = "You are a conference program chair assigning papers to sessions."
        cands = "\n".join(
            f'{i+1}. "{c["name"]}" - {c["description"]} '
            f'({c["count"]}/{max_papers} papers)'
            for i, c in enumerate(candidates)
        )
        user = (f"This paper needs to be assigned to one of the following sessions:\n\n"
                f"Paper: {paper.title}\nAbstract: {paper.abstract}\n\n"
                f"Available sessions:\n{cands}\n\n"
                f'Which session is the best thematic fit? '
                f'Respond as JSON: {{"best_session_index": <integer>}}')
        try:
            result = self.chat_json(system, user)
            idx = result.get("best_session_index", 1)
            return max(0, min(idx - 1, len(candidates) - 1))
        except Exception:
            return 0

    def check_suitability(self, session_name: str, papers: list[dict],
                          session_type: str = "oral") -> list[dict]:
        """Check if papers fit a session. (Appendix A.3)"""
        system = "You are a conference program chair reviewing session assignments."
        plist = "\n".join(f'{i+1}. [{p["id"]}] {p["title"]}' for i, p in enumerate(papers))
        user = (f'Here is a {session_type} session named "{session_name}":\n\n'
                f'Papers:\n{plist}\n\n'
                'Are any of these papers a poor fit for this session? A paper is a poor '
                'fit if its topic is clearly unrelated to the session\'s focus.\n\n'
                'If all papers fit well, respond: {"status": "ALL_SUITABLE"}\n'
                'Otherwise, respond:\n'
                '{"status": "HAS_MISFITS", "misfits": [{"paper_id": "...", "reason": "..."}]}')
        try:
            result = self.chat_json(system, user)
            if result.get("status") == "ALL_SUITABLE":
                return []
            return result.get("misfits", [])
        except Exception:
            return []

    def form_new_sessions(self, papers: list[dict], deficit: int,
                          stc: "SessionTypeConfig" = None) -> list[dict]:
        """Ask LLM to group papers into new sessions. (Appendix A.4)"""
        min_p = stc.min_papers if stc else config.SESSION_MIN
        max_p = stc.max_papers if stc else config.SESSION_MAX
        stype = stc.session_type if stc else "oral"

        system = f"You are a conference program chair organizing new {stype} sessions."
        plist = "\n".join(
            f'{i+1}. [{p["id"]}] {p["title"]}: {p.get("abstract", "")[:200]}'
            for i, p in enumerate(papers)
        )
        poster_note = ""
        if stype == "poster":
            poster_note = f"\n4. Poster session names should be thematically broad."

        user = (f"I have {len(papers)} papers that need to be organized into "
                f"{deficit} {stype} sessions ({min_p}-{max_p} "
                f"papers each).\n\nPapers:\n{plist}\n\nPlease:\n"
                f"1. Group these papers into {deficit} coherent topical sessions.\n"
                f"2. Provide a descriptive name for each session.\n"
                f"3. Ensure each session has at least {min_p} papers.{poster_note}\n\n"
                f'Respond as JSON:\n'
                f'{{"sessions": [{{"name": "Session Name", "paper_ids": ["id1", ...]}}]}}')
        try:
            result = self.chat_json(system, user)
            return result.get("sessions", [])
        except Exception:
            return []


_llm = _LLMHelper()


# ════════════════════════════════════════════════════════════════════
# Shared: build parent map for taxonomy
# ════════════════════════════════════════════════════════════════════

def _build_parent_map(root: TaxonomyNode) -> dict[str, TaxonomyNode]:
    """Map node_id → parent TaxonomyNode."""
    parent_map = {}

    def walk(node, parent):
        if parent is not None:
            parent_map[node.node_id] = parent
        for child in node.children:
            walk(child, node)

    walk(root, None)
    return parent_map


def _build_node_map(root: TaxonomyNode) -> dict[str, TaxonomyNode]:
    """Map node_id → TaxonomyNode."""
    nmap = {}

    def walk(node):
        nmap[node.node_id] = node
        for child in node.children:
            walk(child)

    walk(root)
    return nmap


# ════════════════════════════════════════════════════════════════════
# METHOD 1: Bottom-Up Greedy with Last-Mile LLM Editing
# ════════════════════════════════════════════════════════════════════

class GreedySessionFormer:
    """
    Bottom-up post-order traversal of the taxonomy.
    At each node, form sessions or bubble up papers that can't form sessions.
    Then adjust session count to target T and resolve edge cases.
    Works identically for oral and poster, differing only in capacity bounds
    and LLM naming style (via SessionTypeConfig).
    """

    def __init__(self, papers: dict[str, Paper], sim: SimilarityEngine,
                 taxonomy_root: TaxonomyNode, stc: SessionTypeConfig = None):
        self.papers = papers
        self.sim = sim
        self.root = taxonomy_root
        self.stc = stc or SessionTypeConfig.oral()
        self.target_T = self.stc.target_sessions
        self._session_counter = 0
        self.sessions: list[Session] = []
        self.edits: list[LastMileEdit] = []

    def form_sessions(self) -> tuple[list[Session], list[LastMileEdit]]:
        """Stage 1: paper-to-session assignment."""
        logger.info(f"Greedy session formation ({self.stc.session_type}) | "
                    f"target T={self.target_T}")

        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        # Step 1.1: Initialize effective_papers on each node
        node_papers: dict[str, list[str]] = {}  # node_id → effective papers
        bubbled: dict[str, list[str]] = {}       # node_id → bubbled-up papers

        def init(node):
            node_papers[node.node_id] = list(node.paper_ids)
            bubbled[node.node_id] = []
            for child in node.children:
                init(child)

        init(self.root)

        # Step 1.2: Post-order traversal
        parent_map = _build_parent_map(self.root)

        def postorder(node):
            # Process children first
            for child in node.children:
                postorder(child)

            # Accumulate bubbled-up papers
            effective = node_papers[node.node_id] + bubbled[node.node_id]
            n = len(effective)

            if n == 0:
                return

            if min_p <= n <= max_p:
                # Case A: fits perfectly
                self._create_session(effective, node.name, node.description,
                                     node.node_id)
            elif n > max_p:
                # Case B: too many — split
                leftovers = self._split_and_form(effective, node)
                # Bubble leftovers to parent
                if node.node_id in parent_map:
                    pid = parent_map[node.node_id].node_id
                    bubbled[pid].extend(leftovers)
                else:
                    # Root — handle below in Step 1.3
                    node_papers[node.node_id] = leftovers
                    return
            else:
                # Case C: too few — bubble up
                if node.node_id in parent_map:
                    pid = parent_map[node.node_id].node_id
                    bubbled[pid].extend(effective)
                else:
                    # Root with < min_papers → handled in Step 1.3
                    node_papers[node.node_id] = effective
                    return

            node_papers[node.node_id] = []

        postorder(self.root)

        # Step 1.3: Handle root-level orphans
        orphans = node_papers[self.root.node_id] + bubbled[self.root.node_id]
        if orphans:
            self._handle_orphans(orphans)

        # Step 1.4: Session count adjustment
        self._adjust_session_count()

        # Step 1.5: Validate capacity
        self._validate_capacity()

        logger.info(f"Greedy formation complete: {len(self.sessions)} sessions, "
                    f"{len(self.edits)} edits")
        return self.sessions, self.edits

    # ── Case B: Split ──────────────────────────────────────────────

    def _split_and_form(self, papers: list[str], node: TaxonomyNode) -> list[str]:
        """Split papers into k sessions, return leftover papers."""
        n = len(papers)
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        # Step B1: Find optimal k
        best = None
        mid_size = (min_p + max_p) / 2.0
        for k in range(2, n // min_p + 1):
            size = n // k
            leftover = n - k * size
            if min_p <= size <= max_p:
                score = (leftover, abs(k - n / mid_size))
                if best is None or score < (best[2], best[3]):
                    best = (k, size, leftover, abs(k - n / mid_size))
            # Also try filling to max
            leftover_max = n - k * max_p
            if leftover_max >= 0:
                score = (leftover_max, abs(k - n / mid_size))
                if best is None or score < (best[2], best[3]):
                    best = (k, max_p, leftover_max,
                            abs(k - n / mid_size))

        if best is None:
            # Fallback: just use max sessions
            k = max(1, n // max_p)
            leftover = n - k * max_p
            best = (k, max_p, max(0, leftover), 0)

        k, _, leftover_count, _ = best

        # Step B2: Select leftover papers (most outlier)
        leftovers = []
        remaining = list(papers)
        if leftover_count > 0:
            outlier_scores = {}
            for pid in remaining:
                others = [p for p in remaining if p != pid]
                outlier_scores[pid] = self.sim.average_distance(pid, others)
            remaining.sort(key=lambda p: outlier_scores[p], reverse=True)
            leftovers = remaining[:leftover_count]
            remaining = remaining[leftover_count:]

        # Step B3: Partition remaining into k sessions
        groups = self._partition_papers(remaining, k)

        # Step B4: Name sessions via LLM
        session_papers_info = [
            [{"title": self.papers[pid].title} for pid in g]
            for g in groups
        ]
        try:
            names = _llm.name_sessions(node.name, node.description,
                                       session_papers_info, k,
                                       self.stc.session_type)
        except Exception:
            names = [f"{node.name} (Part {i+1})" for i in range(k)]

        # Step B6: Create sessions
        for i, group in enumerate(groups):
            name = names[i] if i < len(names) else f"{node.name} (Part {i+1})"
            self._create_session(group, name, node.description, node.node_id)

        return leftovers

    def _partition_papers(self, papers: list[str], k: int) -> list[list[str]]:
        """Partition papers into k groups maximizing intra-group similarity.
        Uses constrained greedy assignment with centroid initialization."""
        if k <= 1:
            return [papers]

        n = len(papers)
        indices = [self.sim._id_to_idx[pid] for pid in papers
                   if pid in self.sim._id_to_idx]
        if not indices:
            # Fallback: equal chunks
            chunk_size = n // k
            return [papers[i*chunk_size:(i+1)*chunk_size] for i in range(k)]

        emb = self.sim.embeddings[indices]

        # K-means++ initialization
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(emb)

        groups = [[] for _ in range(k)]
        for idx, label in enumerate(labels):
            groups[label].append(papers[idx])

        # Repair: ensure min/max constraints
        groups = self._repair_groups(groups, papers)
        return groups

    def _repair_groups(self, groups: list[list[str]],
                       all_papers: list[str]) -> list[list[str]]:
        """Repair groups to satisfy min/max constraints."""
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        changed = True
        while changed:
            changed = False
            for g in groups:
                while len(g) > max_p:
                    worst = max(g, key=lambda p: self.sim.average_distance(p, g))
                    g.remove(worst)
                    targets = [gg for gg in groups if gg is not g
                               and len(gg) < max_p]
                    if targets:
                        best = min(targets,
                                   key=lambda gg: self.sim.average_distance(worst, gg))
                        best.append(worst)
                    else:
                        g.append(worst)  # no better option
                        break
                    changed = True

            for g in groups:
                while len(g) < min_p:
                    donors = [gg for gg in groups if gg is not g
                              and len(gg) > min_p]
                    if not donors:
                        break
                    donor = max(donors, key=len)
                    best_p = min(donor,
                                 key=lambda p: self.sim.average_distance(p, g) if g else 0)
                    donor.remove(best_p)
                    g.append(best_p)
                    changed = True

        return [g for g in groups if g]

    # ── Step 1.3: Handle root orphans ──────────────────────────────

    def _handle_orphans(self, orphans: list[str]):
        """Handle papers that bubbled all the way to root."""
        if not orphans:
            return

        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        if len(orphans) >= min_p:
            if len(orphans) <= max_p:
                self._create_session(orphans, "Miscellaneous Topics",
                                     "Papers spanning diverse topics",
                                     self.root.node_id)
            else:
                leftovers = self._split_and_form(orphans, self.root)
                for pid in leftovers:
                    self._place_orphan(pid)
        else:
            for pid in orphans:
                self._place_orphan(pid)

    def _place_orphan(self, pid: str):
        """Place a single orphan paper in the best-fit existing session."""
        max_p = self.stc.max_papers

        if not self.sessions:
            self._create_session([pid], "Miscellaneous",
                                 "Orphan papers", self.root.node_id)
            return

        candidates = [s for s in self.sessions
                      if len(s.paper_ids) < max_p]
        if not candidates:
            self._create_session([pid], "Overflow",
                                 "Could not fit in existing sessions",
                                 self.root.node_id)
            self.edits.append(LastMileEdit(pid, None, self.sessions[-1].session_id,
                                           "root_orphan_overflow"))
            return

        best_s = max(candidates,
                     key=lambda s: self.sim.average_similarity(pid, s.paper_ids))
        best_s.paper_ids.append(pid)
        self.edits.append(LastMileEdit(pid, None, best_s.session_id,
                                       "root_orphan"))

    # ── Step 1.4: Session count adjustment ─────────────────────────

    def _adjust_session_count(self):
        """Adjust session count to match target T."""
        T = self.target_T
        K = len(self.sessions)

        if K == T:
            return

        if K > T:
            self._dissolve_sessions(K - T)
        elif K < T:
            self._create_new_sessions(T - K)

    def _dissolve_sessions(self, count: int):
        """Dissolve `count` sessions, reassigning papers. (Step 1.4a)"""
        max_p = self.stc.max_papers

        for _ in range(count):
            if len(self.sessions) <= 1:
                break

            scores = {}
            for s in self.sessions:
                others = [o for o in self.sessions if o is not s
                          and len(o.paper_ids) < max_p]
                if not others:
                    scores[s.session_id] = -1
                    continue
                avg = np.mean([
                    max(self.sim.average_similarity(pid, o.paper_ids) for o in others)
                    for pid in s.paper_ids
                ])
                scores[s.session_id] = avg

            target_sid = max(scores, key=lambda sid: (scores[sid], -len(
                next(s for s in self.sessions if s.session_id == sid).paper_ids)))
            target_s = next(s for s in self.sessions if s.session_id == target_sid)

            for pid in list(target_s.paper_ids):
                candidates = [s for s in self.sessions if s is not target_s
                              and len(s.paper_ids) < max_p]
                if not candidates:
                    break
                best = max(candidates,
                           key=lambda s: self.sim.average_similarity(pid, s.paper_ids))
                best.paper_ids.append(pid)
                self.edits.append(LastMileEdit(
                    pid, target_s.session_id, best.session_id, "session_dissolved"))

            self.sessions.remove(target_s)

    def _create_new_sessions(self, deficit: int):
        """Create `deficit` new sessions by extracting papers. (Step 1.4b)"""
        min_p = self.stc.min_papers

        papers_needed = deficit * min_p

        budgets = {s.session_id: max(0, len(s.paper_ids) - min_p)
                   for s in self.sessions}
        total_budget = sum(budgets.values())

        if total_budget < papers_needed:
            logger.warning(f"Cannot form {deficit} new sessions (budget={total_budget}, "
                           f"need={papers_needed}). Creating {total_budget // min_p} instead.")
            deficit = total_budget // min_p
            if deficit == 0:
                return
            papers_needed = deficit * min_p

        extracted = []
        for s in sorted(self.sessions, key=lambda s: budgets[s.session_id], reverse=True):
            while budgets[s.session_id] > 0 and len(extracted) < papers_needed:
                outlier = max(s.paper_ids,
                              key=lambda p: self.sim.average_distance(p, s.paper_ids))
                s.paper_ids.remove(outlier)
                extracted.append(outlier)
                self.edits.append(LastMileEdit(
                    outlier, s.session_id, "TBD", "extracted_for_new_session"))
                budgets[s.session_id] -= 1

        if len(extracted) < min_p:
            for pid in extracted:
                self._place_orphan(pid)
            return

        paper_infos = [{"id": pid, "title": self.papers[pid].title,
                        "abstract": self.papers[pid].abstract[:200]}
                       for pid in extracted if pid in self.papers]
        try:
            llm_groups = _llm.form_new_sessions(paper_infos, deficit, self.stc)
        except Exception:
            llm_groups = []

        if llm_groups and len(llm_groups) >= 1:
            for g in llm_groups:
                pids = [p for p in g.get("paper_ids", []) if p in self.papers]
                if pids:
                    self._create_session(pids, g.get("name", "New Session"),
                                         "Formed during session count adjustment",
                                         self.root.node_id)
                    for pid in pids:
                        for e in self.edits:
                            if e.paper_id == pid and e.target_session == "TBD":
                                e.target_session = self.sessions[-1].session_id
        else:
            groups = self._partition_papers(extracted, deficit)
            for i, group in enumerate(groups):
                self._create_session(group, f"New Session {i+1}",
                                     "Formed during session count adjustment",
                                     self.root.node_id)
                for pid in group:
                    for e in self.edits:
                        if e.paper_id == pid and e.target_session == "TBD":
                            e.target_session = self.sessions[-1].session_id

    # ── Helpers ────────────────────────────────────────────────────

    def _create_session(self, paper_ids: list[str], name: str,
                        description: str, node_id: str):
        self._session_counter += 1
        prefix = self.stc.session_id_prefix
        self.sessions.append(Session(
            session_id=f"{prefix}{self._session_counter:03d}",
            name=name,
            description=description,
            paper_ids=list(paper_ids),
            taxonomy_node_id=node_id,
        ))

    def _validate_capacity(self):
        """Log capacity violations. (Step 1.5)"""
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers
        for s in self.sessions:
            n = len(s.paper_ids)
            if n < min_p or n > max_p:
                logger.warning(f"Capacity violation: session '{s.name}' has "
                               f"{n} papers (expected {min_p}-{max_p})")


# ════════════════════════════════════════════════════════════════════
# METHOD 2: LCA-Based Optimization
# ════════════════════════════════════════════════════════════════════

class LCASessionFormer:
    """
    Formulate paper-to-session as constrained optimization using a
    taxonomy-derived LCA distance metric. Solve via ILP or heuristic.
    Then apply LLM pass for naming and suitability checking.
    Works identically for oral and poster (via SessionTypeConfig).
    """

    def __init__(self, papers: dict[str, Paper], sim: SimilarityEngine,
                 taxonomy_root: TaxonomyNode, stc: SessionTypeConfig = None):
        self.papers = papers
        self.sim = sim
        self.root = taxonomy_root
        self.stc = stc or SessionTypeConfig.oral()
        self.target_T = self.stc.target_sessions
        self.alpha = self.stc.alpha
        self._session_counter = 0
        self.sessions: list[Session] = []
        self.edits: list[LastMileEdit] = []

        self._node_map = _build_node_map(taxonomy_root)
        self._parent_map = _build_parent_map(taxonomy_root)
        self._paper_to_leaf: dict[str, str] = {}  # paper_id → leaf node_id

    def form_sessions(self) -> tuple[list[Session], list[LastMileEdit]]:
        """Stage 1: paper-to-session via LCA optimization."""
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        logger.info(f"LCA optimization ({self.stc.session_type}) | target T={self.target_T}, "
                    f"alpha={self.alpha}, solver={self.stc.solver}")

        paper_ids = sorted(self.papers.keys())
        N = len(paper_ids)
        T = self.target_T

        # Validate feasibility
        if T * min_p > N or T * max_p < N:
            logger.warning(f"Target T={T} may not be feasible with N={N} papers "
                           f"and session size [{min_p}, {max_p}]")
            T = max(1, min(T, N // min_p))

        # Step 2.1: Compute LCA distance matrix
        self._build_paper_to_leaf()
        self.sim.build_node_embeddings(self.root)
        d_final = self._compute_final_distance(paper_ids)

        # Step 2.2-2.3: Solve
        if self.stc.solver == "ilp":
            assignment = self._solve_ilp(paper_ids, d_final, T)
        else:
            assignment = self._solve_heuristic(paper_ids, d_final, T)

        # Build sessions from assignment
        groups: dict[int, list[str]] = defaultdict(list)
        for pid, s_idx in zip(paper_ids, assignment):
            groups[s_idx].append(pid)

        prefix = self.stc.session_id_prefix
        for s_idx in sorted(groups.keys()):
            self._session_counter += 1
            self.sessions.append(Session(
                session_id=f"{prefix}{self._session_counter:03d}",
                name=f"Session {self._session_counter}",
                description="",
                paper_ids=groups[s_idx],
            ))

        # Step 2.4: LLM post-processing
        self._llm_name_sessions()
        self._llm_suitability_check()

        # Step 2.5: Validate
        self._validate_capacity()

        logger.info(f"LCA formation complete: {len(self.sessions)} sessions, "
                    f"{len(self.edits)} edits")
        return self.sessions, self.edits

    # ── Step 2.1: LCA distance ─────────────────────────────────────

    def _build_paper_to_leaf(self):
        """Map each paper to its taxonomy leaf node."""
        def walk(node):
            if node.is_leaf:
                for pid in node.paper_ids:
                    self._paper_to_leaf[pid] = node.node_id
            for child in node.children:
                walk(child)
        walk(self.root)

    def _lca(self, nid_a: str, nid_b: str) -> str:
        """Find the lowest common ancestor of two nodes."""
        ancestors_a = set()
        n = nid_a
        while n:
            ancestors_a.add(n)
            parent = self._parent_map.get(n)
            n = parent.node_id if parent else None

        n = nid_b
        while n:
            if n in ancestors_a:
                return n
            parent = self._parent_map.get(n)
            n = parent.node_id if parent else None

        return self.root.node_id

    def _path_to_ancestor(self, nid: str, ancestor_id: str) -> list[tuple[str, str]]:
        """Return list of (parent_id, child_id) edges from nid up to ancestor."""
        edges = []
        n = nid
        while n != ancestor_id:
            parent = self._parent_map.get(n)
            if parent is None:
                break
            edges.append((parent.node_id, n))
            n = parent.node_id
        return edges

    def _edge_weight(self, parent_id: str, child_id: str) -> float:
        """Compute edge weight based on node embedding similarity."""
        cos_sim = self.sim.node_similarity(parent_id, child_id)
        return 1.0 - (cos_sim + 1.0) / 2.0

    def _compute_final_distance(self, paper_ids: list[str]) -> np.ndarray:
        """Compute the blended LCA + embedding distance matrix."""
        N = len(paper_ids)
        d_lca = np.zeros((N, N), dtype=np.float32)

        for i in range(N):
            for j in range(i + 1, N):
                leaf_i = self._paper_to_leaf.get(paper_ids[i])
                leaf_j = self._paper_to_leaf.get(paper_ids[j])
                if leaf_i and leaf_j:
                    lca_node = self._lca(leaf_i, leaf_j)
                    path_i = self._path_to_ancestor(leaf_i, lca_node)
                    path_j = self._path_to_ancestor(leaf_j, lca_node)
                    dist = sum(self._edge_weight(p, c) for p, c in path_i) + \
                           sum(self._edge_weight(p, c) for p, c in path_j)
                    d_lca[i, j] = d_lca[j, i] = dist

        # Blend with embedding distance
        if self.alpha < 1.0:
            d_embed = np.zeros((N, N), dtype=np.float32)
            for i in range(N):
                for j in range(i + 1, N):
                    d = self.sim.distance(paper_ids[i], paper_ids[j])
                    d_embed[i, j] = d_embed[j, i] = d
            d_final = self.alpha * d_lca + (1.0 - self.alpha) * d_embed
        else:
            d_final = d_lca

        return d_final

    # ── Step 2.3 Path A: ILP solver ────────────────────────────────

    def _solve_ilp(self, paper_ids: list[str], d: np.ndarray,
                   T: int) -> list[int]:
        """Exact ILP solver using PuLP/CBC."""
        try:
            import pulp
        except ImportError:
            logger.warning("PuLP not installed, falling back to heuristic")
            return self._solve_heuristic(paper_ids, d, T)

        min_p = self.stc.min_papers
        max_p = self.stc.max_papers

        N = len(paper_ids)
        prob = pulp.LpProblem("SessionAssignment", pulp.LpMinimize)

        # Decision variables
        x = {}
        for i in range(N):
            for s in range(T):
                x[i, s] = pulp.LpVariable(f"x_{i}_{s}", cat="Binary")

        z = {}
        for s in range(T):
            for i in range(N):
                for j in range(i + 1, N):
                    z[i, j, s] = pulp.LpVariable(f"z_{i}_{j}_{s}", cat="Binary")

        # Objective
        prob += pulp.lpSum(
            d[i, j] * z[i, j, s]
            for s in range(T) for i in range(N) for j in range(i + 1, N)
        )

        # C1: Each paper in exactly one session
        for i in range(N):
            prob += pulp.lpSum(x[i, s] for s in range(T)) == 1

        # C2, C3: Capacity bounds
        for s in range(T):
            prob += pulp.lpSum(x[i, s] for i in range(N)) >= min_p
            prob += pulp.lpSum(x[i, s] for i in range(N)) <= max_p

        # Linearization constraints
        for s in range(T):
            for i in range(N):
                for j in range(i + 1, N):
                    prob += z[i, j, s] <= x[i, s]
                    prob += z[i, j, s] <= x[j, s]
                    prob += z[i, j, s] >= x[i, s] + x[j, s] - 1

        # Solve
        solver = pulp.PULP_CBC_CMD(
            timeLimit=self.stc.ilp_time_limit,
            gapRel=self.stc.ilp_mip_gap,
            msg=0,
        )
        prob.solve(solver)

        if prob.status != pulp.constants.LpStatusOptimal:
            logger.warning(f"ILP solver status: {pulp.LpStatus[prob.status]}, "
                           f"falling back to heuristic")
            return self._solve_heuristic(paper_ids, d, T)

        # Extract assignment
        assignment = []
        for i in range(N):
            for s in range(T):
                if pulp.value(x[i, s]) > 0.5:
                    assignment.append(s)
                    break
            else:
                assignment.append(0)

        logger.info(f"ILP solved: objective={pulp.value(prob.objective):.4f}")
        return assignment

    # ── Step 2.3 Path B: Heuristic solver ──────────────────────────

    def _solve_heuristic(self, paper_ids: list[str], d: np.ndarray,
                         T: int) -> list[int]:
        """Heuristic: balanced k-means + local search refinement."""
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers
        N = len(paper_ids)

        # Step B1: Initial assignment via k-means on embeddings
        indices = [self.sim._id_to_idx.get(pid) for pid in paper_ids]
        valid = [i for i in indices if i is not None]
        if valid:
            emb = self.sim.embeddings[valid]
            from sklearn.cluster import KMeans
            km = KMeans(n_clusters=T, n_init=10, random_state=42)
            labels = km.fit_predict(emb)
            assignment = list(labels)
        else:
            assignment = [i % T for i in range(N)]

        # Step B2: Capacity repair
        assignment = self._repair_capacity(assignment, N, T)

        # Step B3: Local search — single-move refinement
        improved = True
        max_iter = 200
        iteration = 0
        while improved and iteration < max_iter:
            improved = False
            iteration += 1
            for i in range(N):
                cur_s = assignment[i]
                cur_cost = self._paper_session_cost(i, cur_s, assignment, d)
                cur_size = sum(1 for a in assignment if a == cur_s)

                for s_prime in range(T):
                    if s_prime == cur_s:
                        continue
                    target_size = sum(1 for a in assignment if a == s_prime)
                    if target_size >= max_p:
                        continue
                    if cur_size <= min_p:
                        continue

                    new_cost = self._paper_session_cost(i, s_prime, assignment, d)
                    if new_cost < cur_cost - 1e-6:
                        assignment[i] = s_prime
                        improved = True
                        break

        # Step B4: Pairwise swap refinement
        improved = True
        iteration = 0
        while improved and iteration < max_iter:
            improved = False
            iteration += 1
            for i in range(N):
                for j in range(i + 1, N):
                    si, sj = assignment[i], assignment[j]
                    if si == sj:
                        continue
                    cost_before = (self._paper_session_cost(i, si, assignment, d) +
                                   self._paper_session_cost(j, sj, assignment, d))
                    # Swap
                    assignment[i], assignment[j] = sj, si
                    cost_after = (self._paper_session_cost(i, sj, assignment, d) +
                                  self._paper_session_cost(j, si, assignment, d))
                    if cost_after < cost_before - 1e-6:
                        improved = True
                        break
                    else:
                        assignment[i], assignment[j] = si, sj  # revert
                if improved:
                    break

        logger.info(f"Heuristic solved in {iteration} iterations")
        return assignment

    def _paper_session_cost(self, paper_idx: int, session_idx: int,
                            assignment: list[int], d: np.ndarray) -> float:
        """Cost of paper_idx being in session_idx."""
        return sum(d[paper_idx, j] for j in range(len(assignment))
                   if assignment[j] == session_idx and j != paper_idx)

    def _repair_capacity(self, assignment: list[int], N: int, T: int) -> list[int]:
        """Repair capacity violations after initial assignment."""
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers
        assignment = list(assignment)

        # Fix oversized sessions
        for s in range(T):
            members = [i for i in range(N) if assignment[i] == s]
            while len(members) > max_p:
                smallest_s = min(range(T),
                                 key=lambda t: sum(1 for a in assignment if a == t))
                if smallest_s == s:
                    break
                paper_idx = members.pop()
                assignment[paper_idx] = smallest_s

        # Fix undersized sessions
        for s in range(T):
            members = [i for i in range(N) if assignment[i] == s]
            while len(members) < min_p:
                donors = [(t, sum(1 for a in assignment if a == t))
                          for t in range(T) if t != s]
                donors.sort(key=lambda x: -x[1])
                moved = False
                for donor_s, donor_size in donors:
                    if donor_size <= min_p:
                        continue
                    donor_members = [i for i in range(N) if assignment[i] == donor_s]
                    assignment[donor_members[-1]] = s
                    members.append(donor_members[-1])
                    moved = True
                    break
                if not moved:
                    break

        return assignment

    # ── Step 2.4: LLM post-processing ──────────────────────────────

    def _llm_name_sessions(self):
        """Name sessions using LLM. (Step 2.4a)"""
        stype = self.stc.session_type
        for s in self.sessions:
            node_counts = defaultdict(int)
            for pid in s.paper_ids:
                leaf = self._paper_to_leaf.get(pid)
                if leaf:
                    node_counts[leaf] += 1

            dominant_nid = max(node_counts, key=node_counts.get) if node_counts else None
            dominant_node = self._node_map.get(dominant_nid) if dominant_nid else None

            node_name = dominant_node.name if dominant_node else "General"
            node_desc = dominant_node.description if dominant_node else ""

            papers_info = [[{"title": self.papers[pid].title}
                            for pid in s.paper_ids if pid in self.papers]]
            try:
                names = _llm.name_sessions(node_name, node_desc, papers_info, 1,
                                           stype)
                s.name = names[0] if names else node_name
                s.description = node_desc
            except Exception:
                s.name = node_name
                s.description = node_desc

    def _llm_suitability_check(self):
        """Check suitability and reassign misfits. (Steps 2.4b, 2.4c)"""
        max_p = self.stc.max_papers
        stype = self.stc.session_type

        for s in list(self.sessions):
            papers_info = [{"id": pid, "title": self.papers[pid].title}
                           for pid in s.paper_ids if pid in self.papers]
            try:
                misfits = _llm.check_suitability(s.name, papers_info, stype)
            except Exception:
                misfits = []

            for m in misfits:
                pid = m.get("paper_id")
                if pid and pid in s.paper_ids:
                    candidates = [
                        {"name": o.name, "description": o.description,
                         "count": len(o.paper_ids), "sid": o.session_id}
                        for o in self.sessions
                        if o is not s and len(o.paper_ids) < max_p
                    ]
                    if not candidates:
                        continue

                    try:
                        idx = _llm.reassign_paper(self.papers[pid], candidates,
                                                  max_p)
                        target = next(o for o in self.sessions
                                      if o.session_id == candidates[idx]["sid"])
                        s.paper_ids.remove(pid)
                        target.paper_ids.append(pid)
                        self.edits.append(LastMileEdit(
                            pid, s.session_id, target.session_id,
                            f"llm_flagged: {m.get('reason', '')}"))
                    except Exception:
                        pass

    def _validate_capacity(self):
        min_p = self.stc.min_papers
        max_p = self.stc.max_papers
        for s in self.sessions:
            n = len(s.paper_ids)
            if n < min_p or n > max_p:
                logger.warning(f"Capacity violation: '{s.name}' has {n} papers "
                               f"(expected {min_p}-{max_p})")


# ════════════════════════════════════════════════════════════════════
# STAGE 2: Session-to-Slot Scheduling (Shared)
# ════════════════════════════════════════════════════════════════════

class SessionScheduler:
    """
    Assign sessions to time slots + tracks/areas.
    Minimizes audience overlap (soft) subject to presenter conflict (hard).
    Supports ILP and heuristic solvers. Works for both oral and poster.
    """

    def __init__(self, papers: dict[str, Paper], sim: SimilarityEngine,
                 stc: SessionTypeConfig = None):
        self.papers = papers
        self.sim = sim
        self.stc = stc or SessionTypeConfig.oral()
        self.num_slots = self.stc.num_slots
        self.num_tracks = self.stc.num_parallel
        self.conflict_report: list[dict] = []

    def schedule(self, sessions: list[Session]) -> list[Session]:
        """Assign time_slot and track to each session."""
        if not sessions:
            return sessions

        logger.info(f"Scheduling {len(sessions)} {self.stc.session_type} sessions "
                    f"into {self.num_slots} slots × {self.num_tracks} tracks")

        # Step 5.1: Build conflict graphs
        G_hard = self._build_hard_conflict_graph(sessions)
        G_soft = self._build_soft_conflict_graph(sessions)
        logger.info(f"Hard conflicts: {G_hard.number_of_edges()} edges, "
                    f"Soft conflicts: {G_soft.number_of_edges()} edges")

        # Step 5.2-5.3: Solve scheduling
        coloring = self._solve_scheduling(sessions, G_hard, G_soft)

        # Assign slots
        for s in sessions:
            s.time_slot = coloring.get(s.session_id, 0)

        # Step 5.4: Assign tracks within slots
        self._assign_tracks(sessions, G_soft)

        # Step 5.5: Validate
        self._validate(sessions)

        return sessions

    # ── Step 5.1: Conflict graphs ──────────────────────────────────

    def _build_hard_conflict_graph(self, sessions: list[Session]) -> nx.Graph:
        """Hard conflict: sessions sharing a presenter."""
        G = nx.Graph()
        for s in sessions:
            G.add_node(s.session_id)

        if not self.stc.enable_conflict_avoidance:
            return G  # Empty graph — no hard constraints

        author_sessions: dict[str, list[str]] = defaultdict(list)
        for s in sessions:
            for pid in s.paper_ids:
                if pid in self.papers:
                    for author in self.papers[pid].author_set():
                        author_sessions[author].append(s.session_id)

        for author, sids in author_sessions.items():
            unique_sids = list(set(sids))
            for i in range(len(unique_sids)):
                for j in range(i + 1, len(unique_sids)):
                    if not G.has_edge(unique_sids[i], unique_sids[j]):
                        G.add_edge(unique_sids[i], unique_sids[j],
                                   authors=set())
                    G[unique_sids[i]][unique_sids[j]]["authors"].add(author)

        return G

    def _build_soft_conflict_graph(self, sessions: list[Session]) -> nx.Graph:
        """Soft conflict: sessions with topically similar papers."""
        G = nx.Graph()
        for s in sessions:
            G.add_node(s.session_id)

        threshold = self.stc.audience_sim_threshold

        for i in range(len(sessions)):
            for j in range(i + 1, len(sessions)):
                si, sj = sessions[i], sessions[j]
                sims = []
                for pi in si.paper_ids:
                    for pj in sj.paper_ids:
                        sims.append(self.sim.similarity(pi, pj))
                avg_sim = np.mean(sims) if sims else 0.0

                if avg_sim > threshold:
                    G.add_edge(si.session_id, sj.session_id, weight=avg_sim)

        return G

    # ── Step 5.2-5.3: Solve ────────────────────────────────────────

    def _solve_scheduling(self, sessions: list[Session],
                          G_hard: nx.Graph, G_soft: nx.Graph) -> dict[str, int]:
        """Try ILP first, fall back to heuristic."""
        try:
            coloring = self._schedule_ilp(sessions, G_hard, G_soft)
            if coloring:
                return coloring
        except Exception as e:
            logger.info(f"ILP scheduling failed ({e}), using heuristic")

        return self._schedule_heuristic(sessions, G_hard, G_soft)

    def _schedule_ilp(self, sessions: list[Session],
                      G_hard: nx.Graph, G_soft: nx.Graph) -> Optional[dict[str, int]]:
        """ILP scheduling."""
        try:
            import pulp
        except ImportError:
            return None

        sids = [s.session_id for s in sessions]
        S = len(sids)
        T = self.num_slots
        sid_idx = {sid: i for i, sid in enumerate(sids)}

        prob = pulp.LpProblem("SessionScheduling", pulp.LpMinimize)

        # Variables
        y = {}
        for i in range(S):
            for t in range(T):
                y[i, t] = pulp.LpVariable(f"y_{i}_{t}", cat="Binary")

        u = {}
        for t in range(T):
            for i in range(S):
                for j in range(i + 1, S):
                    u[i, j, t] = pulp.LpVariable(f"u_{i}_{j}_{t}", cat="Binary")

        # Soft conflict weights
        soft_w = {}
        for i in range(S):
            for j in range(i + 1, S):
                if G_soft.has_edge(sids[i], sids[j]):
                    soft_w[i, j] = G_soft[sids[i]][sids[j]]["weight"]
                else:
                    soft_w[i, j] = 0.0

        # Objective: minimize audience overlap
        prob += pulp.lpSum(
            soft_w.get((i, j), 0) * u[i, j, t]
            for t in range(T) for i in range(S) for j in range(i + 1, S)
        )

        # S1: Each session in exactly one slot
        for i in range(S):
            prob += pulp.lpSum(y[i, t] for t in range(T)) == 1

        # S2: Track capacity per slot
        for t in range(T):
            prob += pulp.lpSum(y[i, t] for i in range(S)) <= self.num_tracks

        # S3: Hard presenter conflicts
        if self.stc.enable_conflict_avoidance:
            for sid_a, sid_b in G_hard.edges():
                ia, ib = sid_idx.get(sid_a), sid_idx.get(sid_b)
                if ia is not None and ib is not None:
                    for t in range(T):
                        prob += y[ia, t] + y[ib, t] <= 1

        # Linearization
        for t in range(T):
            for i in range(S):
                for j in range(i + 1, S):
                    prob += u[i, j, t] <= y[i, t]
                    prob += u[i, j, t] <= y[j, t]
                    prob += u[i, j, t] >= y[i, t] + y[j, t] - 1

        solver = pulp.PULP_CBC_CMD(timeLimit=60, gapRel=0.01, msg=0)
        prob.solve(solver)

        if prob.status not in (pulp.constants.LpStatusOptimal, 1):
            logger.info("ILP infeasible with hard constraints, relaxing...")
            return None

        coloring = {}
        for i in range(S):
            for t in range(T):
                if pulp.value(y[i, t]) > 0.5:
                    coloring[sids[i]] = t
                    break

        return coloring

    def _schedule_heuristic(self, sessions: list[Session],
                            G_hard: nx.Graph,
                            G_soft: nx.Graph) -> dict[str, int]:
        """DSatur-based heuristic with audience-aware tiebreaking."""
        coloring: dict[str, int] = {}
        uncolored = set(s.session_id for s in sessions)

        def saturation(sid):
            return len({coloring[nb] for nb in G_hard.neighbors(sid)
                        if nb in coloring})

        while uncolored:
            node = max(uncolored, key=lambda n: (saturation(n), G_hard.degree(n)))
            uncolored.remove(node)

            slot_scores = {}
            for t in range(self.num_slots):
                hard = sum(1 for nb in G_hard.neighbors(node)
                           if coloring.get(nb) == t)
                sessions_in_slot = sum(1 for v, c in coloring.items() if c == t)
                capacity_ok = sessions_in_slot < self.num_tracks
                soft = sum(G_soft[node][nb].get("weight", 0)
                           for nb in G_soft.neighbors(node)
                           if coloring.get(nb) == t)
                slot_scores[t] = (hard, 0 if capacity_ok else 1, soft)

            best_t = min(slot_scores, key=lambda t: slot_scores[t])
            coloring[node] = best_t

        return coloring

    # ── Step 5.4: Track assignment ─────────────────────────────────

    def _assign_tracks(self, sessions: list[Session], G_soft: nx.Graph):
        """Assign tracks within each slot, grouping similar sessions together."""
        slot_groups: dict[int, list[Session]] = defaultdict(list)
        for s in sessions:
            if s.time_slot is not None:
                slot_groups[s.time_slot].append(s)

        for slot, slot_sessions in slot_groups.items():
            if len(slot_sessions) > 1:
                centroids = {
                    s.session_id: self.sim.session_centroid(s.paper_ids)
                    for s in slot_sessions
                }
                ordered = [slot_sessions[0]]
                remaining = set(s.session_id for s in slot_sessions[1:])
                while remaining:
                    last_c = centroids[ordered[-1].session_id]
                    best = min(remaining,
                               key=lambda sid: np.linalg.norm(
                                   last_c - centroids[sid]))
                    remaining.remove(best)
                    ordered.append(next(s for s in slot_sessions
                                        if s.session_id == best))
                slot_sessions = ordered

            for track_idx, session in enumerate(slot_sessions):
                session.track = track_idx

    # ── Step 5.5: Validate ─────────────────────────────────────────

    def _validate(self, sessions: list[Session]):
        """Count remaining hard conflicts."""
        slot_sessions: dict[int, list[Session]] = defaultdict(list)
        for s in sessions:
            if s.time_slot is not None:
                slot_sessions[s.time_slot].append(s)

        total_conflicts = 0
        for slot, ss in slot_sessions.items():
            for i in range(len(ss)):
                for j in range(i + 1, len(ss)):
                    authors_i = ss[i].author_set(self.papers)
                    authors_j = ss[j].author_set(self.papers)
                    common = authors_i & authors_j
                    if common:
                        total_conflicts += len(common)
                        self.conflict_report.append({
                            "slot": slot,
                            "session_a": ss[i].session_id,
                            "session_b": ss[j].session_id,
                            "authors": list(common),
                        })

        if total_conflicts:
            logger.warning(f"Remaining hard conflicts: {total_conflicts}")
        else:
            logger.info("No hard conflicts in schedule.")


# ════════════════════════════════════════════════════════════════════
# LAST-MILE EDIT PROTOCOL (Section 6)
# ════════════════════════════════════════════════════════════════════

class LastMileEditor:
    """
    Resolve post-scheduling conflicts by moving papers between sessions.
    For poster sessions with enable_conflict_avoidance=False, only runs
    final validation (skips conflict repair).
    """

    def __init__(self, papers: dict[str, Paper], sim: SimilarityEngine,
                 stc: SessionTypeConfig = None):
        self.papers = papers
        self.sim = sim
        self.stc = stc or SessionTypeConfig.oral()
        self.edits: list[LastMileEdit] = []
        self._affected_sessions: set[str] = set()  # sessions whose papers changed

    @property
    def affected_session_ids(self) -> set[str]:
        """Session IDs that were modified during repair (for poster board re-layout)."""
        return self._affected_sessions

    def repair_conflicts(self, sessions: list[Session]) -> list[Session]:
        """Iteratively repair hard conflicts. (Steps 6.1-6.2)"""
        if not self.stc.enable_conflict_avoidance:
            return sessions

        max_iter = self.stc.max_repair_iterations
        max_p = self.stc.max_papers
        min_p = self.stc.min_papers
        session_map = {s.session_id: s for s in sessions}

        for iteration in range(max_iter):
            conflicts = self._find_conflicts(sessions)
            if not conflicts:
                logger.info(f"All conflicts resolved after {iteration} iterations")
                break

            # Step 6.2A: Select highest-priority conflict
            conflict = max(conflicts, key=lambda c: len(c["authors"]))

            # Step 6.2B: Select paper to move
            s_a = session_map[conflict["session_a"]]
            s_b = session_map[conflict["session_b"]]
            paper_to_move, source = self._select_paper_to_move(
                s_a, s_b, conflict["authors"])

            if paper_to_move is None:
                logger.warning(f"Cannot resolve conflict between "
                               f"'{s_a.name}' and '{s_b.name}'")
                continue

            # Step 6.2C: Identify valid targets
            valid_targets = self._find_valid_targets(
                paper_to_move, source, sessions)

            # Step 6.2D: Choose best target
            if valid_targets:
                best_target = max(
                    valid_targets,
                    key=lambda s: self.sim.average_similarity(
                        paper_to_move, s.paper_ids))

                source.paper_ids.remove(paper_to_move)
                best_target.paper_ids.append(paper_to_move)
                self.edits.append(LastMileEdit(
                    paper_to_move, source.session_id,
                    best_target.session_id, "conflict_repair"))
                self._affected_sessions.add(source.session_id)
                self._affected_sessions.add(best_target.session_id)
            else:
                swapped = self._try_swap(paper_to_move, source, sessions)
                if not swapped:
                    logger.warning(f"Unresolvable conflict for paper {paper_to_move}")

        return sessions

    def _find_conflicts(self, sessions: list[Session]) -> list[dict]:
        """Find all hard conflicts in the current schedule."""
        slot_sessions: dict[int, list[Session]] = defaultdict(list)
        for s in sessions:
            if s.time_slot is not None:
                slot_sessions[s.time_slot].append(s)

        conflicts = []
        for slot, ss in slot_sessions.items():
            for i in range(len(ss)):
                for j in range(i + 1, len(ss)):
                    common = ss[i].author_set(self.papers) & ss[j].author_set(self.papers)
                    if common:
                        conflicts.append({
                            "slot": slot,
                            "session_a": ss[i].session_id,
                            "session_b": ss[j].session_id,
                            "authors": common,
                        })
        return conflicts

    def _select_paper_to_move(self, s_a: Session, s_b: Session,
                              conflict_authors: set) -> tuple[Optional[str], Optional[Session]]:
        """Select the paper with worst fit that involves a conflicting author."""
        candidates = []
        for s in (s_a, s_b):
            for pid in s.paper_ids:
                if pid in self.papers:
                    p = self.papers[pid]
                    if p.author_set() & conflict_authors:
                        fit = self.sim.average_similarity(pid, s.paper_ids)
                        candidates.append((pid, s, fit))

        if not candidates:
            return None, None

        # Worst fit = lowest similarity
        candidates.sort(key=lambda x: x[2])
        return candidates[0][0], candidates[0][1]

    def _find_valid_targets(self, pid: str, source: Session,
                            sessions: list[Session]) -> list[Session]:
        """Find sessions where moving pid won't create new conflicts."""
        paper = self.papers.get(pid)
        if not paper:
            return []

        max_p = self.stc.max_papers
        paper_authors = paper.author_set()
        valid = []

        for s in sessions:
            if s is source:
                continue
            if len(s.paper_ids) >= max_p:
                continue

            creates_conflict = False
            if s.time_slot is not None:
                for other in sessions:
                    if (other is not s and other.time_slot == s.time_slot
                            and other is not source):
                        other_authors = other.author_set(self.papers)
                        if paper_authors & other_authors:
                            creates_conflict = True
                            break

            if not creates_conflict:
                valid.append(s)

        return valid

    def _try_swap(self, pid: str, source: Session,
                  sessions: list[Session]) -> bool:
        """Try swapping pid with a paper from a non-conflicting session."""
        min_p = self.stc.min_papers
        for target in sessions:
            if target is source or target.time_slot == source.time_slot:
                continue
            for qid in target.paper_ids:
                if (len(source.paper_ids) >= min_p and
                        len(target.paper_ids) >= min_p):
                    source.paper_ids.remove(pid)
                    target.paper_ids.remove(qid)
                    target.paper_ids.append(pid)
                    source.paper_ids.append(qid)

                    new_conflicts = self._find_conflicts(sessions)
                    if not new_conflicts:
                        self.edits.append(LastMileEdit(
                            pid, source.session_id, target.session_id,
                            "conflict_swap"))
                        self.edits.append(LastMileEdit(
                            qid, target.session_id, source.session_id,
                            "conflict_swap"))
                        self._affected_sessions.add(source.session_id)
                        self._affected_sessions.add(target.session_id)
                        return True
                    else:
                        # Revert
                        target.paper_ids.remove(pid)
                        source.paper_ids.remove(qid)
                        source.paper_ids.append(pid)
                        target.paper_ids.append(qid)

        return False


# ════════════════════════════════════════════════════════════════════
# FINAL VALIDATION (Section 6.3)
# ════════════════════════════════════════════════════════════════════

def final_validation(sessions: list[Session], papers: dict[str, Paper],
                     sim: SimilarityEngine,
                     stc: SessionTypeConfig = None) -> dict:
    """Run all final validation checks and compute statistics."""
    stc = stc or SessionTypeConfig.oral()

    report = {
        "capacity_violations": [],
        "conflict_violations": [],
        "coverage": {"total_papers": 0, "unique_assigned": 0, "duplicates": 0},
        "session_count": len(sessions),
        "target_count": stc.target_sessions,
        "stats": {},
    }

    # 1. Capacity check
    for s in sessions:
        n = len(s.paper_ids)
        if n < stc.min_papers or n > stc.max_papers:
            report["capacity_violations"].append({
                "session": s.session_id, "name": s.name,
                "size": n, "expected": f"{stc.min_papers}-{stc.max_papers}",
            })

    # 2. Conflict check
    slot_sessions: dict[int, list[Session]] = defaultdict(list)
    for s in sessions:
        if s.time_slot is not None:
            slot_sessions[s.time_slot].append(s)

    for slot, ss in slot_sessions.items():
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                common = ss[i].author_set(papers) & ss[j].author_set(papers)
                if common:
                    report["conflict_violations"].append({
                        "slot": slot,
                        "sessions": [ss[i].session_id, ss[j].session_id],
                        "authors": list(common),
                    })

    # 3. Coverage check
    all_assigned = []
    for s in sessions:
        all_assigned.extend(s.paper_ids)
    report["coverage"]["total_papers"] = len(papers)
    report["coverage"]["unique_assigned"] = len(set(all_assigned))
    report["coverage"]["duplicates"] = len(all_assigned) - len(set(all_assigned))

    # 4. Stats
    intra_sims = [sim.intra_session_similarity(s.paper_ids) for s in sessions]
    report["stats"]["avg_intra_session_similarity"] = float(np.mean(intra_sims)) if intra_sims else 0
    report["stats"]["capacity_violations"] = len(report["capacity_violations"])
    report["stats"]["hard_conflicts"] = len(report["conflict_violations"])
    report["stats"]["sessions_formed"] = len(sessions)

    return report


# ════════════════════════════════════════════════════════════════════
def _deduplicate_papers(sessions: list[Session],
                        papers_map: dict[str, Paper],
                        sim: SimilarityEngine) -> list[Session]:
    """Ensure each paper appears in exactly one session.

    If a paper is found in multiple sessions, it stays in the session
    where it has the highest average similarity to the other papers.
    """
    # Find duplicates
    paper_sessions: dict[str, list[int]] = {}  # paper_id -> [session indices]
    for i, s in enumerate(sessions):
        for pid in s.paper_ids:
            paper_sessions.setdefault(pid, []).append(i)

    duplicates = {pid: idxs for pid, idxs in paper_sessions.items() if len(idxs) > 1}
    if not duplicates:
        return sessions

    logger.warning(f"Found {len(duplicates)} papers in multiple sessions — deduplicating")

    for pid, session_idxs in duplicates.items():
        # Score each session by average similarity of this paper to the others
        best_idx = session_idxs[0]
        best_score = -1.0
        for si in session_idxs:
            other_pids = [p for p in sessions[si].paper_ids if p != pid]
            if not other_pids:
                continue
            try:
                avg_sim = sum(sim.similarity(pid, other) for other in other_pids) / len(other_pids)
            except Exception:
                avg_sim = 0.0
            if avg_sim > best_score:
                best_score = avg_sim
                best_idx = si

        # Remove from all other sessions
        for si in session_idxs:
            if si != best_idx:
                sessions[si].paper_ids = [p for p in sessions[si].paper_ids if p != pid]
                logger.info(f"  Removed duplicate paper {pid} from session '{sessions[si].name}' "
                            f"(kept in '{sessions[best_idx].name}')")

    # Remove empty sessions
    sessions = [s for s in sessions if s.paper_ids]

    return sessions


# ════════════════════════════════════════════════════════════════════
# TOP-LEVEL API
# ════════════════════════════════════════════════════════════════════

def _run_organization(papers: list[Paper], taxonomy_root: TaxonomyNode,
                      stc: SessionTypeConfig,
                      sim: SimilarityEngine = None) -> OrganizationResult:
    """
    Core pipeline shared by oral and poster.
    Stage 1 → (Stage 1.5 poster only, handled by caller) → Stage 2 → Last-Mile.
    """
    papers_map = {p.id: p for p in papers}

    # Preprocessing: build similarity engine
    if sim is None:
        logger.info("Building similarity engine...")
        sim = SimilarityEngine(papers_map)
        sim.build()

    # Stage 1: Paper → Session
    method = stc.method
    logger.info(f"Stage 1: Paper → Session (method={method}, type={stc.session_type})")

    if method == "optimization":
        former = LCASessionFormer(papers_map, sim, taxonomy_root, stc)
    else:
        former = GreedySessionFormer(papers_map, sim, taxonomy_root, stc)

    sessions, edits = former.form_sessions()

    # Deduplicate: ensure each paper appears in exactly one session
    sessions = _deduplicate_papers(sessions, papers_map, sim)

    # Stage 2: Session → Slot
    logger.info(f"Stage 2: Session → Slot ({stc.session_type})")
    scheduler = SessionScheduler(papers_map, sim, stc)
    sessions = scheduler.schedule(sessions)

    # Last-Mile Edits
    logger.info("Last-mile conflict repair...")
    editor = LastMileEditor(papers_map, sim, stc)
    sessions = editor.repair_conflicts(sessions)
    edits.extend(editor.edits)

    # Final validation
    report = final_validation(sessions, papers_map, sim, stc)

    logger.info(f"Organization complete ({stc.session_type}): "
                f"{len(sessions)} sessions, "
                f"{report['stats']['hard_conflicts']} conflicts, "
                f"{len(edits)} edits, "
                f"avg intra-sim={report['stats']['avg_intra_session_similarity']:.3f}")

    return OrganizationResult(
        sessions=sessions,
        session_type=stc.session_type,
        last_mile_edits=edits,
        capacity_report=report["capacity_violations"],
        conflict_report=report["conflict_violations"],
        stats=report["stats"],
    )


def run_oral_organization(papers: list[Paper],
                          taxonomy_root: TaxonomyNode) -> OrganizationResult:
    """Full oral session organization pipeline."""
    stc = SessionTypeConfig.oral()
    return _run_organization(papers, taxonomy_root, stc)


def run_poster_organization(papers: list[Paper],
                            taxonomy_root: TaxonomyNode,
                            sim: SimilarityEngine = None) -> OrganizationResult:
    """
    Full poster session organization pipeline.
    Stage 1 → Stage 1.5 (board layout) → Stage 2 → Last-Mile (with board re-layout).

    Stage 1.5 and board re-layout are handled by poster_organizer.py.
    This function only runs Stages 1, 2, and Last-Mile using poster config.
    Call poster_organizer.run_poster_pipeline() for the full pipeline with layout.
    """
    stc = SessionTypeConfig.poster()
    return _run_organization(papers, taxonomy_root, stc, sim)
