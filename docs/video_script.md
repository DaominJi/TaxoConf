# TaxoConf Demo Video Script

**Estimated duration: 6–8 minutes**

---

## Scene 1: Introduction (0:00 – 0:40)

**[Screen: Overview page — TaxoConf title, four feature cards visible]**

> Welcome to TaxoConf — a taxonomy-driven framework for organizing academic conference sessions.
>
> TaxoConf takes a list of accepted papers and uses large language models to build a hierarchical topic taxonomy. It then uses this taxonomy to automatically organize papers into coherent oral or poster sessions.
>
> The system supports four key functions: paper–reviewer assignment, PC member discovery, oral session organization, and poster session organization. Today we'll walk through the full workflow for oral and poster sessions.

**[Action: Scroll down to show Input Data section with CSV/JSON tabs]**

> TaxoConf accepts paper data in CSV or JSON format. The required fields are ID, title, and authors. An optional abstract field improves the quality of topic classification.

---

## Scene 2: Setting Up the LLM (0:40 – 1:30)

**[Action: Click "Settings" in the sidebar]**

> Before running any organization task, we configure the LLM. TaxoConf uses OpenRouter, which provides unified access to over 300 models from OpenAI, Anthropic, Google, and other providers — all through a single API key.

**[Screen: Settings page — provider filter dropdown, model list with pricing]**

> We can filter models by provider. Each model shows its pricing per million tokens directly in the dropdown. Let's select GPT-5.4 Mini from OpenAI.

**[Action: Select OpenAI from provider filter, select openai/gpt-5.4-mini]**

> The pricing detail shows the input and output cost and the context window size. If you need to enter your API key manually, switch to "Enter manually" and paste it here. Otherwise, set the `OPENROUTER_API_KEY` environment variable on your server.

**[Action: Click "Test Connection"]**

> Click Test Connection to verify the LLM is working. We see a success message — we're ready to go.

**[Action: Click "Save Settings"]**

---

## Scene 3: Oral Session Organization (1:30 – 4:30)

### 3.1 Data and Parameters (1:30 – 2:00)

**[Action: Click "Oral Session Organization" in the sidebar]**

> Let's organize oral sessions. The workspace selector shows our conference — SIGIR 2025 with 251 papers. The setup panel has three sections.

**[Screen: Oral setup panel expanded — three control cards]**

> On the left, Session Parameters: parallel sessions M, time slots N, and the min/max papers per session. These are auto-calculated from the paper count but you can adjust them. We also have two checkboxes — one to avoid presenter conflicts across parallel sessions, and one to use abstracts for taxonomy construction.
>
> In the center, the Capacity Check confirms the configuration can fit all papers.
>
> On the right, the export format selector — Excel, HTML, or CSV.

### 3.2 Running (2:00 – 2:40)

**[Action: Click "Run Oral Organization"]**

> Click Run. The status bar shows real-time progress as each pipeline step executes.

**[Screen: Status bar cycling through steps with elapsed time]**

> Step 1 builds the paper similarity matrix. Step 2 constructs the topic taxonomy using the LLM — this is the longest step, as each taxonomy node requires LLM calls to propose sub-categories and classify papers. Steps 3 and 4 form sessions, schedule them into time slots, and name each session using a context-aware bottom-up cascade. The final steps review sessions for misplaced papers.
>
> The elapsed time updates every 15 seconds so you always know the system is still working.

**[Screen: Results appear — setup panel collapses, sidebar collapses, schedule grid visible]**

> When complete, the setup panel and sidebar collapse automatically to give the results maximum space.

### 3.3 Schedule Grid (2:40 – 3:20)

**[Screen: Full schedule grid with session tiles]**

> The result is a two-dimensional schedule grid. Each row is a time slot, each column is a location. At the top, the Track field lets you set the track name — for example, "Full Paper Track" — which applies to all sessions and appears in exports.
>
> Each column header has a Room/Location field. Each time slot shows editable date and time fields on the left. Setting the time for one slot automatically propagates to all parallel sessions in that row.
>
> Each session tile shows the LLM-generated session name, paper count, and a capacity badge.

### 3.4 Editing (3:20 – 4:00)

**[Action: Click a session tile — slide-in panel opens from right]**

> Click any session to open the detail panel. Here you can edit the session name, assign a session chair, set the date, time, and location. Time changes propagate to all parallel sessions in the same slot.
>
> Below the metadata, each paper has a dropdown to move it to a different session. The system checks for presenter conflicts before applying the move.

**[Action: Close panel, scroll to Last-Mile section]**

> Below the grid is the Last-Mile Modification panel. The LLM reviews all sessions and flags papers that may not fit their session's theme. Click a flagged paper to see the reason and a list of alternative sessions. Select a better fit and click Apply.

### 3.5 Save, Load, Export (4:00 – 4:30)

**[Action: Click "Save Progress"]**

> Click Save Progress. Enter a name — for example, "SIGIR oral v1" — and save. Your edits are stored on the server.

**[Action: Click "Load Progress"]**

> Click Load Progress to see all saved versions with timestamps. Click any save to restore it. This is useful when finding session chairs takes time — you can save your work and continue later.

**[Action: Select Excel format, click "Export"]**

> To export, select a format — Excel uses a conference template, CSV follows the same schema, and HTML produces an interactive page with search and print support. Click Export and the file downloads.

---

## Scene 4: Poster Session Organization (4:30 – 5:45)

### 4.1 Setup (4:30 – 5:00)

**[Action: Click "Poster Session Organization" in the sidebar]**

> Poster organization follows the same workflow. The setup panel offers floor plan options — Rectangle with rows and columns, or Line and Circle layouts. Set the session count and optionally enable the checkbox to prevent the same presenter from appearing in the same session.

### 4.2 Running and Editing (5:00 – 5:30)

**[Action: Click "Run Poster Organization"]**

> Click Run. The pipeline is similar — taxonomy construction, session formation, board layout optimization, session naming, and review. Each step shows real-time progress.

**[Screen: Poster grid with session cards and board layouts]**

> The results show poster session cards, each with the floor plan layout and board assignments. Click a session card to edit metadata and move papers between sessions — the interface is consistent with oral sessions.

### 4.3 Save and Export (5:30 – 5:45)

> Save Progress, Load Progress, and Export work the same way. All three export formats are available — Excel, CSV, and HTML.

---

## Scene 5: Token and Cost Tracking (5:45 – 6:15)

**[Action: Click "Token & Cost" in the sidebar]**

> The Token & Cost page tracks LLM usage. Three summary cards show the last run, current workspace totals, and global totals — including prompt tokens, completion tokens, and estimated cost based on live pricing from OpenRouter.
>
> Below is the run history table with timestamps, token counts, cost, and the model used for each run. You can reset workspace or global counters with the Reset buttons.

---

## Scene 6: Closing (6:15 – 6:30)

**[Screen: Back to Overview page]**

> That's TaxoConf — from paper data to a complete conference schedule in one integrated workspace. The system handles taxonomy construction, session formation, intelligent naming, conflict avoidance, and last-mile review, with full support for manual editing and multi-format export.
>
> Visit our GitHub repository for the source code and installation guide. Thank you for watching.

---

## Quick Reference

| Action | Steps |
|--------|-------|
| Configure LLM | Settings → Filter provider → Select model → Test → Save |
| Run oral/poster | Select task → Configure parameters → Run |
| Edit metadata | Click session tile → Edit fields → Save |
| Edit track/times | Type in grid header fields (auto-propagates) |
| Move papers | Session detail → Select target → Move |
| Review hard papers | Last-Mile panel → Click flagged paper → Apply |
| Save progress | Toolbar → Save Progress → Enter name → Save |
| Load progress | Toolbar → Load Progress → Select from list |
| Export | Select format (Excel/CSV/HTML) → Export |
| Check costs | Token & Cost tab → View summaries and history |
