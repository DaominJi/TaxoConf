"""
FastAPI backend for the TaxoConf Workspace.

Serves the index.html frontend and exposes JSON API endpoints that
the frontend calls for:
  - Oral session organization   (GET /api/oral/info, POST /api/oral/run)
  - Poster session organization (GET /api/poster/info, POST /api/poster/run)
  - Paper assignment            (placeholder)
  - Reviewer discovery          (placeholder)

Usage:
    pip install fastapi uvicorn pyyaml scikit-learn
    python server.py                     # starts on http://127.0.0.1:8000
    python server.py --port 9000         # custom port
    python server.py --host 0.0.0.0      # bind all interfaces

The server auto-discovers conference datasets under ./data/<conference_name>/
and builds taxonomy + similarity on first request (cached for subsequent calls).
"""

import argparse
import json
import logging
import os
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Add project root to path so we can import our modules ──
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from models import Paper, TaxonomyNode, Session, PosterSession, FloorPlanType
from taxonomy_builder import (TaxonomyBuilder, LLMClient, collect_leaves,
                              print_taxonomy)
from session_organizer import run_oral_organization, OrganizationResult
from poster_organizer import run_poster_pipeline, PosterOrganizationResult
from similarity import SimilarityEngine
from token_tracker import get_global_tracker, reset_global_tracker
from session_reviewer import review_sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")


# ════════════════════════════════════════════════════════════════════
# Data discovery and caching
# ════════════════════════════════════════════════════════════════════

DATA_DIR = PROJECT_ROOT / "data"


def discover_conferences() -> list[str]:
    """Find available conference datasets under ./data/."""
    if not DATA_DIR.is_dir():
        return []
    conferences = []
    for entry in sorted(DATA_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            # Check for any JSON file in the directory
            json_files = list(entry.glob("*.json"))
            if json_files:
                conferences.append(entry.name)
    return conferences


def load_conference_papers(conference: str) -> list[Paper]:
    """Load papers from a conference data directory."""
    conf_dir = DATA_DIR / conference
    if not conf_dir.is_dir():
        raise ValueError(f"Conference directory not found: {conf_dir}")

    # Find the papers JSON file
    json_files = list(conf_dir.glob("*.json"))
    if not json_files:
        raise ValueError(f"No JSON files in {conf_dir}")

    # Try to find the main paper file (prefer *Full_Papers*.json, else first json)
    # Skip known non-paper JSON files
    _SKIP_NAMES = {"metadata", "workspace", "token_usage"}
    paper_file = None
    for f in json_files:
        if not any(skip in f.name.lower() for skip in _SKIP_NAMES):
            paper_file = f
            break
    if paper_file is None:
        paper_file = json_files[0]

    # Also look for a companion metadata file for abstracts
    abstract_lookup: dict[str, str] = {}
    for f in json_files:
        if "metadata" in f.name.lower():
            try:
                with open(f) as mf:
                    meta = json.load(mf)
                for m in meta:
                    if m.get("abstract"):
                        abstract_lookup[m["title"]] = m["abstract"]
                logger.info(f"Loaded {len(abstract_lookup)} abstracts from {f.name}")
            except Exception:
                pass
            break

    with open(paper_file) as f:
        data = json.load(f)

    papers = []
    for e in data:
        paper_id = str(e["id"])
        raw_authors = e.get("authors", [])
        if isinstance(raw_authors, str):
            authors = [a.strip() for a in raw_authors.split(",") if a.strip()]
        else:
            authors = raw_authors
        abstract = e.get("abstract", "")
        if not abstract:
            abstract = abstract_lookup.get(e.get("title", ""), "")
        papers.append(Paper(id=paper_id, title=e["title"],
                            abstract=abstract, authors=authors))

    logger.info(f"Loaded {len(papers)} papers from {paper_file}")
    return papers


# ── Caches ──

_paper_cache: dict[str, list[Paper]] = {}
_taxonomy_cache: dict[str, TaxonomyNode] = {}
_similarity_cache: dict[str, SimilarityEngine] = {}


def get_papers(conference: str) -> list[Paper]:
    if conference not in _paper_cache:
        _paper_cache[conference] = load_conference_papers(conference)
    return _paper_cache[conference]


def get_taxonomy(conference: str, papers: list[Paper]) -> TaxonomyNode:
    """Get or build taxonomy. Uses demo taxonomy if no LLM key is set."""
    if conference not in _taxonomy_cache:
        has_api_key = bool(
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("XAI_API_KEY")
        )

        if has_api_key:
            logger.info(f"Building LLM taxonomy for {conference}...")
            llm = LLMClient()
            builder = TaxonomyBuilder(papers, llm=llm)
            root = builder.build()
        else:
            logger.info(f"No LLM API key found; building automatic taxonomy for {conference}...")
            root = _build_auto_taxonomy(papers)

        _taxonomy_cache[conference] = root
    return _taxonomy_cache[conference]


def _build_auto_taxonomy(papers: list[Paper]) -> TaxonomyNode:
    """Build a simple automatic taxonomy by clustering papers using similarity."""
    # Simple single-level taxonomy: all papers in one group
    # The session organizer will handle the actual splitting
    root = TaxonomyNode(
        node_id="0",
        name="All Papers",
        description="Root node containing all accepted papers",
        paper_ids=[p.id for p in papers],
        depth=0,
        is_leaf=False,
    )

    # Try to create meaningful groups using TF-IDF clustering
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
        import numpy as np

        texts = [p.text_for_embedding() for p in papers]
        vectorizer = TfidfVectorizer(max_features=3000, stop_words="english")
        tfidf = vectorizer.fit_transform(texts)

        n_clusters = min(max(3, len(papers) // 8), 15)
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(tfidf)

        # Get top terms per cluster for naming
        feature_names = vectorizer.get_feature_names_out()
        cluster_groups: dict[int, list[str]] = defaultdict(list)
        for i, label in enumerate(labels):
            cluster_groups[label].append(papers[i].id)

        root.paper_ids = []
        root.is_leaf = False

        for idx, (cluster_id, paper_ids) in enumerate(sorted(cluster_groups.items())):
            # Name the cluster by top TF-IDF terms of its papers
            cluster_tfidf = tfidf[labels == cluster_id].toarray().mean(axis=0)
            top_term_indices = cluster_tfidf.argsort()[-3:][::-1]
            cluster_name = " & ".join(
                feature_names[i].title() for i in top_term_indices
            )

            child = TaxonomyNode(
                node_id=f"0.{idx}",
                name=cluster_name,
                description=f"Auto-clustered group of {len(paper_ids)} papers",
                parent_id="0",
                paper_ids=paper_ids,
                depth=1,
                is_leaf=True,
            )
            root.children.append(child)

        logger.info(f"Auto-taxonomy: {n_clusters} clusters for {len(papers)} papers")

    except Exception as e:
        logger.warning(f"Auto-taxonomy clustering failed, using flat: {e}")
        root.is_leaf = True

    return root


def get_similarity(conference: str, papers: list[Paper]) -> SimilarityEngine:
    if conference not in _similarity_cache:
        papers_map = {p.id: p for p in papers}
        engine = SimilarityEngine(
            papers_map,
            method=config.SIMILARITY_METHOD,
            use_cache=getattr(config, "EMBEDDING_CACHE_ENABLED", True),
        )
        engine.build()
        _similarity_cache[conference] = engine
    return _similarity_cache[conference]


def get_presenter_stats(papers: list[Paper]) -> dict:
    """Compute presenter / author statistics."""
    author_papers: dict[str, list[str]] = defaultdict(list)
    for p in papers:
        for a in p.authors:
            author_papers[a.strip()].append(p.id)

    multi = {a: pids for a, pids in author_papers.items() if len(pids) > 1}
    max_papers = max((len(pids) for pids in author_papers.values()), default=0)

    return {
        "presenterCount": len(author_papers),
        "multiPresenterCount": len(multi),
        "maxPapersPerPresenter": max_papers,
    }


# ════════════════════════════════════════════════════════════════════
# FastAPI app
# ════════════════════════════════════════════════════════════════════

app = FastAPI(title="TaxoConf API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Serve index.html and static files ──

@app.get("/")
async def serve_index():
    index_path = PROJECT_ROOT / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), media_type="text/html")
    return JSONResponse({"error": "index.html not found"}, status_code=404)


# Static file extensions allowed for catch-all route (registered at end)
STATIC_EXTENSIONS = {".css", ".js", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".ttf"}


# ════════════════════════════════════════════════════════════════════
# API: Oral Session Organization
# ════════════════════════════════════════════════════════════════════

@app.get("/api/oral/info")
async def oral_info(conference: str = Query("SIGIR25")):
    """Return info about available oral session data."""
    try:
        conferences = discover_conferences()
        # Normalize conference name
        conf = _resolve_conference(conference, conferences)

        papers = get_papers(conf)
        stats = get_presenter_stats(papers)

        return {
            "result": {
                "conference": conf,
                "availableConferences": conferences,
                "paperCount": len(papers),
                "presenterCount": stats["presenterCount"],
                "multiPresenterCount": stats["multiPresenterCount"],
                "maxPapersPerPresenter": stats["maxPapersPerPresenter"],
                "paperDataPath": f"data/{conf}/",
                "similarityMatrixPath": f".cache/embeddings/ (auto-computed)",
            }
        }
    except Exception as e:
        logger.error(f"oral/info error: {e}\n{traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/oral/run")
async def oral_run(request: Request):
    """Run oral session organization."""
    try:
        body = await request.json()
        conference = body.get("conference", "SIGIR25")
        parallel_sessions = int(body.get("parallel_sessions", 7))
        time_slots = int(body.get("time_slots", 19))
        max_per_session = int(body.get("max_per_session", 4))
        min_per_session = int(body.get("min_per_session", 3))

        conferences = discover_conferences()
        conf = _resolve_conference(conference, conferences)

        # Override config for this run
        config.SESSION_MIN = min_per_session
        config.SESSION_MAX = max_per_session
        config.NUM_SLOTS = time_slots
        config.NUM_PARALLEL_TRACKS = parallel_sessions

        papers = get_papers(conf)
        papers_map = {p.id: p for p in papers}
        taxonomy_root = get_taxonomy(conf, papers)

        logger.info(f"Running oral organization: {len(papers)} papers, "
                     f"{parallel_sessions}x{time_slots} grid, "
                     f"session size {min_per_session}-{max_per_session}")

        result = run_oral_organization(papers, taxonomy_root)

        # Build response in the format the frontend expects.
        # The frontend renders a 2-D grid (slot × track) and looks up sessions
        # by id = "slot_{slot}_track_{track}" (both 1-indexed).  The backend
        # produces 0-indexed time_slot/track, so we convert here.
        sessions_out = []
        assignment_map = {}  # paper_id -> session_id (frontend format)

        for s in result.sessions:
            slot_1 = (s.time_slot or 0) + 1   # 0-indexed → 1-indexed
            track_1 = (s.track or 0) + 1
            frontend_id = f"slot_{slot_1}_track_{track_1}"

            session_data = {
                "id": frontend_id,
                "sessionName": s.name,
                "description": s.description,
                "slot": slot_1,
                "track": track_1,
                "paperCount": len(s.paper_ids),
                "targetSize": max_per_session,
                "papers": [],
            }
            for pid in s.paper_ids:
                p = papers_map.get(pid)
                if p:
                    session_data["papers"].append({
                        "id": p.id,
                        "title": p.title,
                        "abstract": p.abstract,
                        "authors": p.authors,
                        "presenters": p.authors,
                    })
                    assignment_map[p.id] = frontend_id

            sessions_out.append(session_data)

        # All papers list
        all_papers = []
        for p in papers:
            all_papers.append({
                "id": p.id,
                "title": p.title,
                "abstract": p.abstract,
                "authors": p.authors,
                "presenters": p.authors,
            })

        # ── LLM-based session review: flag misplaced papers ──
        hard_papers, review_status = _llm_review_sessions(sessions_out, mode="oral")

        response = {
            "result": {
                "sessions": sessions_out,
                "papers": all_papers,
                "assignment": assignment_map,
                "hardPapers": hard_papers,
                "reviewStatus": review_status,
                "stats": result.stats,
                "parallelSessions": parallel_sessions,
                "timeSlots": time_slots,
                "maxPerSession": max_per_session,
                "minPerSession": min_per_session,
                "tokenUsage": get_global_tracker().to_dict(),
            }
        }

        # Persist token stats
        try:
            tracker_data = get_global_tracker().to_dict()
            save_run_token_stats(conf, "oral", {
                "calls": tracker_data.get("total_calls", 0),
                "prompt_tokens": tracker_data.get("total_prompt_tokens", 0),
                "completion_tokens": tracker_data.get("total_completion_tokens", 0),
                "total_tokens": tracker_data.get("total_tokens", 0),
                "cost_usd": tracker_data.get("total_cost_usd", 0.0),
                "provider": config.LLM_PROVIDER,
                "model": config.LLM_MODEL,
            })
        except Exception as tok_err:
            logger.warning(f"Failed to save token stats: {tok_err}")

        return response

    except Exception as e:
        logger.error(f"oral/run error: {e}\n{traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ════════════════════════════════════════════════════════════════════
# API: Poster Session Organization
# ════════════════════════════════════════════════════════════════════

@app.get("/api/poster/info")
async def poster_info(conference: str = Query("SIGIR25")):
    """Return info about available poster session data."""
    try:
        conferences = discover_conferences()
        conf = _resolve_conference(conference, conferences)

        papers = get_papers(conf)
        stats = get_presenter_stats(papers)

        return {
            "result": {
                "conference": conf,
                "availableConferences": conferences,
                "paperCount": len(papers),
                "presenterCount": stats["presenterCount"],
                "multiPresenterCount": stats["multiPresenterCount"],
                "maxPapersPerPresenter": stats["maxPapersPerPresenter"],
                "paperDataPath": f"data/{conf}/",
                "similarityMatrixPath": f".cache/embeddings/ (auto-computed)",
            }
        }
    except Exception as e:
        logger.error(f"poster/info error: {e}\n{traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/poster/run")
async def poster_run(request: Request):
    """Run poster session organization."""
    try:
        body = await request.json()
        conference = body.get("conference", "SIGIR25")
        layout_type = body.get("layout_type", "rectangle")
        board_count = int(body.get("board_count", 12))
        rows = int(body.get("rows", 3))
        cols = int(body.get("cols", 4))
        session_count = int(body.get("session_count", 44))
        prevent_same_presenter = bool(body.get("prevent_same_presenter", False))
        optimize_within = bool(body.get("optimize_within_layout", True))

        conferences = discover_conferences()
        conf = _resolve_conference(conference, conferences)

        # Compute session capacity
        if layout_type == "rectangle":
            session_capacity = rows * cols
        else:
            session_capacity = board_count

        # Override config for this run
        config.POSTER_SESSION_MIN = max(1, session_capacity // 2)
        config.POSTER_SESSION_MAX = session_capacity
        config.POSTER_NUM_SLOTS = max(1, session_count // max(1, 2))  # rough: 2 parallel areas
        config.POSTER_NUM_PARALLEL = min(session_count, 2)
        config.POSTER_FLOOR_PLAN = layout_type
        config.POSTER_RECT_COLS = cols
        config.POSTER_PROXIMITY = optimize_within
        config.POSTER_ENABLE_CONFLICT_AVOIDANCE = prevent_same_presenter

        papers = get_papers(conf)
        papers_map = {p.id: p for p in papers}
        taxonomy_root = get_taxonomy(conf, papers)

        floor_plan = FloorPlanType(layout_type) if layout_type in ("line", "circle", "rectangle") else FloorPlanType.RECTANGLE

        logger.info(f"Running poster organization: {len(papers)} papers, "
                     f"{session_count} sessions, layout={layout_type}, "
                     f"capacity={session_capacity}")

        poster_result = run_poster_pipeline(
            papers=papers,
            taxonomy_root=taxonomy_root,
            floor_plan=floor_plan,
            rect_cols=cols,
            enable_proximity=optimize_within,
            avoid_conflicts=prevent_same_presenter,
            num_slots=config.POSTER_NUM_SLOTS,
            num_parallel=config.POSTER_NUM_PARALLEL,
        )

        # Build response
        sessions_out = []
        placements = {}  # paper_id -> {sessionId, cellIndex}

        for ps in poster_result.poster_sessions:
            session_data = {
                "id": ps.session_id,
                "sessionName": ps.name,
                "description": ps.description,
                "slot": ps.time_slot,
                "area": ps.area,
                "paperCount": len(ps.assignments),
                "cells": [],
                "papers": [],
            }

            # Build the cells array (fixed size = session_capacity)
            cell_map: dict[int, dict] = {}
            for a in ps.assignments:
                p = papers_map.get(a.paper_id)
                if p:
                    paper_data = {
                        "id": p.id,
                        "title": p.title,
                        "abstract": p.abstract,
                        "authors": p.authors,
                        "presenters": p.authors,
                    }
                    cell_map[a.board.index] = paper_data
                    session_data["papers"].append(paper_data)
                    placements[p.id] = {
                        "sessionId": ps.session_id,
                        "cellIndex": a.board.index,
                    }

            # Fill cells array
            for idx in range(session_capacity):
                session_data["cells"].append(cell_map.get(idx, None))

            sessions_out.append(session_data)

        # All papers
        all_papers = []
        for p in papers:
            all_papers.append({
                "id": p.id,
                "title": p.title,
                "abstract": p.abstract,
                "authors": p.authors,
                "presenters": p.authors,
            })

        # ── LLM-based session review: flag misplaced papers ──
        hard_papers, review_status = _llm_review_sessions(sessions_out, mode="poster")

        response = {
            "result": {
                "sessions": sessions_out,
                "papers": all_papers,
                "placements": placements,
                "hardPapers": hard_papers,
                "reviewStatus": review_status,
                "layoutType": layout_type,
                "rows": rows,
                "cols": cols,
                "boardCount": board_count,
                "sessionCount": len(sessions_out),
                "sessionCapacity": session_capacity,
                "optimizeWithinLayout": optimize_within,
                "stats": poster_result.stats,
                "tokenUsage": get_global_tracker().to_dict(),
            }
        }

        # Persist token stats
        try:
            tracker_data = get_global_tracker().to_dict()
            save_run_token_stats(conf, "poster", {
                "calls": tracker_data.get("total_calls", 0),
                "prompt_tokens": tracker_data.get("total_prompt_tokens", 0),
                "completion_tokens": tracker_data.get("total_completion_tokens", 0),
                "total_tokens": tracker_data.get("total_tokens", 0),
                "cost_usd": tracker_data.get("total_cost_usd", 0.0),
                "provider": config.LLM_PROVIDER,
                "model": config.LLM_MODEL,
            })
        except Exception as tok_err:
            logger.warning(f"Failed to save token stats: {tok_err}")

        return response

    except Exception as e:
        logger.error(f"poster/run error: {e}\n{traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ════════════════════════════════════════════════════════════════════
# API: Paper Assignment (placeholder)
# ════════════════════════════════════════════════════════════════════

@app.get("/api/assignment/info")
async def assignment_info(conference: str = Query("SIGIR25")):
    """Placeholder for assignment info endpoint."""
    conferences = discover_conferences()
    conf = _resolve_conference(conference, conferences)
    try:
        papers = get_papers(conf)
        paper_count = len(papers)
    except Exception:
        paper_count = 0

    return {
        "result": {
            "conference": conf,
            "availableConferences": conferences,
            "paperCount": paper_count,
            "reviewerCount": 0,
            "metaReviewerCount": 0,
            "status": "placeholder",
            "message": "Paper assignment backend is not yet integrated. "
                       "This is a placeholder endpoint.",
        }
    }


@app.post("/api/assignment/run")
async def assignment_run(request: Request):
    """Placeholder for assignment run endpoint."""
    return JSONResponse(
        {"error": "Paper assignment backend is not yet integrated. "
                  "This endpoint is a placeholder."},
        status_code=501,
    )


# ════════════════════════════════════════════════════════════════════
# API: Reviewer Discovery (placeholder)
# ════════════════════════════════════════════════════════════════════

@app.get("/api/discovery/info")
async def discovery_info():
    """Placeholder for reviewer discovery."""
    return {
        "result": {
            "status": "in_progress",
            "message": "Reviewer discovery is still being integrated.",
        }
    }


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════

def _resolve_conference(name: str, available: list[str]) -> str:
    """Resolve a conference name to one of the available directories.

    Tries exact match, then case-insensitive, then partial match.
    """
    if not available:
        raise ValueError("No conference data directories found under ./data/")

    # Exact match
    if name in available:
        return name

    # Case-insensitive
    lower_map = {c.lower(): c for c in available}
    if name.lower() in lower_map:
        return lower_map[name.lower()]

    # Partial match (e.g. "sigir2025" matches "SIGIR25")
    name_norm = name.lower().replace("-", "").replace("_", "").replace(" ", "")
    for c in available:
        c_norm = c.lower().replace("-", "").replace("_", "").replace(" ", "")
        if name_norm in c_norm or c_norm in name_norm:
            return c

    # Default to first available
    logger.warning(f"Conference '{name}' not found, defaulting to '{available[0]}'")
    return available[0]


def _llm_review_sessions(sessions_out: list[dict], mode: str = "oral"
                         ) -> tuple[list[dict], dict]:
    """Run LLM-based review on organized sessions to flag misplaced papers.

    Returns (hard_papers, review_status) where review_status contains
    diagnostic info for the API response.
    """
    has_api_key = bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("XAI_API_KEY")
    )
    if not has_api_key:
        logger.info(f"No LLM API key found; skipping {mode} session review")
        return [], {"status": "skipped", "reason": "No LLM API key configured"}

    try:
        llm = LLMClient()
        logger.info(f"LLM session review ({mode}): using provider={llm.provider}, "
                     f"model={llm.model}")
        hard_papers = review_sessions(
            llm,
            sessions_out,
            all_sessions=sessions_out,
            mode=mode,
        )
        return hard_papers, {
            "status": "completed",
            "provider": llm.provider,
            "model": llm.model,
            "sessionsReviewed": len(sessions_out),
            "flaggedCount": len(hard_papers),
        }
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"LLM session review ({mode}) failed: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return [], {"status": "error", "reason": error_msg}


# ════════════════════════════════════════════════════════════════════
# API: Workspace Management
# ════════════════════════════════════════════════════════════════════

def _ensure_workspace_json(ws_dir: Path, name: str):
    """Create workspace.json if it doesn't exist (migration for legacy dirs)."""
    ws_json = ws_dir / "workspace.json"
    if ws_json.exists():
        return
    # Auto-migrate: look for existing paper JSON to get counts
    paper_count = 0
    for f in ws_dir.glob("*.json"):
        if "metadata" not in f.name.lower() and "workspace" not in f.name.lower():
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    paper_count = len(data) if isinstance(data, list) else 0
            except Exception:
                pass
            break

    import datetime
    meta = {
        "name": name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "description": f"Auto-migrated workspace for {name}",
        "paper_count": paper_count,
    }
    with open(ws_json, "w") as fh:
        json.dump(meta, fh, indent=2)
    logger.info(f"Created workspace.json for '{name}' (migrated)")


def _list_workspaces() -> list[dict]:
    """List all workspaces under DATA_DIR."""
    workspaces = []
    if not DATA_DIR.is_dir():
        return workspaces
    for entry in sorted(DATA_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            _ensure_workspace_json(entry, entry.name)
            ws_json = entry / "workspace.json"
            if ws_json.exists():
                try:
                    with open(ws_json) as fh:
                        meta = json.load(fh)
                    meta["name"] = entry.name  # ensure name matches dir
                    workspaces.append(meta)
                except Exception:
                    workspaces.append({"name": entry.name})
    return workspaces


@app.get("/api/workspaces")
async def list_workspaces():
    """List all available workspaces."""
    return {"result": _list_workspaces()}


@app.post("/api/workspaces")
async def create_workspace(request: Request):
    """Create a new workspace directory."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Workspace name is required."}, status_code=400)
    # Sanitize name
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        return JSONResponse({"error": "Invalid workspace name."}, status_code=400)

    ws_dir = DATA_DIR / safe_name
    if ws_dir.exists():
        return JSONResponse({"error": f"Workspace '{safe_name}' already exists."}, status_code=409)

    ws_dir.mkdir(parents=True, exist_ok=True)

    import datetime
    meta = {
        "name": safe_name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "description": body.get("description", ""),
        "paper_count": 0,
    }
    with open(ws_dir / "workspace.json", "w") as fh:
        json.dump(meta, fh, indent=2)

    logger.info(f"Created workspace '{safe_name}'")
    return {"success": True, "workspace": meta}


@app.get("/api/workspaces/{name}")
async def get_workspace(name: str):
    """Get workspace details."""
    ws_dir = DATA_DIR / name
    if not ws_dir.is_dir():
        return JSONResponse({"error": f"Workspace '{name}' not found."}, status_code=404)

    _ensure_workspace_json(ws_dir, name)
    ws_json = ws_dir / "workspace.json"
    try:
        with open(ws_json) as fh:
            meta = json.load(fh)
    except Exception:
        meta = {"name": name}

    # Count papers from any JSON file
    paper_count = 0
    for f in ws_dir.glob("*.json"):
        if "metadata" not in f.name.lower() and "workspace" not in f.name.lower() and "token" not in f.name.lower():
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    paper_count = len(data) if isinstance(data, list) else 0
            except Exception:
                pass
            break
    meta["paper_count"] = paper_count
    return {"result": meta}


@app.post("/api/workspaces/{name}/upload")
async def upload_workspace_papers(name: str, request: Request):
    """Upload a paper JSON file to a workspace."""
    ws_dir = DATA_DIR / name
    if not ws_dir.is_dir():
        return JSONResponse({"error": f"Workspace '{name}' not found."}, status_code=404)

    body = await request.json()
    papers = body.get("papers", [])
    filename = body.get("filename", f"{name}_papers.json")

    if not papers or not isinstance(papers, list):
        return JSONResponse({"error": "Invalid papers data. Expected a JSON array."}, status_code=400)

    # Save papers file
    out_path = ws_dir / filename
    with open(out_path, "w") as fh:
        json.dump(papers, fh, indent=2)

    # Update workspace.json
    _ensure_workspace_json(ws_dir, name)
    ws_json = ws_dir / "workspace.json"
    try:
        with open(ws_json) as fh:
            meta = json.load(fh)
    except Exception:
        meta = {"name": name}
    meta["paper_count"] = len(papers)
    with open(ws_json, "w") as fh:
        json.dump(meta, fh, indent=2)

    # Clear paper cache so next load picks up new data
    _paper_cache.pop(name, None)
    _taxonomy_cache.pop(name, None)
    _similarity_cache.pop(name, None)

    logger.info(f"Uploaded {len(papers)} papers to workspace '{name}' as '{filename}'")
    return {"success": True, "paper_count": len(papers), "filename": filename}


@app.delete("/api/workspaces/{name}")
async def delete_workspace(name: str):
    """Delete a workspace directory."""
    ws_dir = DATA_DIR / name
    if not ws_dir.is_dir():
        return JSONResponse({"error": f"Workspace '{name}' not found."}, status_code=404)

    import shutil
    try:
        shutil.rmtree(ws_dir)
    except PermissionError as pe:
        logger.warning(f"Permission error deleting workspace '{name}': {pe}")
        return JSONResponse(
            {"error": f"Cannot delete workspace '{name}': permission denied. "
                      "Please delete the folder manually."},
            status_code=403,
        )

    # Clear caches
    _paper_cache.pop(name, None)
    _taxonomy_cache.pop(name, None)
    _similarity_cache.pop(name, None)

    logger.info(f"Deleted workspace '{name}'")
    return {"success": True, "message": f"Workspace '{name}' deleted."}


# ════════════════════════════════════════════════════════════════════
# API: Token & Cost Statistics
# ════════════════════════════════════════════════════════════════════

_GLOBAL_TOKEN_FILE = DATA_DIR / "global_token_usage.json"


def _load_json_file(path: Path) -> dict:
    if path.exists():
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def _save_json_file(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def _get_workspace_token_file(workspace: str) -> Path:
    return DATA_DIR / workspace / "token_usage.json"


def save_run_token_stats(workspace: str, mode: str, run_stats: dict):
    """Save token usage for a completed run to workspace and global files."""
    import datetime
    run_entry = {
        "run_id": f"{mode}_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')}",
        "mode": mode,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **run_stats,
    }

    # Update workspace token file
    ws_file = _get_workspace_token_file(workspace)
    ws_data = _load_json_file(ws_file)
    if "runs" not in ws_data:
        ws_data = {
            "workspace": workspace,
            "total_calls": 0, "total_prompt_tokens": 0,
            "total_completion_tokens": 0, "total_tokens": 0,
            "total_cost_usd": 0.0, "runs": [],
        }
    ws_data["total_calls"] += run_stats.get("calls", 0)
    ws_data["total_prompt_tokens"] += run_stats.get("prompt_tokens", 0)
    ws_data["total_completion_tokens"] += run_stats.get("completion_tokens", 0)
    ws_data["total_tokens"] += run_stats.get("total_tokens", 0)
    ws_data["total_cost_usd"] += run_stats.get("cost_usd", 0.0)
    ws_data["runs"].append(run_entry)
    _save_json_file(ws_file, ws_data)

    # Update global token file
    global_data = _load_json_file(_GLOBAL_TOKEN_FILE)
    if "total_calls" not in global_data:
        global_data = {
            "total_calls": 0, "total_prompt_tokens": 0,
            "total_completion_tokens": 0, "total_tokens": 0,
            "total_cost_usd": 0.0, "last_reset": None,
        }
    global_data["total_calls"] += run_stats.get("calls", 0)
    global_data["total_prompt_tokens"] += run_stats.get("prompt_tokens", 0)
    global_data["total_completion_tokens"] += run_stats.get("completion_tokens", 0)
    global_data["total_tokens"] += run_stats.get("total_tokens", 0)
    global_data["total_cost_usd"] += run_stats.get("cost_usd", 0.0)
    _save_json_file(_GLOBAL_TOKEN_FILE, global_data)


@app.get("/api/token-stats")
async def get_token_stats(workspace: str = Query("SIGIR25")):
    """Return token stats: current tracker, workspace, and global."""
    tracker = get_global_tracker()
    current_run = tracker.to_dict()

    ws_data = _load_json_file(_get_workspace_token_file(workspace))
    global_data = _load_json_file(_GLOBAL_TOKEN_FILE)

    return {
        "result": {
            "currentRun": current_run,
            "workspace": ws_data if ws_data else None,
            "global": global_data if global_data else None,
        }
    }


@app.get("/api/token-stats/workspace/{name}")
async def get_workspace_token_stats(name: str):
    """Return detailed token stats for a specific workspace."""
    ws_data = _load_json_file(_get_workspace_token_file(name))
    return {"result": ws_data if ws_data else {"workspace": name, "runs": []}}


@app.post("/api/token-stats/reset/workspace/{name}")
async def reset_workspace_token_stats(name: str):
    """Reset token stats for a workspace."""
    ws_file = _get_workspace_token_file(name)
    if ws_file.exists():
        ws_file.unlink()
    return {"success": True, "message": f"Token stats reset for workspace '{name}'."}


@app.post("/api/token-stats/reset/global")
async def reset_global_token_stats():
    """Reset global token stats."""
    import datetime
    _save_json_file(_GLOBAL_TOKEN_FILE, {
        "total_calls": 0, "total_prompt_tokens": 0,
        "total_completion_tokens": 0, "total_tokens": 0,
        "total_cost_usd": 0.0,
        "last_reset": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return {"success": True, "message": "Global token stats reset."}


# ════════════════════════════════════════════════════════════════════
# API: Settings
# ════════════════════════════════════════════════════════════════════

# Track manually-entered API keys (session-only, never persisted to disk)
_manual_api_keys: dict[str, str] = {}

# Map provider -> environment variable name
_PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
}


@app.get("/api/settings")
async def get_settings():
    """Return current settings from the config module."""
    provider = getattr(config, "LLM_PROVIDER", "openai")
    env_key = _PROVIDER_ENV_KEYS.get(provider, "")
    has_key = bool(os.environ.get(env_key) or _manual_api_keys.get(provider))

    return {
        "result": {
            "llm": {
                "provider": provider,
                "model": getattr(config, "LLM_MODEL", "gpt-4o"),
                "temperature": getattr(config, "LLM_TEMPERATURE", 0.3),
                "api_key_source": "manual" if _manual_api_keys.get(provider) else "environment",
                "api_key_set": has_key,
            },
            "oral": {
                "method": getattr(config, "ORAL_METHOD", "greedy"),
                "solver": getattr(config, "ORAL_SOLVER", "heuristic"),
                "alpha": getattr(config, "ORAL_ALPHA", 1.0),
                "enable_conflict_avoidance": getattr(config, "ENABLE_CONFLICT_AVOIDANCE", True),
            },
            "poster": {
                "method": getattr(config, "POSTER_METHOD", "greedy"),
                "solver": getattr(config, "POSTER_SOLVER", "heuristic"),
                "alpha": getattr(config, "POSTER_ALPHA", 1.0),
                "enable_conflict_avoidance": getattr(config, "POSTER_ENABLE_CONFLICT_AVOIDANCE", True),
                "proximity": getattr(config, "POSTER_PROXIMITY", True),
            },
            "similarity": {
                "method": getattr(config, "SIMILARITY_METHOD", "tfidf"),
                "embedding_model": getattr(config, "EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                "cache_enabled": getattr(config, "EMBEDDING_CACHE_ENABLED", True),
            },
        }
    }


@app.put("/api/settings")
async def update_settings(request: Request):
    """Update settings in-memory. Optionally accepts a manual API key (session-only)."""
    body = await request.json()

    llm = body.get("llm", {})
    if llm.get("provider"):
        config.LLM_PROVIDER = llm["provider"]
    if llm.get("model"):
        config.LLM_MODEL = llm["model"]
    if llm.get("temperature") is not None:
        config.LLM_TEMPERATURE = float(llm["temperature"])
    if llm.get("api_key"):
        # Store manual key in session memory AND set as env var so LLMClient picks it up
        provider = llm.get("provider", config.LLM_PROVIDER)
        env_key = _PROVIDER_ENV_KEYS.get(provider, "")
        if env_key:
            _manual_api_keys[provider] = llm["api_key"]
            os.environ[env_key] = llm["api_key"]
            logger.info(f"Manual API key set for provider '{provider}' (session-only)")

    oral = body.get("oral", {})
    if oral.get("method"):
        config.ORAL_METHOD = oral["method"]
    if oral.get("solver"):
        config.ORAL_SOLVER = oral["solver"]
    if oral.get("alpha") is not None:
        config.ORAL_ALPHA = float(oral["alpha"])
    if "enable_conflict_avoidance" in oral:
        config.ENABLE_CONFLICT_AVOIDANCE = bool(oral["enable_conflict_avoidance"])

    poster = body.get("poster", {})
    if poster.get("method"):
        config.POSTER_METHOD = poster["method"]
    if poster.get("solver"):
        config.POSTER_SOLVER = poster["solver"]
    if poster.get("alpha") is not None:
        config.POSTER_ALPHA = float(poster["alpha"])
    if "enable_conflict_avoidance" in poster:
        config.POSTER_ENABLE_CONFLICT_AVOIDANCE = bool(poster["enable_conflict_avoidance"])
    if "proximity" in poster:
        config.POSTER_PROXIMITY = bool(poster["proximity"])

    sim = body.get("similarity", {})
    if sim.get("method"):
        config.SIMILARITY_METHOD = sim["method"]
    if sim.get("embedding_model"):
        config.EMBEDDING_MODEL = sim["embedding_model"]
    if "cache_enabled" in sim:
        config.EMBEDDING_CACHE_ENABLED = bool(sim["cache_enabled"])

    # Clear caches so next run uses new settings
    _taxonomy_cache.clear()
    _similarity_cache.clear()

    logger.info(f"Settings updated: provider={config.LLM_PROVIDER}, model={config.LLM_MODEL}")
    return {"success": True, "message": "Settings updated."}


@app.post("/api/settings/test-llm")
async def test_llm_connection(request: Request):
    """Test LLM connectivity with current or provided settings."""
    body = await request.json()
    provider = body.get("provider", config.LLM_PROVIDER)
    model = body.get("model", config.LLM_MODEL)

    # If a manual key is provided, temporarily set it
    temp_key = body.get("api_key")
    env_key = _PROVIDER_ENV_KEYS.get(provider, "")
    old_env = None
    if temp_key and env_key:
        old_env = os.environ.get(env_key)
        os.environ[env_key] = temp_key

    # Temporarily override config for this test
    old_provider = config.LLM_PROVIDER
    old_model = config.LLM_MODEL
    config.LLM_PROVIDER = provider
    config.LLM_MODEL = model

    try:
        llm = LLMClient()
        response = llm.chat("You are a helpful assistant.", "Say 'hello' in one word.", call_label="test-connection")
        config.LLM_PROVIDER = old_provider
        config.LLM_MODEL = old_model
        if temp_key and env_key and old_env is not None:
            os.environ[env_key] = old_env
        elif temp_key and env_key:
            os.environ.pop(env_key, None)
        return {"success": True, "message": f"Model responded: {response[:80]}"}
    except Exception as e:
        config.LLM_PROVIDER = old_provider
        config.LLM_MODEL = old_model
        if temp_key and env_key and old_env is not None:
            os.environ[env_key] = old_env
        elif temp_key and env_key:
            os.environ.pop(env_key, None)
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════════
# Catch-all static file route (MUST be after all /api/ routes)
# ════════════════════════════════════════════════════════════════════

@app.get("/{filepath:path}")
async def serve_static(filepath: str):
    """Serve static assets (CSS, JS, images). Registered last so API routes win."""
    full_path = PROJECT_ROOT / filepath
    if full_path.is_file() and full_path.suffix in STATIC_EXTENSIONS:
        return FileResponse(str(full_path))
    return JSONResponse({"error": "Not found"}, status_code=404)


# ════════════════════════════════════════════════════════════════════
# Entrypoint
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="TaxoConf API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    parser.add_argument("--config", type=str, default=None, help="YAML config file")
    args = parser.parse_args()

    # Load YAML config if provided
    if args.config:
        config.load_from_yaml(args.config)

    conferences = discover_conferences()
    logger.info(f"Available conferences: {conferences}")
    logger.info(f"Starting TaxoConf server on http://{args.host}:{args.port}")

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
