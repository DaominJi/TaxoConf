/**
 * modal.js — Generic modal open/close utilities for .modal-shell elements.
 */

/**
 * Open a modal by its DOM element or ID string.
 * Adds the "is-open" class and sets aria-hidden to "false".
 */
export function openModal(modalOrId) {
  const modal = typeof modalOrId === "string"
    ? document.getElementById(modalOrId)
    : modalOrId;
  if (!modal) return;
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

/**
 * Close a modal by its DOM element or ID string.
 * Removes the "is-open" class and sets aria-hidden to "true".
 */
export function closeModal(modalOrId) {
  const modal = typeof modalOrId === "string"
    ? document.getElementById(modalOrId)
    : modalOrId;
  if (!modal) return;
  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
}

/**
 * Wire up standard close behaviours for a .modal-shell:
 *   - clicking the close button (by ID)
 *   - clicking the backdrop (the .modal-shell itself)
 */
export function setupModalClose(modalId, closeBtnId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;

  if (closeBtnId) {
    const btn = document.getElementById(closeBtnId);
    if (btn) {
      btn.addEventListener("click", () => closeModal(modal));
    }
  }

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal(modal);
  });
}
