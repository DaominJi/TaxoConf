"""
Generate a single self-contained HTML file that visualises the oral and
poster session schedules in a clean, academic aesthetic.

Usage:
    python visualize_schedule.py [--oral oral_schedule.json]
                                 [--poster poster_schedule.json]
                                 [--output schedule.html]
"""

import argparse
import json
import os
from html import escape

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ORAL = os.path.join(SCRIPT_DIR, "output", "oral_schedule.json")
DEFAULT_POSTER = os.path.join(SCRIPT_DIR, "output", "poster_schedule.json")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "output", "schedule.html")

# ── Palette ────────────────────────────────────────────────────────
TRACK_COLORS = [
    "#4A90D9", "#E07A5F", "#81B29A", "#F2CC8F",
    "#6C5B7B", "#C06C84", "#355C7D", "#F8B500",
]

AREA_COLORS = ["#5B8C5A", "#8B5E3C"]


def _authors_html(authors) -> str:
    if isinstance(authors, list):
        return escape(", ".join(authors))
    return escape(str(authors))


def _build_oral_html(data: dict) -> str:
    sessions = data["sessions"]
    summary = data["summary"]

    slots: dict[int, list] = {}
    for s in sessions:
        slots.setdefault(s["time_slot"], []).append(s)
    for k in slots:
        slots[k].sort(key=lambda s: s["track"])

    num_tracks = max((s["track"] for s in sessions), default=0) + 1
    num_slots = len(slots)

    # Grid
    rows_html = []
    for slot_idx in sorted(slots):
        cells = ['<td class="slot-label">Session&nbsp;' + str(slot_idx + 1) + '</td>']
        track_sessions = {s["track"]: s for s in slots[slot_idx]}
        for t in range(num_tracks):
            s = track_sessions.get(t)
            if s:
                color = TRACK_COLORS[t % len(TRACK_COLORS)]
                papers_li = "".join(
                    f'<li><span class="paper-title">{escape(p["title"])}</span>'
                    f'<span class="paper-authors">{_authors_html(p["authors"])}</span></li>'
                    for p in s["papers"]
                )
                cells.append(
                    f'<td class="session-cell" style="border-top:3px solid {color}">'
                    f'<div class="session-name" style="color:{color}">{escape(s["name"])}</div>'
                    f'<div class="session-desc">{escape(s.get("description",""))}</div>'
                    f'<div class="toggle-hint"><span class="hint-text">▼ Show {len(s["papers"])} papers</span></div>'
                    f'<ul class="paper-list">{papers_li}</ul>'
                    f'<div class="paper-count">{len(s["papers"])} paper{"s" if len(s["papers"])!=1 else ""}</div>'
                    f'</td>'
                )
            else:
                cells.append('<td class="session-cell empty"></td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    track_headers = "".join(
        f'<th style="border-bottom:3px solid {TRACK_COLORS[t % len(TRACK_COLORS)]}">'
        f'Track {t+1}</th>'
        for t in range(num_tracks)
    )

    return f"""
    <section class="schedule-section" id="oral">
      <h2>Oral Sessions</h2>
      <div class="summary-bar">
        <span><strong>{summary['total_papers']}</strong> papers</span>
        <span><strong>{summary['total_sessions']}</strong> sessions</span>
        <span><strong>{num_slots}</strong> time slots</span>
        <span><strong>{num_tracks}</strong> parallel tracks</span>
      </div>
      <div class="table-wrap">
        <table class="schedule-grid oral-grid">
          <thead><tr><th></th>{track_headers}</tr></thead>
          <tbody>{"".join(rows_html)}</tbody>
        </table>
      </div>
    </section>"""


def _build_poster_html(data: dict) -> str:
    sessions = data["sessions"]
    summary = data["summary"]

    slots: dict[int, list] = {}
    for s in sessions:
        slots.setdefault(s["time_slot"], []).append(s)
    for k in slots:
        slots[k].sort(key=lambda s: s["area"])

    num_areas = max((s["area"] for s in sessions), default=0) + 1

    blocks_html = []
    for slot_idx in sorted(slots):
        area_cards = []
        for s in slots[slot_idx]:
            color = AREA_COLORS[s["area"] % len(AREA_COLORS)]
            boards = sorted(s["boards"], key=lambda b: b["board_index"])

            board_rows = "".join(
                f'<tr>'
                f'<td class="board-idx">{b["board_index"]}</td>'
                f'<td class="board-title">{escape(b["title"])}</td>'
                f'<td class="board-authors">{_authors_html(b["authors"])}</td>'
                f'</tr>'
                for b in boards
            )

            area_cards.append(
                f'<div class="poster-card" style="border-left:4px solid {color}">'
                f'<div class="poster-card-header">'
                f'<span class="poster-area-badge" style="background:{color}">Area {s["area"]+1}</span>'
                f'<span class="poster-layout-badge">{escape(s["floor_plan"].upper())}</span>'
                f'</div>'
                f'<div class="poster-session-name">{escape(s["name"])}</div>'
                f'<div class="poster-session-desc">{escape(s.get("description",""))}</div>'
                f'<div class="toggle-hint"><span class="hint-text">▼ Show {len(boards)} papers</span></div>'
                f'<table class="board-table">'
                f'<thead><tr><th>#</th><th>Paper</th><th>Authors</th></tr></thead>'
                f'<tbody>{board_rows}</tbody>'
                f'</table>'
                f'<div class="paper-count">{len(boards)} paper{"s" if len(boards)!=1 else ""}</div>'
                f'</div>'
            )

        blocks_html.append(
            f'<div class="poster-slot">'
            f'<h3 class="slot-heading">Poster Slot {slot_idx+1}</h3>'
            f'<div class="poster-area-row">{"".join(area_cards)}</div>'
            f'</div>'
        )

    return f"""
    <section class="schedule-section" id="poster">
      <h2>Poster Sessions</h2>
      <div class="summary-bar">
        <span><strong>{summary['total_papers']}</strong> papers</span>
        <span><strong>{summary['total_sessions']}</strong> sessions</span>
        <span><strong>{summary['time_slots_used']}</strong> time slots</span>
        <span><strong>{num_areas}</strong> parallel areas</span>
        <span>Layout: <strong>{escape(summary.get('floor_plan','N/A'))}</strong></span>
      </div>
      {"".join(blocks_html)}
    </section>"""


def build_html(oral_data: dict | None, poster_data: dict | None,
               title: str = "Conference Session Schedule") -> str:
    oral_html = _build_oral_html(oral_data) if oral_data else ""
    poster_html = _build_poster_html(poster_data) if poster_data else ""

    nav_items = []
    if oral_data:
        nav_items.append('<a href="#oral">Oral Sessions</a>')
    if poster_data:
        nav_items.append('<a href="#poster">Poster Sessions</a>')
    nav_html = " &middot; ".join(nav_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,300;8..60,400;8..60,600;8..60,700&family=Inter:wght@300;400;500;600&display=swap');

  :root {{
    --bg: #FAFAF8;
    --surface: #FFFFFF;
    --border: #E2E0DC;
    --text: #2C2C2C;
    --text-secondary: #6B6B6B;
    --text-muted: #9B9B9B;
    --accent: #4A90D9;
    --radius: 6px;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}

  /* ── Header ─────────────────────────────────── */
  .page-header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #fff;
    padding: 3rem 2rem 2.5rem;
    text-align: center;
  }}
  .page-header h1 {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-weight: 700;
    font-size: 2.2rem;
    letter-spacing: -0.02em;
    margin-bottom: .4rem;
  }}
  .page-header .subtitle {{
    font-weight: 300;
    font-size: .95rem;
    opacity: .75;
    margin-bottom: 1rem;
  }}
  .page-nav a {{
    color: rgba(255,255,255,.85);
    text-decoration: none;
    font-weight: 500;
    font-size: .85rem;
    padding: .35rem .9rem;
    border: 1px solid rgba(255,255,255,.25);
    border-radius: 20px;
    transition: all .2s;
  }}
  .page-nav a:hover {{
    background: rgba(255,255,255,.15);
    border-color: rgba(255,255,255,.5);
  }}

  /* ── Layout ─────────────────────────────────── */
  .container {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 2rem 1.5rem 4rem;
  }}

  /* ── Section ────────────────────────────────── */
  .schedule-section {{
    margin-bottom: 3.5rem;
  }}
  .schedule-section h2 {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.6rem;
    font-weight: 600;
    margin-bottom: .8rem;
    padding-bottom: .5rem;
    border-bottom: 2px solid var(--border);
  }}

  /* ── Summary bar ────────────────────────────── */
  .summary-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: .6rem 1.5rem;
    margin-bottom: 1.5rem;
    font-size: .82rem;
    color: var(--text-secondary);
  }}
  .summary-bar strong {{
    color: var(--text);
    font-weight: 600;
  }}

  /* ── Oral grid ──────────────────────────────── */
  .table-wrap {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  .schedule-grid {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 6px;
    table-layout: fixed;
  }}
  .schedule-grid th {{
    font-size: .75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--text-secondary);
    padding: .5rem .6rem;
    text-align: center;
    background: transparent;
  }}
  .slot-label {{
    font-size: .7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-muted);
    white-space: nowrap;
    padding: .8rem .5rem;
    vertical-align: top;
    width: 70px;
  }}

  .session-cell {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: .7rem .8rem;
    vertical-align: top;
    transition: box-shadow .2s, transform .15s;
    cursor: default;
  }}
  .session-cell:hover {{
    box-shadow: 0 4px 16px rgba(0,0,0,.07);
    transform: translateY(-1px);
  }}
  .session-cell.empty {{
    background: transparent;
    border: 1px dashed var(--border);
    opacity: .4;
  }}

  .session-name {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-weight: 600;
    font-size: .82rem;
    line-height: 1.35;
    margin-bottom: .3rem;
  }}
  .session-desc {{
    font-size: .68rem;
    color: var(--text-muted);
    line-height: 1.4;
    margin-bottom: .5rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}

  .paper-list {{
    list-style: none;
    padding: 0;
    margin: 0;
  }}
  .paper-list li {{
    padding: .3rem 0;
    border-top: 1px solid #f0efed;
    font-size: .7rem;
    line-height: 1.4;
  }}
  .paper-list li:first-child {{ border-top: none; }}
  .paper-title {{
    display: block;
    font-weight: 500;
    color: var(--text);
  }}
  .paper-authors {{
    display: block;
    color: var(--text-muted);
    font-size: .65rem;
    font-style: italic;
  }}
  .paper-count {{
    margin-top: .4rem;
    font-size: .65rem;
    font-weight: 500;
    color: var(--text-muted);
    text-align: right;
  }}

  /* ── Poster ─────────────────────────────────── */
  .poster-slot {{
    margin-bottom: 2rem;
  }}
  .slot-heading {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text);
    margin-bottom: .8rem;
    padding-left: .2rem;
  }}
  .poster-area-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(560px, 1fr));
    gap: 1rem;
  }}
  .poster-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem 1.2rem;
    transition: box-shadow .2s;
  }}
  .poster-card:hover {{
    box-shadow: 0 4px 20px rgba(0,0,0,.06);
  }}
  .poster-card-header {{
    display: flex;
    gap: .5rem;
    margin-bottom: .5rem;
  }}
  .poster-area-badge {{
    font-size: .65rem;
    font-weight: 600;
    color: #fff;
    padding: .15rem .55rem;
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: .04em;
  }}
  .poster-layout-badge {{
    font-size: .6rem;
    font-weight: 500;
    color: var(--text-muted);
    border: 1px solid var(--border);
    padding: .12rem .5rem;
    border-radius: 10px;
    letter-spacing: .04em;
  }}
  .poster-session-name {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-weight: 600;
    font-size: .88rem;
    line-height: 1.35;
    margin-bottom: .25rem;
    color: var(--text);
  }}
  .poster-session-desc {{
    font-size: .7rem;
    color: var(--text-muted);
    margin-bottom: .7rem;
    line-height: 1.4;
  }}

  .board-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .7rem;
  }}
  .board-table thead th {{
    font-size: .62rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-muted);
    text-align: left;
    padding: .35rem .4rem;
    border-bottom: 1.5px solid var(--border);
  }}
  .board-table thead th:first-child {{ width: 30px; text-align: center; }}
  .board-table tbody tr {{ border-bottom: 1px solid #f4f3f1; }}
  .board-table tbody tr:last-child {{ border-bottom: none; }}
  .board-idx {{
    text-align: center;
    color: var(--text-muted);
    font-weight: 500;
    font-size: .65rem;
    padding: .3rem .4rem;
  }}
  .board-title {{
    font-weight: 500;
    color: var(--text);
    padding: .3rem .4rem;
    line-height: 1.35;
  }}
  .board-authors {{
    color: var(--text-muted);
    font-style: italic;
    font-size: .65rem;
    padding: .3rem .4rem;
    line-height: 1.35;
  }}

  /* ── Footer ─────────────────────────────────── */
  .page-footer {{
    text-align: center;
    font-size: .72rem;
    color: var(--text-muted);
    padding: 2rem 1rem;
    border-top: 1px solid var(--border);
  }}

  /* ── Toggle ─────────────────────────────────── */
  .session-cell .paper-list {{ max-height: 0; overflow: hidden; transition: max-height .3s ease; }}
  .session-cell.expanded .paper-list {{ max-height: 2000px; }}
  .session-cell .toggle-hint {{
    font-size: .6rem; color: var(--accent); cursor: pointer;
    font-weight: 500; margin-top: .2rem; user-select: none;
  }}
  .session-cell.expanded .toggle-hint .hint-text {{ display: none; }}
  .session-cell.expanded .toggle-hint::after {{ content: "▲ Collapse"; }}
  .session-cell:not(.expanded) .toggle-hint::after {{ content: ""; }}

  .board-table {{ max-height: 0; overflow: hidden; transition: max-height .3s ease; }}
  .poster-card.expanded .board-table {{ max-height: 5000px; }}
  .poster-card .toggle-hint {{
    font-size: .6rem; color: var(--accent); cursor: pointer;
    font-weight: 500; margin-top: .2rem; user-select: none;
  }}
  .poster-card.expanded .toggle-hint .hint-text {{ display: none; }}
  .poster-card.expanded .toggle-hint::after {{ content: "▲ Collapse"; }}
  .poster-card:not(.expanded) .toggle-hint::after {{ content: ""; }}

  /* ── Responsive ─────────────────────────────── */
  @media (max-width: 900px) {{
    .poster-area-row {{ grid-template-columns: 1fr; }}
    .page-header h1 {{ font-size: 1.6rem; }}
  }}
</style>
</head>
<body>

<header class="page-header">
  <h1>{escape(title)}</h1>
  <div class="subtitle">Auto-generated session layout with taxonomy-driven paper grouping</div>
  <nav class="page-nav">{nav_html}</nav>
</header>

<div class="container">
{oral_html}
{poster_html}
</div>

<footer class="page-footer">
  Generated by PaperCrawler &middot; Session Organizer
</footer>

<script>
// Toggle paper lists in oral cells
document.querySelectorAll('.session-cell:not(.empty)').forEach(cell => {{
  cell.addEventListener('click', () => cell.classList.toggle('expanded'));
}});
// Toggle board tables in poster cards
document.querySelectorAll('.poster-card').forEach(card => {{
  card.addEventListener('click', () => card.classList.toggle('expanded'));
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Visualise session schedule as HTML")
    parser.add_argument("--oral", type=str, default=DEFAULT_ORAL,
                        help="Path to oral_schedule.json")
    parser.add_argument("--poster", type=str, default=DEFAULT_POSTER,
                        help="Path to poster_schedule.json")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT,
                        help="Output HTML file path")
    parser.add_argument("--title", type=str,
                        default="Conference Session Schedule",
                        help="Page title")
    args = parser.parse_args()

    oral_data = None
    poster_data = None

    if os.path.exists(args.oral):
        with open(args.oral) as f:
            oral_data = json.load(f)
        print(f"Loaded oral schedule: {oral_data['summary']['total_sessions']} sessions")

    if os.path.exists(args.poster):
        with open(args.poster) as f:
            poster_data = json.load(f)
        print(f"Loaded poster schedule: {poster_data['summary']['total_sessions']} sessions")

    if not oral_data and not poster_data:
        print("No schedule data found. Run the session organizer first.")
        return

    html = build_html(oral_data, poster_data, title=args.title)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML saved to {args.output}")


if __name__ == "__main__":
    main()
