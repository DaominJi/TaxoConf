/**
 * overview.js
 *
 * Minimal overview view module. The overview page is largely static HTML;
 * this module exists as a placeholder for any future overview-specific
 * render logic and event wiring.
 */

/**
 * Bind any overview-specific DOM events.
 * Currently a no-op -- the overview panel has no interactive controls.
 */
export function setupOverviewEvents() {
  /* Tab switching for CSV/JSON input data example */
  document.querySelectorAll("[data-overview-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.overviewTab;
      document.querySelectorAll("[data-overview-tab]").forEach((b) => b.classList.toggle("is-active", b === btn));
      document.getElementById("overviewTabCsv").style.display = tab === "csv" ? "block" : "none";
      document.getElementById("overviewTabJson").style.display = tab === "json" ? "block" : "none";
    });
  });
}
