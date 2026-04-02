/**
 * router.js — Task switching (page navigation) and sidebar toggle logic.
 */

import { state } from "./state.js";
import { showToast } from "./toast.js";

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

  /* Load page-specific data (these functions must be available globally or injected) */
  if (task === "settings" && typeof window.loadSettings === "function") window.loadSettings();
  if (task === "tokens" && typeof window.loadTokenStats === "function") window.loadTokenStats();
}

function toggleSidebar() {
  const app = document.querySelector(".app");
  const collapsed = app.classList.toggle("sidebar-collapsed");
  const btn = document.getElementById("sidebarToggle");
  btn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
}

/**
 * Wire up sidebar navigation buttons and sidebar toggle.
 */
export function setupNavEvents() {
  [...document.querySelectorAll(".nav-btn")].forEach((btn) => {
    btn.addEventListener("click", () => switchTask(btn.dataset.task));
  });

  document.getElementById("sidebarToggle").addEventListener("click", toggleSidebar);
}
