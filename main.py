"""
Main entry point: Papers → Taxonomy → Oral/Poster Sessions → Schedule.

Usage:
  # Oral sessions (demo)
  python main.py --mode oral --demo

  # Poster sessions (demo, rectangle layout with proximity)
  python main.py --mode poster --demo --floor_plan rectangle --proximity

  # Full pipeline with real data
  python main.py --mode both --input papers.json --proximity --floor_plan circle

Options:
  --input           Path to papers JSON file
  --output_dir      Output directory (default: output)
  --mode            "oral", "poster", or "both" (default: both)
  --max_depth       Maximum taxonomy depth (default: 3)
  --demo            Run with synthetic demo data (no LLM needed)

  Oral options:
    --session_min   Min papers per oral session (default: 3)
    --session_max   Max papers per oral session (default: 5)
    --oral_slots    Number of oral time slots (default: 8)
    --oral_tracks   Number of parallel oral tracks (default: 4)

  Poster options:
    --poster_slots     Number of poster time slots (default: 3)
    --poster_parallel  Number of parallel poster areas (default: 2)
    --floor_plan       Board layout: line, circle, rectangle (default: rectangle)
    --rect_cols        Columns per row in rectangle layout (default: 6)
    --proximity        Enable proximity-based board placement
    --no_proximity     Disable proximity-based board placement
    --poster_conflicts Enable author conflict avoidance for posters
    --no_poster_conflicts  Disable author conflict avoidance for posters
    --circle_right_priority  Prioritize right-side similarity in circle (default)
    --no_circle_right_priority  Use symmetric circle optimization
"""
import argparse
import json
import logging
import os
import sys
from collections import defaultdict

import config
from models import Paper, Session, PosterSession, FloorPlanType, TaxonomyNode
from taxonomy_builder import (TaxonomyBuilder, LLMClient, print_taxonomy,
                              collect_leaves, render_taxonomy,
                              export_taxonomy_readable, export_taxonomy_html)
from session_organizer import run_oral_organization, OrganizationResult
from poster_organizer import run_poster_pipeline, PosterOrganizationResult
from token_tracker import get_global_tracker, reset_global_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# I/O
# ════════════════════════════════════════════════════════════════════

def load_papers(path: str) -> list[Paper]:
    """Load papers from JSON.

    Supports two input formats:
      1. Session-organizer format:
         {"id": "p01", "title": "...", "abstract": "...", "authors": ["A", "B"]}
      2. SIGIR / PaperCrawler format:
         {"id": 1, "title": "...", "authors": "A, B, C"}
         Abstract may be absent; if a companion metadata file exists in the same
         directory (*_With_Metadata.json), abstracts are merged automatically.
    """
    with open(path) as f:
        data = json.load(f)

    # Try to load abstracts from a companion metadata file
    parent_dir = os.path.dirname(path)
    abstract_lookup: dict[str, str] = {}
    for candidate in os.listdir(parent_dir):
        if candidate.endswith("_With_Metadata.json"):
            meta_path = os.path.join(parent_dir, candidate)
            try:
                with open(meta_path) as mf:
                    meta = json.load(mf)
                for m in meta:
                    if m.get("abstract"):
                        abstract_lookup[m["title"]] = m["abstract"]
                logger.info(f"Loaded {len(abstract_lookup)} abstracts from {candidate}")
            except Exception:
                pass
            break

    papers = []
    for e in data:
        # Normalize id to str
        paper_id = str(e["id"])

        # Normalize authors: accept both list[str] and comma-separated str
        raw_authors = e.get("authors", [])
        if isinstance(raw_authors, str):
            authors = [a.strip() for a in raw_authors.split(",") if a.strip()]
        else:
            authors = raw_authors

        # Get abstract: from the entry itself, or from the metadata lookup
        abstract = e.get("abstract", "")
        if not abstract:
            abstract = abstract_lookup.get(e.get("title", ""), "")

        papers.append(Paper(id=paper_id, title=e["title"],
                            abstract=abstract, authors=authors))

    logger.info(f"Loaded {len(papers)} papers from {path}")
    return papers


def taxonomy_to_dict(node: TaxonomyNode) -> dict:
    d = {
        "node_id": node.node_id, "name": node.name,
        "description": node.description, "paper_ids": node.paper_ids,
        "is_leaf": node.is_leaf, "depth": node.depth,
    }
    if node.children:
        d["children"] = [taxonomy_to_dict(c) for c in node.children]
    return d


def save_oral_schedule(result: OrganizationResult, papers: dict[str, Paper],
                       taxonomy_json: dict, path: str):
    """Save the full oral organization result to JSON."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sessions = result.sessions
    schedule = {
        "type": "oral",
        "method": config.ORAL_METHOD,
        "taxonomy": taxonomy_json,
        "sessions": [],
        "summary": {
            "total_papers": sum(len(s.paper_ids) for s in sessions),
            "total_sessions": len(sessions),
            "time_slots_used": len({s.time_slot for s in sessions
                                    if s.time_slot is not None}),
        },
        "stats": result.stats,
        "last_mile_edits": [e.to_dict() for e in result.last_mile_edits],
        "capacity_report": result.capacity_report,
        "conflict_report": result.conflict_report,
    }
    for s in sorted(sessions, key=lambda s: (s.time_slot or 0, s.track or 0)):
        schedule["sessions"].append({
            "session_id": s.session_id, "name": s.name,
            "description": s.description,
            "time_slot": s.time_slot, "track": s.track,
            "papers": [{"id": pid, "title": papers[pid].title,
                        "authors": papers[pid].authors}
                       for pid in s.paper_ids if pid in papers],
        })
    with open(path, "w") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)
    logger.info(f"Oral schedule saved to {path}")


def save_poster_schedule(sessions: list[PosterSession], papers: dict[str, Paper],
                         taxonomy_json: dict, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    schedule = {
        "type": "poster",
        "taxonomy": taxonomy_json,
        "sessions": [],
        "summary": {
            "total_papers": sum(len(s.assignments) for s in sessions),
            "total_sessions": len(sessions),
            "time_slots_used": len({s.time_slot for s in sessions
                                    if s.time_slot is not None}),
            "floor_plan": sessions[0].floor_plan.value if sessions else "N/A",
        },
    }
    for s in sorted(sessions, key=lambda s: (s.time_slot or 0, s.area or 0)):
        session_data = {
            "session_id": s.session_id, "name": s.name,
            "description": s.description,
            "time_slot": s.time_slot, "area": s.area,
            "floor_plan": s.floor_plan.value,
            "boards": [],
        }
        for a in s.assignments:
            p = papers.get(a.paper_id)
            board_data = {
                "paper_id": a.paper_id,
                "title": p.title if p else "?",
                "authors": p.authors if p else [],
                "board_index": a.board.index,
            }
            if a.board.row is not None:
                board_data["row"] = a.board.row
                board_data["col"] = a.board.col
            if a.board.angle is not None:
                board_data["angle"] = round(a.board.angle, 1)
            session_data["boards"].append(board_data)
        schedule["sessions"].append(session_data)

    with open(path, "w") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)
    logger.info(f"Poster schedule saved to {path}")


# ════════════════════════════════════════════════════════════════════
# Demo data (30 papers with rich overlap for poster demos)
# ════════════════════════════════════════════════════════════════════

def generate_demo_papers() -> list[Paper]:
    """Generate 30 synthetic papers spanning 6 research areas with author overlaps."""
    demo = [
        # ── Query Optimization (5 papers) ──
        Paper("p01", "Learned Cost Models for Query Optimization",
              "We train a neural network to predict query execution costs, enabling the optimizer to make better plan choices.",
              ["Alice Chen", "Bob Zhang"]),
        Paper("p02", "Reinforcement Learning for Join Order Selection",
              "We model join enumeration as an MDP and solve it with deep Q-learning for complex multi-way joins.",
              ["Alice Chen", "Carol Li"]),
        Paper("p03", "Adaptive Query Re-Optimization Using Runtime Feedback",
              "Mid-query replanning based on cardinality estimation errors detected during execution.",
              ["David Wang", "Eve Liu"]),
        Paper("p04", "Cardinality Estimation with Graph Neural Networks",
              "GNN-based approach that captures join graph structure for better cardinality estimates.",
              ["Bob Zhang", "Frank Zhao"]),
        Paper("p05", "Parametric Query Optimization via Workload Embeddings",
              "Workload-aware optimization using embedding representations of query patterns.",
              ["Carol Li", "Grace Wu"]),

        # ── Vector Search (4 papers) ──
        Paper("p06", "High-Dimensional ANN Search with Learned Hashing",
              "We learn hash functions that adapt to data distribution for faster approximate nearest neighbor queries.",
              ["Grace Wu", "Henry Xu"]),
        Paper("p07", "GPU-Accelerated Vector Search for Billion-Scale Datasets",
              "CUDA-optimized proximity graph traversal for real-time vector search at scale.",
              ["Grace Wu", "Ivan Patel"]),
        Paper("p08", "Filtered Vector Search: Combining Metadata Predicates with ANN",
              "Efficient pre-filtering and post-filtering strategies for hybrid metadata-vector queries.",
              ["Jack Ma", "Kelly Sun"]),
        Paper("p09", "Product Quantization Revisited: Residual Codebooks for Dense Retrieval",
              "Improved PQ with residual learning for compact embedding compression in retrieval systems.",
              ["Henry Xu", "Leo Park"]),

        # ── Transaction Processing (5 papers) ──
        Paper("p10", "Deterministic Concurrency Control for Multi-Core OLTP",
              "A deterministic protocol that eliminates aborts in high-contention OLTP workloads.",
              ["Leo Park", "Mia Chen"]),
        Paper("p11", "Disaggregated Memory Transactions in Cloud-Native Databases",
              "RDMA-based remote memory transactions for CXL-attached disaggregated storage.",
              ["Leo Park", "Nina Huang"]),
        Paper("p12", "Hybrid OLTP/OLAP on Modern Hardware: An HTAP Perspective",
              "Combining fresh OLTP data with columnar OLAP scans in a single engine for real-time analytics.",
              ["Oscar Tan", "Mia Chen"]),
        Paper("p13", "Epoch-Based Isolation for Serializable Multi-Version Concurrency",
              "An epoch-based MVCC scheme providing serializable isolation with minimal overhead.",
              ["Nina Huang", "Pat Reeves"]),
        Paper("p14", "Persistent Memory Transactions with Hardware Log Offloading",
              "Leveraging Intel Optane PMem and hardware log offloading for durable transactions.",
              ["Oscar Tan", "Quincy Ng"]),

        # ── Data Integration / Data Lakes (5 papers) ──
        Paper("p15", "Schema Matching at Scale with Pre-Trained Language Models",
              "Fine-tuning BERT for column-level schema matching across enterprise data lakes.",
              ["David Wang", "Quincy Ng"]),
        Paper("p16", "Entity Resolution via Contrastive Learning",
              "Self-supervised entity matching using data augmentation and contrastive loss functions.",
              ["Rachel Kim", "Sam Lee"]),
        Paper("p17", "Integrable Set Discovery in Data Lakes",
              "Detecting groups of tables that can be meaningfully unioned or joined in data lake settings.",
              ["Rachel Kim", "Tom Jiang"]),
        Paper("p18", "Holistic Data Profiling for Automated Data Discovery",
              "End-to-end profiling combining statistics, patterns, and semantics for automated dataset discovery.",
              ["Sam Lee", "Uma Sharma"]),
        Paper("p19", "Federated Table Search Across Organizational Boundaries",
              "Privacy-preserving table search using secure sketching across multiple data owners.",
              ["Tom Jiang", "Victor Gao"]),

        # ── LLM + DB (6 papers) ──
        Paper("p20", "Text-to-SQL with Chain-of-Thought Prompting",
              "Multi-step reasoning improves LLM-generated SQL accuracy on complex queries.",
              ["Uma Sharma", "Victor Gao"]),
        Paper("p21", "LLM-Augmented Data Cleaning Pipelines",
              "Using GPT-4 to detect and repair semantic data quality issues in relational data.",
              ["Uma Sharma", "Wendy Zhou"]),
        Paper("p22", "Natural Language Interfaces for Knowledge Graphs",
              "KGQA system combining LLM parsing with graph pattern matching for QA.",
              ["Xavier Qin", "Yara Osman"]),
        Paper("p23", "Retrieval-Augmented Generation for Database Documentation",
              "RAG pipelines that ground LLM answers in schema metadata and query logs.",
              ["Victor Gao", "Zach Ye"]),
        Paper("p24", "Self-Debugging SQL with LLM Feedback Loops",
              "Iterative LLM-based SQL repair using execution error messages and schema constraints.",
              ["Wendy Zhou", "Alice Chen"]),
        Paper("p25", "Benchmarking LLMs on Complex Analytical SQL Queries",
              "Comprehensive evaluation of 12 LLMs on TPC-DS-derived natural language queries.",
              ["Xavier Qin", "Bob Zhang"]),

        # ── Graph Analytics (5 papers) ──
        Paper("p26", "Streaming Graph Partitioning for Distributed Analytics",
              "An online algorithm for balanced graph partitioning with bounded edge cuts.",
              ["Zach Ye", "Alice Chen"]),
        Paper("p27", "Temporal Graph Neural Networks for Dynamic Relationship Prediction",
              "TGN model capturing temporal evolution of edges in financial transaction networks.",
              ["Zach Ye", "Bob Zhang"]),
        Paper("p28", "Subgraph Matching on Property Graphs with Attributed Edges",
              "Efficient subgraph isomorphism with attribute predicates on both nodes and edges.",
              ["Frank Zhao", "Kelly Sun"]),
        Paper("p29", "Distributed Triangle Counting in Trillion-Edge Graphs",
              "MapReduce-based approach for exact triangle counting with provable communication bounds.",
              ["Jack Ma", "Eve Liu"]),
        Paper("p30", "Graph Database Query Optimization via Worst-Case Optimal Joins",
              "Integrating worst-case optimal join algorithms into a native graph query engine.",
              ["Frank Zhao", "David Wang"]),
    ]
    logger.info(f"Generated {len(demo)} demo papers with author overlaps")
    return demo


def build_demo_taxonomy(papers: list[Paper]) -> TaxonomyNode:
    """Build a hard-coded 2-level taxonomy for demo (no LLM)."""
    groups = {
        "Query Optimization": {
            "desc": "Learned and adaptive query optimization techniques",
            "pids": ["p01", "p02", "p03", "p04", "p05"],
        },
        "Vector Search": {
            "desc": "Approximate nearest neighbor and vector retrieval",
            "pids": ["p06", "p07", "p08", "p09"],
        },
        "Transaction Processing": {
            "desc": "Concurrency control, HTAP, and distributed transactions",
            "pids": ["p10", "p11", "p12", "p13", "p14"],
        },
        "Data Integration": {
            "desc": "Schema matching, entity resolution, data lake discovery",
            "pids": ["p15", "p16", "p17", "p18", "p19"],
        },
        "LLM for Data Management": {
            "desc": "Large language models for SQL, cleaning, and QA over data",
            "pids": ["p20", "p21", "p22", "p23", "p24", "p25"],
        },
        "Graph Analytics": {
            "desc": "Graph partitioning, GNNs, subgraph matching, graph DB queries",
            "pids": ["p26", "p27", "p28", "p29", "p30"],
        },
    }
    root = TaxonomyNode(node_id="0", name="All Papers",
                         description="Root", paper_ids=[], depth=0, is_leaf=False)
    for idx, (name, info) in enumerate(groups.items()):
        child = TaxonomyNode(
            node_id=f"0.{idx}", name=name, description=info["desc"],
            parent_id="0", paper_ids=info["pids"], depth=1, is_leaf=True)
        root.children.append(child)
    return root


# ════════════════════════════════════════════════════════════════════
# Pretty-print
# ════════════════════════════════════════════════════════════════════

def print_oral_schedule(sessions: list[Session], papers: dict[str, Paper]):
    slot_groups: dict[int, list[Session]] = defaultdict(list)
    for s in sessions:
        slot_groups[s.time_slot or 0].append(s)

    print("\n" + "=" * 72)
    print("  ORAL SESSION SCHEDULE")
    print("=" * 72)

    for slot in sorted(slot_groups.keys()):
        print(f"\n{'─' * 72}")
        print(f"  ⏰ TIME SLOT {slot + 1}")
        print(f"{'─' * 72}")
        for s in sorted(slot_groups[slot], key=lambda s: s.track or 0):
            print(f"\n  🎤 [{s.session_id}] {s.name}  (Track {(s.track or 0) + 1})")
            for pid in s.paper_ids:
                p = papers.get(pid)
                if p:
                    print(f"     • {p.title}")
                    print(f"       {', '.join(p.authors)}")

    # Conflict check
    print(f"\n{'=' * 72}")
    print("  ORAL AUTHOR CONFLICT REPORT")
    print("=" * 72)
    conflicts = 0
    for slot, ss in slot_groups.items():
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                common = ss[i].author_set(papers) & ss[j].author_set(papers)
                if common:
                    conflicts += len(common)
                    print(f"  ⚠️  Slot {slot+1}: '{ss[i].name}' ↔ '{ss[j].name}' "
                          f"share: {common}")
    if conflicts == 0:
        print("  ✅ No author conflicts. Schedule is conflict-free.")


def print_poster_schedule(sessions: list[PosterSession], papers: dict[str, Paper]):
    slot_groups: dict[int, list[PosterSession]] = defaultdict(list)
    for s in sessions:
        slot_groups[s.time_slot or 0].append(s)

    print("\n" + "=" * 72)
    print("  POSTER SESSION SCHEDULE")
    print("=" * 72)

    for slot in sorted(slot_groups.keys()):
        print(f"\n{'─' * 72}")
        print(f"  ⏰ POSTER SLOT {slot + 1}")
        print(f"{'─' * 72}")

        for s in sorted(slot_groups[slot], key=lambda s: s.area or 0):
            area_label = f"Area {(s.area or 0) + 1}"
            print(f"\n  🖼️  [{s.session_id}] {s.name}  ({area_label})")
            print(f"      Layout: {s.floor_plan.value.upper()}  |  "
                  f"Papers: {len(s.assignments)}")

            if s.floor_plan == FloorPlanType.RECTANGLE:
                _print_rect_layout(s, papers)
            elif s.floor_plan == FloorPlanType.CIRCLE:
                _print_circle_layout(s, papers)
            else:
                _print_line_layout(s, papers)

    # Conflict check
    print(f"\n{'=' * 72}")
    print("  POSTER AUTHOR CONFLICT REPORT")
    print("=" * 72)
    conflicts = 0
    for slot, ss in slot_groups.items():
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                common = ss[i].author_set(papers) & ss[j].author_set(papers)
                if common:
                    conflicts += len(common)
                    print(f"  ⚠️  Slot {slot+1}: '{ss[i].name}' ↔ '{ss[j].name}' "
                          f"share: {common}")
    if conflicts == 0:
        print("  ✅ No poster author conflicts.")


def _print_rect_layout(session: PosterSession, papers: dict[str, Paper]):
    """Print rectangle layout as a grid."""
    grid: dict[tuple[int, int], str] = {}
    max_row, max_col = 0, 0
    for a in session.assignments:
        r, c = a.board.row or 0, a.board.col or 0
        grid[(r, c)] = a.paper_id
        max_row = max(max_row, r)
        max_col = max(max_col, c)

    for r in range(max_row + 1):
        print(f"      Row {r}: ", end="")
        cells = []
        for c in range(max_col + 1):
            pid = grid.get((r, c))
            if pid:
                p = papers.get(pid)
                short = p.title[:35] + "..." if p and len(p.title) > 35 else (p.title if p else pid)
                cells.append(f"[{pid}] {short}")
        print("  |  ".join(cells))


def _print_circle_layout(session: PosterSession, papers: dict[str, Paper]):
    """Print circle layout as an angular list with walking direction."""
    sorted_a = sorted(session.assignments, key=lambda a: a.board.angle or 0)
    if config.CIRCLE_RIGHT_PRIORITY:
        print(f"      Walking direction: → (left to right, clockwise)")
    for i, a in enumerate(sorted_a):
        p = papers.get(a.paper_id)
        angle = a.board.angle or 0
        title = p.title[:50] if p else a.paper_id
        arrow = "→" if config.CIRCLE_RIGHT_PRIORITY else "·"
        print(f"      {angle:5.0f}° {arrow} [{a.paper_id}] {title}")


def _print_line_layout(session: PosterSession, papers: dict[str, Paper]):
    """Print line layout as a sequential list."""
    sorted_a = sorted(session.assignments, key=lambda a: a.board.index)
    for a in sorted_a:
        p = papers.get(a.paper_id)
        title = p.title[:55] if p else a.paper_id
        print(f"      Board {a.board.index:2d} → [{a.paper_id}] {title}")


# ════════════════════════════════════════════════════════════════════
# Pre-flight validation
# ════════════════════════════════════════════════════════════════════

def validate_configuration(num_papers: int, mode: str) -> bool:
    """Check whether the current session configuration can accommodate all
    papers, and whether the paper count meets the minimum requirements.

    Any capacity shortfall is FATAL — the program stops immediately rather
    than overflowing sessions beyond the configured slots/tracks/areas.

    Returns True if configuration is sufficient, False otherwise.
    """
    ok = True
    print("\n🔍 Pre-flight configuration check")
    print(f"   Papers: {num_papers}")

    if mode in ("oral", "both"):
        capacity = config.NUM_SLOTS * config.NUM_PARALLEL_TRACKS * config.SESSION_MAX
        oral_min_sessions = -(-num_papers // config.SESSION_MAX)  # ceil div
        oral_slots_needed = -(-oral_min_sessions // config.NUM_PARALLEL_TRACKS)

        print(f"\n   ── Oral ──")
        print(f"   Slots: {config.NUM_SLOTS}  |  Tracks: {config.NUM_PARALLEL_TRACKS}  |  "
              f"Session size: {config.SESSION_MIN}–{config.SESSION_MAX}")
        print(f"   Capacity: {config.NUM_SLOTS} slots × "
              f"{config.NUM_PARALLEL_TRACKS} tracks × {config.SESSION_MAX} papers "
              f"= {capacity} papers")
        print(f"   Min sessions needed: {oral_min_sessions}  |  "
              f"Min slots needed: {oral_slots_needed}")

        if num_papers < config.SESSION_MIN:
            print(f"   ❌ FATAL: {num_papers} papers below minimum session size "
                  f"({config.SESSION_MIN}). Cannot form even one oral session.")
            ok = False
        elif num_papers > capacity:
            print(f"   ❌ FATAL: {num_papers} papers exceed oral capacity ({capacity}). "
                  f"Increase --oral_slots (currently {config.NUM_SLOTS}) or "
                  f"--oral_tracks (currently {config.NUM_PARALLEL_TRACKS}) or "
                  f"--session_max (currently {config.SESSION_MAX}).")
            ok = False
        else:
            utilisation = num_papers / capacity * 100
            print(f"   ✅ Oral: fits within capacity ({utilisation:.0f}% utilisation)")

    if mode in ("poster", "both"):
        capacity = (config.POSTER_NUM_SLOTS * config.POSTER_NUM_PARALLEL
                    * config.POSTER_SESSION_MAX)
        poster_min_sessions = -(-num_papers // config.POSTER_SESSION_MAX)
        poster_slots_needed = -(-poster_min_sessions // config.POSTER_NUM_PARALLEL)

        print(f"\n   ── Poster ──")
        print(f"   Slots: {config.POSTER_NUM_SLOTS}  |  Areas: {config.POSTER_NUM_PARALLEL}  |  "
              f"Session size: {config.POSTER_SESSION_MIN}–{config.POSTER_SESSION_MAX}")
        print(f"   Capacity: {config.POSTER_NUM_SLOTS} slots × "
              f"{config.POSTER_NUM_PARALLEL} areas × {config.POSTER_SESSION_MAX} papers "
              f"= {capacity} papers")
        print(f"   Min sessions needed: {poster_min_sessions}  |  "
              f"Min slots needed: {poster_slots_needed}")

        if num_papers < config.POSTER_SESSION_MIN:
            print(f"   ❌ FATAL: {num_papers} papers below minimum poster session size "
                  f"({config.POSTER_SESSION_MIN}). Cannot form even one poster session.")
            ok = False
        elif num_papers > capacity:
            print(f"   ❌ FATAL: {num_papers} papers exceed poster capacity ({capacity}). "
                  f"Increase --poster_slots (currently {config.POSTER_NUM_SLOTS}) or "
                  f"--poster_parallel (currently {config.POSTER_NUM_PARALLEL}) or "
                  f"POSTER_SESSION_MAX (currently {config.POSTER_SESSION_MAX}).")
            ok = False
        else:
            utilisation = num_papers / capacity * 100
            print(f"   ✅ Poster: fits within capacity ({utilisation:.0f}% utilisation)")

    if ok:
        print(f"\n   ✅ All checks passed. Proceeding.\n")
    else:
        print(f"\n   ❌ Validation failed. Please adjust configuration and retry.\n")

    return ok


# ════════════════════════════════════════════════════════════════════
# Pipeline runners
# ════════════════════════════════════════════════════════════════════

def run_oral_pipeline(papers: list[Paper], taxonomy_root: TaxonomyNode,
                      papers_map: dict[str, Paper]) -> OrganizationResult:
    """Oral session pipeline: taxonomy → sessions → schedule → last-mile repair."""
    print(f"\n📋 Running oral organization (method={config.ORAL_METHOD})...")
    result = run_oral_organization(papers, taxonomy_root)
    print_oral_schedule(result.sessions, papers_map)

    # Print summary stats
    stats = result.stats
    print(f"\n📊 Oral Organization Stats:")
    print(f"   Sessions: {len(result.sessions)}")
    print(f"   Hard conflicts remaining: {stats.get('hard_conflicts', '?')}")
    print(f"   Avg intra-session similarity: {stats.get('avg_intra_session_similarity', 0):.3f}")
    print(f"   Last-mile edits: {len(result.last_mile_edits)}")
    if result.capacity_report:
        print(f"   ⚠️  Capacity violations: {len(result.capacity_report)}")
    if result.conflict_report:
        print(f"   ⚠️  Conflict violations: {len(result.conflict_report)}")

    return result


def run_poster_pipeline_full(papers: list[Paper], taxonomy_root: TaxonomyNode,
                             papers_map: dict[str, Paper],
                             oral_sessions: list[Session] = None,
                             ) -> PosterOrganizationResult:
    """Poster session pipeline: Stage 1 → 1.5 → 2 → Last-Mile."""
    floor_plan = FloorPlanType(config.POSTER_FLOOR_PLAN) if config.POSTER_FLOOR_PLAN else None

    print(f"\n🖼️  Running poster organization pipeline...")
    result = run_poster_pipeline(
        papers=papers,
        taxonomy_root=taxonomy_root,
        floor_plan=floor_plan,
        rect_cols=config.POSTER_RECT_COLS,
        enable_proximity=config.POSTER_PROXIMITY,
        avoid_conflicts=config.POSTER_ENABLE_CONFLICT_AVOIDANCE,
        num_slots=config.POSTER_NUM_SLOTS,
        num_parallel=config.POSTER_NUM_PARALLEL,
        oral_sessions=oral_sessions,
    )

    print_poster_schedule(result.poster_sessions, papers_map)

    # Print summary stats
    stats = result.stats
    print(f"\n📊 Poster Organization Summary:")
    print(f"   Method: {config.POSTER_METHOD}")
    print(f"   Sessions formed: {stats.get('sessions_formed', '?')}")
    print(f"   Avg intra-session similarity: {stats.get('avg_intra_session_similarity', 0):.3f}")
    print(f"   Hard conflicts: {stats.get('hard_conflicts', '?')}")
    print(f"   Capacity violations: {stats.get('capacity_violations', '?')}")
    print(f"   Last-mile edits: {len(result.organization.last_mile_edits)}")
    print(f"   Floor plan: {result.floor_plan.value}")

    return result


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="LLM-Taxonomy Conference Session Organizer (Oral + Poster)\n\n"
                    "All parameters can be set via a YAML config file (--config).\n"
                    "CLI arguments override YAML values.",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # Config file
    parser.add_argument("--config", type=str, default=None,
                        help="Path to YAML configuration file")

    # Top-level (can also come from YAML)
    parser.add_argument("--input", type=str, default=None,
                        help="Path to papers JSON file")
    parser.add_argument("--output_dir", type=str, default=None)
    parser.add_argument("--mode", type=str, default=None,
                        choices=["oral", "poster", "both"])
    parser.add_argument("--max_depth", type=int, default=None)
    parser.add_argument("--demo", action="store_true", default=None,
                        help="Run with synthetic demo data (no LLM needed)")

    # Oral options
    parser.add_argument("--session_min", type=int, default=None)
    parser.add_argument("--session_max", type=int, default=None)
    parser.add_argument("--oral_slots", type=int, default=None)
    parser.add_argument("--oral_tracks", type=int, default=None)

    # LLM provider options
    parser.add_argument("--provider", type=str, default=None,
                        choices=["openai", "google", "anthropic", "xai"],
                        help="LLM provider (default: openai)")
    parser.add_argument("--model", type=str, default=None,
                        help="LLM model name (provider-specific)")

    # Embedding cache options
    parser.add_argument("--no_cache", dest="embedding_cache",
                        action="store_false", default=None,
                        help="Disable embedding cache")
    parser.add_argument("--clear_cache", action="store_true", default=False,
                        help="Clear embedding cache before running")

    # Poster options
    parser.add_argument("--poster_slots", type=int, default=None)
    parser.add_argument("--poster_parallel", type=int, default=None)
    parser.add_argument("--floor_plan", type=str, default=None,
                        choices=["line", "circle", "rectangle"])
    parser.add_argument("--rect_cols", type=int, default=None)
    parser.add_argument("--proximity", action="store_true", default=None,
                        help="Enable proximity-based board placement")
    parser.add_argument("--no_proximity", dest="proximity",
                        action="store_false")
    parser.add_argument("--poster_conflicts", action="store_true", default=None,
                        help="Enable author conflict avoidance for posters")
    parser.add_argument("--no_poster_conflicts", dest="poster_conflicts",
                        action="store_false")
    parser.add_argument("--circle_right_priority", action="store_true",
                        default=None)
    parser.add_argument("--no_circle_right_priority",
                        dest="circle_right_priority", action="store_false")

    args = parser.parse_args()

    # ── Step 1: Load YAML config (sets config.* module globals) ──
    yaml_data = {}
    if args.config:
        yaml_path = os.path.abspath(args.config)
        if not os.path.isfile(yaml_path):
            parser.error(f"Config file not found: {yaml_path}")
        logger.info(f"Loading configuration from {yaml_path}")
        yaml_data = config.load_from_yaml(yaml_path)

    # ── Step 2: CLI args override YAML / defaults ──
    if args.provider is not None:
        config.LLM_PROVIDER = args.provider
    if args.model is not None:
        config.LLM_MODEL = args.model
    if args.embedding_cache is not None:
        config.EMBEDDING_CACHE_ENABLED = args.embedding_cache
    if args.max_depth is not None:
        config.MAX_DEPTH = args.max_depth
    if args.session_min is not None:
        config.SESSION_MIN = args.session_min
    if args.session_max is not None:
        config.SESSION_MAX = args.session_max
    if args.oral_slots is not None:
        config.NUM_SLOTS = args.oral_slots
    if args.oral_tracks is not None:
        config.NUM_PARALLEL_TRACKS = args.oral_tracks
    if args.poster_slots is not None:
        config.POSTER_NUM_SLOTS = args.poster_slots
    if args.poster_parallel is not None:
        config.POSTER_NUM_PARALLEL = args.poster_parallel
    if args.rect_cols is not None:
        config.POSTER_RECT_COLS = args.rect_cols
    if args.floor_plan is not None:
        config.POSTER_FLOOR_PLAN = args.floor_plan
    if args.proximity is not None:
        config.POSTER_PROXIMITY = args.proximity
    if args.poster_conflicts is not None:
        config.POSTER_AUTHOR_CONFLICT = args.poster_conflicts
    if args.circle_right_priority is not None:
        config.CIRCLE_RIGHT_PRIORITY = args.circle_right_priority

    # Resolve output_dir: CLI > YAML > default
    output_dir = args.output_dir or yaml_data.get("output_dir") or config.OUTPUT_DIR
    config.OUTPUT_DIR = output_dir

    # Resolve mode: CLI > YAML > default
    mode = args.mode or yaml_data.get("mode") or "both"

    # ── Step 3: Resolve input source ──
    # Priority: CLI --demo > CLI --input > YAML demo > YAML input
    use_demo = args.demo
    input_path = args.input

    if use_demo is None:
        use_demo = yaml_data.get("demo", False)
    if input_path is None:
        input_path = yaml_data.get("input")

    # ── Clear embedding cache if requested ──
    if args.clear_cache:
        from similarity import clear_embedding_cache
        clear_embedding_cache()

    # ── Reset global token tracker ──
    reset_global_tracker()

    if use_demo:
        papers = generate_demo_papers()
        use_llm = False
    elif input_path:
        papers = load_papers(os.path.abspath(input_path))
        use_llm = True
    else:
        parser.error("No input specified. Set 'input' in the YAML config, "
                     "use --input <path>, or use --demo.")
        return

    papers_map = {p.id: p for p in papers}

    # Pre-flight validation
    if not validate_configuration(len(papers), mode):
        sys.exit(1)

    # Build taxonomy
    print("\n📊 Phase 1: Building taxonomy...")
    if use_llm:
        llm = LLMClient()
        print(f"   LLM provider: {config.LLM_PROVIDER}")
        print(f"   LLM model:    {config.LLM_MODEL}")
        builder = TaxonomyBuilder(papers, llm=llm)
        taxonomy_root = builder.build()
    else:
        taxonomy_root = build_demo_taxonomy(papers)

    print("\n📐 Taxonomy:")
    print_taxonomy(taxonomy_root)

    # Export human-readable taxonomy files
    os.makedirs(output_dir, exist_ok=True)
    export_taxonomy_readable(
        taxonomy_root,
        os.path.join(output_dir, "taxonomy.txt"),
        papers_map=papers_map, fmt="tree", show_papers=True)
    export_taxonomy_readable(
        taxonomy_root,
        os.path.join(output_dir, "taxonomy.md"),
        papers_map=papers_map, fmt="markdown", show_papers=True)
    export_taxonomy_html(
        taxonomy_root,
        os.path.join(output_dir, "taxonomy.html"),
        papers_map=papers_map, title="Session Taxonomy")

    taxonomy_json = taxonomy_to_dict(taxonomy_root)

    # Run pipelines
    oral_result = None
    if mode in ("oral", "both"):
        oral_result = run_oral_pipeline(papers, taxonomy_root, papers_map)
        save_oral_schedule(oral_result, papers_map, taxonomy_json,
                           os.path.join(output_dir, "oral_schedule.json"))

    if mode in ("poster", "both"):
        # Pass oral sessions for cross-type scheduling (Section 7) if available
        oral_sessions_for_cross = None
        if oral_result and config.ENABLE_CROSS_TYPE_SCHEDULING:
            oral_sessions_for_cross = oral_result.sessions

        poster_result = run_poster_pipeline_full(
            papers, taxonomy_root, papers_map,
            oral_sessions=oral_sessions_for_cross)
        save_poster_schedule(poster_result.poster_sessions, papers_map,
                             taxonomy_json,
                             os.path.join(output_dir, "poster_schedule.json"))

    # ── Token usage summary ──
    tracker = get_global_tracker()
    if tracker.total_calls > 0:
        tracker.print_summary()

        # Save token stats to JSON
        token_stats_path = os.path.join(output_dir, "token_usage.json")
        with open(token_stats_path, "w") as f:
            json.dump(tracker.to_dict(), f, indent=2)
        logger.info(f"Token usage stats saved to {token_stats_path}")

    print(f"\n✅ Done! Outputs saved to {output_dir}/")


if __name__ == "__main__":
    main()
