/**
 * oral.js
 *
 * All oral-session organisation functions: loading info, running the solver,
 * rendering the schedule grid / editor / last-mile panels, session and
 * hard-paper modals, CSV/HTML export, and oral-specific event wiring.
 */

import { state } from "../state.js";
import { apiGet, apiPost, requireApiResult } from "../api.js";
import {
  submissionDist,
  avgDist,
  topTopicEntries,
  byId,
} from "../taxonomy.js";
import {
  escapeHtml,
  formatNum,
  loadingHtml,
  setRunState,
  renderConferenceSelect,
  ensureSessionMetadata,
  sessionSpeakersChairLabel,
  sessionTimeLabel,
  paperAuthorsOrPresentersLabel,
  downloadFile,
} from "../utils.js";
import {
  buildStyledExportHtml,
  csvEscape,
  exportSummaryChip,
  exportMetaCard,
} from "../export-template.js";

/* ═══════════════════ ID / label helpers ═══════════════════ */

export function scheduleSessionId(slot, track) {
  return `slot_${slot}_track_${track}`;
}

export function parseSessionId(sessionId) {
  const m = /slot_(\d+)_track_(\d+)/.exec(sessionId);
  if (!m) return { slot: 0, track: 0 };
  return { slot: Number(m[1]), track: Number(m[2]) };
}

function oralPaperId(paper) {
  return String(paper.id ?? paper.submission_id ?? "");
}

function oralPresentersLabel(paper) {
  if (Array.isArray(paper.presenters) && paper.presenters.length) return paper.presenters.join(", ");
  if (paper.presenter) return String(paper.presenter);
  return "N/A";
}

function oralPaperDist(paper) {
  if (!paper.topicDist) {
    paper.topicDist = submissionDist({
      title: paper.title || "",
      abstract: paper.abstract || "",
      topic_hints: paper.topic_hints || [],
    });
  }
  return paper.topicDist;
}

function sessionTopicNames(papers, distFn, limit = 2) {
  if (!Array.isArray(papers) || !papers.length) return "Empty";
  return topTopicEntries(avgDist(papers.map((paper) => distFn(paper))), limit)
    .map((entry) => byId[entry.id].label)
    .join(" \u00b7 ");
}

function oralSessionLabel(sessionId) {
  const pos = parseSessionId(sessionId);
  return `Slot ${pos.slot} / Track ${pos.track}`;
}

function oralSessionName(session) {
  return String(session && session.sessionName ? session.sessionName : "").trim() || oralSessionLabel(session.id);
}

function findOralSession(result, sessionId) {
  return result.sessions.find((session) => session.id === sessionId) || null;
}

function prepareOralResult(result) {
  if (!result) return null;
  const paperMap = new Map();
  (result.papers || []).forEach((paper) => {
    paper.presenters = Array.isArray(paper.presenters)
      ? paper.presenters
      : paper.presenter
        ? String(paper.presenter).split(",").map((x) => x.trim()).filter(Boolean)
        : [];
    oralPaperDist(paper);
    paperMap.set(oralPaperId(paper), paper);
  });
  (result.sessions || []).forEach((session) => {
    ensureSessionMetadata(session);
    session.papers = (session.papers || []).map((paper) => {
      const canonical = paperMap.get(oralPaperId(paper)) || paper;
      canonical.presenters = Array.isArray(canonical.presenters)
        ? canonical.presenters
        : canonical.presenter
          ? String(canonical.presenter).split(",").map((x) => x.trim()).filter(Boolean)
          : [];
      oralPaperDist(canonical);
      return canonical;
    });
    session.paperCount = session.papers.length;
  });
  return result;
}

function setOralSessionFields(sessionId, fields) {
  const result = state.oral.result;
  if (!result) return;
  const session = findOralSession(result, sessionId);
  if (!session) return;
  ensureSessionMetadata(session);
  Object.assign(session, {
    sessionName: String(fields.sessionName || "").trim(),
    sessionChair: String(fields.sessionChair || "").trim(),
    sessionDate: String(fields.sessionDate || "").trim(),
    startTime: String(fields.startTime || "").trim(),
    endTime: String(fields.endTime || "").trim(),
    trackLabel: String(fields.trackLabel || "").trim(),
    location: String(fields.location || "").trim(),
    speakers: String(fields.speakers || "").trim(),
    description: String(fields.description || "").trim(),
  });
  renderOralResults();
}

/* ═══════════════════ Load info ═══════════════════ */

export async function loadOralDemoInfo() {
  try {
    const resp = await apiGet(`/oral/info?conference=${encodeURIComponent(state.oral.conference)}`);
    state.oral.demoInfo = requireApiResult(resp, "Oral info");
    state.oral.availableConferences = state.oral.demoInfo.availableConferences || [];
    state.oral.conference = state.oral.demoInfo.conference || state.oral.conference;

    const sp = state.oral.demoInfo.suggested_params;
    if (sp) {
      state.oral.parallelSessions = sp.parallel_sessions;
      state.oral.timeSlots = sp.time_slots;
      state.oral.maxPerSession = sp.max_per_session;
      state.oral.minPerSession = sp.min_per_session;
      document.getElementById("oralParallelInput").value = sp.parallel_sessions;
      document.getElementById("oralSlotsInput").value = sp.time_slots;
      document.getElementById("oralMaxInput").value = sp.max_per_session;
      document.getElementById("oralMinInput").value = sp.min_per_session;
    }
  } catch (err) {
    state.oral.demoInfo = { error: err.message };
  }
  renderOralCapacityNotice();
  renderOralResults();
}

/* ═══════════════════ Capacity notice ═══════════════════ */

export function renderOralCapacityNotice() {
  const sourceStatus = document.getElementById("oralSourceStatus");
  const note = document.getElementById("oralCapacityNotice");
  if (!sourceStatus || !note) return;
  renderConferenceSelect("oralConferenceSelect", state.oral.conference, state.oral.availableConferences);

  if (!state.oral.demoInfo) {
    sourceStatus.innerHTML = `Loading server-side presentation data...`;
    note.classList.remove("warn");
    note.innerHTML = `Checking capacity against the demo paper set...`;
    return;
  }

  if (state.oral.demoInfo.error) {
    sourceStatus.innerHTML = `Failed to load demo data: <span class="mono">${state.oral.demoInfo.error}</span>`;
    note.classList.add("warn");
    note.innerHTML = `Backend demo data is unavailable, so oral organization cannot run.`;
    return;
  }

  const paperCount = Number(state.oral.demoInfo.paperCount || 0);
  const totalSessions = state.oral.parallelSessions * state.oral.timeSlots;
  const minCapacity = totalSessions * state.oral.minPerSession;
  const maxCapacity = totalSessions * state.oral.maxPerSession;

  sourceStatus.innerHTML = `
    conference: <span class="mono">${escapeHtml(state.oral.demoInfo.conference || state.oral.conference)}</span><br>
    papers: <span class="mono">${paperCount}</span><br>
    unique presenters: <span class="mono">${state.oral.demoInfo.presenterCount}</span><br>
    repeated presenters: <span class="mono">${state.oral.demoInfo.multiPresenterCount}</span><br>
    paper data: <span class="mono">${state.oral.demoInfo.paperDataPath}</span><br>
    similarity matrix: <span class="mono">${state.oral.demoInfo.similarityMatrixPath}</span>
  `;

  const issues = [];
  if (state.oral.minPerSession > state.oral.maxPerSession) {
    issues.push("`Min` cannot be larger than `Max`.");
  }
  if (paperCount > maxCapacity) {
    issues.push(`Current capacity is too small: ${paperCount} papers but only ${maxCapacity} maximum slots are available.`);
  }
  if (paperCount < minCapacity) {
    issues.push(`Current minimum requirement is too high: minimum filled capacity is ${minCapacity} for only ${paperCount} papers.`);
  }

  if (issues.length) {
    note.classList.add("warn");
    note.innerHTML = issues.join("<br>");
    return;
  }

  note.classList.remove("warn");
  note.innerHTML = `
    Total sessions: <span class="mono">${totalSessions}</span><br>
    Paper count: <span class="mono">${paperCount}</span><br>
    Capacity range: <span class="mono">${minCapacity}</span> to <span class="mono">${maxCapacity}</span><br>
    Current configuration can accommodate all demo papers.
  `;
}

/* ═══════════════════ Run ═══════════════════ */

export async function runOralOrganization() {
  state.oral.parallelSessions = Math.max(1, Number(document.getElementById("oralParallelInput").value) || 1);
  state.oral.timeSlots = Math.max(1, Number(document.getElementById("oralSlotsInput").value) || 1);
  state.oral.maxPerSession = Math.max(1, Number(document.getElementById("oralMaxInput").value) || 1);
  state.oral.minPerSession = Math.max(1, Number(document.getElementById("oralMinInput").value) || 1);
  renderOralCapacityNotice();

  if (!state.oral.demoInfo || state.oral.demoInfo.error) {
    alert("Oral demo data is unavailable from the server.");
    return;
  }
  if (state.oral.minPerSession > state.oral.maxPerSession) {
    alert("Invalid oral session constraints: Min cannot be larger than Max.");
    return;
  }

  const paperCount = Number(state.oral.demoInfo.paperCount || 0);
  const totalSessions = state.oral.parallelSessions * state.oral.timeSlots;
  if (paperCount > totalSessions * state.oral.maxPerSession) {
    alert("The current oral session configuration cannot hold all papers. Increase M, N, or Max.");
    return;
  }
  if (paperCount < totalSessions * state.oral.minPerSession) {
    alert("The current oral session configuration is infeasible because the minimum requirement is too high.");
    return;
  }

  state.oral.isRunning = true;
  state.oral.activeSessionId = null;
  state.oral.activeHardPaperId = null;
  setRunState("oral", true, "Computing conflict-free sessions and optimizing within-session similarity...");
  renderOralResults();
  try {
    const resp = await apiPost("/oral/run", {
      conference: state.oral.conference,
      parallel_sessions: state.oral.parallelSessions,
      time_slots: state.oral.timeSlots,
      max_per_session: state.oral.maxPerSession,
      min_per_session: state.oral.minPerSession,
    });
    state.oral.result = prepareOralResult(requireApiResult(resp, "Oral organization"));
    state.oral.activeSessionId = null;
    state.oral.activeHardPaperId = null;
  } catch (err) {
    alert(`Oral organization backend error: ${err.message}`);
  } finally {
    state.oral.isRunning = false;
    setRunState("oral", false);
    renderOralResults();
  }
}

/* ═══════════════════ Move / conflict helpers ═══════════════════ */

function oralPresenterConflict(result, paper, targetSessionId) {
  const target = findOralSession(result, targetSessionId);
  if (!target) return null;
  const presenters = Array.isArray(paper.presenters) ? paper.presenters : [];
  if (!presenters.length) return null;

  for (const session of result.sessions) {
    if (session.id === targetSessionId || session.slot !== target.slot) continue;
    for (const existing of session.papers) {
      if (oralPaperId(existing) === oralPaperId(paper)) continue;
      const otherPresenters = Array.isArray(existing.presenters) ? existing.presenters : [];
      const conflict = presenters.find((name) => otherPresenters.includes(name));
      if (conflict) return conflict;
    }
  }
  return null;
}

function moveOralPaper(paperId, targetSessionId) {
  const result = state.oral.result;
  if (!result) return;
  const paper = result.papers.find((row) => oralPaperId(row) === String(paperId));
  if (!paper) return;
  const sourceSessionId = result.assignment[String(paperId)];
  if (!sourceSessionId || !targetSessionId) {
    alert("Select a valid target session.");
    return;
  }
  if (sourceSessionId === targetSessionId) {
    alert("This paper is already assigned to the selected session.");
    return;
  }
  const source = findOralSession(result, sourceSessionId);
  const target = findOralSession(result, targetSessionId);
  if (!source || !target) return;
  if (source.papers.length - 1 < state.oral.minPerSession) {
    alert(`Move failed: ${oralSessionLabel(source.id)} would drop below the minimum session size.`);
    return;
  }
  if (target.papers.length + 1 > state.oral.maxPerSession) {
    alert(`Move failed: ${oralSessionLabel(target.id)} would exceed the maximum session size.`);
    return;
  }
  const conflictName = oralPresenterConflict(result, paper, targetSessionId);
  if (conflictName) {
    alert(`Move failed: presenter conflict for ${conflictName} in ${oralSessionLabel(targetSessionId)}.`);
    return;
  }

  source.papers = source.papers.filter((row) => oralPaperId(row) !== String(paperId));
  target.papers.push(paper);
  source.paperCount = source.papers.length;
  target.paperCount = target.papers.length;
  result.assignment[String(paperId)] = targetSessionId;
  result.hardPapers = (result.hardPapers || []).filter((row) => String(row.paper_id) !== String(paperId));
  state.oral.activeSessionId = targetSessionId;
  state.oral.activeHardPaperId = null;
  renderOralResults();
  alert(`Move successful: paper ${paperId} moved to ${oralSessionLabel(targetSessionId)}.`);
}

/* ═══════════════════ Schedule preview ═══════════════════ */

function oralSchedulePreviewHtml(session) {
  const detailed = state.oral.detailMode === "detailed";
  if (!session || !session.papers.length) return `<span class="tiny">(empty)</span>`;
  if (detailed) {
    return session.papers
      .slice(0, 3)
      .map((paper) => `<div>${escapeHtml(oralPaperId(paper))}: ${escapeHtml(paper.title || "")}</div>`)
      .join("");
  }
  const paperIds = session.papers.slice(0, 5).map((paper) => escapeHtml(oralPaperId(paper))).join(", ");
  const meta = [
    `Topics: ${escapeHtml(sessionTopicNames(session.papers, oralPaperDist, 2))}`,
    paperIds ? `Papers: ${paperIds}${session.papers.length > 5 ? ", ..." : ""}` : "",
    sessionTimeLabel(session) ? `Time: ${escapeHtml(sessionTimeLabel(session))}` : "",
    session.location ? `Location: ${escapeHtml(session.location)}` : "",
  ].filter(Boolean);
  return meta.map((line) => `<div>${line}</div>`).join("");
}

function findOralHardPaper(result, paperId) {
  return ((result && result.hardPapers) || []).find((row) => String(row.paper_id) === String(paperId)) || null;
}

/* ═══════════════════ Session modal ═══════════════════ */

export function renderOralSessionModal() {
  const modal = document.getElementById("oralSessionModal");
  const title = document.getElementById("oralSessionModalTitle");
  const body = document.getElementById("oralSessionModalBody");
  const result = state.oral.result;
  const sessionId = state.oral.activeSessionId;

  if (!result || !sessionId) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const session = findOralSession(result, sessionId);
  if (!session) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  ensureSessionMetadata(session);
  title.textContent = oralSessionName(session);
  body.innerHTML = `
    <div class="tiny">
      Papers in this session: <span class="mono">${session.papers.length}</span><br>
      Allowed size range: <span class="mono">${state.oral.minPerSession}</span> to <span class="mono">${state.oral.maxPerSession}</span><br>
      Move a paper by selecting a target session and clicking the move button.
    </div>
    <div class="paper-move-card">
      <div><strong>Session Metadata</strong></div>
      <div class="tiny" style="margin-top:4px">Edit the generated session title, scheduling fields, location, description, and speaker information used by the export.</div>
      <div class="modal-field-grid">
        <div class="modal-field">
          <label>Session Name</label>
          <input data-oral-session-name-input="${session.id}" type="text" value="${escapeHtml(session.sessionName || "")}" placeholder="Concise academic session name">
        </div>
        <div class="modal-field">
          <label>Session Chair</label>
          <input data-oral-session-chair-input="${session.id}" type="text" value="${escapeHtml(session.sessionChair || "")}" placeholder="Leave blank or assign manually">
        </div>
        <div class="modal-field">
          <label>Date</label>
          <input data-oral-session-date-input="${session.id}" type="text" value="${escapeHtml(session.sessionDate || "")}" placeholder="e.g. 2025-07-17">
        </div>
        <div class="modal-field">
          <label>Track</label>
          <input data-oral-session-track-input="${session.id}" type="text" value="${escapeHtml(session.trackLabel || "")}" placeholder="Optional track label">
        </div>
        <div class="modal-field">
          <label>Start Time</label>
          <input data-oral-session-start-input="${session.id}" type="text" value="${escapeHtml(session.startTime || "")}" placeholder="e.g. 09:00">
        </div>
        <div class="modal-field">
          <label>End Time</label>
          <input data-oral-session-end-input="${session.id}" type="text" value="${escapeHtml(session.endTime || "")}" placeholder="e.g. 10:30">
        </div>
        <div class="modal-field">
          <label>Room / Location</label>
          <input data-oral-session-location-input="${session.id}" type="text" value="${escapeHtml(session.location || "")}" placeholder="Optional room or venue">
        </div>
        <div class="modal-field">
          <label>Speakers</label>
          <input data-oral-session-speakers-input="${session.id}" type="text" value="${escapeHtml(session.speakers || "")}" placeholder="Optional speakers">
        </div>
        <div class="modal-field modal-field-span">
          <label>Description</label>
          <textarea data-oral-session-description-input="${session.id}" rows="3" placeholder="Optional session description">${escapeHtml(session.description || "")}</textarea>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-secondary" data-action="save-oral-session" data-session-id="${session.id}" type="button">Save Session Metadata</button>
      </div>
    </div>
    <div class="modal-section">
      <div><strong>Presentations</strong></div>
      ${session.papers.map((paper) => `
        <div class="paper-move-card">
          <div><strong>${escapeHtml(oralPaperId(paper))}</strong> - ${escapeHtml(paper.title || "")}</div>
          <div class="tiny" style="margin-top:4px">Presenter: ${escapeHtml(oralPresentersLabel(paper))}</div>
          <div class="paper-move-row">
            <div class="tiny">Target session</div>
            <select data-oral-move-select="${escapeHtml(oralPaperId(paper))}">
              <option value="">Select target session</option>
              ${result.sessions
                .filter((candidate) => candidate.id !== session.id)
                .map((candidate) => `<option value="${candidate.id}">${escapeHtml(oralSessionName(candidate))} (${escapeHtml(oralSessionLabel(candidate.id))})</option>`)
                .join("")}
            </select>
            <button class="btn-secondary" data-action="move-oral-paper" data-paper-id="${escapeHtml(oralPaperId(paper))}" type="button">Move</button>
          </div>
        </div>
      `).join("") || `<div class="tiny" style="margin-top:8px">No papers in this session.</div>`}
    </div>
  `;

  /* Event delegation for move and save buttons */
  body.addEventListener("click", (e) => {
    const moveBtn = e.target.closest("button[data-action='move-oral-paper']");
    if (moveBtn) {
      const paperId = moveBtn.getAttribute("data-paper-id");
      const select = body.querySelector(`select[data-oral-move-select="${paperId}"]`);
      const targetSessionId = select ? select.value : "";
      if (!targetSessionId) {
        alert("Select a target session first.");
        return;
      }
      moveOralPaper(paperId, targetSessionId);
      return;
    }

    const saveBtn = e.target.closest("button[data-action='save-oral-session']");
    if (saveBtn) {
      const sid = saveBtn.getAttribute("data-session-id");
      setOralSessionFields(sid, {
        sessionName: body.querySelector(`input[data-oral-session-name-input="${sid}"]`)?.value || "",
        sessionChair: body.querySelector(`input[data-oral-session-chair-input="${sid}"]`)?.value || "",
        sessionDate: body.querySelector(`input[data-oral-session-date-input="${sid}"]`)?.value || "",
        trackLabel: body.querySelector(`input[data-oral-session-track-input="${sid}"]`)?.value || "",
        startTime: body.querySelector(`input[data-oral-session-start-input="${sid}"]`)?.value || "",
        endTime: body.querySelector(`input[data-oral-session-end-input="${sid}"]`)?.value || "",
        location: body.querySelector(`input[data-oral-session-location-input="${sid}"]`)?.value || "",
        speakers: body.querySelector(`input[data-oral-session-speakers-input="${sid}"]`)?.value || "",
        description: body.querySelector(`textarea[data-oral-session-description-input="${sid}"]`)?.value || "",
      });
    }
  });

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function openOralSessionModal(sessionId) {
  state.oral.activeSessionId = sessionId;
  renderOralSessionModal();
}

function closeOralSessionModal() {
  state.oral.activeSessionId = null;
  renderOralSessionModal();
}

/* ═══════════════════ Hard-paper modal ═══════════════════ */

export function renderOralHardPaperModal() {
  const modal = document.getElementById("oralHardPaperModal");
  const title = document.getElementById("oralHardPaperModalTitle");
  const body = document.getElementById("oralHardPaperModalBody");
  const result = state.oral.result;
  const paperId = state.oral.activeHardPaperId;

  if (!result || !paperId) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const row = findOralHardPaper(result, paperId);
  if (!row) {
    state.oral.activeHardPaperId = null;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const alternatives = (row.alternative_sessions || []).length
    ? row.alternative_sessions
    : result.sessions
        .filter((session) => session.id !== row.current_session_id)
        .map((session) => ({ session_id: session.id, session_name: oralSessionName(session) }));

  title.textContent = `Last-Mile: ${row.paper_id}`;
  body.innerHTML = `
    <div class="tiny">
      This paper was flagged as hard to place. Inspect the explanation and apply a last-mile move only if it improves the schedule.
    </div>
    <div class="paper-move-card">
      <div><strong>${escapeHtml(row.paper_id)}</strong> - ${escapeHtml(row.title || "")}</div>
      <div class="tiny" style="margin-top:4px">Current session: ${escapeHtml(row.current_session_name || row.current_session_id || "N/A")}</div>
      <div class="tiny">Reason: ${escapeHtml(row.difficultyReason || "Low assignment confidence.")}</div>
      <div class="tiny">Suggested action: ${escapeHtml(row.suggestedAction || "Review manually.")}</div>
      <div class="paper-move-row">
        <div class="tiny">Target session</div>
        <select data-oral-hard-paper-select="${escapeHtml(row.paper_id)}">
          <option value="">Keep current assignment</option>
          ${alternatives.map((alt) => `<option value="${alt.session_id}">${escapeHtml(alt.session_name || alt.session_id)}</option>`).join("")}
        </select>
        <button class="btn-secondary" data-action="apply-oral-hard-paper" data-paper-id="${escapeHtml(row.paper_id)}" type="button">Apply</button>
      </div>
      <div class="modal-actions">
        <button class="btn-muted" data-action="open-oral-hard-paper-session" data-session-id="${escapeHtml(row.current_session_id || "")}" type="button">Open Current Session</button>
      </div>
    </div>
  `;

  /* Event delegation */
  body.addEventListener("click", (e) => {
    const applyBtn = e.target.closest("button[data-action='apply-oral-hard-paper']");
    if (applyBtn) {
      const currentPaperId = applyBtn.getAttribute("data-paper-id");
      const select = body.querySelector(`select[data-oral-hard-paper-select="${currentPaperId}"]`);
      const targetSessionId = select ? select.value : "";
      if (!targetSessionId) {
        alert("Select a target session if you want to change this assignment.");
        return;
      }
      moveOralPaper(currentPaperId, targetSessionId);
      return;
    }

    const sessionBtn = e.target.closest("button[data-action='open-oral-hard-paper-session']");
    if (sessionBtn) {
      const sid = sessionBtn.getAttribute("data-session-id");
      if (!sid) return;
      closeOralHardPaperModal();
      openOralSessionModal(sid);
    }
  });

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function openOralHardPaperModal(paperId) {
  state.oral.activeHardPaperId = paperId;
  renderOralHardPaperModal();
}

function closeOralHardPaperModal() {
  state.oral.activeHardPaperId = null;
  renderOralHardPaperModal();
}

/* ═══════════════════ Render results ═══════════════════ */

export function renderOralResults() {
  const summary = document.getElementById("oralSummary");
  const schedulePanel = document.getElementById("oralSchedulePanel");
  const editorPanel = document.getElementById("oralEditorPanel");
  const lastMilePanel = document.getElementById("oralLastMilePanel");
  const exportBtn = document.getElementById("exportOralBtn");

  const result = state.oral.result;
  const loadingBanner = state.oral.isRunning
    ? loadingHtml("Optimizing the oral schedule. This may take a short while on the full demo data.")
    : "";
  renderOralCapacityNotice();
  if (exportBtn) exportBtn.disabled = state.oral.isRunning || !result;

  if (!result) {
    const paperCount = state.oral.demoInfo && !state.oral.demoInfo.error ? state.oral.demoInfo.paperCount : "\u2026";
    summary.innerHTML = `
      <div class="metric"><div class="label">Papers</div><div class="value">${paperCount}</div></div>
      <div class="metric"><div class="label">Parallel Sessions</div><div class="value">${state.oral.parallelSessions}</div></div>
      <div class="metric"><div class="label">Time Slots</div><div class="value">${state.oral.timeSlots}</div></div>
      <div class="metric"><div class="label">Session Bounds</div><div class="value">${state.oral.minPerSession}-${state.oral.maxPerSession}</div></div>
    `;
    schedulePanel.innerHTML = `${loadingBanner}<div class="tiny" style="padding:10px">${state.oral.isRunning ? "Waiting for the oral organizer to finish..." : "Run oral organization to generate the 2-D session grid."}</div>`;
    editorPanel.innerHTML = `<div class="tiny">${state.oral.isRunning ? "Please wait. The oral result panel will refresh automatically when the run finishes." : "After the run, click any session cell to inspect papers, edit session metadata, and move them between sessions."}</div>`;
    if (lastMilePanel) {
      lastMilePanel.innerHTML = `<div class="tiny">${state.oral.isRunning ? "Hard-to-assign papers will be analyzed after the schedule is generated." : "The last-mile modification panel will list the papers the system considers hard to place."}</div>`;
    }
    renderOralSessionModal();
    renderOralHardPaperModal();
    return;
  }

  summary.innerHTML = `
    <div class="metric"><div class="label">Papers</div><div class="value">${result.papers.length}</div></div>
    <div class="metric"><div class="label">Sessions</div><div class="value">${result.sessions.length}</div></div>
    <div class="metric"><div class="label">Session Bounds</div><div class="value">${state.oral.minPerSession}-${state.oral.maxPerSession}</div></div>
    <div class="metric"><div class="label">Hard Papers</div><div class="value">${(result.hardPapers || []).length}</div></div>
  `;

  const T = state.oral.timeSlots;
  const K = state.oral.parallelSessions;

  schedulePanel.innerHTML = `${loadingBanner}
    <div class="schedule-shell">
      <table>
        <thead>
          <tr>
            <th>Time Slot</th>
            ${Array.from({ length: K }, (_, i) => `<th>Track ${i + 1}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${Array.from({ length: T }, (_, tIdx) => {
            const slot = tIdx + 1;
            return `
              <tr>
                <td><strong>Slot ${slot}</strong></td>
                ${Array.from({ length: K }, (_, kIdx) => {
                  const track = kIdx + 1;
                  const sid = scheduleSessionId(slot, track);
                  const session = result.sessions.find((s) => s.id === sid);
                  if (!session) {
                    return `<td><div class="tiny" style="padding:10px">(missing session)</div></td>`;
                  }
                  ensureSessionMetadata(session);
                  const trackText = session.trackLabel ? `${session.trackLabel} \u00b7 ${oralSessionLabel(session.id)}` : oralSessionLabel(session.id);
                  return `
                    <td>
                      <button class="session-tile" data-action="open-oral-session" data-session-id="${session.id}" type="button">
                        <div class="session-heading">
                          <div>
                            <strong>${escapeHtml(oralSessionName(session))}</strong><br>
                            <span class="tiny">${escapeHtml(trackText)} \u00b7 ${session.papers.length} papers</span>
                          </div>
                          <span class="badge ${session.papers.length < state.oral.minPerSession || session.papers.length > state.oral.maxPerSession ? "badge-warn" : "badge-ok"}">
                            ${session.papers.length}/${session.targetSize}
                          </span>
                        </div>
                        <div class="session-preview">
                          ${oralSchedulePreviewHtml(session)}
                        </div>
                      </button>
                    </td>
                  `;
                }).join("")}
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;

  editorPanel.innerHTML = `
    <h3>Manual Modification</h3>
    <div class="tiny">
      Click a session cell in the 2-D grid to open the session detail window.
      Every manual move is checked for presenter conflicts and session size violations before it is applied.
      The schedule view switcher toggles between concise tiles and a detailed preview with paper titles.
    </div>
  `;

  if (lastMilePanel) {
    lastMilePanel.innerHTML = `
      <h3>Last-Mile Modification</h3>
      <div class="tiny" style="margin-bottom:8px">
        The initial grid stays concise. Click a flagged paper to open a detailed popup with explanation and move actions.
      </div>
      <div class="last-mile-grid">
        ${(result.hardPapers || []).map((row) => `
          <button class="last-mile-tile" data-action="open-oral-hard-paper" data-paper-id="${escapeHtml(row.paper_id)}" type="button">
            <strong>${escapeHtml(row.paper_id)}</strong>
            <div class="tiny">Current: ${escapeHtml(row.current_session_name || row.current_session_id || "N/A")}</div>
            <div class="tiny">Alternatives: ${escapeHtml(String((row.alternative_sessions || []).length || 0))}</div>
            ${state.oral.detailMode === "detailed" ? `<div class="tiny">${escapeHtml(row.title || "")}</div>` : ""}
            ${state.oral.detailMode === "detailed" ? `<div class="tiny">${escapeHtml(row.suggestedAction || "Review manually.")}</div>` : ""}
          </button>
        `).join("") || `<div class="tiny">No hard-to-assign oral papers were flagged for last-mile modification.</div>`}
      </div>
    `;
    /* Delegation for hard-paper tiles */
    lastMilePanel.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-action='open-oral-hard-paper']");
      if (btn) openOralHardPaperModal(btn.getAttribute("data-paper-id"));
    });
  }

  /* Delegation for session tiles */
  schedulePanel.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action='open-oral-session']");
    if (btn) openOralSessionModal(btn.getAttribute("data-session-id"));
  });

  renderOralSessionModal();
  renderOralHardPaperModal();
}

/* ═══════════════════ Render helper panels ═══════════════════ */

export function renderOralSchedulePanel() {
  /* Included inside renderOralResults -- exposed for external callers */
  renderOralResults();
}

export function renderOralEditorPanel() {
  /* Included inside renderOralResults -- exposed for external callers */
  renderOralResults();
}

export function renderOralLastMilePanel() {
  /* Included inside renderOralResults -- exposed for external callers */
  renderOralResults();
}

/* ═══════════════════ Export ═══════════════════ */

function oralSessionAnchorId(session) {
  return `oral-session-${String(session.id || "").replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
}

export function buildOralExportHtml() {
  const result = state.oral.result;
  if (!result) return "";
  const rows = [];
  for (let slot = 1; slot <= state.oral.timeSlots; slot += 1) {
    rows.push(`
      <tr>
        <td><div class="slot-label">Slot ${slot}</div></td>
        ${Array.from({ length: state.oral.parallelSessions }, (_, idx) => {
          const track = idx + 1;
          const session = findOralSession(result, scheduleSessionId(slot, track));
          if (!session) return "<td></td>";
          return `
            <td>
              <a class="schedule-link" href="#${oralSessionAnchorId(session)}">
                <strong>${escapeHtml(oralSessionName(session))}</strong>
                <span>${escapeHtml(session.trackLabel || `Track ${track}`)} \u00b7 ${session.papers.length} papers</span>
              </a>
            </td>
          `;
        }).join("")}
      </tr>
    `);
  }
  const sections = result.sessions.map((session) => `
    <section id="${oralSessionAnchorId(session)}" class="session-card">
      <div class="session-head">
        <div>
          <h3>${escapeHtml(oralSessionName(session))}</h3>
          <div class="session-kicker">${escapeHtml(oralSessionLabel(session.id))}</div>
        </div>
        <a class="back-link" href="#top">Back to overview</a>
      </div>
      <div class="meta-grid">
        ${exportMetaCard("Date", session.sessionDate)}
        ${exportMetaCard("Time", sessionTimeLabel(session))}
        ${exportMetaCard("Track", session.trackLabel || oralSessionLabel(session.id))}
        ${exportMetaCard("Room / Location", session.location)}
        ${exportMetaCard("Speakers / Chair", sessionSpeakersChairLabel(session))}
        ${exportMetaCard("Description", session.description)}
      </div>
      <div class="paper-list">
        ${(session.papers || []).map((paper) => `
          <div class="paper-item">
            <strong>${escapeHtml(oralPaperId(paper))} \u00b7 ${escapeHtml(paper.title || "")}</strong>
            <span>Presenters: ${escapeHtml(oralPresentersLabel(paper))}</span>
            <span>Authors: ${escapeHtml(paperAuthorsOrPresentersLabel(paper) || "Not set")}</span>
          </div>
        `).join("") || `<div class="paper-item"><strong>Empty session</strong><span>No papers assigned.</span></div>`}
      </div>
    </section>
  `).join("");
  const summaryHtml = [
    exportSummaryChip("Papers", result.papers.length),
    exportSummaryChip("Sessions", result.sessions.length),
    exportSummaryChip("Tracks", state.oral.parallelSessions),
    exportSummaryChip("Time Slots", state.oral.timeSlots),
  ].join("");
  return buildStyledExportHtml({
    title: "Oral Session Schedule",
    subtitle: "A polished conference-ready schedule export with linked overview and session cards.",
    summaryHtml,
    headerHtml: `
      <tr>
        <th>Time Slot</th>
        ${Array.from({ length: state.oral.parallelSessions }, (_, idx) => `<th>Track ${idx + 1}</th>`).join("")}
      </tr>
    `,
    rowsHtml: rows.join(""),
    sectionsHtml: sections,
  });
}

export function buildOralExportCsv() {
  const result = state.oral.result;
  if (!result) return "";
  const rows = [[
    "Date",
    "Time Start",
    "Time End",
    "Tracks",
    "Session Title",
    "Room/Location",
    "Description",
    "Speakers/Session Chair",
    "Authors",
    "Session or Sub-session(Sub)",
  ]];
  result.sessions.forEach((session) => {
    rows.push([
      session.sessionDate || "",
      session.startTime || "",
      session.endTime || "",
      session.trackLabel || "",
      oralSessionName(session),
      session.location || "",
      session.description || "",
      sessionSpeakersChairLabel(session) || "",
      "",
      "Session",
    ]);
    (session.papers || []).forEach((paper) => {
      rows.push([
        session.sessionDate || "",
        session.startTime || "",
        session.endTime || "",
        session.trackLabel || "",
        paper.title || oralPaperId(paper),
        session.location || "",
        oralPaperId(paper),
        oralPresentersLabel(paper),
        paperAuthorsOrPresentersLabel(paper),
        "Sub",
      ]);
    });
  });
  return rows.map((row) => row.map(csvEscape).join(",")).join("\n");
}

/* ═══════════════════ Event setup ═══════════════════ */

export function setupOralEvents() {
  document.getElementById("runOralBtn").addEventListener("click", runOralOrganization);
  document.getElementById("oralConferenceSelect").addEventListener("change", (e) => {
    state.oral.conference = e.target.value;
    state.oral.result = null;
    state.oral.activeSessionId = null;
    state.oral.activeHardPaperId = null;
    void loadOralDemoInfo();
  });
  ["oralParallelInput", "oralSlotsInput", "oralMaxInput", "oralMinInput"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      state.oral.parallelSessions = Math.max(1, Number(document.getElementById("oralParallelInput").value) || 1);
      state.oral.timeSlots = Math.max(1, Number(document.getElementById("oralSlotsInput").value) || 1);
      state.oral.maxPerSession = Math.max(1, Number(document.getElementById("oralMaxInput").value) || 1);
      state.oral.minPerSession = Math.max(1, Number(document.getElementById("oralMinInput").value) || 1);
      renderOralCapacityNotice();
    });
  });
  document.getElementById("oralViewModeSelect").addEventListener("change", (e) => {
    state.oral.detailMode = e.target.value === "detailed" ? "detailed" : "concise";
    renderOralResults();
  });
  document.getElementById("exportOralBtn").addEventListener("click", () => {
    if (!state.oral.result) {
      alert("Run oral organization first.");
      return;
    }
    const format = document.getElementById("oralExportFormatSelect").value;
    if (format === "csv") {
      downloadFile("oral_session_schedule.csv", buildOralExportCsv(), "text/csv;charset=utf-8");
      return;
    }
    downloadFile("oral_session_schedule.html", buildOralExportHtml(), "text/html;charset=utf-8");
  });
  document.getElementById("oralSessionModalClose").addEventListener("click", closeOralSessionModal);
  document.getElementById("oralSessionModal").addEventListener("click", (e) => {
    if (e.target.id === "oralSessionModal") closeOralSessionModal();
  });
  document.getElementById("oralHardPaperModalClose").addEventListener("click", closeOralHardPaperModal);
  document.getElementById("oralHardPaperModal").addEventListener("click", (e) => {
    if (e.target.id === "oralHardPaperModal") closeOralHardPaperModal();
  });
}
