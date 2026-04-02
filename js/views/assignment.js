/**
 * assignment.js
 *
 * All assignment-related functions: loading info, running the solver,
 * rendering the result list / detail panels, normalizing uploads, and
 * building the JSON export object.
 */

import { state } from "../state.js";
import { apiGet, apiPost, requireApiResult } from "../api.js";
import { normalizeTopicHints } from "../taxonomy.js";
import {
  escapeHtml,
  formatPct,
  formatNum,
  keyPair,
  normalizeAuthors,
  authorsLabel,
  loadingHtml,
  setRunState,
  renderConferenceSelect,
  parseJsonFile,
  downloadJson,
} from "../utils.js";

/* ═══════════════════ Normalisation helpers ═══════════════════ */

export function normalizeSubmissionList(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : Array.isArray(payload.submissions)
      ? payload.submissions
      : [];
  return rows
    .map((x) => ({
      submission_id: x.submission_id || x.id || x.paper_id,
      title: x.title || "Untitled",
      abstract: x.abstract || "",
      authors: normalizeAuthors(x.authors || x.author || x.author_names || x.authorNames),
      topic_hints: normalizeTopicHints(x.topic_hints || x.topics || x.topic_tags || x.topicTags),
    }))
    .filter((x) => x.submission_id);
}

export function normalizePcList(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : Array.isArray(payload.pc_members)
      ? payload.pc_members
      : Array.isArray(payload.pcMembers)
        ? payload.pcMembers
        : [];

  return rows
    .map((x) => ({
      pc_id: x.pc_id || x.id,
      role: x.role || "Reviewer",
      name: x.name || x.full_name || x.display_name || x.pc_name || x.pc_id || x.id || "Unknown",
      publication_history: Array.isArray(x.publication_history)
        ? x.publication_history.map((p) => ({ title: p.title || "", abstract: p.abstract || "" }))
        : [],
    }))
    .filter((x) => x.pc_id);
}

export function normalizeCoi(payload) {
  const set = new Set();

  function push(subId, pcId, flag = true) {
    if (!subId || !pcId) return;
    if (flag) set.add(keyPair(String(subId), String(pcId)));
  }

  if (Array.isArray(payload)) {
    payload.forEach((row) => {
      if (Array.isArray(row) && row.length >= 2) {
        push(row[0], row[1], true);
      } else if (row && typeof row === "object") {
        push(
          row.submission_id || row.submissionId || row.paper_id,
          row.pc_id || row.pcId || row.reviewer_id,
          row.conflict !== false,
        );
      }
    });
  } else if (payload && typeof payload === "object") {
    if (Array.isArray(payload.conflicts)) {
      return normalizeCoi(payload.conflicts);
    }
    Object.entries(payload).forEach(([subId, value]) => {
      if (Array.isArray(value)) {
        value.forEach((pcId) => push(subId, pcId, true));
      } else if (value && typeof value === "object") {
        Object.entries(value).forEach(([pcId, v]) => push(subId, pcId, Boolean(v)));
      }
    });
  }
  return set;
}

/* ═══════════════════ Info / state helpers ═══════════════════ */

export async function loadAssignmentInfo() {
  try {
    const resp = await apiGet(`/assignment/info?conference=${encodeURIComponent(state.assignment.conference)}`);
    state.assignment.info = requireApiResult(resp, "Assignment info");
    state.assignment.availableConferences = state.assignment.info.availableConferences || [];
    state.assignment.conference = state.assignment.info.conference || state.assignment.conference;
  } catch (err) {
    state.assignment.info = { error: err.message };
  }
  renderAssignmentResults();
}

function assignmentModeLabel() {
  return state.assignment.mode === "demo" ? "Demonstration Mode" : "Normal Mode";
}

export function resetAssignmentResult() {
  state.assignment.result = null;
  state.assignment.selected = null;
}

export function renderAssignmentModeUI() {
  const select = document.getElementById("assignmentModeSelect");
  const demoPanel = document.getElementById("assignmentDemoPanel");
  const uploadPanel = document.getElementById("assignmentUploadPanel");
  if (select) select.value = state.assignment.mode;
  renderConferenceSelect(
    "assignmentConferenceSelect",
    state.assignment.conference,
    state.assignment.availableConferences,
  );
  if (demoPanel) demoPanel.hidden = state.assignment.mode !== "demo";
  if (uploadPanel) uploadPanel.hidden = state.assignment.mode !== "normal";
}

function renderAssignmentUploadStatus() {
  const status = document.getElementById("assignmentUploadStatus");
  if (!status) return;
  status.innerHTML = `
    submissions: <span class="mono">${state.assignment.submissions.length}</span> (${escapeHtml(state.assignment.uploadNames.submissions || "not uploaded")})<br>
    reviewers: <span class="mono">${state.assignment.reviewers.length}</span> (${escapeHtml(state.assignment.uploadNames.reviewers || "not uploaded")})<br>
    meta-reviewers: <span class="mono">${state.assignment.metaReviewers.length}</span> (${escapeHtml(state.assignment.uploadNames.metaReviewers || "not uploaded")})<br>
    COI pairs: <span class="mono">${state.assignment.coi.size}</span> (${escapeHtml(state.assignment.uploadNames.coi || "not uploaded")})
  `;
}

function assignmentWorkloadForRole(role) {
  return role === "Meta-Reviewer" ? state.assignment.metaReviewerWorkload : state.assignment.reviewerWorkload;
}

function findAssignmentPaperRow(result, submissionId) {
  return result.byPaper.find((row) => row.submission.submission_id === String(submissionId)) || null;
}

function findAssignmentPersonRow(result, pcId) {
  return result.byPerson.find((row) => row.person.pc_id === String(pcId)) || null;
}

function refreshAssignmentDerived(result) {
  if (!result) return;

  result.byPaper.forEach((row) => {
    row.assignedReviewerCount = row.reviewers.length;
    row.assignedMetaReviewerCount = row.metareviewers.length;
    row.reviewerShortage = Math.max(0, row.requestedReviewerCoverage - row.reviewers.length);
    row.metaReviewerShortage = Math.max(0, row.metaReviewerCoverage - row.metareviewers.length);

    const reviewerAssignedIds = new Set(row.reviewers.map((entry) => entry.person.pc_id));
    const metaAssignedIds = new Set(row.metareviewers.map((entry) => entry.person.pc_id));
    row.reviewerCandidates.forEach((cand) => { cand.assigned = reviewerAssignedIds.has(cand.pc_id); });
    row.metareviewerCandidates.forEach((cand) => { cand.assigned = metaAssignedIds.has(cand.pc_id); });
  });

  const personMap = new Map();
  [...(result.reviewers || []), ...(result.metaReviewers || [])].forEach((person) => {
    const workload = assignmentWorkloadForRole(person.role);
    personMap.set(person.pc_id, {
      person,
      assignedReviewPapers: [],
      assignedMetaPapers: [],
      assignedCount: 0,
      workload,
      remaining: workload,
    });
  });

  result.byPaper.forEach((row) => {
    row.reviewers.forEach((assignment) => {
      const entry = personMap.get(assignment.person.pc_id);
      if (!entry) return;
      entry.assignedReviewPapers.push({
        submission: row.submission,
        score: assignment.score,
        assignmentType: "review",
      });
    });
    row.metareviewers.forEach((assignment) => {
      const entry = personMap.get(assignment.person.pc_id);
      if (!entry) return;
      entry.assignedMetaPapers.push({
        submission: row.submission,
        score: assignment.score,
        assignmentType: "metareview",
      });
    });
  });

  result.byPerson = Array.from(personMap.values())
    .map((row) => {
      row.assignedReviewPapers.sort((a, b) => b.score - a.score);
      row.assignedMetaPapers.sort((a, b) => b.score - a.score);
      row.assignedCount = row.assignedReviewPapers.length + row.assignedMetaPapers.length;
      row.remaining = Math.max(0, row.workload - row.assignedCount);
      return row;
    })
    .sort((a, b) => a.person.role.localeCompare(b.person.role) || a.person.name.localeCompare(b.person.name));

  result.meta.assignedReviewerPairs = result.byPaper.reduce((acc, row) => acc + row.reviewers.length, 0);
  result.meta.assignedMetaReviewerPairs = result.byPaper.reduce((acc, row) => acc + row.metareviewers.length, 0);
  result.meta.requestedReviewerPairs = result.byPaper.length * state.assignment.reviewerCoverage;
  result.meta.requestedMetaReviewerPairs = result.byPaper.length;
  result.meta.reviewerShortage = result.meta.requestedReviewerPairs - result.meta.assignedReviewerPairs;
  result.meta.metaReviewerShortage = result.meta.requestedMetaReviewerPairs - result.meta.assignedMetaReviewerPairs;
  result.meta.reviewerWorkload = state.assignment.reviewerWorkload;
  result.meta.reviewerCoverage = state.assignment.reviewerCoverage;
  result.meta.metaReviewerWorkload = state.assignment.metaReviewerWorkload;
}

/* ═══════════════════ Run ═══════════════════ */

export async function runAssignment() {
  const mode = state.assignment.mode;
  state.assignment.reviewerWorkload = Math.max(1, Number(document.getElementById("reviewerWorkloadInput").value) || 1);
  state.assignment.reviewerCoverage = Math.max(1, Number(document.getElementById("reviewerCoverageInput").value) || 1);
  state.assignment.metaReviewerWorkload = Math.max(1, Number(document.getElementById("metaReviewerWorkloadInput").value) || 1);

  if (mode === "demo") {
    if (!state.assignment.info || state.assignment.info.error) {
      alert("Assignment demo data is unavailable from the server.");
      return;
    }
  } else {
    if (!state.assignment.submissions.length) {
      alert("Normal mode requires uploaded submissions.");
      return;
    }
    if (!state.assignment.reviewers.length) {
      alert("Normal mode requires uploaded reviewers.");
      return;
    }
    if (!state.assignment.metaReviewers.length) {
      alert("Normal mode requires uploaded meta-reviewers.");
      return;
    }
  }

  state.assignment.isRunning = true;
  state.assignment.selected = null;
  setRunState(
    "assignment",
    true,
    mode === "demo"
      ? "Computing reviewer and meta-reviewer assignments from the server-side affinity matrices..."
      : "Computing reviewer and meta-reviewer assignments from the uploaded data...",
  );
  renderAssignmentResults();
  try {
    const resp = await apiPost("/assignment/run", {
      mode,
      conference: mode === "demo" ? state.assignment.conference : undefined,
      reviewer_workload: state.assignment.reviewerWorkload,
      reviewer_coverage: state.assignment.reviewerCoverage,
      metareviewer_workload: state.assignment.metaReviewerWorkload,
      submissions: mode === "normal" ? state.assignment.submissions : undefined,
      reviewers: mode === "normal" ? state.assignment.reviewers : undefined,
      metareviewers: mode === "normal" ? state.assignment.metaReviewers : undefined,
      conflicts: mode === "normal" ? [...state.assignment.coi] : undefined,
    });
    state.assignment.result = requireApiResult(resp, "Assignment run");
    refreshAssignmentDerived(state.assignment.result);
  } catch (err) {
    alert(`Assignment backend error: ${err.message}`);
  } finally {
    state.assignment.isRunning = false;
    setRunState("assignment", false);
    renderAssignmentResults();
  }
}

/* ═══════════════════ Rendering ═══════════════════ */

function assignmentSummaryCards() {
  const result = state.assignment.result;
  const info = state.assignment.info;
  if (!result) {
    return `
      <div class="metric"><div class="label">Mode</div><div class="value">${assignmentModeLabel()}</div></div>
      <div class="metric"><div class="label">Papers</div><div class="value">${state.assignment.mode === "demo" ? (info && !info.error ? info.paperCount : "\u2026") : state.assignment.submissions.length}</div></div>
      <div class="metric"><div class="label">Reviewers</div><div class="value">${state.assignment.mode === "demo" ? (info && !info.error ? info.reviewerCount : "\u2026") : state.assignment.reviewers.length}</div></div>
      <div class="metric"><div class="label">Meta-Reviewers</div><div class="value">${state.assignment.mode === "demo" ? (info && !info.error ? info.metaReviewerCount : "\u2026") : state.assignment.metaReviewers.length}</div></div>
      <div class="metric"><div class="label">Status</div><div class="value">${state.assignment.isRunning ? "Running" : "Not Run"}</div></div>
    `;
  }
  return `
    <div class="metric"><div class="label">Reviewer Pairs</div><div class="value">${result.meta.assignedReviewerPairs}/${result.meta.requestedReviewerPairs}</div></div>
    <div class="metric"><div class="label">Meta-Reviewer Pairs</div><div class="value">${result.meta.assignedMetaReviewerPairs}/${result.meta.requestedMetaReviewerPairs}</div></div>
    <div class="metric"><div class="label">Reviewer Shortage</div><div class="value">${result.meta.reviewerShortage}</div></div>
    <div class="metric"><div class="label">Meta Shortage</div><div class="value">${result.meta.metaReviewerShortage}</div></div>
  `;
}

function assignmentCandidateSelectHtml(row, role, slotIndex) {
  const result = state.assignment.result;
  const assignments = role === "reviewer" ? row.reviewers : row.metareviewers;
  const candidates = role === "reviewer" ? row.reviewerCandidates : row.metareviewerCandidates;
  const current = assignments[slotIndex] || null;
  const currentId = current ? current.person.pc_id : "";
  const seen = new Set();
  const merged = [];

  if (current) {
    merged.push({
      pc_id: current.person.pc_id,
      name: current.person.name,
      role: current.person.role,
      score: current.score,
      conflict: false,
      assigned: true,
    });
    seen.add(current.person.pc_id);
  }
  candidates.forEach((cand) => {
    if (!seen.has(cand.pc_id)) {
      merged.push(cand);
      seen.add(cand.pc_id);
    }
  });

  return `
    <select data-assignment-role="${role}" data-assignment-paper="${row.submission.submission_id}" data-assignment-slot="${slotIndex}">
      <option value="">Select ${role === "reviewer" ? "reviewer" : "meta-reviewer"}</option>
      ${merged.map((cand) => {
        const personRow = findAssignmentPersonRow(result, cand.pc_id);
        const workload = assignmentWorkloadForRole(cand.role);
        const tags = [];
        if (cand.conflict) tags.push("conflict");
        if (personRow && personRow.assignedCount >= workload && cand.pc_id !== currentId) tags.push("full");
        const label = `${cand.name} (${cand.pc_id}) \u00b7 ${formatNum(cand.score, 3)}${tags.length ? ` \u00b7 ${tags.join(", ")}` : ""}`;
        return `<option value="${cand.pc_id}" ${cand.pc_id === currentId ? "selected" : ""}>${escapeHtml(label)}</option>`;
      }).join("")}
    </select>
  `;
}

function applyAssignmentEdit(submissionId, role, slotIndex, targetPcId) {
  const result = state.assignment.result;
  const row = findAssignmentPaperRow(result, submissionId);
  if (!result || !row || !targetPcId) {
    alert("Select a valid assignee first.");
    return;
  }

  const isReviewer = role === "reviewer";
  const assignments = isReviewer ? row.reviewers : row.metareviewers;
  const candidates = isReviewer ? row.reviewerCandidates : row.metareviewerCandidates;
  const current = assignments[slotIndex] || null;
  const targetCandidate = candidates.find((cand) => cand.pc_id === targetPcId)
    || (current && current.person.pc_id === targetPcId
      ? { pc_id: current.person.pc_id, name: current.person.name, role: current.person.role, score: current.score, conflict: false }
      : null);

  if (!targetCandidate) {
    alert("The selected assignee is not available in the candidate list.");
    return;
  }
  if (current && current.person.pc_id === targetPcId) {
    alert("This assignment is already in place.");
    return;
  }
  if (targetCandidate.conflict) {
    alert("Assignment change blocked: the selected assignee has a conflict with this paper.");
    return;
  }
  if (assignments.some((entry, idx) => idx !== slotIndex && entry.person.pc_id === targetPcId)) {
    alert("Assignment change blocked: the selected assignee is already assigned to this paper.");
    return;
  }

  const targetPersonRow = findAssignmentPersonRow(result, targetPcId);
  const targetPerson = targetPersonRow
    ? targetPersonRow.person
    : [...(result.reviewers || []), ...(result.metaReviewers || [])].find((person) => person.pc_id === targetPcId);
  if (!targetPerson) {
    alert("Unable to locate the selected assignee.");
    return;
  }
  const workload = assignmentWorkloadForRole(targetPerson.role);
  const currentId = current ? current.person.pc_id : null;
  if (targetPersonRow && targetPersonRow.assignedCount >= workload && targetPcId !== currentId) {
    alert("Assignment change blocked: the selected assignee is already at workload capacity.");
    return;
  }

  const nextAssignment = {
    person: targetPerson,
    score: targetCandidate.score,
    conflict: false,
  };
  if (current) assignments.splice(slotIndex, 1, nextAssignment);
  else assignments.push(nextAssignment);

  assignments.sort((a, b) => b.score - a.score);
  refreshAssignmentDerived(result);
  renderAssignmentResults();
  alert(`Assignment updated successfully for paper ${submissionId}.`);
}

function assignmentCombinedBadges(personRow) {
  const reviewBadges = personRow.assignedReviewPapers.map(
    (item) => `<span class="pill">R: ${item.submission.submission_id}</span>`,
  );
  const metaBadges = personRow.assignedMetaPapers.map(
    (item) => `<span class="pill">M: ${item.submission.submission_id}</span>`,
  );
  return [...reviewBadges, ...metaBadges].join("") || `<span class="badge badge-warn">None</span>`;
}

export function renderAssignmentList() {
  const container = document.getElementById("assignmentListTable");
  const title = document.getElementById("assignmentListTitle");
  const result = state.assignment.result;
  const loadingBanner = state.assignment.isRunning
    ? loadingHtml(
        state.assignment.mode === "demo"
          ? "Optimizing reviewer and meta-reviewer assignment. This may take several seconds on the full matrix."
          : "Optimizing reviewer and meta-reviewer assignment from the uploaded data.",
      )
    : "";

  if (!result) {
    title.textContent = "Result List";
    container.innerHTML = `${loadingBanner}<div class="tiny" style="padding:10px">${
      state.assignment.isRunning
        ? "Waiting for the assignment solver to finish..."
        : state.assignment.mode === "demo"
          ? "Run assignment to generate paper and assignee views."
          : "Upload data and run assignment to generate paper and assignee views."
    }</div>`;
    return;
  }

  if (state.assignment.viewMode === "paper") {
    title.textContent = "Paper View List";
    container.innerHTML = `${loadingBanner}
      <table>
        <thead>
          <tr>
            <th>Paper</th>
            <th>Reviewers</th>
            <th>Meta-Reviewer</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${result.byPaper.map((row) => {
            const selected = state.assignment.selected && state.assignment.selected.type === "paper" && state.assignment.selected.id === row.submission.submission_id;
            return `
              <tr class="clickable ${selected ? "selected" : ""}" data-type="paper" data-id="${row.submission.submission_id}">
                <td><strong>${row.submission.submission_id}</strong><br><span class="tiny">${escapeHtml(row.submission.title)}</span><br><span class="tiny">Authors: ${escapeHtml(authorsLabel(row.submission.authors))}</span></td>
                <td>${row.reviewers.map((entry) => `<span class="pill">${escapeHtml(entry.person.name)}</span>`).join("") || `<span class="badge badge-warn">None</span>`}</td>
                <td>${row.metareviewers.map((entry) => `<span class="pill">${escapeHtml(entry.person.name)}</span>`).join("") || `<span class="badge badge-warn">None</span>`}</td>
                <td class="mono">R ${row.reviewers.length}/${row.requestedReviewerCoverage} \u00b7 M ${row.metareviewers.length}/1</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    `;
  } else {
    title.textContent = "Reviewer / Meta-Reviewer View List";
    container.innerHTML = `${loadingBanner}
      <table>
        <thead>
          <tr>
            <th>Assignee</th>
            <th>Role</th>
            <th>Assigned Papers</th>
            <th>Load</th>
          </tr>
        </thead>
        <tbody>
          ${result.byPerson.map((row) => {
            const selected = state.assignment.selected && state.assignment.selected.type === "person" && state.assignment.selected.id === row.person.pc_id;
            return `
              <tr class="clickable ${selected ? "selected" : ""}" data-type="person" data-id="${row.person.pc_id}">
                <td><strong>${escapeHtml(row.person.name)}</strong><br><span class="tiny">${escapeHtml(row.person.pc_id)}</span></td>
                <td>${escapeHtml(row.person.role)}</td>
                <td>${assignmentCombinedBadges(row)}</td>
                <td class="mono">${row.assignedCount}/${row.workload}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    `;
  }

  /* Event delegation for clickable rows */
  container.addEventListener("click", (e) => {
    const tr = e.target.closest("tr.clickable");
    if (!tr) return;
    state.assignment.selected = { type: tr.dataset.type, id: tr.dataset.id };
    renderAssignmentList();
    renderAssignmentDetail();
  });
}

export function renderAssignmentDetail() {
  const panel = document.getElementById("assignmentDetailPanel");
  const result = state.assignment.result;
  const selected = state.assignment.selected;

  if (!result || !selected) {
    panel.innerHTML = `<div class="tiny">Select a paper or assignee to inspect assignment details and, from paper view, modify the current assignment.</div>`;
    return;
  }

  if (selected.type === "paper") {
    const row = findAssignmentPaperRow(result, selected.id);
    if (!row) {
      panel.innerHTML = `<div class="tiny">Selected paper not found.</div>`;
      return;
    }

    const reviewerSlots = Array.from({ length: row.requestedReviewerCoverage }, (_, slotIndex) => {
      const current = row.reviewers[slotIndex] || null;
      return `
        <div class="paper-move-card">
          <div><strong>Reviewer Slot ${slotIndex + 1}</strong></div>
          <div class="tiny" style="margin-top:4px">${current ? `${escapeHtml(current.person.name)} (${escapeHtml(current.person.pc_id)}) \u00b7 score ${formatNum(current.score, 3)}` : "Unassigned reviewer slot"}</div>
          <div class="paper-move-row">
            <div class="tiny">Replace with</div>
            ${assignmentCandidateSelectHtml(row, "reviewer", slotIndex)}
            <button class="btn-secondary" data-assignment-save="reviewer" data-assignment-paper="${row.submission.submission_id}" data-assignment-slot="${slotIndex}" type="button">${current ? "Replace" : "Assign"}</button>
          </div>
        </div>
      `;
    }).join("");

    const metaSlots = Array.from({ length: 1 }, (_, slotIndex) => {
      const current = row.metareviewers[slotIndex] || null;
      return `
        <div class="paper-move-card">
          <div><strong>Meta-Reviewer</strong></div>
          <div class="tiny" style="margin-top:4px">${current ? `${escapeHtml(current.person.name)} (${escapeHtml(current.person.pc_id)}) \u00b7 score ${formatNum(current.score, 3)}` : "Unassigned meta-reviewer slot"}</div>
          <div class="paper-move-row">
            <div class="tiny">Replace with</div>
            ${assignmentCandidateSelectHtml(row, "metareviewer", slotIndex)}
            <button class="btn-secondary" data-assignment-save="metareviewer" data-assignment-paper="${row.submission.submission_id}" data-assignment-slot="${slotIndex}" type="button">${current ? "Replace" : "Assign"}</button>
          </div>
        </div>
      `;
    }).join("");

    panel.innerHTML = `
      <div class="tiny"><strong>Paper:</strong> ${escapeHtml(row.submission.submission_id)} - ${escapeHtml(row.submission.title)}</div>
      <div class="tiny"><strong>Authors:</strong> ${escapeHtml(authorsLabel(row.submission.authors))}</div>
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Current Reviewer Assignments</strong></div>
      ${row.reviewers.map((entry) => `
        <div class="detail-card" style="margin-top:8px;padding:8px">
          <div class="tiny"><strong>${escapeHtml(entry.person.name)}</strong> (${escapeHtml(entry.person.pc_id)}) \u00b7 reviewer affinity <span class="mono">${formatNum(entry.score, 3)}</span></div>
        </div>
      `).join("") || `<div class="tiny">No reviewers assigned yet.</div>`}
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Current Meta-Reviewer</strong></div>
      ${row.metareviewers.map((entry) => `
        <div class="detail-card" style="margin-top:8px;padding:8px">
          <div class="tiny"><strong>${escapeHtml(entry.person.name)}</strong> (${escapeHtml(entry.person.pc_id)}) \u00b7 meta-reviewer affinity <span class="mono">${formatNum(entry.score, 3)}</span></div>
        </div>
      `).join("") || `<div class="tiny">No meta-reviewer assigned yet.</div>`}
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Modify Reviewer Assignment</strong></div>
      ${reviewerSlots}
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Modify Meta-Reviewer Assignment</strong></div>
      ${metaSlots}
    `;

    /* Event delegation for save buttons inside the detail panel */
    panel.addEventListener("click", (e) => {
      const button = e.target.closest("button[data-assignment-save]");
      if (!button) return;
      const role = button.getAttribute("data-assignment-save");
      const paperId = button.getAttribute("data-assignment-paper");
      const slot = Number(button.getAttribute("data-assignment-slot"));
      const select = panel.querySelector(
        `select[data-assignment-role="${role}"][data-assignment-paper="${paperId}"][data-assignment-slot="${slot}"]`,
      );
      applyAssignmentEdit(paperId, role, slot, select ? select.value : "");
    });
  } else {
    const row = findAssignmentPersonRow(result, selected.id);
    if (!row) {
      panel.innerHTML = `<div class="tiny">Selected assignee not found.</div>`;
      return;
    }
    panel.innerHTML = `
      <div class="tiny"><strong>Assignee:</strong> ${escapeHtml(row.person.name)} (${escapeHtml(row.person.pc_id)})</div>
      <div class="tiny"><strong>Role:</strong> ${escapeHtml(row.person.role)} \u00b7 load <span class="mono">${row.assignedCount}/${row.workload}</span></div>
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Review Assignments</strong></div>
      ${row.assignedReviewPapers.map((item) => `
        <div class="detail-card" style="margin-top:8px;padding:8px">
          <div class="tiny"><strong>${escapeHtml(item.submission.submission_id)}</strong> - ${escapeHtml(item.submission.title)}</div>
          <div class="tiny">Affinity <span class="mono">${formatNum(item.score, 3)}</span></div>
        </div>
      `).join("") || `<div class="tiny">No reviewer assignments.</div>`}
      <div style="margin-top:10px"><strong style="font-size:0.82rem">Meta-Review Assignments</strong></div>
      ${row.assignedMetaPapers.map((item) => `
        <div class="detail-card" style="margin-top:8px;padding:8px">
          <div class="tiny"><strong>${escapeHtml(item.submission.submission_id)}</strong> - ${escapeHtml(item.submission.title)}</div>
          <div class="tiny">Affinity <span class="mono">${formatNum(item.score, 3)}</span></div>
        </div>
      `).join("") || `<div class="tiny">No meta-review assignments.</div>`}
      <div class="tiny" style="margin-top:10px">Switch back to paper view to modify a paper's reviewer or meta-reviewer assignment.</div>
    `;
  }
}

export function buildAssignmentExportObject() {
  const result = state.assignment.result;
  if (!result) return {};
  return {
    task: "paper_assignment",
    parameters: {
      mode: state.assignment.mode,
      reviewer_workload: state.assignment.reviewerWorkload,
      reviewer_coverage: state.assignment.reviewerCoverage,
      metareviewer_workload: state.assignment.metaReviewerWorkload,
    },
    summary: {
      assigned_reviewer_pairs: result.meta.assignedReviewerPairs,
      requested_reviewer_pairs: result.meta.requestedReviewerPairs,
      assigned_metareviewer_pairs: result.meta.assignedMetaReviewerPairs,
      requested_metareviewer_pairs: result.meta.requestedMetaReviewerPairs,
      reviewer_shortage: result.meta.reviewerShortage,
      metareviewer_shortage: result.meta.metaReviewerShortage,
    },
    papers: result.byPaper.map((row) => ({
      paper_id: row.submission.submission_id,
      title: row.submission.title,
      reviewers: row.reviewers.map((entry) => ({
        reviewer_id: entry.person.pc_id,
        name: entry.person.name,
        score: Number(entry.score),
      })),
      metareviewers: row.metareviewers.map((entry) => ({
        metareviewer_id: entry.person.pc_id,
        name: entry.person.name,
        score: Number(entry.score),
      })),
    })),
    assignees: result.byPerson.map((row) => ({
      person_id: row.person.pc_id,
      name: row.person.name,
      role: row.person.role,
      workload: row.workload,
      assigned_count: row.assignedCount,
      review_assignments: row.assignedReviewPapers.map((item) => ({
        paper_id: item.submission.submission_id,
        title: item.submission.title,
        score: Number(item.score),
      })),
      metareview_assignments: row.assignedMetaPapers.map((item) => ({
        paper_id: item.submission.submission_id,
        title: item.submission.title,
        score: Number(item.score),
      })),
    })),
  };
}

export function renderAssignmentResults() {
  const summary = document.getElementById("assignmentSummary");
  const sourceStatus = document.getElementById("assignmentSourceStatus");
  const exportBtn = document.getElementById("exportAssignmentBtn");
  const result = state.assignment.result;

  summary.innerHTML = assignmentSummaryCards();
  if (exportBtn) exportBtn.disabled = state.assignment.isRunning || !result;
  renderAssignmentModeUI();
  renderAssignmentUploadStatus();

  if (!sourceStatus) {
    renderAssignmentList();
    renderAssignmentDetail();
    return;
  }

  if (state.assignment.mode === "demo") {
    if (!state.assignment.info) {
      sourceStatus.innerHTML = `Loading assignment data summary from the server...`;
    } else if (state.assignment.info.error) {
      sourceStatus.innerHTML = `Failed to load assignment data: <span class="mono">${escapeHtml(state.assignment.info.error)}</span>`;
    } else {
      sourceStatus.innerHTML = `
        mode: <span class="mono">demo</span><br>
        conference: <span class="mono">${escapeHtml(state.assignment.info.conference || state.assignment.conference)}</span><br>
        papers: <span class="mono">${state.assignment.info.paperCount}</span><br>
        reviewers: <span class="mono">${state.assignment.info.reviewerCount}</span><br>
        meta-reviewers: <span class="mono">${state.assignment.info.metaReviewerCount}</span><br>
        paper data: <span class="mono">${state.assignment.info.paperDataPath}</span><br>
        reviewer data: <span class="mono">${state.assignment.info.reviewerDataPath}</span><br>
        meta-reviewer data: <span class="mono">${state.assignment.info.metaReviewerDataPath}</span>
      `;
    }
  } else {
    sourceStatus.innerHTML = `
      mode: <span class="mono">normal</span><br>
      uploaded submissions: <span class="mono">${state.assignment.submissions.length}</span><br>
      uploaded reviewers: <span class="mono">${state.assignment.reviewers.length}</span><br>
      uploaded meta-reviewers: <span class="mono">${state.assignment.metaReviewers.length}</span><br>
      uploaded COI pairs: <span class="mono">${state.assignment.coi.size}</span>
    `;
  }

  renderAssignmentList();
  renderAssignmentDetail();
}

/* ═══════════════════ Event setup ═══════════════════ */

/**
 * Wire up all assignment-specific DOM events.
 *
 * NOTE: The original inline onclick handlers have been converted to
 * data-action attributes with event delegation inside renderAssignmentList
 * and renderAssignmentDetail (see those functions above).
 */
export function setupAssignmentEvents() {
  document.getElementById("paperViewBtn").addEventListener("click", () => {
    state.assignment.viewMode = "paper";
    document.getElementById("paperViewBtn").classList.add("is-active");
    document.getElementById("pcViewBtn").classList.remove("is-active");
    renderAssignmentList();
    renderAssignmentDetail();
  });

  document.getElementById("pcViewBtn").addEventListener("click", () => {
    state.assignment.viewMode = "pc";
    document.getElementById("pcViewBtn").classList.add("is-active");
    document.getElementById("paperViewBtn").classList.remove("is-active");
    renderAssignmentList();
    renderAssignmentDetail();
  });

  document.getElementById("assignmentModeSelect").addEventListener("change", (e) => {
    state.assignment.mode = e.target.value === "normal" ? "normal" : "demo";
    resetAssignmentResult();
    renderAssignmentResults();
  });
  document.getElementById("assignmentConferenceSelect").addEventListener("change", (e) => {
    state.assignment.conference = e.target.value;
    resetAssignmentResult();
    void loadAssignmentInfo();
  });

  document.getElementById("runAssignmentBtn").addEventListener("click", runAssignment);
  document.getElementById("exportAssignmentBtn").addEventListener("click", () => {
    if (!state.assignment.result) {
      alert("Run assignment first.");
      return;
    }
    downloadJson("paper_assignment.json", buildAssignmentExportObject());
  });

  /* File upload buttons */
  document.getElementById("uploadAssignmentSubmissionBtn").addEventListener("click", () => {
    document.getElementById("assignmentSubmissionFileInput").click();
  });
  document.getElementById("assignmentSubmissionFileInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    parseJsonFile(file, (payload) => {
      const rows = normalizeSubmissionList(payload);
      if (!rows.length) {
        alert("No valid submissions found in file.");
        return;
      }
      state.assignment.submissions = rows;
      state.assignment.uploadNames.submissions = file.name;
      resetAssignmentResult();
      renderAssignmentResults();
    });
    e.target.value = "";
  });
  document.getElementById("uploadAssignmentReviewerBtn").addEventListener("click", () => {
    document.getElementById("assignmentReviewerFileInput").click();
  });
  document.getElementById("assignmentReviewerFileInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    parseJsonFile(file, (payload) => {
      const rows = normalizePcList(payload);
      if (!rows.length) {
        alert("No valid reviewers found in file.");
        return;
      }
      state.assignment.reviewers = rows.map((row) => ({ ...row, role: "Reviewer" }));
      state.assignment.uploadNames.reviewers = file.name;
      resetAssignmentResult();
      renderAssignmentResults();
    });
    e.target.value = "";
  });
  document.getElementById("uploadAssignmentMetaReviewerBtn").addEventListener("click", () => {
    document.getElementById("assignmentMetaReviewerFileInput").click();
  });
  document.getElementById("assignmentMetaReviewerFileInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    parseJsonFile(file, (payload) => {
      const rows = normalizePcList(payload);
      if (!rows.length) {
        alert("No valid meta-reviewers found in file.");
        return;
      }
      state.assignment.metaReviewers = rows.map((row) => ({ ...row, role: "Meta-Reviewer" }));
      state.assignment.uploadNames.metaReviewers = file.name;
      resetAssignmentResult();
      renderAssignmentResults();
    });
    e.target.value = "";
  });
  document.getElementById("uploadAssignmentCoiBtn").addEventListener("click", () => {
    document.getElementById("assignmentCoiFileInput").click();
  });
  document.getElementById("assignmentCoiFileInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    parseJsonFile(file, (payload) => {
      state.assignment.coi = normalizeCoi(payload);
      state.assignment.uploadNames.coi = file.name;
      resetAssignmentResult();
      renderAssignmentResults();
    });
    e.target.value = "";
  });
}
