# LLM-Taxonomy Conference Session Organizer

## Overview

Organizes conference **oral** and **poster** sessions using a two-phase approach:

1. **Taxonomy Construction**: Iteratively builds a topic taxonomy from paper
   titles/abstracts using LLM-driven subdivision and classification.
2. **Session Organization**: Maps taxonomy to sessions, then schedules them
   with author-conflict avoidance and (for posters) proximity-aware board layouts.

## Pipeline

```
Papers (title + abstract + authors)
        │
        ▼
┌──────────────────────────┐
│  Taxonomy Builder        │  LLM iteratively subdivides & classifies
│  (taxonomy_builder.py)   │  ⚡ Multi-threaded sibling expansion
└──────────────────────────┘
        │
        ├─── ORAL PATH ────────────────┐
        │                              │
        ▼                              ▼
┌──────────────────┐          ┌──────────────────────┐
│  Session Former  │          │  Poster Former       │
│  (merge/split)   │          │  (larger groups)     │
└──────────────────┘          └──────────────────────┘
        │                              │
        ▼                              ▼
┌──────────────────┐          ┌──────────────────────┐
│  Graph-Coloring  │          │  Conflict-Aware      │
│  Scheduler       │          │  Scheduler (optional)│
└──────────────────┘          └──────────────────────┘
        │                              │
        ▼                              ▼
  Oral Schedule             ┌──────────────────────┐
  (conflict-free)           │  Floor Plan Layout   │
                            │  (Line/Circle/Rect)  │
                            └──────────────────────┘
                                       │
                                       ▼
                              Poster Schedule
                              (with board positions)
```

## Floor Plan Layouts

The poster organizer supports three physical layouts for board assignment:

### Line
Boards in a single row. Adjacent boards present similar topics.
```
[Board 0] ─ [Board 1] ─ [Board 2] ─ [Board 3] ─ ...
```

### Circle
Boards arranged around a circle. Adjacent boards (including wrap-around)
present similar topics. **Right-priority mode** (default): optimizes for a
left-to-right walking direction — the right-side neighbor of each board is
prioritized to be more similar, so topics transition smoothly as you walk
clockwise around the circle.
```
        [Board 0]
    [5]     →     [1]    ← Walking direction: clockwise
  [4]       →       [2]
        [Board 3]
```

### Rectangle
Boards in a grid (R rows × C cols). Papers within a row are similar;
adjacent rows also share thematic proximity.
```
  Row 0: [QO paper] | [QO paper] | [QO paper] | [QO paper]
  Row 1: [VS paper] | [VS paper] | [VS paper] | [VS paper]
  Row 2: [TX paper] | [TX paper] | [TX paper] | [TX paper]
```

## Quick Start

### Demo (no LLM / API key needed)

```bash
pip install networkx scikit-learn numpy

# Oral sessions only
python main.py --mode oral --demo

# Poster sessions with rectangle layout + proximity
python main.py --mode poster --demo --floor_plan rectangle --proximity

# Poster sessions with circle layout
python main.py --mode poster --demo --floor_plan circle

# Both oral and poster
python main.py --mode both --demo --floor_plan rectangle
```

### Real Data (requires OpenAI API key)

```bash
pip install openai networkx scikit-learn numpy

export OPENAI_API_KEY="sk-..."
python main.py --input papers.json --mode both \
    --floor_plan rectangle --proximity --poster_conflicts
```

### Input Format (`papers.json`)
```json
[
  {
    "id": "paper_001",
    "title": "Learned Index Structures for Dynamic Workloads",
    "abstract": "We propose a method for ...",
    "authors": ["Alice Chen", "Bob Zhang"]
  }
]
```

## CLI Options

| Option                  | Default     | Description                                  |
|-------------------------|-------------|----------------------------------------------|
| `--mode`                | `both`      | `oral`, `poster`, or `both`                  |
| `--demo`                | -           | Use synthetic demo data                      |
| `--input`               | -           | Path to papers JSON                          |
| `--max_depth`           | `3`         | Max taxonomy depth                           |
| `--floor_plan`          | `rectangle` | `line`, `circle`, or `rectangle`             |
| `--rect_cols`           | `6`         | Columns per row (rectangle only)             |
| `--proximity`           | on          | Enable proximity-based board placement       |
| `--no_proximity`        | -           | Disable proximity optimization               |
| `--poster_conflicts`    | on          | Avoid author conflicts in poster scheduling  |
| `--no_poster_conflicts` | -           | Disable author conflict avoidance            |
| `--circle_right_priority` | on        | Prioritize right-side similarity (circle)    |
| `--no_circle_right_priority` | -      | Use symmetric circle optimization            |
| `--poster_slots`        | `3`         | Number of poster time slots                  |
| `--poster_parallel`     | `2`         | Number of parallel poster areas              |
| `--oral_slots`          | `8`         | Number of oral time slots                    |
| `--oral_tracks`         | `4`         | Number of parallel oral tracks               |

## Project Structure

```
session_organizer/
├── main.py                 # Entry point, CLI, demo data, pretty-print
├── config.py               # All tunable parameters
├── models.py               # Paper, TaxonomyNode, Session, PosterSession, etc.
├── taxonomy_builder.py     # LLM-based iterative taxonomy construction
├── session_organizer.py    # Oral session formation + conflict-free scheduling
├── poster_organizer.py     # Poster session formation, scheduling, layout
├── similarity.py           # TF-IDF / embedding paper similarity engine
├── floor_plan.py           # Proximity layout optimizer (Line/Circle/Rectangle)
└── output/                 # Generated schedule JSON files
```

## Algorithms

### Taxonomy Construction (Multi-Threaded)
Iterative LLM-driven process: at each node, the LLM proposes child categories
and classifies papers. Input is title+abstract when under the token threshold,
or title-only when over it. Stops at max depth or when the LLM says CANNOT_SPLIT.

**Parallelism**: After a node's children are created and papers classified,
all sibling children are expanded concurrently via `ThreadPoolExecutor`
(configurable `LLM_MAX_WORKERS`, default 4). Each child's subdivision +
classification involves sequential LLM calls, but siblings at the same depth
run in parallel threads. This provides up to N× speedup where N is the
branching factor.

### Oral Scheduling
Graph coloring on the session conflict graph (edges = shared authors between
sessions). Greedy most-constrained-first with DSatur fallback.

### Poster Proximity Layout
- **Line**: Solved as a TSP variant using nearest-neighbor heuristic +
  2-opt local search to minimize total dissimilarity between adjacent boards.
- **Circle** (with right-priority): A 3-step process:
  1. Standard circular TSP (nearest-neighbor + 2-opt) for initial ordering
  2. Direction selection: evaluate both clockwise and counterclockwise using a
     **directional cost function** that sums weighted forward-hop distances
     (`w1 * dist(i, i+1) + w2 * dist(i, i+2)`), then pick the better direction
  3. Directional local search: adjacent swaps and Or-opt moves (relocating a
     single paper to a new position) evaluated with the asymmetric cost function,
     ensuring the right-side transition quality improves monotonically
- **Rectangle**: (1) Spectral partitioning (Fiedler vector) to assign papers
  to rows, (2) TSP within each row for intra-row coherence, (3) TSP on row
  centroids for inter-row coherence.
```
