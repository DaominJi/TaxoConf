"""
Configuration for the LLM-Taxonomy Conference Session Organizer.
Covers both oral and poster session organization.

Values are loaded in this priority order (highest wins):
  1. CLI arguments (--oral_slots 10, etc.)
  2. YAML config file (--config config.yaml)
  3. Defaults defined below
"""

import os
import sys

# ─── LLM Settings ──────────────────────────────────────────────────
LLM_PROVIDER = "openai"             # LLM provider: "openai", "google", "anthropic", "xai"
LLM_MODEL = "gpt-4o"                # Model name (provider-specific)
LLM_TEMPERATURE = 0.3               # Low temperature for deterministic outputs
LLM_MAX_RETRIES = 3                 # Retries on API failure
LLM_MAX_WORKERS = 4                 # Max parallel threads for taxonomy expansion

# ─── Taxonomy Construction ──────────────────────────────────────────
MAX_DEPTH = 3                        # Maximum depth of the taxonomy tree
MIN_PAPERS_TO_SPLIT = 3              # Don't subdivide nodes with fewer papers
MAX_CHILDREN = 8                     # Max children per taxonomy node
TOKEN_THRESHOLD = 60000              # Estimated token budget; if total input
                                     # exceeds this, use titles only.
TOKEN_EST_CHARS_PER_TOKEN = 4        # Rough char-to-token ratio
USE_ABSTRACTS = True                 # Include abstracts in taxonomy construction
                                     # (falls back to titles-only if exceeding
                                     # TOKEN_THRESHOLD even when enabled)

# ─── Oral Session Formation ─────────────────────────────────────────
SESSION_MIN = 3                      # Minimum papers per oral session
SESSION_MAX = 5                      # Maximum papers per oral session

# ─── Oral Scheduling ────────────────────────────────────────────────
NUM_SLOTS = 8                        # Number of oral time slots
NUM_PARALLEL_TRACKS = 4              # Number of parallel oral rooms

# ─── Oral Session Formation Method ──────────────────────────────────
ORAL_METHOD = "greedy"               # "greedy" (bottom-up) or "optimization" (LCA)
ORAL_SOLVER = "heuristic"            # "ilp" or "heuristic" (for optimization method)
ORAL_ALPHA = 1.0                     # Taxonomy vs embedding blend (1.0=taxonomy)
ENABLE_CONFLICT_AVOIDANCE = True     # Enable presenter conflict constraints

# ─── Oral Scheduling Tuning ────────────────────────────────────────
AUDIENCE_SIM_THRESHOLD = 0.1         # Min inter-session similarity for soft edge
ILP_TIME_LIMIT = 300                 # ILP solver time limit (seconds)
ILP_MIP_GAP = 0.01                   # Accept solutions within 1% of optimal
MAX_REPAIR_ITERATIONS = 50           # Max last-mile conflict repair iterations

# ─── Poster Session Formation ───────────────────────────────────────
POSTER_SESSION_MIN = 8               # Minimum papers per poster session
POSTER_SESSION_MAX = 30              # Maximum papers per poster session

# ─── Poster Scheduling ─────────────────────────────────────────────
POSTER_NUM_SLOTS = 3                 # Number of poster time slots
POSTER_NUM_PARALLEL = 2              # Number of parallel poster areas

# ─── Poster Session Formation Method ──────────────────────────────
POSTER_METHOD = "greedy"             # "greedy" (bottom-up) or "optimization" (LCA)
POSTER_SOLVER = "heuristic"          # "ilp" or "heuristic" (for optimization method)
POSTER_ALPHA = 1.0                   # Taxonomy vs embedding blend (1.0=taxonomy)
POSTER_ENABLE_CONFLICT_AVOIDANCE = True  # Enable presenter conflict constraints

# ─── Poster Floor Plan ─────────────────────────────────────────────
POSTER_FLOOR_PLAN = "rectangle"
POSTER_RECT_COLS = 6
POSTER_PROXIMITY = True
POSTER_AUTHOR_CONFLICT = True        # Legacy alias for POSTER_ENABLE_CONFLICT_AVOIDANCE

# ─── Circle Right-Priority ──────────────────────────────────────
CIRCLE_RIGHT_PRIORITY = True
CIRCLE_FORWARD_WEIGHTS = [1.0, 0.4]

# ─── Cross-Type Scheduling ─────────────────────────────────────────
ENABLE_CROSS_TYPE_SCHEDULING = False  # Joint oral+poster scheduling

# ─── Similarity ─────────────────────────────────────────────────────
SIMILARITY_METHOD = "tfidf"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ─── Embedding Cache ───────────────────────────────────────────────
EMBEDDING_CACHE_ENABLED = True       # Enable/disable embedding caching
EMBEDDING_CACHE_DIR = ".cache/embeddings"  # Cache directory for embeddings

# ─── Output ─────────────────────────────────────────────────────────
OUTPUT_DIR = "output"


# ════════════════════════════════════════════════════════════════════
# YAML loader
# ════════════════════════════════════════════════════════════════════

def load_from_yaml(path: str):
    """Load a YAML config file and override the module-level globals."""
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML is required to load config files. "
              "Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    module = sys.modules[__name__]

    # ── top-level ──
    _set(module, "OUTPUT_DIR", data.get("output_dir"))

    # ── llm ──
    llm = data.get("llm", {})
    _set(module, "LLM_PROVIDER", llm.get("provider"))
    _set(module, "LLM_MODEL", llm.get("model"))
    _set(module, "LLM_TEMPERATURE", llm.get("temperature"))
    _set(module, "LLM_MAX_RETRIES", llm.get("max_retries"))
    _set(module, "LLM_MAX_WORKERS", llm.get("max_workers"))

    # ── taxonomy ──
    tax = data.get("taxonomy", {})
    _set(module, "MAX_DEPTH", tax.get("max_depth"))
    _set(module, "MIN_PAPERS_TO_SPLIT", tax.get("min_papers_to_split"))
    _set(module, "MAX_CHILDREN", tax.get("max_children"))
    _set(module, "TOKEN_THRESHOLD", tax.get("token_threshold"))
    _set(module, "TOKEN_EST_CHARS_PER_TOKEN", tax.get("token_est_chars_per_token"))

    # ── oral ──
    oral = data.get("oral", {})
    _set(module, "SESSION_MIN", oral.get("session_min"))
    _set(module, "SESSION_MAX", oral.get("session_max"))
    _set(module, "NUM_SLOTS", oral.get("num_slots"))
    _set(module, "NUM_PARALLEL_TRACKS", oral.get("num_tracks"))
    _set(module, "ORAL_METHOD", oral.get("method"))
    _set(module, "ORAL_SOLVER", oral.get("solver"))
    _set(module, "ORAL_ALPHA", oral.get("alpha"))
    _set(module, "ENABLE_CONFLICT_AVOIDANCE", oral.get("enable_conflict_avoidance"))
    _set(module, "AUDIENCE_SIM_THRESHOLD", oral.get("audience_sim_threshold"))
    _set(module, "ILP_TIME_LIMIT", oral.get("ilp_time_limit"))
    _set(module, "ILP_MIP_GAP", oral.get("ilp_mip_gap"))
    _set(module, "MAX_REPAIR_ITERATIONS", oral.get("max_repair_iterations"))

    # ── poster ──
    poster = data.get("poster", {})
    _set(module, "POSTER_SESSION_MIN", poster.get("session_min"))
    _set(module, "POSTER_SESSION_MAX", poster.get("session_max"))
    _set(module, "POSTER_NUM_SLOTS", poster.get("num_slots"))
    _set(module, "POSTER_NUM_PARALLEL", poster.get("num_parallel"))
    _set(module, "POSTER_METHOD", poster.get("method"))
    _set(module, "POSTER_SOLVER", poster.get("solver"))
    _set(module, "POSTER_ALPHA", poster.get("alpha"))
    _set(module, "POSTER_ENABLE_CONFLICT_AVOIDANCE",
         poster.get("enable_conflict_avoidance"))
    _set(module, "POSTER_FLOOR_PLAN", poster.get("floor_plan"))
    _set(module, "POSTER_RECT_COLS", poster.get("rect_cols"))
    _set(module, "POSTER_PROXIMITY", poster.get("proximity"))
    _set(module, "POSTER_AUTHOR_CONFLICT", poster.get("author_conflict"))
    _set(module, "CIRCLE_RIGHT_PRIORITY", poster.get("circle_right_priority"))
    fw = poster.get("circle_forward_weights")
    if fw is not None:
        _set(module, "CIRCLE_FORWARD_WEIGHTS", fw)

    # ── cross-type ──
    _set(module, "ENABLE_CROSS_TYPE_SCHEDULING",
         data.get("cross_type_scheduling"))

    # ── similarity ──
    sim = data.get("similarity", {})
    _set(module, "SIMILARITY_METHOD", sim.get("method"))
    _set(module, "EMBEDDING_MODEL", sim.get("embedding_model"))

    # ── embedding cache ──
    cache = data.get("embedding_cache", {})
    _set(module, "EMBEDDING_CACHE_ENABLED", cache.get("enabled"))
    _set(module, "EMBEDDING_CACHE_DIR", cache.get("cache_dir"))

    return data  # return raw dict so main.py can read input/mode/demo


def _set(module, attr: str, value):
    """Set a module attribute only if value is not None."""
    if value is not None:
        setattr(module, attr, value)
