/**
 * toast.js — Global toast notification helper.
 */

let _toastTimer = null;

export function showToast(message, duration = 3000) {
  const el = document.getElementById("globalToast");
  el.textContent = message;
  el.classList.add("is-visible");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("is-visible"), duration);
}
