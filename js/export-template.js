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
      --bg-1: #f8f2e7;
      --bg-2: #edf5f3;
      --paper: rgba(255, 255, 255, 0.9);
      --panel: rgba(255, 255, 255, 0.78);
      --ink: #1d2a37;
      --ink-soft: #5b6f7b;
      --line: #d6e1dd;
      --accent: #128684;
      --accent-strong: #0f706e;
      --accent-warm: #da6c31;
      --shadow: 0 22px 44px rgba(25, 47, 63, 0.12);
      --radius-xl: 28px;
      --radius-lg: 20px;
      --radius-md: 14px;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }

    body {
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
      background:
        radial-gradient(circle at 8% 0%, rgba(218, 108, 49, 0.16), transparent 36%),
        radial-gradient(circle at 88% 12%, rgba(18, 134, 132, 0.18), transparent 38%),
        linear-gradient(165deg, var(--bg-1), var(--bg-2) 56%, #faf0e2 100%);
    }

    .page {
      width: min(1180px, calc(100vw - 32px));
      margin: 22px auto 48px;
    }

    /* ── Hero ───────────────────────── */

    .hero {
      border-radius: var(--radius-xl);
      padding: 30px 32px 28px;
      background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(248, 253, 251, 0.9)),
        linear-gradient(120deg, rgba(18, 134, 132, 0.08), rgba(218, 108, 49, 0.06));
      border: 1px solid rgba(255, 255, 255, 0.85);
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }

    .hero::after {
      content: "";
      position: absolute;
      inset: auto -90px -110px auto;
      width: 280px; height: 280px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(18, 134, 132, 0.14), rgba(18, 134, 132, 0));
      pointer-events: none;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(18, 134, 132, 0.1);
      border: 1px solid rgba(18, 134, 132, 0.14);
      color: var(--accent-strong);
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    h1 {
      margin: 14px 0 6px;
      font-size: clamp(1.9rem, 3vw, 2.8rem);
      letter-spacing: -0.04em;
    }

    .hero-subtitle {
      max-width: 760px;
      margin: 0;
      color: var(--ink-soft);
      font-size: 0.98rem;
      line-height: 1.65;
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
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid rgba(214, 225, 221, 0.9);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
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
      border-radius: var(--radius-lg);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border: 1px solid var(--line);
      box-shadow: 0 4px 16px rgba(25, 47, 63, 0.06);
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
      border: 1px solid rgba(255, 255, 255, 0.82);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .surface-head {
      padding: 20px 22px 14px;
      border-bottom: 1px solid rgba(214, 225, 221, 0.88);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.42));
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
      padding: 12px 10px;
      border-right: 1px solid rgba(214, 225, 221, 0.92);
      border-bottom: 1px solid rgba(214, 225, 221, 0.92);
      vertical-align: top;
      background: rgba(255, 255, 255, 0.7);
    }

    th:first-child, td:first-child { border-left: 1px solid rgba(214, 225, 221, 0.92); }

    thead th {
      background: linear-gradient(180deg, rgba(234, 246, 243, 0.95), rgba(246, 251, 249, 0.95));
      color: #355766;
      text-align: left;
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    thead th:first-child { border-top-left-radius: 16px; }
    thead th:last-child { border-top-right-radius: 16px; }
    tbody tr:last-child td:first-child { border-bottom-left-radius: 16px; }
    tbody tr:last-child td:last-child { border-bottom-right-radius: 16px; }

    .slot-label { font-weight: 700; color: var(--ink); font-size: 0.9rem; }

    .schedule-link {
      display: block;
      text-decoration: none;
      color: var(--ink);
      border-radius: 14px;
      padding: 12px 13px;
      background: linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(242, 249, 246, 0.95));
      border: 1px solid rgba(214, 225, 221, 0.9);
      min-height: 72px;
      transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    }

    .schedule-link:hover {
      transform: translateY(-1px);
      box-shadow: 0 14px 28px rgba(25, 47, 63, 0.08);
      border-color: rgba(18, 134, 132, 0.28);
    }

    .schedule-link strong { display: block; font-size: 0.88rem; line-height: 1.35; }
    .schedule-link span { display: block; margin-top: 5px; color: var(--ink-soft); font-size: 0.77rem; line-height: 1.45; }

    /* ── Session cards ─────────────── */

    .session-list { display: grid; gap: 18px; padding: 18px; }

    .session-card {
      border-radius: 22px;
      background: linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(247, 251, 250, 0.96));
      border: 1px solid rgba(214, 225, 221, 0.88);
      box-shadow: 0 16px 30px rgba(25, 47, 63, 0.07);
      padding: 22px 22px 20px;
      scroll-margin-top: 80px;
    }

    .session-card:target {
      border-color: rgba(18, 134, 132, 0.42);
      box-shadow: 0 18px 34px rgba(18, 134, 132, 0.14);
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
      gap: 6px;
      text-decoration: none;
      color: var(--accent-strong);
      background: rgba(18, 134, 132, 0.08);
      border: 1px solid rgba(18, 134, 132, 0.16);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 0.74rem;
      font-weight: 700;
      white-space: nowrap;
      transition: background 0.15s;
    }

    .session-nav a:hover, .back-link:hover {
      background: rgba(18, 134, 132, 0.16);
    }

    /* ── Meta cards ────────────────── */

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }

    .meta-card {
      padding: 12px 13px;
      border-radius: 16px;
      background: rgba(245, 250, 248, 0.86);
      border: 1px solid rgba(214, 225, 221, 0.9);
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
      padding: 14px 15px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid rgba(214, 225, 221, 0.86);
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
      width: 44px;
      height: 44px;
      border-radius: 50%;
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
