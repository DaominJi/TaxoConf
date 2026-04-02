/**
 * workspace.js — Workspace loading, switching, creation, and related event setup.
 */

import { state } from "./state.js";
import { API_BASE } from "./api.js";
import { showToast } from "./toast.js";

export async function loadWorkspaces() {
  try {
    const res = await fetch(`${API_BASE}/workspaces`);
    const data = await res.json();
    const list = data.result || [];
    const sel = document.getElementById("workspaceSelect");
    sel.innerHTML = "";
    list.forEach(ws => {
      const opt = document.createElement("option");
      opt.value = ws.name;
      opt.textContent = ws.name + (ws.paper_count ? ` (${ws.paper_count} papers)` : "");
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
  /* Re-render — these functions must be available globally or injected */
  if (typeof window.renderOralResults === "function") window.renderOralResults();
  if (typeof window.renderPosterResults === "function") window.renderPosterResults();
  if (typeof window.loadOralDemoInfo === "function") void window.loadOralDemoInfo();
  if (typeof window.loadPosterDemoInfo === "function") void window.loadPosterDemoInfo();
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
  const btn = document.getElementById("wsCreateBtn");
  btn.disabled = true;
  btn.textContent = "Creating...";

  try {
    /* 1. Create workspace */
    const res = await fetch(`${API_BASE}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to create workspace");

    /* 2. Upload papers if a file was selected */
    const fileInput = document.getElementById("wsNewPapersFile");
    if (fileInput.files && fileInput.files[0]) {
      const file = fileInput.files[0];
      const text = await file.text();
      const papers = JSON.parse(text);
      const safeName = data.workspace?.name || name;
      const uploadRes = await fetch(`${API_BASE}/workspaces/${encodeURIComponent(safeName)}/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ papers, filename: file.name }),
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

export function setupWorkspaceEvents() {
  document.getElementById("workspaceSelect").addEventListener("change", (e) => {
    switchWorkspace(e.target.value);
  });
  document.getElementById("wsAddBtn").addEventListener("click", openCreateWorkspaceModal);
  document.getElementById("wsCreateBtn").addEventListener("click", createWorkspace);
  document.getElementById("wsCreateCancelBtn").addEventListener("click", closeCreateWorkspaceModal);
  document.getElementById("wsCreateModal").addEventListener("click", (e) => {
    if (e.target.id === "wsCreateModal") closeCreateWorkspaceModal();
  });
}
