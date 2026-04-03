<p align="center">
  <h1 align="center">TaxoConf</h1>
  <p align="center">
    A taxonomy-driven framework for conference session organization
    <br />
    <a href="https://taxoconf.github.io/taxoconf/">Online Demo</a>
    &middot;
    <a href="https://drive.google.com/drive/folders/1CGWR8dQAImLSdPQ58_7c_KENvS-6L9ca?usp=drive_link">Supplementary Materials</a>
    &middot;
    <a href="https://github.com/DaominJi/TaxoConf/issues">Report Bug</a>
  </p>
</p>

---

TaxoConf constructs a hierarchical taxonomy over accepted papers using LLMs, then leverages this structure to organize conference sessions. It provides a web-based workspace with interactive schedule editing, metadata management, and multi-format export.

## Features

| | Feature | Description |
|---|---|---|
| 01 | **Paper-reviewer assignment** | Matches papers to reviewers based on topical alignment via taxonomy-derived expertise distributions |
| 02 | **PC member discovery** | Identifies additional reviewers from external pools when existing PC coverage is insufficient |
| 03 | **Oral session organization** | Groups papers into coherent sessions across time slots and parallel tracks with conflict avoidance |
| 04 | **Poster session organization** | Arranges posters using proximity-aware layouts (line, circle, rectangle) for topical coherence |

## Screenshots

<details>
<summary>Click to expand</summary>

**Overview page** &mdash; Input/output format documentation and project links

**Oral schedule grid** &mdash; 2D schedule with inline time/date/room editing per slot and track

**Session detail panel** &mdash; Slide-in panel for editing session metadata and moving papers

**Export** &mdash; Excel, CSV, and interactive HTML with search, print styles, and navigation

</details>

## Quick Start

### Prerequisites

- Python 3.10+
- An API key from one of: [OpenAI](https://platform.openai.com/), [Google Gemini](https://ai.google.dev/), [Anthropic](https://console.anthropic.com/), or [xAI](https://console.x.ai/)

### Installation

```bash
# Clone the repository
git clone https://github.com/DaominJi/TaxoConf.git
cd TaxoConf

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install openpyxl  # For Excel export
```

### Set up your LLM API key

```bash
# Choose one provider:
export OPENAI_API_KEY="sk-..."           # OpenAI
export GOOGLE_API_KEY="AI..."            # Google Gemini
export ANTHROPIC_API_KEY="sk-ant-..."    # Anthropic
export XAI_API_KEY="xai-..."             # xAI Grok
```

### Run the server

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** in your browser.

### First-time setup

1. Go to **Settings** and verify your LLM provider is configured (you should see "Key configured" in green)
2. Click **Test Connection** to confirm
3. Create a workspace or use the default SIGIR25 demo data

## Usage

### 1. Create a workspace

Click the **+** button in the sidebar to create a new workspace. Each workspace is either **oral** or **poster** (they use separate paper sets). Upload your paper data as JSON or CSV.

### 2. Input data format

TaxoConf accepts paper metadata in **JSON** or **CSV**. Required fields: `id`, `title`, `authors`. Optional: `abstract` (improves topic classification).

**JSON:**
```json
[
  {
    "id": 1,
    "title": "Retrieval-Augmented Generation with Adaptive Passage Selection",
    "authors": "Alice Wang, Bob Chen, Carol Liu",
    "abstract": "We propose a novel RAG framework..."
  }
]
```

**CSV:**
```
id,title,authors,abstract
1,"Retrieval-Augmented Generation with Adaptive Passage Selection","Alice Wang, Bob Chen, Carol Liu","We propose a novel RAG framework..."
```

### 3. Configure and run

- Set session parameters (parallel tracks, time slots, min/max papers per session)
- Click **Run Oral Organization** or **Run Poster Organization**
- The system builds a taxonomy via your LLM and generates an optimized schedule

### 4. Edit session metadata

- **Inline grid editing**: Edit track names, room locations, dates, and times directly in the schedule grid
- **Session detail panel**: Click any session tile to edit the session name, chair, and move papers between sessions
- **Last-mile modifications**: Review LLM-flagged hard-to-place papers and reassign them

### 5. Save and export

- **Save Progress** / **Load Progress**: Persist your edits to the server with named saves
- **Export**: Download the schedule as Excel (.xlsx using conference template), CSV, or interactive HTML

## Project Structure

```
TaxoConf/
├── server.py                 # FastAPI backend (API + static file server)
├── taxonomy_builder.py       # LLM-based iterative taxonomy construction
├── session_organizer.py      # Oral session formation + conflict-free scheduling
├── poster_organizer.py       # Poster session formation + floor plan layouts
├── session_reviewer.py       # LLM-based session review (hard paper flagging)
├── similarity.py             # TF-IDF / embedding paper similarity engine
├── floor_plan.py             # Proximity layout optimizer (line/circle/rectangle)
├── token_tracker.py          # LLM token usage and cost tracking
├── config.py                 # Configuration defaults
├── models.py                 # Data models (Paper, Session, TaxonomyNode, etc.)
├── index.html                # Web UI (721-line HTML shell)
├── css/                      # Modular CSS (10 files)
├── js/                       # ES modules (17 files)
│   ├── app.js                # Entry point
│   ├── state.js              # Central state management
│   ├── views/                # Task-specific UI modules
│   │   ├── oral.js           # Oral session organization
│   │   ├── poster.js         # Poster session organization
│   │   ├── settings.js       # LLM provider configuration
│   │   └── ...
│   └── ...
├── template/                 # Excel export template
├── data/                     # Workspace data directories
│   └── {workspace}/
│       ├── workspace.json    # Workspace metadata (name, mode, paper path)
│       ├── papers.json       # Paper data
│       └── progress/         # Saved editing progress
└── requirements.txt
```

## Supported LLM Providers

| Provider | Environment Variable | Example Models |
|----------|---------------------|----------------|
| OpenAI | `OPENAI_API_KEY` | gpt-4o, gpt-4.1, gpt-5.4, o3-mini |
| Google Gemini | `GOOGLE_API_KEY` | gemini-2.5-flash, gemini-2.5-pro, gemini-3.1-pro-preview |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5 |
| xAI | `XAI_API_KEY` | grok-3, grok-4, grok-4-fast |

The model can be selected in the Settings page. When an API key is configured, available models are fetched dynamically from the provider.

## Deployment

For local use, the dev server (`uvicorn --reload`) is sufficient. For shared access on a remote server:

```bash
# Production deployment with nginx reverse proxy
python -m uvicorn server:app --host 127.0.0.1 --port 8000

# Then configure nginx to proxy port 80/443 → 8000
# and use Let's Encrypt for HTTPS
```

See the full [deployment guide](https://github.com/DaominJi/TaxoConf/wiki/Deployment) for Docker and nginx configuration.

## Algorithms

### Taxonomy Construction
Iterative LLM-driven process with multi-threaded sibling expansion. At each node, the LLM proposes child categories and classifies papers. Parallelism via `ThreadPoolExecutor` provides up to N&times; speedup where N is the branching factor.

### Oral Scheduling
Graph coloring on the session conflict graph (edges = shared authors). Greedy most-constrained-first with DSatur fallback ensures conflict-free parallel sessions.

### Poster Proximity Layout
- **Line**: TSP variant with nearest-neighbor + 2-opt for adjacent topic similarity
- **Circle**: 3-step process with directional cost function for clockwise walking optimization
- **Rectangle**: Spectral partitioning (Fiedler vector) for row assignment, TSP within and between rows

## Contact

- **Issues**: [GitHub Issues](https://github.com/DaominJi/TaxoConf/issues)
- **Email**: [daominji@student.rmit.edu.au](mailto:daominji@student.rmit.edu.au)

## License

This project is for academic and research purposes.
