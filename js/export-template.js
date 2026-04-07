/**
 * export-template.js
 *
 * Shared export utilities and the buildStyledExportHtml function that produces
 * a standalone, styled HTML document for oral / poster schedule exports.
 *
 * Features:
 * - Live search/filter bar (filters sessions and papers by keyword)
 * - Print-friendly @media print styles
 * - Floating back-to-top button
 * - Prev/next navigation between session cards
 * - Paper abstracts in expandable details
 * - Conference name and generation timestamp in hero
 * - Responsive design down to 480px
 */

import { escapeHtml } from "./utils.js";

/* ── Small export helpers ─────────────────────────────────────────── */

export function csvEscape(value) {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

export function exportDisplay(value, fallback = "Not set") {
  const text = String(value || "").trim();
  return escapeHtml(text || fallback);
}

export function exportSummaryChip(label, value) {
  return `
    <div class="summary-chip">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `;
}

export function exportMetaCard(label, value) {
  return `
    <div class="meta-card">
      <span>${escapeHtml(label)}</span>
      <strong>${exportDisplay(value)}</strong>
    </div>
  `;
}

/* ── Full styled HTML document builder ────────────────────────────── */

export function buildStyledExportHtml({ title, subtitle, conference, summaryHtml, headerHtml, rowsHtml, sectionsHtml }) {
  const timestamp = new Date().toLocaleString("en-US", {
    year: "numeric", month: "long", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
  const confLabel = conference ? escapeHtml(conference) : "Conference";

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)} \u2014 ${confLabel}</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --paper: #ffffff;
      --ink: #1a1a2e;
      --ink-soft: #64748b;
      --line: #e2e8f0;
      --accent: #2563eb;
      --accent-light: #eff6ff;
      --accent-strong: #1d4ed8;
      --accent-warm: #f59e0b;
      --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
      --shadow: 0 4px 16px rgba(0,0,0,0.06);
      --shadow-lg: 0 12px 32px rgba(0,0,0,0.08);
      --radius-xl: 16px;
      --radius-lg: 12px;
      --radius-md: 8px;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }

    body {
      margin: 0;
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      line-height: 1.6;
    }

    .page {
      width: min(1180px, calc(100vw - 32px));
      margin: 22px auto 48px;
    }

    /* ── Hero ───────────────────────── */

    .hero {
      border-radius: var(--radius-xl);
      padding: 32px 36px 28px;
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 6px;
      background: var(--accent-light);
      color: var(--accent-strong);
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    h1 {
      margin: 12px 0 6px;
      font-size: clamp(1.6rem, 2.5vw, 2.2rem);
      font-weight: 700;
      letter-spacing: -0.03em;
    }

    .hero-subtitle {
      max-width: 700px;
      margin: 0;
      color: var(--ink-soft);
      font-size: 0.92rem;
      line-height: 1.6;
    }

    .hero-meta {
      margin-top: 6px;
      color: var(--ink-soft);
      font-size: 0.78rem;
      opacity: 0.7;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-top: 20px;
    }

    .summary-chip {
      padding: 12px 16px;
      border-radius: var(--radius-md);
      background: var(--accent-light);
      border: 1px solid #dbeafe;
    }

    .summary-chip span {
      display: block;
      color: var(--ink-soft);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }

    .summary-chip strong {
      font-size: 1.1rem;
      letter-spacing: -0.03em;
    }

    /* ── Search bar ────────────────── */

    .search-bar {
      position: sticky;
      top: 0;
      z-index: 10;
      margin-top: 16px;
      padding: 10px 16px;
      border-radius: var(--radius-md);
      background: rgba(255, 255, 255, 0.95);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border: 1px solid var(--line);
      box-shadow: var(--shadow-sm);
      display: flex;
      gap: 10px;
      align-items: center;
    }

    .search-bar input {
      flex: 1;
      border: none;
      outline: none;
      background: transparent;
      font-family: inherit;
      font-size: 0.92rem;
      color: var(--ink);
      padding: 6px 0;
    }

    .search-bar input::placeholder { color: var(--ink-soft); opacity: 0.6; }

    .search-bar .search-icon {
      color: var(--ink-soft);
      font-size: 1.1rem;
      flex-shrink: 0;
    }

    .search-bar .search-count {
      font-size: 0.76rem;
      color: var(--ink-soft);
      white-space: nowrap;
    }

    /* ── Surface ───────────────────── */

    .surface {
      margin-top: 20px;
      border-radius: var(--radius-lg);
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .surface-head {
      padding: 20px 24px 14px;
      border-bottom: 1px solid var(--line);
      background: #fafbfc;
    }

    .surface-head h2 {
      margin: 0 0 6px;
      font-size: 1.08rem;
      letter-spacing: -0.02em;
    }

    .surface-head p {
      margin: 0;
      color: var(--ink-soft);
      font-size: 0.9rem;
      line-height: 1.55;
    }

    /* ── Schedule table ────────────── */

    .table-shell { overflow: auto; padding: 16px 18px 18px; }

    table {
      width: 100%;
      min-width: 760px;
      border-collapse: separate;
      border-spacing: 0;
    }

    th, td {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }

    thead th {
      background: var(--accent-light);
      color: var(--accent-strong);
      text-align: left;
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 2px solid #bfdbfe;
    }

    .slot-label { font-weight: 700; color: var(--ink); font-size: 0.9rem; }

    .slot-meta { font-size: 0.75rem; color: var(--ink-soft); margin-top: 2px; }

    .schedule-link {
      display: block;
      text-decoration: none;
      color: var(--ink);
      border-radius: var(--radius-md);
      padding: 10px 12px;
      background: #fff;
      border: 1px solid var(--line);
      min-height: 60px;
      transition: border-color 0.15s, box-shadow 0.15s;
    }

    .schedule-link:hover {
      border-color: var(--accent);
      box-shadow: var(--shadow-sm);
    }

    .schedule-link strong { display: block; font-size: 0.84rem; line-height: 1.35; }
    .schedule-link span { display: block; margin-top: 4px; color: var(--ink-soft); font-size: 0.75rem; }

    /* ── Session cards ─────────────── */

    .session-list { display: grid; gap: 18px; padding: 18px; }

    .session-card {
      border-radius: var(--radius-lg);
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      padding: 24px;
      scroll-margin-top: 80px;
    }

    .session-card:target {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
    }

    .session-card.is-hidden { display: none; }

    .session-head {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }

    .session-head h3 { margin: 0 0 6px; font-size: 1.22rem; letter-spacing: -0.03em; }
    .session-kicker { color: var(--ink-soft); font-size: 0.88rem; line-height: 1.5; }

    .session-nav {
      display: flex;
      gap: 6px;
      align-items: center;
    }

    .session-nav a, .back-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      text-decoration: none;
      color: var(--accent);
      background: var(--accent-light);
      border: 1px solid #dbeafe;
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 0.72rem;
      font-weight: 600;
      white-space: nowrap;
      transition: background 0.15s;
    }

    .session-nav a:hover, .back-link:hover {
      background: #dbeafe;
    }

    /* ── Meta cards ────────────────── */

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }

    .meta-card {
      padding: 10px 14px;
      border-radius: var(--radius-md);
      background: #f8fafc;
      border: 1px solid var(--line);
    }

    .meta-card span {
      display: block;
      color: var(--ink-soft);
      font-size: 0.73rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }

    .meta-card strong { display: block; font-size: 0.9rem; line-height: 1.45; }

    /* ── Paper items ───────────────── */

    .paper-list { display: grid; gap: 10px; }

    .paper-item {
      padding: 12px 14px;
      border-radius: var(--radius-md);
      background: #fff;
      border: 1px solid var(--line);
    }

    .paper-item strong { display: block; margin-bottom: 4px; font-size: 0.9rem; line-height: 1.45; }
    .paper-item .paper-authors { display: block; color: var(--ink-soft); font-size: 0.8rem; line-height: 1.55; }

    .paper-item .paper-abstract {
      margin-top: 6px;
      color: var(--ink-soft);
      font-size: 0.8rem;
      line-height: 1.6;
    }

    .paper-item details summary {
      cursor: pointer;
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 600;
      margin-top: 6px;
      user-select: none;
    }

    .paper-item details summary:hover { text-decoration: underline; }

    /* ── Back to top button ─────────── */

    .back-to-top {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      border: none;
      box-shadow: 0 6px 20px rgba(18, 134, 132, 0.35);
      cursor: pointer;
      font-size: 1.2rem;
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 20;
      transition: opacity 0.2s, transform 0.2s;
    }

    .back-to-top:hover { transform: translateY(-2px); }
    .back-to-top.is-visible { display: flex; }

    /* ── Responsive ─────────────────── */

    @media (max-width: 720px) {
      .page { width: min(100vw - 18px, 100%); margin: 12px auto 28px; }
      .hero { padding: 22px 18px 20px; }
      .surface-head, .table-shell, .session-list { padding-left: 14px; padding-right: 14px; }
      .search-bar { margin-left: -2px; margin-right: -2px; border-radius: 14px; }
    }

    /* ── Print styles ──────────────── */

    @media print {
      body {
        background: #fff !important;
        color: #000 !important;
        font-size: 11pt;
      }
      .page { width: 100%; margin: 0; }
      .hero {
        background: #fff !important;
        box-shadow: none !important;
        border: 1px solid #ccc;
        border-radius: 0;
        padding: 16px;
      }
      .hero::after { display: none; }
      .search-bar, .back-to-top, .session-nav, .back-link { display: none !important; }
      .surface {
        box-shadow: none !important;
        border: 1px solid #ccc;
        border-radius: 0;
        page-break-inside: avoid;
      }
      .session-card {
        box-shadow: none !important;
        border: 1px solid #ccc;
        border-radius: 0;
        page-break-inside: avoid;
      }
      .schedule-link {
        border: 1px solid #ccc;
        border-radius: 0;
        background: #fff !important;
      }
      .summary-chip, .meta-card, .paper-item {
        background: #f8f8f8 !important;
        border-radius: 0;
      }
      a { color: #000 !important; text-decoration: none; }
      table { min-width: 0; }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero" id="top">
      <div class="eyebrow">${confLabel}</div>
      <h1>${escapeHtml(title)}</h1>
      <p class="hero-subtitle">${escapeHtml(subtitle)}</p>
      <div class="hero-meta">Generated ${timestamp}</div>
      <div class="summary-grid">
        ${summaryHtml}
      </div>
    </section>

    <div class="search-bar" id="searchBar">
      <span class="search-icon">\u{1F50D}</span>
      <input type="text" id="searchInput" placeholder="Search sessions, papers, or authors..." autocomplete="off" />
      <span class="search-count" id="searchCount"></span>
    </div>

    <section class="surface" id="overviewSection">
      <div class="surface-head">
        <h2>Schedule Overview</h2>
        <p>Click a session title to jump to its detail card below.</p>
      </div>
      <div class="table-shell">
        <table>
          <thead>${headerHtml}</thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    </section>

    <section class="surface" id="detailSection">
      <div class="surface-head">
        <h2>Session Details</h2>
        <p>Each card shows session metadata and the assigned presentations with expandable abstracts.</p>
      </div>
      <div class="session-list" id="sessionList">
        ${sectionsHtml}
      </div>
    </section>
  </main>

  <button class="back-to-top" id="backToTop" title="Back to top" onclick="window.scrollTo({top:0})">\u2191</button>

  <script>
    /* ── Search / filter ──────────── */
    (function() {
      var input = document.getElementById("searchInput");
      var count = document.getElementById("searchCount");
      var cards = Array.from(document.querySelectorAll(".session-card"));
      var links = Array.from(document.querySelectorAll(".schedule-link"));
      var total = cards.length;

      input.addEventListener("input", function() {
        var q = input.value.toLowerCase().trim();
        if (!q) {
          cards.forEach(function(c) { c.classList.remove("is-hidden"); });
          links.forEach(function(l) { l.closest("td").style.opacity = ""; });
          count.textContent = "";
          return;
        }
        var visible = 0;
        var visibleIds = new Set();
        cards.forEach(function(c) {
          var text = c.textContent.toLowerCase();
          var match = text.indexOf(q) !== -1;
          c.classList.toggle("is-hidden", !match);
          if (match) { visible++; visibleIds.add(c.id); }
        });
        links.forEach(function(l) {
          var href = l.getAttribute("href") || "";
          var targetId = href.replace("#", "");
          l.closest("td").style.opacity = visibleIds.has(targetId) ? "" : "0.3";
        });
        count.textContent = visible + " of " + total + " sessions";
      });
    })();

    /* ── Back to top visibility ───── */
    (function() {
      var btn = document.getElementById("backToTop");
      window.addEventListener("scroll", function() {
        btn.classList.toggle("is-visible", window.scrollY > 400);
      });
    })();
  </script>
</body>
</html>`;
}
