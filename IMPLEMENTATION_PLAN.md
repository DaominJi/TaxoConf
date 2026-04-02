# Implementation Plan: Four Feature Requests

---

## Feature 1: Conference Workspace Management

### Concept
Each workspace = one conference. Users can create, switch, and persist workspaces. Each workspace stores its own paper data, oral/poster results, taxonomy cache, similarity cache, and token usage history.

### Data Folder Layout (Proposed)

```
data/
├── SIGIR25/                         ← one workspace = one folder
│   ├── workspace.json               ← NEW: workspace metadata
│   ├── oral/                        ← NEW: oral-specific data
│   │   ├── papers.json              ← oral paper list (uploaded or copied)
│   │   ├── result.json              ← last oral run result (sessions, assignment, hardPapers)
│   │   └── taxonomy.json            ← cached oral taxonomy tree
│   ├── poster/                      ← NEW: poster-specific data
│   │   ├── papers.json              ← poster paper list (can differ from oral)
│   │   ├── result.json              ← last poster run result
│   │   └── taxonomy.json            ← cached poster taxonomy tree
│   ├── token_usage.json             ← accumulated token/cost stats for this workspace
│   └── .cache/                      ← embedding cache (already exists conceptually)
│       └── embeddings/
├── AAAI26/                          ← another workspace
│   ├── workspace.json
│   ├── oral/
│   ├── poster/
│   └── ...
```

### workspace.json Schema

```json
{
  "name": "SIGIR25",
  "created_at": "2026-04-02T10:00:00Z",
  "description": "SIGIR 2025 Full Papers",
  "oral_paper_count": 170,
  "poster_paper_count": 251,
  "last_oral_run": "2026-04-02T12:30:00Z",
  "last_poster_run": null
}
```

### Backend Changes (server.py)

New endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/workspaces` | GET | List all workspaces (scan `data/` for folders with `workspace.json`) |
| `POST /api/workspaces` | POST | Create a new workspace. Body: `{name, description?}`. Creates folder + `workspace.json` |
| `GET /api/workspaces/<name>` | GET | Get workspace details (metadata, paper counts, last run times) |
| `POST /api/workspaces/<name>/upload/oral` | POST | Upload oral paper JSON file |
| `POST /api/workspaces/<name>/upload/poster` | POST | Upload poster paper JSON file |
| `DELETE /api/workspaces/<name>` | DELETE | Delete a workspace (with confirmation) |

Modify existing endpoints to accept workspace context:
- All `/api/oral/*` and `/api/poster/*` endpoints already take `conference` param — this becomes the workspace name
- `load_conference_papers()` → split into `load_oral_papers(workspace)` and `load_poster_papers(workspace)`, reading from `data/<workspace>/oral/papers.json` and `data/<workspace>/poster/papers.json` respectively
- Result saving: after each run, save the result to `data/<workspace>/oral/result.json` or `data/<workspace>/poster/result.json`
- Result loading: when switching back to a workspace, load the last saved result

**Migration for existing data:** On startup, if `data/SIGIR25/SIGIR25_Full_Papers.json` exists but `data/SIGIR25/workspace.json` does not, auto-migrate by creating `workspace.json` and copying papers into both `oral/papers.json` and `poster/papers.json`.

### Frontend Changes (index.html)

**New UI: Workspace Switcher (top of sidebar, above nav buttons)**
- A dropdown/select showing all available workspaces
- A "+" button to create a new workspace (opens a modal)
- Displays current workspace name prominently

**New State:**
```javascript
state.workspace = {
  current: null,          // current workspace name
  available: [],          // list of {name, description, created_at, ...}
}
```

**Create Workspace Modal:**
- Fields: workspace name (required), description (optional)
- Two file upload areas: "Oral Papers (JSON)" and "Poster Papers (JSON)"
- Create button → POST `/api/workspaces` then uploads files
- The JSON format should be documented in the modal (array of `{id, title, authors}` objects)

**Workspace Switch Behavior:**
- Switching workspace resets `state.oral.result`, `state.poster.result`
- Calls `/api/oral/info?conference=<workspace>` and `/api/poster/info?conference=<workspace>` to refresh
- If a saved result exists for this workspace, loads and displays it

### Key Design Decisions

1. **Oral and poster papers are separate files.** The same paper data can be uploaded to both, but they are stored independently. This allows conferences where oral and poster tracks have different paper sets.
2. **Results are persisted per workspace.** When users switch away and come back, they see their last run results without re-running.
3. **Backward compatible.** Existing `data/SIGIR25/` folder is auto-migrated on first load.

---

## Feature 2: Lock Paper Assignment & Reviewer Discovery Pages

### Concept
Disable the "Paper Assignment" and "Reviewer Discovery" nav buttons. Clicking them shows a banner/toast saying "Under Construction" instead of switching to a broken page.

### Frontend Changes (index.html)

**Option A: Visual Lock (Recommended)**

Add a CSS class `.nav-btn.is-locked` with a distinct style (grayed out, lock icon or "(Coming Soon)" label):

```css
.nav-btn.is-locked {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;  /* OR handle click to show message */
  position: relative;
}
.nav-btn.is-locked::after {
  content: " (Coming Soon)";
  font-size: 0.75em;
  opacity: 0.7;
}
```

Modify `switchTask()`:
```javascript
function switchTask(task) {
  if (task === "assignment" || task === "discovery") {
    showToast("This feature is under construction. Stay tuned!");
    return;  // do not switch
  }
  // ... existing logic
}
```

**Changes to nav buttons in HTML:**
```html
<button class="nav-btn is-locked" data-task="assignment">Paper Assignment</button>
<button class="nav-btn is-locked" data-task="discovery">Reviewer Discovery</button>
```

**Toast/Banner:** A small temporary notification that appears at the top of the main content area for ~3 seconds:
```html
<div id="globalToast" class="toast" aria-live="polite"></div>
```
```javascript
function showToast(message, duration = 3000) {
  const el = document.getElementById("globalToast");
  el.textContent = message;
  el.classList.add("is-visible");
  setTimeout(() => el.classList.remove("is-visible"), duration);
}
```

### Backend Changes
- Keep the placeholder endpoints as-is (they already return 501/placeholder status)
- No additional backend work needed

---

## Feature 3: Settings Page

### Concept
A new "Settings" page (or a slide-out panel / modal) where users configure:
- **LLM provider & model** selection
- **API key** management (load from env or manual input)
- **Oral organization method** (greedy vs. optimization, solver choice)
- **Poster organization method** (greedy vs. optimization, solver choice, floor plan type)
- **Embedding/similarity method** (TF-IDF vs. sentence-transformer, model name)

### Frontend: Settings Page

**Add to sidebar navigation:**
```html
<button class="nav-btn" data-task="settings">Settings</button>
```

**Add a new task view:**
```html
<section id="task-settings" class="task-view">
  <!-- Settings content -->
</section>
```

**Settings Layout (4 panels):**

#### Panel 1: LLM Configuration
```
┌─────────────────────────────────────────────────┐
│ LLM Provider & Model                            │
│                                                 │
│ Provider:  [OpenAI ▼]                           │
│ Model:     [gpt-4o   ]  (editable text input)   │
│ Temperature: [0.3]                              │
│                                                 │
│ API Key Source:                                  │
│   ○ Load from environment variable              │
│   ○ Enter manually                              │
│                                                 │
│ [API key input, shown only when manual]         │
│                                                 │
│ ┌─ Guidance ──────────────────────────────────┐ │
│ │ To load from environment variables, set     │ │
│ │ the appropriate key before starting the     │ │
│ │ server:                                     │ │
│ │                                             │ │
│ │  • Google Gemini:                           │ │
│ │    export GOOGLE_API_KEY=your_key_here      │ │
│ │                                             │ │
│ │  • OpenAI GPT:                              │ │
│ │    export OPENAI_API_KEY=your_key_here      │ │
│ │                                             │ │
│ │  • Anthropic Claude:                        │ │
│ │    export ANTHROPIC_API_KEY=your_key_here   │ │
│ │                                             │ │
│ │  • xAI Grok:                                │ │
│ │    export XAI_API_KEY=your_key_here         │ │
│ │                                             │ │
│ │ On Windows, use:                            │ │
│ │    set OPENAI_API_KEY=your_key_here         │ │
│ │                                             │ │
│ │ Or add to a .env file in the project root.  │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ [Test Connection]  → calls a small API test     │
└─────────────────────────────────────────────────┘
```

**Provider → Environment Variable mapping (displayed to user):**
| Provider | Env Variable | Models |
|----------|-------------|--------|
| Google Gemini | `GOOGLE_API_KEY` | gemini-2.5-flash, gemini-2.5-pro, gemini-3-flash, ... |
| OpenAI GPT | `OPENAI_API_KEY` | gpt-4o, gpt-4.1, gpt-4.1-mini, gpt-5, o3-mini, ... |
| Anthropic Claude | `ANTHROPIC_API_KEY` | claude-sonnet-4, claude-opus-4.6, claude-haiku-4.5, ... |
| xAI Grok | `XAI_API_KEY` | grok-3, grok-4, grok-4-fast, ... |

#### Panel 2: Oral Session Organization Settings
```
┌─────────────────────────────────────────────────┐
│ Oral Session Method                             │
│                                                 │
│ Organization method:  [Greedy ▼]                │
│   Options: Greedy, Optimization (ILP)           │
│                                                 │
│ Solver (if Optimization):  [Heuristic ▼]        │
│   Options: Heuristic, ILP                       │
│                                                 │
│ Conflict avoidance:  [✓] Enable                 │
│ Similarity weight (α): [1.0]                    │
└─────────────────────────────────────────────────┘
```

#### Panel 3: Poster Session Organization Settings
```
┌─────────────────────────────────────────────────┐
│ Poster Session Method                           │
│                                                 │
│ Organization method:  [Greedy ▼]                │
│   Options: Greedy, Optimization (ILP)           │
│                                                 │
│ Solver (if Optimization):  [Heuristic ▼]        │
│   Options: Heuristic, ILP                       │
│                                                 │
│ Conflict avoidance:  [✓] Enable                 │
│ Proximity optimization: [✓] Enable              │
│ Similarity weight (α): [1.0]                    │
└─────────────────────────────────────────────────┘
```

#### Panel 4: Embedding & Similarity Settings
```
┌─────────────────────────────────────────────────┐
│ Similarity & Embedding                          │
│                                                 │
│ Similarity method:  [TF-IDF ▼]                  │
│   Options: TF-IDF, Sentence Transformer         │
│                                                 │
│ Embedding model (if Sentence Transformer):      │
│   [all-MiniLM-L6-v2     ]                       │
│                                                 │
│ Embedding cache:  [✓] Enable                    │
└─────────────────────────────────────────────────┘
```

**Save behavior:** A single "Save Settings" button at the bottom. Saves to backend which updates `config` module in-memory and optionally persists to `config.yaml`.

### Backend Changes (server.py)

New endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/settings` | GET | Return current settings (LLM provider, model, methods, similarity, etc.) |
| `PUT /api/settings` | PUT | Update settings. Body: partial settings object. Updates `config` module in-memory. |
| `POST /api/settings/test-llm` | POST | Test LLM connectivity. Body: `{provider, model, api_key?}`. Makes a tiny test call and returns success/error. |

**Settings response shape:**
```json
{
  "result": {
    "llm": {
      "provider": "openai",
      "model": "gpt-4o",
      "temperature": 0.3,
      "api_key_source": "environment",
      "api_key_set": true
    },
    "oral": {
      "method": "greedy",
      "solver": "heuristic",
      "enable_conflict_avoidance": true,
      "alpha": 1.0
    },
    "poster": {
      "method": "greedy",
      "solver": "heuristic",
      "enable_conflict_avoidance": true,
      "proximity": true,
      "alpha": 1.0
    },
    "similarity": {
      "method": "tfidf",
      "embedding_model": "all-MiniLM-L6-v2",
      "cache_enabled": true
    }
  }
}
```

**API key handling:**
- When `api_key_source` is `"environment"`: use `os.environ.get(KEY_NAME)` as today
- When `api_key_source` is `"manual"`: the frontend sends the key in the PUT body, server stores it in `os.environ[KEY_NAME]` for the session (NOT persisted to disk for security). The key value is never returned in GET responses — only `api_key_set: true/false`.

### Key Design Decisions

1. **API keys entered manually are session-only.** They are set as environment variables in the running server process but never written to disk. On server restart, manual keys are lost — this is by design for security.
2. **Settings are applied immediately.** No server restart needed. The `config` module variables are updated in-place.
3. **The model field is a free-text input**, not a fixed dropdown, because new models are released frequently. The provider dropdown determines which SDK/API is used.

---

## Feature 4: Token & Cost Statistics Dashboard

### Concept
A dashboard panel (visible on the Overview page or as its own page) that shows:
- **Per-run stats:** token usage and cost for the most recent oral/poster run
- **Per-workspace stats:** accumulated tokens and cost across all runs in this workspace
- **Global (total) stats:** accumulated across all workspaces
- **Reset buttons** for workspace and global counters

### Data Storage

**Per-workspace:** `data/<workspace>/token_usage.json`
```json
{
  "workspace": "SIGIR25",
  "total_calls": 45,
  "total_prompt_tokens": 125000,
  "total_completion_tokens": 48000,
  "total_tokens": 173000,
  "total_cost_usd": 1.2340,
  "runs": [
    {
      "run_id": "oral_2026-04-02T12:30:00",
      "mode": "oral",
      "timestamp": "2026-04-02T12:30:00Z",
      "calls": 12,
      "prompt_tokens": 45000,
      "completion_tokens": 18000,
      "total_tokens": 63000,
      "cost_usd": 0.4500,
      "provider": "openai",
      "model": "gpt-4o"
    },
    ...
  ]
}
```

**Global:** `data/global_token_usage.json`
```json
{
  "total_calls": 120,
  "total_prompt_tokens": 450000,
  "total_completion_tokens": 180000,
  "total_tokens": 630000,
  "total_cost_usd": 4.5600,
  "last_reset": null
}
```

### Backend Changes (server.py)

New endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/token-stats` | GET | Return all three levels: current run (from in-memory tracker), workspace stats (from file), global stats (from file) |
| `GET /api/token-stats/workspace/<name>` | GET | Return detailed stats for a specific workspace including run history |
| `POST /api/token-stats/reset/workspace/<name>` | POST | Reset workspace token stats (clears the file) |
| `POST /api/token-stats/reset/global` | POST | Reset global token stats |

After each oral/poster run:
1. Get the run's token usage from `get_global_tracker().to_dict()`
2. Append it as a new run entry to `data/<workspace>/token_usage.json`
3. Add it to `data/global_token_usage.json` totals
4. Return the run stats in the API response (already done via `tokenUsage` field)

### Frontend: Token Stats Dashboard

**Location:** On the Overview page, add a new collapsible panel below the existing content.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Token & Cost Statistics                                     │
│                                                             │
│ ┌─ Last Run ──────────────────────────────────────────────┐ │
│ │ Mode: Oral │ Provider: openai/gpt-4o                    │ │
│ │ Calls: 12  │ Prompt: 45,000 │ Completion: 18,000        │ │
│ │ Total: 63,000 tokens │ Cost: $0.4500                    │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ Workspace: SIGIR25 ─────────────────── [Reset] ────────┐ │
│ │ Total runs: 5 │ Total calls: 45                         │ │
│ │ Total tokens: 173,000 │ Total cost: $1.2340             │ │
│ │                                                         │ │
│ │ Run History:                                            │ │
│ │  • oral  04/02 12:30  63K tokens  $0.45  gpt-4o        │ │
│ │  • poster 04/02 13:15  42K tokens  $0.30  gpt-4o       │ │
│ │  • oral  04/01 09:00  68K tokens  $0.48  gemini-2.5    │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ Global (All Workspaces) ────────────── [Reset] ────────┐ │
│ │ Total calls: 120 │ Total tokens: 630,000                │ │
│ │ Total cost: $4.5600                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**New State:**
```javascript
state.tokenStats = {
  lastRun: null,           // from the most recent API response's tokenUsage field
  workspace: null,         // from GET /api/token-stats
  global: null,            // from GET /api/token-stats
}
```

**Behavior:**
- Stats refresh automatically after each oral/poster run (data is already in the response)
- Clicking "Reset" calls the POST reset endpoint and refreshes the display
- The overview page loads stats on init via `GET /api/token-stats`

---

## Implementation Order (Recommended)

| Phase | Feature | Reason |
|-------|---------|--------|
| 1 | **Feature 2: Lock pages** | Smallest change, immediate UX improvement, no backend work |
| 2 | **Feature 3: Settings page** | Enables LLM configuration from UI, unblocks users who struggle with env vars |
| 3 | **Feature 1: Workspace management** | Largest change — restructures data layer, needs careful migration |
| 4 | **Feature 4: Token stats dashboard** | Depends on workspace structure (Feature 1) for per-workspace tracking |

**Estimated scope:**
- Feature 2: ~50 lines HTML/CSS/JS changes
- Feature 3: ~300 lines frontend + ~100 lines backend
- Feature 1: ~400 lines frontend + ~200 lines backend + data migration logic
- Feature 4: ~200 lines frontend + ~100 lines backend + file I/O

---

## Open Questions for Discussion

1. **Workspace creation:** Should creating a workspace require uploading paper files immediately, or can users create an empty workspace and upload later?
2. **Shared vs. separate papers:** When users upload one paper JSON, should it auto-populate both oral and poster, or must they upload separately?
3. **Settings persistence:** Should settings be per-workspace or global? (Plan assumes global.)
4. **Token stats granularity:** Should the run history show every individual LLM call, or just per-run summaries?
5. **Manual API key security:** Is session-only storage (lost on restart) acceptable, or do users want persistent encrypted storage?
