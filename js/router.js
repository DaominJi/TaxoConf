/**
 * router.js — Task switching, sidebar toggle, and setup panel collapse logic.
 */

import { state } from "./state.js";
import { showToast } from "./toast.js";

/* Callbacks registered by view modules for page-enter events */
const _onEnterCallbacks = {};

/** Register a callback to run when a task tab is activated. */
export function onTaskEnter(task, fn) {
  _onEnterCallbacks[task] = fn;
}

export function switchTask(task) {
  /* Guard locked pages */
  if (task === "assignment" || task === "discovery") {
    showToast("This feature is under construction. Stay tuned!");
    return;
  }
  state.activeTask = task;
  [...document.querySelectorAll(".nav-btn")].forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.task === task);
  });
  [...document.querySelectorAll(".task-view")].forEach((view) => {
    view.classList.toggle("is-active", view.id === `task-${task}`);
  });

  /* Fire page-enter callback if registered */
  if (_onEnterCallbacks[task]) _onEnterCallbacks[task]();
}

function toggleSidebar() {
  const app = document.querySelector(".app");
  const collapsed = app.classList.toggle("sidebar-collapsed");
  const btn = document.getElementById("sidebarToggle");
  btn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
}

/* ── Setup panel collapse/expand ────────────── */

export function toggleSetupPanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const isCollapsed = panel.classList.toggle("is-collapsed");
  const btn = panel.querySelector(".btn-configure");
  if (btn) btn.classList.toggle("is-collapsed", isCollapsed);
}

export function collapseSetupPanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel || panel.classList.contains("is-collapsed")) return;
  toggleSetupPanel(panelId);
}

export function expandSetupPanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel || !panel.classList.contains("is-collapsed")) return;
  toggleSetupPanel(panelId);
}

/** Update the summary bar chips when panel is collapsed. */
export function updateSetupSummary(chipId, text) {
  const chip = document.getElementById(chipId);
  if (chip) chip.textContent = text;
}

/**
 * Wire up sidebar navigation buttons, sidebar toggle, and configure buttons.
 */
export function setupNavEvents() {
  [...document.querySelectorAll(".nav-btn")].forEach((btn) => {
    btn.addEventListener("click", () => switchTask(btn.dataset.task));
  });

  document.getElementById("sidebarToggle").addEventListener("click", toggleSidebar);

  /* Configure toggle buttons */
  document.querySelectorAll("[data-toggle-setup]").forEach((btn) => {
    btn.addEventListener("click", () => toggleSetupPanel(btn.dataset.toggleSetup));
  });
}
