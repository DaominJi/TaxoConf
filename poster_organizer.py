"""
Poster session organizer — unified pipeline with board layout.

Pipeline:
  Stage 1:   Paper → Session  (shared with oral via SessionTypeConfig)
             Method 1 (Greedy) or Method 2 (LCA Optimization)
  Stage 1.5: Board Layout Optimization per session
             TSP/spectral per floor plan (line / circle / rectangle)
  Stage 2:   Session → Slot   (shared scheduler, conflict avoidance)
  Last-Mile: Iterative conflict repair
             Re-run Stage 1.5 for sessions affected by paper moves.

Cross-type scheduling (Section 7) merges oral + poster conflict graphs
when time slots overlap.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import networkx as nx

import config
from models import (Paper, Session, TaxonomyNode, PosterSession,
                    PosterAssignment, BoardPosition, FloorPlanType)
from similarity import SimilarityEngine
from floor_plan import FloorPlanOptimizer
from session_organizer import (
    SessionTypeConfig, GreedySessionFormer, LCASessionFormer,
    SessionScheduler, LastMileEditor, LastMileEdit,
    final_validation, OrganizationResult,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Poster-specific result
# ════════════════════════════════════════════════════════════════════

@dataclass
class PosterOrganizationResult:
    """Full output from the poster organizer, including board layout."""
    poster_sessions: list[PosterSession]
    organization: OrganizationResult  # underlying Stage 1/2/LM result
    floor_plan: FloorPlanType = FloorPlanType.RECTANGLE

    @property
    def sessions(self) -> list[PosterSession]:
        return self.poster_sessions

    @property
    def stats(self) -> dict:
        return self.organization.stats


# ════════════════════════════════════════════════════════════════════
# Stage 1.5: Board Layout Optimization
# ════════════════════════════════════════════════════════════════════

def _apply_board_layout(sessions: list[Session],
                        sim: SimilarityEngine,
                        floor_plan: FloorPlanType,
                        rect_cols: int,
                        enable_proximity: bool,
                        session_filter: set[str] = None,
                        ) -> dict[str, list[PosterAssignment]]:
    """
    Run Stage 1.5 board layout optimization for each session.

    Args:
        sessions:        List of Session objects from Stage 1.
        sim:             SimilarityEngine (must be built).
        floor_plan:      Layout type (LINE, CIRCLE, RECTANGLE).
        rect_cols:       Columns per row for RECTANGLE layout.
        enable_proximity: Whether to run TSP/spectral optimization.
        session_filter:  If given, only optimize these session IDs.

    Returns:
        Dict mapping session_id → list[PosterAssignment] with optimized
        board positions.
    """
    layouts: dict[str, list[PosterAssignment]] = {}

    for session in sessions:
        if session_filter and session.session_id not in session_filter:
            continue

        paper_ids = list(session.paper_ids)
        n = len(paper_ids)

        if n == 0:
            layouts[session.session_id] = []
            continue

        if n < 2 or not enable_proximity:
            # Trivial layout: sequential assignment
            layouts[session.session_id] = [
                PosterAssignment(pid, BoardPosition(index=i))
                for i, pid in enumerate(paper_ids)
            ]
            continue

        # Get similarity sub-matrix for this session's papers
        ordered_ids, sub_sim = sim.submatrix(paper_ids)

        # Run FloorPlanOptimizer
        optimizer = FloorPlanOptimizer(
            sim_matrix=sub_sim,
            paper_ids=ordered_ids,
            floor_plan=floor_plan,
            rect_cols=rect_cols,
        )
        layouts[session.session_id] = optimizer.optimize()

    return layouts


# ════════════════════════════════════════════════════════════════════
# Session → PosterSession conversion
# ════════════════════════════════════════════════════════════════════

def _convert_to_poster_sessions(
        sessions: list[Session],
        layouts: dict[str, list[PosterAssignment]],
        floor_plan: FloorPlanType,
) -> list[PosterSession]:
    """Convert Session objects to PosterSession objects with board assignments."""
    poster_sessions = []
    for s in sessions:
        assignments = layouts.get(s.session_id, [])
        if not assignments:
            # Fallback: create default assignments
            assignments = [
                PosterAssignment(pid, BoardPosition(index=i))
                for i, pid in enumerate(s.paper_ids)
            ]

        ps = PosterSession(
            session_id=s.session_id,
            name=s.name,
            description=s.description,
            time_slot=s.time_slot,
            area=s.track,  # track → area mapping
            assignments=assignments,
            taxonomy_node_ids=[s.taxonomy_node_id] if s.taxonomy_node_id else [],
            floor_plan=floor_plan,
        )
        poster_sessions.append(ps)

    return poster_sessions


# ════════════════════════════════════════════════════════════════════
# Cross-Type Scheduling (Section 7)
# ════════════════════════════════════════════════════════════════════

def cross_type_schedule(
        oral_sessions: list[Session],
        poster_sessions: list[Session],
        papers: dict[str, Paper],
        sim: SimilarityEngine,
        oral_stc: SessionTypeConfig = None,
        poster_stc: SessionTypeConfig = None,
) -> tuple[list[Session], list[Session]]:
    """
    Joint oral+poster scheduling when time slots overlap.

    Merges hard/soft conflict graphs from both types and schedules
    them jointly. Oral sessions are assigned to oral slots/tracks;
    poster sessions to poster slots/areas. The unified conflict graph
    ensures no presenter has simultaneous obligations across types.

    Args:
        oral_sessions:   Oral sessions (Stage 1 done, no slot assigned yet).
        poster_sessions: Poster sessions (Stage 1 done, no slot assigned yet).
        papers:          All papers.
        sim:             SimilarityEngine.
        oral_stc:        Oral SessionTypeConfig.
        poster_stc:      Poster SessionTypeConfig.

    Returns:
        (oral_sessions, poster_sessions) with time_slot and track/area assigned.
    """
    oral_stc = oral_stc or SessionTypeConfig.oral()
    poster_stc = poster_stc or SessionTypeConfig.poster()

    if not oral_sessions or not poster_sessions:
        logger.info("Cross-type scheduling skipped: one type is empty")
        return oral_sessions, poster_sessions

    logger.info(f"Cross-type scheduling: {len(oral_sessions)} oral + "
                f"{len(poster_sessions)} poster sessions")

    # Total slots = max(oral_slots, poster_slots) to unify the timeline
    total_slots = max(oral_stc.num_slots, poster_stc.num_slots)

    all_sessions = oral_sessions + poster_sessions
    oral_ids = {s.session_id for s in oral_sessions}
    poster_ids = {s.session_id for s in poster_sessions}

    # Build unified hard conflict graph (presenter conflicts across ALL sessions)
    G_hard = nx.Graph()
    for s in all_sessions:
        G_hard.add_node(s.session_id)

    author_sessions: dict[str, list[str]] = defaultdict(list)
    for s in all_sessions:
        for pid in s.paper_ids:
            if pid in papers:
                for author in papers[pid].author_set():
                    author_sessions[author].append(s.session_id)

    for author, sids in author_sessions.items():
        unique_sids = list(set(sids))
        for i in range(len(unique_sids)):
            for j in range(i + 1, len(unique_sids)):
                if not G_hard.has_edge(unique_sids[i], unique_sids[j]):
                    G_hard.add_edge(unique_sids[i], unique_sids[j],
                                    authors=set())
                G_hard[unique_sids[i]][unique_sids[j]]["authors"].add(author)

    logger.info(f"  Unified hard conflict graph: {G_hard.number_of_edges()} edges")

    # Build unified soft conflict graph (audience overlap)
    G_soft = nx.Graph()
    for s in all_sessions:
        G_soft.add_node(s.session_id)

    threshold = min(oral_stc.audience_sim_threshold,
                    poster_stc.audience_sim_threshold)

    for i in range(len(all_sessions)):
        for j in range(i + 1, len(all_sessions)):
            si, sj = all_sessions[i], all_sessions[j]
            sims = []
            for pi in si.paper_ids:
                for pj in sj.paper_ids:
                    sims.append(sim.similarity(pi, pj))
            avg_sim = np.mean(sims) if sims else 0.0
            if avg_sim > threshold:
                G_soft.add_edge(si.session_id, sj.session_id, weight=avg_sim)

    # DSatur heuristic with type-aware capacity constraints
    coloring: dict[str, int] = {}
    uncolored = set(s.session_id for s in all_sessions)

    def saturation(sid):
        return len({coloring[nb] for nb in G_hard.neighbors(sid)
                    if nb in coloring})

    while uncolored:
        node = max(uncolored, key=lambda n: (saturation(n), G_hard.degree(n)))
        uncolored.remove(node)

        is_oral = node in oral_ids
        stc = oral_stc if is_oral else poster_stc
        max_parallel = stc.num_parallel

        slot_scores = {}
        for t in range(total_slots):
            # Hard conflict count
            hard = sum(1 for nb in G_hard.neighbors(node)
                       if coloring.get(nb) == t)

            # Type-specific capacity check
            same_type_in_slot = sum(
                1 for sid, c in coloring.items()
                if c == t and (sid in oral_ids) == is_oral
            )
            capacity_ok = same_type_in_slot < max_parallel

            # Soft conflict weight
            soft = sum(G_soft[node][nb].get("weight", 0)
                       for nb in G_soft.neighbors(node)
                       if coloring.get(nb) == t)

            slot_scores[t] = (hard, 0 if capacity_ok else 1, soft)

        best_t = min(slot_scores, key=lambda t: slot_scores[t])
        coloring[node] = best_t

    # Assign slots and tracks/areas
    oral_slot_counters: dict[int, int] = defaultdict(int)
    poster_slot_counters: dict[int, int] = defaultdict(int)

    for s in all_sessions:
        s.time_slot = coloring.get(s.session_id, 0)
        if s.session_id in oral_ids:
            s.track = oral_slot_counters[s.time_slot] % oral_stc.num_parallel
            oral_slot_counters[s.time_slot] += 1
        else:
            s.track = poster_slot_counters[s.time_slot] % poster_stc.num_parallel
            poster_slot_counters[s.time_slot] += 1

    # Count cross-type conflicts
    cross_conflicts = 0
    slot_groups: dict[int, list[Session]] = defaultdict(list)
    for s in all_sessions:
        slot_groups[s.time_slot].append(s)

    for slot, ss in slot_groups.items():
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                # Only count cross-type conflicts
                i_oral = ss[i].session_id in oral_ids
                j_oral = ss[j].session_id in oral_ids
                if i_oral != j_oral:
                    common = ss[i].author_set(papers) & ss[j].author_set(papers)
                    if common:
                        cross_conflicts += len(common)

    logger.info(f"  Cross-type conflicts remaining: {cross_conflicts}")
    return oral_sessions, poster_sessions


# ════════════════════════════════════════════════════════════════════
# Full Poster Pipeline
# ════════════════════════════════════════════════════════════════════

def run_poster_pipeline(
    papers: list[Paper],
    taxonomy_root: TaxonomyNode,
    floor_plan: FloorPlanType = None,
    rect_cols: int = None,
    enable_proximity: bool = None,
    avoid_conflicts: bool = None,
    num_slots: int = None,
    num_parallel: int = None,
    sim: SimilarityEngine = None,
    oral_sessions: list[Session] = None,
) -> PosterOrganizationResult:
    """
    Full poster session organization pipeline.

    Stage 1:   Paper → Session (greedy or LCA optimization)
    Stage 1.5: Board layout optimization per session
    Stage 2:   Session → Slot scheduling
    Last-Mile: Conflict repair + board re-layout for affected sessions

    Optionally performs cross-type scheduling with oral sessions (Section 7)
    if `oral_sessions` is provided and `config.ENABLE_CROSS_TYPE_SCHEDULING`
    is True.

    Args:
        papers:           List of Paper objects (poster papers).
        taxonomy_root:    Pre-built taxonomy tree.
        floor_plan:       FloorPlanType override (LINE, CIRCLE, RECTANGLE).
        rect_cols:        Columns per row for RECTANGLE layout.
        enable_proximity: Whether to optimize board positions by similarity.
        avoid_conflicts:  Whether to avoid author conflicts across parallel sessions.
        num_slots:        Number of poster time slots.
        num_parallel:     Number of parallel poster areas.
        sim:              Pre-built SimilarityEngine (shared with oral).
        oral_sessions:    Oral sessions for cross-type scheduling (Section 7).

    Returns:
        PosterOrganizationResult with poster sessions, board layouts, and stats.
    """
    papers_map = {p.id: p for p in papers}

    # Resolve config overrides
    fp = floor_plan or FloorPlanType(config.POSTER_FLOOR_PLAN)
    rc = rect_cols or config.POSTER_RECT_COLS
    prox = enable_proximity if enable_proximity is not None else config.POSTER_PROXIMITY

    # Apply overrides to config before building SessionTypeConfig
    if avoid_conflicts is not None:
        config.POSTER_ENABLE_CONFLICT_AVOIDANCE = avoid_conflicts
    if num_slots is not None:
        config.POSTER_NUM_SLOTS = num_slots
    if num_parallel is not None:
        config.POSTER_NUM_PARALLEL = num_parallel

    stc = SessionTypeConfig.poster()

    # ── Preprocessing: build similarity engine ──
    if sim is None:
        logger.info("Building similarity engine for poster sessions...")
        sim = SimilarityEngine(papers_map)
        sim.build()

    # ── Stage 1: Paper → Session ──
    method = stc.method
    logger.info(f"Stage 1: Paper → Session (method={method}, type=poster)")

    if method == "optimization":
        former = LCASessionFormer(papers_map, sim, taxonomy_root, stc)
    else:
        former = GreedySessionFormer(papers_map, sim, taxonomy_root, stc)

    sessions, edits = former.form_sessions()
    logger.info(f"  Stage 1 complete: {len(sessions)} sessions formed")

    # ── Stage 1.5: Board Layout Optimization ──
    logger.info(f"Stage 1.5: Board layout ({fp.value}, proximity={prox})")
    layouts = _apply_board_layout(sessions, sim, fp, rc, prox)
    logger.info(f"  Layouts computed for {len(layouts)} sessions")

    # ── Stage 2: Session → Slot Scheduling ──
    if config.ENABLE_CROSS_TYPE_SCHEDULING and oral_sessions:
        # Section 7: Joint oral+poster scheduling
        logger.info("Stage 2: Cross-type scheduling (oral + poster)")
        oral_stc = SessionTypeConfig.oral()
        _, sessions = cross_type_schedule(
            oral_sessions, sessions, papers_map, sim, oral_stc, stc)
    else:
        logger.info(f"Stage 2: Session → Slot (poster)")
        scheduler = SessionScheduler(papers_map, sim, stc)
        sessions = scheduler.schedule(sessions)

    # ── Last-Mile Edit Protocol ──
    logger.info("Last-mile conflict repair (poster)...")
    editor = LastMileEditor(papers_map, sim, stc)
    sessions = editor.repair_conflicts(sessions)
    edits.extend(editor.edits)

    # Re-run Stage 1.5 for affected sessions
    affected = editor.affected_session_ids
    if affected and prox:
        logger.info(f"  Re-running board layout for {len(affected)} affected sessions")
        updated_layouts = _apply_board_layout(
            sessions, sim, fp, rc, prox, session_filter=affected)
        layouts.update(updated_layouts)

    # ── Final Validation ──
    report = final_validation(sessions, papers_map, sim, stc)

    logger.info(f"Poster organization complete: "
                f"{len(sessions)} sessions, "
                f"{report['stats']['hard_conflicts']} conflicts, "
                f"{len(edits)} edits, "
                f"avg intra-sim={report['stats']['avg_intra_session_similarity']:.3f}")

    # ── Convert to PosterSession objects ──
    poster_sessions = _convert_to_poster_sessions(sessions, layouts, fp)

    org_result = OrganizationResult(
        sessions=sessions,
        session_type="poster",
        last_mile_edits=edits,
        capacity_report=report["capacity_violations"],
        conflict_report=report["conflict_violations"],
        stats=report["stats"],
    )

    return PosterOrganizationResult(
        poster_sessions=poster_sessions,
        organization=org_result,
        floor_plan=fp,
    )
