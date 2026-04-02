/**
 * utils.js — General-purpose utility functions (non-taxonomy).
 */

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatPct(v) { return `${(v * 100).toFixed(1)}%`; }

export function formatNum(v, d = 3) { return Number(v).toFixed(d); }

export function keyPair(subId, pcId) { return `${subId}::${pcId}`; }

export function normalizeAuthors(rawAuthors) {
  if (Array.isArray(rawAuthors)) {
    return rawAuthors
      .map((a) => {
        if (typeof a === "string") return a.trim();
        if (a && typeof a === "object") return String(a.name || a.full_name || a.author_name || "").trim();
        return "";
      })
      .filter(Boolean);
  }
  if (typeof rawAuthors === "string") {
    return rawAuthors.split(",").map((x) => x.trim()).filter(Boolean);
  }
  if (rawAuthors && typeof rawAuthors === "object") {
    const v = String(rawAuthors.name || rawAuthors.full_name || rawAuthors.author_name || "").trim();
    return v ? [v] : [];
  }
  return [];
}

export function authorsLabel(authors) {
  const arr = normalizeAuthors(authors);
  return arr.length ? arr.join(", ") : "N/A";
}

export function paperAuthorsOrPresentersLabel(paper) {
  const authorText = authorsLabel(paper && paper.authors);
  if (authorText !== "N/A") return authorText;
  if (paper && Array.isArray(paper.presenters) && paper.presenters.length) return paper.presenters.join(", ");
  if (paper && paper.presenter) return String(paper.presenter);
  return "";
}

export function ensureSessionMetadata(session) {
  if (!session || typeof session !== "object") return session;
  session.sessionName = String(session.sessionName || "").trim();
  session.sessionChair = String(session.sessionChair || "").trim();
  session.sessionDate = String(session.sessionDate || "").trim();
  session.startTime = String(session.startTime || "").trim();
  session.endTime = String(session.endTime || "").trim();
  session.trackLabel = String(session.trackLabel || "").trim();
  session.location = String(session.location || "").trim();
  session.speakers = String(session.speakers || "").trim();
  session.description = String(session.description || "").trim();
  return session;
}

export function sessionSpeakersChairLabel(session) {
  const values = [session && session.speakers, session && session.sessionChair]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  return values.join(" / ");
}

export function sessionTimeLabel(session) {
  const start = String(session && session.startTime || "").trim();
  const end = String(session && session.endTime || "").trim();
  if (start && end) return `${start} - ${end}`;
  return start || end || "";
}

export function loadingHtml(message) {
  return `
    <div class="run-status is-visible" style="margin-bottom:10px">
      <span class="run-spinner" aria-hidden="true"></span>
      <span>${message}</span>
    </div>
  `;
}

export function setRunState(task, isRunning, message) {
  const config = task === "assignment"
    ? {
        buttonId: "runAssignmentBtn",
        statusId: "assignmentRunStatus",
        defaultLabel: "Run Assignment",
        runningLabel: "Running Assignment..."
      }
    : task === "oral"
      ? {
          buttonId: "runOralBtn",
          statusId: "oralRunStatus",
          defaultLabel: "Run Oral Organization",
          runningLabel: "Running Oral Organization..."
        }
      : {
          buttonId: "runPosterBtn",
          statusId: "posterRunStatus",
          defaultLabel: "Run Poster Organization",
          runningLabel: "Running Poster Organization..."
        };
  const button = document.getElementById(config.buttonId);
  const status = document.getElementById(config.statusId);
  if (!button || !status) return;
  button.disabled = isRunning;
  button.textContent = isRunning ? config.runningLabel : config.defaultLabel;
  status.classList.toggle("is-visible", isRunning);
  status.innerHTML = isRunning
    ? `<span class="run-spinner" aria-hidden="true"></span><span>${message}</span>`
    : "";
}

export function parseJsonFile(file, onSuccess) {
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const json = JSON.parse(String(e.target.result || ""));
      onSuccess(json);
    } catch (_) {
      alert("Invalid JSON file.");
    }
  };
  reader.onerror = () => alert("Failed to read file.");
  reader.readAsText(file);
}

export function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadText(filename, text) {
  downloadFile(filename, text, "text/plain;charset=utf-8");
}

export function downloadFile(filename, text, mimeType) {
  const blob = new Blob([text], { type: mimeType || "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function csvEscape(value) {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, "\"\"")}"`;
}

export function renderConferenceSelect(selectId, selectedValue, options) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const rows = Array.isArray(options) && options.length ? options : [selectedValue || "sigir2025"];
  select.innerHTML = rows.map((value) => `<option value="${escapeHtml(String(value))}">${escapeHtml(String(value))}</option>`).join("");
  select.value = rows.includes(selectedValue) ? selectedValue : rows[0];
}
