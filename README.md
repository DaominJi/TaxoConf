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

TaxoConf constructs a hierarchical taxonomy over accepted papers using LLMs, then leverages this structure to organize conference sessions. It provides a web-based workspace with real-time progress tracking, interactive schedule editing, context-aware session naming, and multi-format export.

## Features

| | Feature | Description |
|---|---|---|
| 01 | **Paper-reviewer assignment** | Matches papers to reviewers based on topical alignment via taxonomy-derived expertise distributions |
| 02 | **PC member discovery** | Identifies additional reviewers from external pools when existing PC coverage is insufficient |
| 03 | **Oral session organization** | Groups papers into coherent sessions across time slots and parallel locations with conflict avoidance |
| 04 | **Poster session organization** | Arranges posters using proximity-aware layouts (line, circle, rectangle) for topical coherence |

## Screenshots

<details>
<summary>Click to expand</summary>

**Overview page** &mdash; Input/output format documentation and project links

**Oral schedule grid** &mdash; 2D schedule with inline time/date/room editing, global track name, and session tiles

**Session detail panel** &mdash; Slide-in panel for editing session metadata, chairs, and moving papers

**Last-mile review** &mdash; LLM-flagged hard-to-place papers with suggested alternative sessions

**Export** &mdash; Excel (conference template), CSV, and interactive HTML with search and print

</details>

## Quick Start

### Prerequisites

- Python 3.10+
- An [OpenRouter](https://openrouter.ai/) API key (provides unified access to OpenAI, Anthropic, Google, and 300+ models)

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

### Set up your API key

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

Get your key at [openrouter.ai/keys](https://openrouter.ai/keys).

### Run the server

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** in your browser.

### First-time setup

1. Go to **Settings** &mdash; verify "Key configured" appears in green
2. Select a model (default: `openai/gpt-5.4-mini`) &mdash; pricing is shown inline
3. Click **Test Connection** to confirm, then **Save Settings**
4. Create a workspace or use the default SIGIR25 demo data

## Usage

### 1. Create a workspace

Click the **+** button in the sidebar. Each workspace is either **oral** or **poster** (separate paper sets). Upload paper data as JSON or CSV.

### 2. Input data format

Required fields: `id`, `title`, `authors`. Optional: `abstract` (improves topic classification).

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

- Set session parameters (parallel locations, time slots, min/max papers per session)
- Optionally enable "Avoid presenter conflicts" and "Use abstracts for taxonomy"
- Click **Run Oral Organization** or **Run Poster Organization**
- Real-time progress shows each pipeline step with elapsed time

### 4. Edit session metadata

- **Track name**: Single input above the grid &mdash; applies to all sessions (e.g., "Full Paper Track")
- **Locations & times**: Edit room names per column and date/time per slot directly in the grid header
- **Session detail panel**: Click any session tile to edit name, chair, location, and move papers
- **Last-mile review**: LLM-flagged hard-to-place papers with suggested alternative sessions

### 5. Save and export

- **Save Progress** / **Load Progress**: Named saves with timestamps, stored on the server
- **Export**: Excel (.xlsx using conference template), CSV (same schema), or interactive HTML with search, print styles, and navigation

## Pipeline

```
Papers (title + abstract + authors)
        |
        v
  Taxonomy Construction        LLM iteratively subdivides & classifies
  (multi-threaded)             papers into a hierarchical topic tree
        |
        v
  Session Formation            Bottom-up: leaf nodes become sessions,
  (greedy or ILP)              capacity-constrained merging/splitting
        |
        v
  Conflict-Free Scheduling     Graph coloring assigns sessions to
                               time slots avoiding author conflicts
        |
        v
  Context-Aware Naming         Bottom-up cascade: leaf sessions named
  + Global Normalization       from papers, parents from child names
        |
        v
  LLM Session Review           Flags misplaced papers with suggested
                               alternative sessions
        |
        v
  Interactive Editing          Web UI for metadata, moves, last-mile
  + Multi-Format Export        Excel / CSV / HTML export
```

## Project Structure

```
TaxoConf/
├── server.py                 # FastAPI backend with SSE streaming
├── llm_client.py             # Unified LLM client (OpenRouter)
├── taxonomy_builder.py       # LLM-based iterative taxonomy construction
├── session_organizer.py      # Session formation + conflict-free scheduling
├── session_namer.py          # Context-aware bottom-up session naming
├── session_reviewer.py       # LLM-based session review (hard paper flagging)
├── poster_organizer.py       # Poster session formation + floor plan layouts
├── similarity.py             # TF-IDF / embedding paper similarity engine
├── floor_plan.py             # Proximity layout optimizer (line/circle/rectangle)
├── token_tracker.py          # Token usage + live pricing from OpenRouter
├── config.py                 # Configuration defaults
├── models.py                 # Data models (Paper, Session, TaxonomyNode)
├── prompts/                  # LLM prompt templates
│   ├── taxonomy_subdivision.py
│   ├── taxonomy_classification.py
│   ├── session_naming.py
│   └── session_review.py
├── index.html                # Web UI shell
├── css/                      # Modular CSS (10 files)
├── js/                       # ES modules (17 files)
│   ├── app.js                # Entry point
│   ├── api.js                # API helpers + SSE stream reader
│   ├── state.js              # Central state management
│   └── views/                # Task-specific UI modules
├── template/                 # Excel export template
├── data/                     # Workspace data directories
│   └── {workspace}/
│       ├── workspace.json    # Metadata (name, mode, paper path)
│       ├── papers.json       # Paper data
│       └── progress/         # Named saves
└── requirements.txt
```

## LLM Access

TaxoConf uses [OpenRouter](https://openrouter.ai/) for unified LLM access. A single `OPENROUTER_API_KEY` provides access to 300+ models from all major providers:

| Provider | Example Models |
|----------|----------------|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4.1, gpt-5.4, gpt-5.4-mini |
| Anthropic | claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5 |
| Google | gemini-2.5-flash, gemini-2.5-pro, gemini-3.1-pro-preview |
| xAI | grok-3, grok-4, grok-4-fast |
| DeepSeek | deepseek-chat, deepseek-r1 |
| Meta | llama-3.3-70b, llama-4-maverick |

Models are fetched dynamically with **live pricing** displayed in the settings page. Filter by provider and see per-token costs before selecting.

## Deployment

### Local development

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### Production (remote server with nginx)

```bash
# 1. Set up systemd service
sudo tee /etc/systemd/system/taxoconf.service <<EOF
[Unit]
Description=TaxoConf Server
After=network.target
[Service]
User=$USER
WorkingDirectory=$HOME/TaxoConf
Environment="OPENROUTER_API_KEY=sk-or-..."
ExecStart=$HOME/TaxoConf/.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now taxoconf

# 2. Configure nginx with SSE support
sudo tee /etc/nginx/sites-available/taxoconf <<'EOF'
server {
    listen 80;
    server_name _;
    proxy_read_timeout 600s;
    proxy_connect_timeout 60s;
    proxy_send_timeout 600s;

    location ~ /api/(oral|poster)/run-stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location ~* \.(js|css)$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        add_header Cache-Control "no-cache, must-revalidate";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        client_max_body_size 50M;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/taxoconf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

### Updating a deployed server

```bash
cd ~/TaxoConf
git pull origin master
sudo systemctl restart taxoconf
```

## Algorithms

### Taxonomy Construction
Iterative LLM-driven top-down process with multi-threaded sibling expansion. At each node, the LLM proposes child categories and classifies papers. Papers with abstracts get better classification; falls back to titles-only when token budget is exceeded. Parallelism via `ThreadPoolExecutor` provides up to N&times; speedup.

### Session Formation
Bottom-up post-order traversal of the taxonomy tree. Leaf nodes that fit within capacity bounds become sessions directly. Over-sized nodes are split via similarity-based clustering; under-sized nodes bubble papers up to their parent. A deduplication step ensures each paper appears in exactly one session.

### Session Naming
Context-aware bottom-up cascade: leaf sessions are named from their taxonomy path + paper titles. Parent sessions are named from their path + already-named child sessions. A final global normalization pass reviews all names together to fix duplicates, generic titles, and inconsistencies.

### Conflict-Free Scheduling
Graph coloring on the session conflict graph (edges = shared authors). Greedy most-constrained-first with DSatur fallback ensures no presenter appears in two parallel sessions.

### Poster Proximity Layout
- **Line**: TSP variant with nearest-neighbor + 2-opt for adjacent topic similarity
- **Circle**: 3-step directional TSP optimized for clockwise walking
- **Rectangle**: Spectral partitioning (Fiedler vector) for row assignment, TSP within and between rows

## Contact

- **Issues**: [GitHub Issues](https://github.com/DaominJi/TaxoConf/issues)
- **Email**: [daominji@student.rmit.edu.au](mailto:daominji@student.rmit.edu.au)

## License

This project is for academic and research purposes.
