/**
 * tokens-page.js
 *
 * Token usage statistics dashboard: loading stats from the API, rendering
 * last-run / workspace / global / run-history panels, and reset actions.
 */

import { state } from "../state.js";
import { API_BASE } from "../api.js";
import { showToast } from "../toast.js";

/* ═══════════════════ Formatting helpers ═══════════════════ */

function fmtTokens(n) {
  return n != null ? n.toLocaleString() : "0";
}

function fmtCost(n) {
  return n != null ? "$" + n.toFixed(4) : "$0.0000";
}

function _statRow(label, value) {
  return `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f0f4f3"><span style="color:var(--ink-soft)">${label}</span><span style="font-family:'IBM Plex Mono',monospace;font-weight:600">${value}</span></div>`;
}

/* ═══════════════════ Load ═══════════════════ */

export async function loadTokenStats() {
  try {
    const ws = document.getElementById("workspaceSelect")?.value || state.oral.conference;
    const res = await fetch(`${API_BASE}/token-stats?workspace=${encodeURIComponent(ws)}`);
    const data = await res.json();
    const s = data.result || {};
    renderTokenStats(s);
  } catch (e) {
    console.warn("Failed to load token stats:", e);
  }
}

/* ═══════════════════ Render ═══════════════════ */

export function renderTokenStats(s) {
  /* Last Run */
  const lr = s.currentRun;
  const lrEl = document.getElementById("tokenLastRunBody");
  if (lr && lr.total_calls > 0) {
    lrEl.innerHTML =
      _statRow("LLM Calls", lr.total_calls)
      + _statRow("Prompt Tokens", fmtTokens(lr.total_prompt_tokens))
      + _statRow("Completion Tokens", fmtTokens(lr.total_completion_tokens))
      + _statRow("Total Tokens", fmtTokens(lr.total_tokens))
      + _statRow("Estimated Cost", fmtCost(lr.total_cost_usd));
  } else {
    lrEl.innerHTML = '<div style="color:var(--ink-soft);padding:8px 0">No run data yet. Run an oral or poster organization to see stats here.</div>';
  }

  /* Workspace */
  const ws = s.workspace;
  const wsEl = document.getElementById("tokenWorkspaceBody");
  if (ws && ws.total_calls > 0) {
    const nRuns = (ws.runs || []).length;
    wsEl.innerHTML =
      _statRow("Runs", nRuns)
      + _statRow("LLM Calls", ws.total_calls)
      + _statRow("Prompt Tokens", fmtTokens(ws.total_prompt_tokens))
      + _statRow("Completion Tokens", fmtTokens(ws.total_completion_tokens))
      + _statRow("Total Tokens", fmtTokens(ws.total_tokens))
      + _statRow("Estimated Cost", fmtCost(ws.total_cost_usd));
  } else {
    wsEl.innerHTML = '<div style="color:var(--ink-soft);padding:8px 0">No token data for this workspace yet.</div>';
  }

  /* Global */
  const gl = s.global;
  const glEl = document.getElementById("tokenGlobalBody");
  if (gl && gl.total_calls > 0) {
    glEl.innerHTML =
      _statRow("LLM Calls", gl.total_calls)
      + _statRow("Total Tokens", fmtTokens(gl.total_tokens))
      + _statRow("Estimated Cost", fmtCost(gl.total_cost_usd))
      + (gl.last_reset
        ? `<div style="padding:6px 0 0;font-size:0.76rem;color:var(--ink-soft)">Last reset: ${new Date(gl.last_reset).toLocaleDateString()}</div>`
        : "");
  } else {
    glEl.innerHTML = '<div style="color:var(--ink-soft);padding:8px 0">No global token data yet.</div>';
  }

  /* Run History */
  const histEl = document.getElementById("tokenRunHistoryBody");
  const runs = (ws && ws.runs) ? ws.runs.slice().reverse() : [];
  if (runs.length === 0) {
    histEl.innerHTML = '<div style="color:var(--ink-soft);padding:8px 0">No runs recorded yet. Stats will appear here after you run oral or poster organization.</div>';
  } else {
    histEl.innerHTML = '<div class="table-wrap"><table><thead><tr>'
      + '<th>Run</th><th>Mode</th><th>Time</th><th>Prompt</th><th>Completion</th><th>Total Tokens</th><th>Cost</th><th>Provider</th><th>Model</th>'
      + '</tr></thead><tbody>'
      + runs.map((r, i) => {
        const t = r.timestamp
          ? new Date(r.timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
          : "\u2014";
        const idx = runs.length - i;
        return `<tr>`
          + `<td style="font-weight:600">#${idx}</td>`
          + `<td><span class="badge ${r.mode === "oral" ? "badge-ok" : "badge-warn"}">${r.mode || "\u2014"}</span></td>`
          + `<td>${t}</td>`
          + `<td style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem">${fmtTokens(r.prompt_tokens)}</td>`
          + `<td style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem">${fmtTokens(r.completion_tokens)}</td>`
          + `<td style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem;font-weight:600">${fmtTokens(r.total_tokens)}</td>`
          + `<td style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem;font-weight:600">${fmtCost(r.cost_usd)}</td>`
          + `<td>${r.provider || "\u2014"}</td>`
          + `<td style="font-family:'IBM Plex Mono',monospace;font-size:0.76rem">${r.model || "\u2014"}</td>`
          + `</tr>`;
      }).join("")
      + '</tbody></table></div>';
  }
}

/* ═══════════════════ Resets ═══════════════════ */

export async function resetWorkspaceTokenStats() {
  const ws = document.getElementById("workspaceSelect")?.value || state.oral.conference;
  if (!confirm(`Reset token stats for workspace "${ws}"?`)) return;
  try {
    await fetch(`${API_BASE}/token-stats/reset/workspace/${encodeURIComponent(ws)}`, { method: "POST" });
    showToast("Workspace token stats reset.");
    await loadTokenStats();
  } catch (e) {
    showToast("Failed: " + e.message);
  }
}

export async function resetGlobalTokenStats() {
  if (!confirm("Reset global token stats across all workspaces?")) return;
  try {
    await fetch(`${API_BASE}/token-stats/reset/global`, { method: "POST" });
    showToast("Global token stats reset.");
    await loadTokenStats();
  } catch (e) {
    showToast("Failed: " + e.message);
  }
}

/* ═══════════════════ Event setup ═══════════════════ */

export function setupTokenStatsEvents() {
  document.getElementById("tokenResetWorkspaceBtn").addEventListener("click", resetWorkspaceTokenStats);
  document.getElementById("tokenResetGlobalBtn").addEventListener("click", resetGlobalTokenStats);
}
