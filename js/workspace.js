/**
 * workspace.js — Workspace loading, switching, creation, and related event setup.
 */

import { state } from "./state.js";
import { API_BASE } from "./api.js";
import { showToast } from "./toast.js";

/** Parse a CSV string into an array of paper objects [{id, title, authors, abstract}]. */
function parseCSVtoPapers(csvText) {
  const lines = csvText.split("\n").map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];
  const header = lines[0].split(",").map(h => h.trim().replace(/^["']|["']$/g, "").toLowerCase());
  const idCol = header.indexOf("id") >= 0 ? header.indexOf("id") : header.indexOf("paper_id");
  const titleCol = header.indexOf("title");
  const authorsCol = header.indexOf("authors");
  const abstractCol = header.indexOf("abstract");
  if (titleCol < 0) { alert("CSV must have a 'title' column."); return []; }

  const papers = [];
  for (let i = 1; i < lines.length; i++) {
    const row = [];
    let inQuotes = false, field = "";
    for (const ch of lines[i]) {
      if (ch === '"') { inQuotes = !inQuotes; }
      else if (ch === "," && !inQuotes) { row.push(field.trim()); field = ""; }
      else { field += ch; }
    }
    row.push(field.trim());
    papers.push({
      id: idCol >= 0 ? row[idCol] || String(i) : String(i),
      title: row[titleCol] || "",
      authors: row[authorsCol] || "",
      abstract: abstractCol >= 0 ? row[abstractCol] || "" : "",
    });
  }
  return papers;
}

/** Full workspace list (cached for filtering by mode). */
let _allWorkspaces = [];

export function getAllWorkspaces() { return _allWorkspaces; }

/** Get workspaces filtered by mode ("oral" or "poster"). */
export function getWorkspacesByMode(mode) {
  return _allWorkspaces.filter(ws => (ws.mode || "oral") === mode);
}

export async function loadWorkspaces() {
  try {
    const res = await fetch(`${API_BASE}/workspaces`);
    const data = await res.json();
    const list = data.result || [];
    _allWorkspaces = list;
    const sel = document.getElementById("workspaceSelect");
    sel.innerHTML = "";
    list.forEach(ws => {
      const opt = document.createElement("option");
      opt.value = ws.name;
      const mode = ws.mode || "oral";
      const modeLabel = mode === "poster" ? "poster" : "oral";
      opt.textContent = `${ws.name} (${modeLabel}, ${ws.paper_count || 0} papers)`;
      sel.appendChild(opt);
    });
    /* If we had a previously selected workspace, keep it; otherwise pick first */
    const prev = state.oral.conference;
    const available = list.map(w => w.name);
    if (available.length === 0) return;
    if (available.includes(prev)) {
      sel.value = prev;
    } else if (available.length > 0) {
      sel.value = available[0];
      switchWorkspace(available[0]);
    }
  } catch (e) {
    console.warn("Failed to load workspaces:", e);
  }
}

/** Callbacks registered by view modules for workspace switch. */
const _onSwitchCallbacks = [];

/** Register a callback to run when the workspace changes. */
export function onWorkspaceSwitch(fn) { _onSwitchCallbacks.push(fn); }

export function switchWorkspace(name) {
  /* Update all conference references across all task states */
  state.oral.conference = name;
  state.poster.conference = name;
  state.assignment.conference = name;
  /* Clear cached results */
  state.oral.result = null;
  state.poster.result = null;
  state.oral.demoInfo = null;
  state.poster.demoInfo = null;

  /* Sync the oral/poster conference selects with the sidebar */
  const oralSel = document.getElementById("oralConferenceSelect");
  if (oralSel) oralSel.value = name;
  const posterSel = document.getElementById("posterConferenceSelect");
  if (posterSel) posterSel.value = name;

  /* Notify view modules */
  _onSwitchCallbacks.forEach(fn => { try { fn(name); } catch (_) {} });
}

export function openCreateWorkspaceModal() {
  document.getElementById("wsNewName").value = "";
  document.getElementById("wsNewDesc").value = "";
  document.getElementById("wsNewPapersFile").value = "";
  document.getElementById("wsCreateModal").classList.add("is-visible");
}

export function closeCreateWorkspaceModal() {
  document.getElementById("wsCreateModal").classList.remove("is-visible");
}

export async function createWorkspace() {
  const name = document.getElementById("wsNewName").value.trim();
  if (!name) { showToast("Please enter a workspace name."); return; }

  const desc = document.getElementById("wsNewDesc").value.trim();
  const mode = document.getElementById("wsNewMode").value || "oral";
  const btn = document.getElementById("wsCreateBtn");
  btn.disabled = true;
  btn.textContent = "Creating...";

  try {
    /* 1. Validate paper file BEFORE creating workspace */
    let papers = null;
    const fileInput = document.getElementById("wsNewPapersFile");
    if (fileInput.files && fileInput.files[0]) {
      const file = fileInput.files[0];
      const text = await file.text();
      try {
        if (file.name.toLowerCase().endsWith(".csv")) {
          papers = parseCSVtoPapers(text);
        } else {
          papers = JSON.parse(text);
        }
      } catch (parseErr) {
        throw new Error(`Invalid file format: ${parseErr.message}`);
      }
      if (!Array.isArray(papers) || papers.length === 0) {
        throw new Error("File contains no papers. Expected a non-empty array of {id, title, authors}.");
      }
      /* Check that papers have required fields */
      const first = papers[0];
      if (!first.title) {
        throw new Error("Papers must have at least a 'title' field. Check your file format.");
      }
    }

    /* 2. Create workspace (only after validation passes) */
    const res = await fetch(`${API_BASE}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc, mode }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to create workspace");

    /* 3. Upload papers if validated */
    if (papers) {
      const safeName = data.workspace?.name || name;
      const uploadRes = await fetch(`${API_BASE}/workspaces/${encodeURIComponent(safeName)}/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ papers }),
      });
      if (!uploadRes.ok) {
        const upErr = await uploadRes.json();
        console.warn("Upload warning:", upErr.error);
      }
    }

    closeCreateWorkspaceModal();
    await loadWorkspaces();
    /* Switch to new workspace */
    const safeName = data.workspace?.name || name;
    document.getElementById("workspaceSelect").value = safeName;
    switchWorkspace(safeName);
    showToast(`Workspace "${safeName}" created!`);
  } catch (e) {
    showToast("Error: " + e.message);
  }
  btn.disabled = false;
  btn.textContent = "Create";
}

export async function deleteWorkspace() {
  const sel = document.getElementById("workspaceSelect");
  const name = sel.value;
  if (!name) return;
  if (!confirm(`Delete workspace "${name}"? This cannot be undone.`)) return;
  try {
    const res = await fetch(`${API_BASE}/workspaces/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`Workspace "${name}" deleted.`);
    await loadWorkspaces();
  } catch (e) {
    showToast("Delete failed: " + e.message);
  }
}

export function setupWorkspaceEvents() {
  document.getElementById("workspaceSelect").addEventListener("change", (e) => {
    switchWorkspace(e.target.value);
  });
  document.getElementById("wsAddBtn").addEventListener("click", openCreateWorkspaceModal);
  document.getElementById("wsDeleteBtn").addEventListener("click", deleteWorkspace);
  document.getElementById("wsCreateBtn").addEventListener("click", createWorkspace);
  document.getElementById("wsCreateCancelBtn").addEventListener("click", closeCreateWorkspaceModal);
  document.getElementById("wsCreateModal").addEventListener("click", (e) => {
    if (e.target.id === "wsCreateModal") closeCreateWorkspaceModal();
  });
}
