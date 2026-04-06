/**
 * poster.js
 *
 * All poster-session organisation functions: loading info, running the solver,
 * rendering the session grid / editor / last-mile panels, session and
 * hard-paper modals, CSV/HTML export, and poster-specific event wiring.
 */

import { state } from "../state.js";
import { API_BASE, apiGet, apiPost, requireApiResult } from "../api.js";
import {
  submissionDist,
  similarity,
  avgDist,
  topTopicEntries,
  byId,
} from "../taxonomy.js";
import {
  escapeHtml,
  formatNum,
  loadingHtml,
  setRunState, updateRunMessage,
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
import { collapseSetupPanel, updateSetupSummary } from "../router.js";
import { onWorkspaceSwitch } from "../workspace.js";
import { showToast } from "../toast.js";

/* ═══════════════════ Save / restore progress ═══════════════════ */

function localStorageKey() {
  return `taxoconf_poster_progress_${state.poster.conference || "default"}`;
}

function autoSavePosterProgress() {
  try {
    const result = state.poster.result;
    if (!result) return;
    localStorage.setItem(localStorageKey(), JSON.stringify(result));
  } catch (_) {}
}

function getLocalSavedProgress() {
  try {
    const raw = localStorage.getItem(localStorageKey());
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

function clearLocalSavedProgress() {
  try { localStorage.removeItem(localStorageKey()); } catch (_) {}
}

function restoreLocalProgress() {
  const saved = getLocalSavedProgress();
  if (!saved) return false;
  state.poster.result = saved;
  renderPosterResults();
  return true;
}

/** Open a modal to save poster progress with a name. */
export function openPosterSaveModal() {
  if (!state.poster.result) { alert("No poster result to save."); return; }
  const modal = document.getElementById("progressModal");
  const title = document.getElementById("progressModalTitle");
  const body = document.getElementById("progressModalBody");
  title.textContent = "Save Poster Session Progress";
  body.innerHTML = `
    <div class="control-group">
      <label class="control-label">Save Name</label>
      <input id="progressSaveNameInput" type="text" value="poster_${new Date().toISOString().slice(0, 10)}" placeholder="Enter a name for this save">
    </div>
    <div class="modal-actions">
      <button class="btn-primary" id="progressSaveConfirmBtn" type="button">Save</button>
    </div>
  `;
  body.querySelector("#progressSaveConfirmBtn").addEventListener("click", async () => {
    const name = body.querySelector("#progressSaveNameInput").value.trim();
    if (!name) return;
    try {
      const resp = await apiPost("/poster/progress", { conference: state.poster.conference, result: state.poster.result, name });
      if (resp.success) showToast("Saved as \\u201c" + (resp.name || name) + "\\u201d.");
      else alert("Failed: " + (resp.error || "Unknown error"));
    } catch (e) { alert("Save failed: " + e.message); }
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  });
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

/** Open a modal to load poster progress from a list of saves. */
export async function openPosterLoadModal() {
  const modal = document.getElementById("progressModal");
  const title = document.getElementById("progressModalTitle");
  const body = document.getElementById("progressModalBody");
  title.textContent = "Load Poster Session Progress";
  body.innerHTML = `<div class="tiny">Loading saved sessions...</div>`;
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
  try {
    const listResp = await apiGet(`/poster/progress/list?conference=${encodeURIComponent(state.poster.conference)}`);
    if (!listResp.success || !listResp.saves || listResp.saves.length === 0) {
      body.innerHTML = `<div class="tiny">No saved progress found for this conference.</div>`;
      return;
    }
    body.innerHTML = `
      <div class="tiny" style="margin-bottom:10px">Select a save to load:</div>
      <div class="progress-save-list">
        ${listResp.saves.map((s) => {
          const date = new Date(s.modified * 1000).toLocaleString();
          const name = s.name.replace(" (legacy)", "");
          return `<button class="progress-save-item" data-save-name="${escapeHtml(name)}" type="button">
            <strong>${escapeHtml(s.name)}</strong>
            <span>${date}</span>
          </button>`;
        }).join("")}
      </div>
    `;
    body.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-save-name]");
      if (!btn) return;
      const name = btn.dataset.saveName;
      try {
        const resp = await apiGet(`/poster/progress?conference=${encodeURIComponent(state.poster.conference)}&name=${encodeURIComponent(name)}`);
        if (resp.success && resp.result) {
          state.poster.result = resp.result;
          autoSavePosterProgress();
          renderPosterResults();
          showToast("Loaded \\u201c" + name + "\\u201d.");
        } else { showToast("Failed to load."); }
      } catch (err) { alert("Load failed: " + err.message); }
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    }, { once: true });
  } catch (e) {
    body.innerHTML = `<div class="tiny" style="color:var(--danger)">Error: ${escapeHtml(e.message)}</div>`;
  }
}

/* ═══════════════════ ID / label helpers ═══════════════════ */

function posterPaperId(paper) {
  return String(paper.id ?? paper.submission_id ?? "");
}

function posterPresentersLabel(paper) {
  if (Array.isArray(paper.presenters) && paper.presenters.length) return paper.presenters.join(", ");
  if (paper.presenter) return String(paper.presenter);
  return "N/A";
}

function posterSessionLabel(sessionId) {
  const tail = String(sessionId || "").split("_").pop();
  return `Session ${tail}`;
}

function posterSessionName(session) {
  return String(session && session.sessionName ? session.sessionName : "").trim() || posterSessionLabel(session.id);
}

function findPosterSession(result, sessionId) {
  return result.sessions.find((session) => session.id === sessionId) || null;
}

function setPosterSessionFields(sessionId, fields) {
  const result = state.poster.result;
  if (!result) return;
  const session = findPosterSession(result, sessionId);
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
  });
  autoSavePosterProgress();
  renderPosterResults();
}

function posterBoardLabel(index, layoutType = state.poster.layoutType, rows = state.poster.rows, cols = state.poster.cols) {
  if (layoutType === "rectangle") {
    return `R${Math.floor(index / cols) + 1}-C${(index % cols) + 1}`;
  }
  return `Board ${index + 1}`;
}

export function posterSessionCapacity(layoutType = state.poster.layoutType, boardCount = state.poster.boardCount, rows = state.poster.rows, cols = state.poster.cols) {
  return layoutType === "rectangle" ? rows * cols : boardCount;
}

/* ═══════════════════ Topic / similarity helpers ═══════════════════ */

function posterPaperDist(paper) {
  if (!paper.topicDist) {
    paper.topicDist = submissionDist({
      title: paper.title || "",
      abstract: paper.abstract || "",
      topic_hints: paper.topic_hints || [],
    });
  }
  return paper.topicDist;
}

function posterPaperSimilarity(left, right) {
  return similarity(posterPaperDist(left), posterPaperDist(right), 4);
}

function sessionTopicNames(papers, distFn, limit = 2) {
  if (!Array.isArray(papers) || !papers.length) return "Empty";
  return topTopicEntries(avgDist(papers.map((paper) => distFn(paper))), limit)
    .map((entry) => byId[entry.id].label)
    .join(" \u00b7 ");
}

/* ═══════════════════ Within-layout ordering ═══════════════════ */

function posterLineInsertionDelta(order, insertPos, paper) {
  if (!order.length) return 0;
  if (insertPos === 0) return posterPaperSimilarity(paper, order[0]);
  if (insertPos === order.length) return posterPaperSimilarity(order[order.length - 1], paper);
  const left = order[insertPos - 1];
  const right = order[insertPos];
  return posterPaperSimilarity(left, paper) + posterPaperSimilarity(paper, right) - posterPaperSimilarity(left, right);
}

function posterCircleInsertionDelta(order, insertPos, paper) {
  if (!order.length) return 0;
  if (order.length === 1) return 2 * posterPaperSimilarity(order[0], paper);
  const left = insertPos > 0 ? order[insertPos - 1] : order[order.length - 1];
  const right = insertPos < order.length ? order[insertPos] : order[0];
  return posterPaperSimilarity(left, paper) + posterPaperSimilarity(paper, right) - posterPaperSimilarity(left, right);
}

function posterBestPair(papers) {
  if (papers.length <= 2) return papers.slice();
  let best = null;
  for (let i = 0; i < papers.length; i += 1) {
    for (let j = i + 1; j < papers.length; j += 1) {
      const score = posterPaperSimilarity(papers[i], papers[j]);
      if (!best || score > best.score) best = { score, left: papers[i], right: papers[j] };
    }
  }
  return [best.left, best.right];
}

function posterGreedyLineOrder(papers) {
  if (papers.length <= 2) return papers.slice();
  const order = posterBestPair(papers);
  const remaining = papers.filter((paper) => !order.includes(paper));
  while (remaining.length) {
    let bestMove = null;
    remaining.forEach((paper) => {
      for (let insertPos = 0; insertPos <= order.length; insertPos += 1) {
        const delta = posterLineInsertionDelta(order, insertPos, paper);
        if (!bestMove || delta > bestMove.delta) {
          bestMove = { paper, insertPos, delta };
        }
      }
    });
    order.splice(bestMove.insertPos, 0, bestMove.paper);
    remaining.splice(remaining.indexOf(bestMove.paper), 1);
  }
  return order;
}

function posterGreedyCircleOrder(papers) {
  if (papers.length <= 2) return papers.slice();
  const order = posterBestPair(papers);
  const remaining = papers.filter((paper) => !order.includes(paper));
  while (remaining.length) {
    let bestMove = null;
    remaining.forEach((paper) => {
      for (let insertPos = 0; insertPos < order.length; insertPos += 1) {
        const delta = posterCircleInsertionDelta(order, insertPos, paper);
        if (!bestMove || delta > bestMove.delta) {
          bestMove = { paper, insertPos, delta };
        }
      }
    });
    order.splice(bestMove.insertPos, 0, bestMove.paper);
    remaining.splice(remaining.indexOf(bestMove.paper), 1);
  }
  return order;
}

function orderPosterSessionPapers(papers, layoutType = state.poster.layoutType) {
  if (!state.poster.optimizeWithinLayout) return papers.slice();
  if (layoutType === "circle") return posterGreedyCircleOrder(papers);
  return posterGreedyLineOrder(papers);
}

/* ═══════════════════ Layout input state ═══════════════════ */

export function posterLayoutInputState() {
  const category = document.getElementById("posterLayoutCategorySelect").value;
  const linearLayout = document.getElementById("posterLinearLayoutSelect").value;
  const lineCirclePanel = document.getElementById("posterLineCircleControls");
  const rectanglePanel = document.getElementById("posterRectangleControls");
  const boardCountInput = document.getElementById("posterBoardCountInput");
  const rowsInput = document.getElementById("posterRowsInput");
  const colsInput = document.getElementById("posterColsInput");
  const note = document.getElementById("posterFloorplanDetailNote");
  const isRect = category === "rectangle";

  state.poster.layoutCategory = category;
  state.poster.linearLayoutType = linearLayout;
  state.poster.layoutType = isRect ? "rectangle" : linearLayout;

  lineCirclePanel.classList.toggle("is-hidden", isRect);
  rectanglePanel.classList.toggle("is-hidden", !isRect);
  boardCountInput.disabled = isRect;
  rowsInput.disabled = !isRect;
  colsInput.disabled = !isRect;
  if (note) {
    note.textContent = state.poster.optimizeWithinLayout
      ? "Floor-plan parameters are used for both visualization and within-session similarity optimization."
      : "Floor-plan parameters are used for visualization and capacity. Within-session adjacency optimization is disabled.";
  }
}

/* ═══════════════════ Prepare result ═══════════════════ */

function preparePosterResult(result) {
  if (!result) return null;
  const paperMap = new Map();
  (result.papers || []).forEach((paper) => {
    paper.presenters = Array.isArray(paper.presenters)
      ? paper.presenters
      : paper.presenter
        ? String(paper.presenter).split(",").map((x) => x.trim()).filter(Boolean)
        : [];
    posterPaperDist(paper);
    paperMap.set(posterPaperId(paper), paper);
  });

  (result.sessions || []).forEach((session) => {
    ensureSessionMetadata(session);
    session.cells = (session.cells || []).map((cell) => {
      if (!cell) return null;
      const canonical = paperMap.get(posterPaperId(cell)) || cell;
      posterPaperDist(canonical);
      return canonical;
    });
    session.papers = session.cells.filter(Boolean);
    session.paperCount = session.papers.length;
    session.boardAssignments = session.papers.map((paper) => {
      const placement = result.placements[posterPaperId(paper)];
      return {
        cellIndex: placement ? placement.cellIndex : -1,
        boardLabel: placement ? posterBoardLabel(placement.cellIndex, result.layoutType, result.rows, result.cols) : "N/A",
        paper,
      };
    });
  });
  return result;
}

function posterAdjacencyEdges(result) {
  const edges = [];
  if (result.layoutType === "line") {
    for (let idx = 0; idx < Math.max(0, result.sessionCapacity - 1); idx += 1) {
      edges.push([idx, idx + 1, 1]);
    }
    return edges;
  }
  if (result.layoutType === "circle") {
    for (let idx = 0; idx < Math.max(0, result.sessionCapacity - 1); idx += 1) {
      edges.push([idx, idx + 1, 1]);
    }
    if (result.sessionCapacity > 2) edges.push([result.sessionCapacity - 1, 0, 1]);
    return edges;
  }
  for (let row = 0; row < result.rows; row += 1) {
    for (let col = 0; col < Math.max(0, result.cols - 1); col += 1) {
      const left = row * result.cols + col;
      edges.push([left, left + 1, 1]);
    }
  }
  for (let row = 0; row < Math.max(0, result.rows - 1); row += 1) {
    for (let col = 0; col < result.cols; col += 1) {
      const top = row * result.cols + col;
      edges.push([top, top + result.cols, 0.25]);
    }
  }
  return edges;
}

function computePosterSessionScores(session, result) {
  const papers = session.papers || [];
  let total = 0;
  let pairs = 0;
  for (let i = 0; i < papers.length; i += 1) {
    for (let j = i + 1; j < papers.length; j += 1) {
      total += posterPaperSimilarity(papers[i], papers[j]);
      pairs += 1;
    }
  }
  session.avgSimilarity = pairs ? total / pairs : 0;
  session.adjacencyScore = posterAdjacencyEdges(result).reduce((acc, [left, right, weight]) => {
    const leftPaper = session.cells[left];
    const rightPaper = session.cells[right];
    if (!leftPaper || !rightPaper) return acc;
    return acc + weight * posterPaperSimilarity(leftPaper, rightPaper);
  }, 0);
}

/* ═══════════════════ Load info ═══════════════════ */

export async function loadPosterDemoInfo() {
  try {
    const resp = await apiGet(`/poster/info?conference=${encodeURIComponent(state.poster.conference)}`);
    state.poster.demoInfo = requireApiResult(resp, "Poster info");
    state.poster.availableConferences = state.poster.demoInfo.availableConferences || [];
    state.poster.conference = state.poster.demoInfo.conference || state.poster.conference;

    const sp = state.poster.demoInfo.suggested_params;
    if (sp) {
      state.poster.sessionCount = sp.session_count;
      state.poster.rows = sp.rows;
      state.poster.cols = sp.cols;
      state.poster.boardCount = sp.board_count;
      document.getElementById("posterSessionCountInput").value = sp.session_count;
      document.getElementById("posterRowsInput").value = sp.rows;
      document.getElementById("posterColsInput").value = sp.cols;
      document.getElementById("posterBoardCountInput").value = sp.board_count;
    }
  } catch (err) {
    state.poster.demoInfo = { error: err.message };
  }
  renderPosterCapacityNotice();
  renderPosterResults();
}

/* ═══════════════════ Capacity notice ═══════════════════ */

export function renderPosterCapacityNotice() {
  const sourceStatus = document.getElementById("posterSourceStatus");
  const note = document.getElementById("posterCapacityNotice");
  if (!sourceStatus || !note) return;
  renderConferenceSelect("posterConferenceSelect", state.poster.conference, state.poster.availableConferences);

  if (!state.poster.demoInfo) {
    sourceStatus.innerHTML = `Loading server-side presentation data...`;
    note.classList.remove("warn");
    note.innerHTML = `Checking capacity against the demo paper set...`;
    return;
  }

  if (state.poster.demoInfo.error) {
    sourceStatus.innerHTML = `Failed to load demo data: <span class="mono">${state.poster.demoInfo.error}</span>`;
    note.classList.add("warn");
    note.innerHTML = `Backend demo data is unavailable, so poster organization cannot run.`;
    return;
  }

  const paperCount = Number(state.poster.demoInfo.paperCount || 0);
  const layoutType = state.poster.layoutType;
  const sessionCap = posterSessionCapacity(layoutType, state.poster.boardCount, state.poster.rows, state.poster.cols);
  const totalCapacity = sessionCap * state.poster.sessionCount;

  sourceStatus.innerHTML = `
    Conference: <span class="mono">${escapeHtml(state.poster.demoInfo.conference || state.poster.conference)}</span><br>
    Papers: <span class="mono">${paperCount}</span><br>
    Unique authors: <span class="mono">${state.poster.demoInfo.presenterCount}</span><br>
    Authors with multiple papers: <span class="mono">${state.poster.demoInfo.multiPresenterCount}</span>
  `;

  const issues = [];
  if (paperCount > totalCapacity) {
    issues.push(`Current poster capacity is too small: ${paperCount} papers but only ${totalCapacity} board slots are available.`);
  }
  if (state.poster.preventSamePresenter && Number(state.poster.demoInfo.maxPapersPerPresenter || 0) > state.poster.sessionCount) {
    issues.push(`Presenter conflict protection is infeasible: at least one presenter has ${state.poster.demoInfo.maxPapersPerPresenter} papers but there are only ${state.poster.sessionCount} sessions.`);
  }

  if (issues.length) {
    note.classList.add("warn");
    note.innerHTML = issues.join("<br>");
    return;
  }

  note.classList.remove("warn");
  note.innerHTML = `
    Floor plan: <span class="mono">${layoutType}</span><br>
    Boards per session: <span class="mono">${sessionCap}</span><br>
    Session count: <span class="mono">${state.poster.sessionCount}</span><br>
    Total capacity: <span class="mono">${totalCapacity}</span> for <span class="mono">${paperCount}</span> papers<br>
    Within-floor-plan similarity: <span class="mono">${state.poster.optimizeWithinLayout ? "enabled" : "disabled"}</span>
  `;
}

/* ═══════════════════ Run ═══════════════════ */

export async function runPosterOrganization() {
  state.poster.layoutCategory = document.getElementById("posterLayoutCategorySelect").value;
  state.poster.linearLayoutType = document.getElementById("posterLinearLayoutSelect").value;
  state.poster.layoutType = state.poster.layoutCategory === "rectangle" ? "rectangle" : state.poster.linearLayoutType;
  state.poster.boardCount = Math.max(1, Number(document.getElementById("posterBoardCountInput").value) || 1);
  state.poster.rows = Math.max(1, Number(document.getElementById("posterRowsInput").value) || 1);
  state.poster.cols = Math.max(1, Number(document.getElementById("posterColsInput").value) || 1);
  state.poster.sessionCount = Math.max(1, Number(document.getElementById("posterSessionCountInput").value) || 1);
  state.poster.preventSamePresenter = Boolean(document.getElementById("posterPresenterConflictInput").checked);
  state.poster.optimizeWithinLayout = Boolean(document.getElementById("posterWithinFloorplanInput").checked);
  posterLayoutInputState();
  renderPosterCapacityNotice();

  if (!state.poster.demoInfo || state.poster.demoInfo.error) {
    alert("Poster demo data is unavailable from the server.");
    return;
  }

  const paperCount = Number(state.poster.demoInfo.paperCount || 0);
  const sessionCap = posterSessionCapacity();
  if (paperCount > state.poster.sessionCount * sessionCap) {
    alert("The current poster session configuration cannot hold all papers. Increase the session count or board capacity.");
    return;
  }
  if (state.poster.preventSamePresenter && Number(state.poster.demoInfo.maxPapersPerPresenter || 0) > state.poster.sessionCount) {
    alert("The presenter conflict option is infeasible for the current session count. Increase the number of sessions or disable the constraint.");
    return;
  }

  state.poster.isRunning = true;
  state.poster.activeSessionId = null;
  state.poster.activeHardPaperId = null;
  setRunState("poster", true, "Preparing...");
  renderPosterResults();

  /* Progress ticker */
  const progressSteps = [
    { delay: 0, msg: "Step 1/8: Building paper similarity matrix..." },
    { delay: 5000, msg: "Step 2/8: Constructing topic taxonomy via LLM..." },
    { delay: 20000, msg: "Step 3/8: Forming poster sessions from taxonomy..." },
    { delay: 35000, msg: "Step 4/8: Scheduling sessions into time slots..." },
    { delay: 45000, msg: "Step 5/8: Optimizing board layout for topical proximity..." },
    { delay: 60000, msg: "Step 6/8: Generating session names (bottom-up cascade)..." },
    { delay: 80000, msg: "Step 7/8: Normalizing session names (global consistency check)..." },
    { delay: 95000, msg: "Step 8/8: Reviewing sessions for misplaced papers..." },
    { delay: 140000, msg: "Still working... large conferences may take a few minutes." },
  ];
  const progressTimers = progressSteps.map(s =>
    setTimeout(() => updateRunMessage("poster", s.msg), s.delay)
  );

  try {
    const useAbstracts = document.getElementById("posterUseAbstractsInput")?.checked ?? true;
    const resp = await apiPost("/poster/run", {
      conference: state.poster.conference,
      layout_type: state.poster.layoutType,
      board_count: state.poster.boardCount,
      rows: state.poster.rows,
      cols: state.poster.cols,
      session_count: state.poster.sessionCount,
      prevent_same_presenter: state.poster.preventSamePresenter,
      optimize_within_layout: state.poster.optimizeWithinLayout,
      use_abstracts: useAbstracts,
    });
    state.poster.result = preparePosterResult(requireApiResult(resp, "Poster organization"));
    state.poster.optimizeWithinLayout = Boolean(state.poster.result && state.poster.result.optimizeWithinLayout);
    state.poster.activeSessionId = null;
    state.poster.activeHardPaperId = null;
    /* Auto-collapse setup panel + sidebar, show summary */
    const r = state.poster.result;
    const sessionCount = r.sessions ? r.sessions.length : 0;
    const totalPapers = r.papers ? r.papers.length : r.sessions ? r.sessions.reduce((s, sess) => s + (sess.papers ? sess.papers.length : 0), 0) : 0;
    updateSetupSummary("posterSummaryChip",
      `${state.poster.demoInfo?.conference || state.poster.conference} \u00b7 ${totalPapers} papers \u00b7 ${sessionCount} sessions \u00b7 ${state.poster.layoutType} layout`);
    collapseSetupPanel("posterSetupPanel");
    document.querySelector(".app")?.classList.add("sidebar-collapsed");
  } catch (err) {
    alert(`Poster organization backend error: ${err.message}`);
  } finally {
    progressTimers.forEach(t => clearTimeout(t));
    state.poster.isRunning = false;
    setRunState("poster", false);
    renderPosterResults();
  }
}

/* ═══════════════════ Move / conflict helpers ═══════════════════ */

function posterSessionPresenterConflict(session, paper, ignorePaperId = null) {
  if (!state.poster.preventSamePresenter) return null;
  const presenters = Array.isArray(paper.presenters) ? paper.presenters : [];
  if (!presenters.length) return null;
  for (const existing of session.papers) {
    if (posterPaperId(existing) === ignorePaperId) continue;
    const otherPresenters = Array.isArray(existing.presenters) ? existing.presenters : [];
    const conflict = presenters.find((name) => otherPresenters.includes(name));
    if (conflict) return conflict;
  }
  return null;
}

function reflowPosterSession(session) {
  const result = state.poster.result;
  if (!result || !session) return;
  const papers = session.papers.slice();
  const ordered = orderPosterSessionPapers(papers, result.layoutType);
  session.cells = Array.from({ length: result.sessionCapacity }, (_, idx) => ordered[idx] || null);
  session.papers = ordered;
  session.paperCount = ordered.length;
  session.boardAssignments = ordered.map((paper, idx) => ({
    cellIndex: idx,
    boardLabel: posterBoardLabel(idx, result.layoutType, result.rows, result.cols),
    paper,
  }));
  ordered.forEach((paper, idx) => {
    result.placements[posterPaperId(paper)] = { sessionId: session.id, cellIndex: idx };
  });
  computePosterSessionScores(session, result);
}

function movePosterPaper(paperId, targetSessionId) {
  const result = state.poster.result;
  if (!result) return;
  const paper = result.papers.find((row) => posterPaperId(row) === String(paperId));
  if (!paper) return;
  const sourcePlacement = result.placements[String(paperId)];
  if (!sourcePlacement || !targetSessionId) {
    alert("Select a valid target session.");
    return;
  }
  if (sourcePlacement.sessionId === targetSessionId) {
    alert("This paper is already assigned to the selected session.");
    return;
  }

  const source = findPosterSession(result, sourcePlacement.sessionId);
  const target = findPosterSession(result, targetSessionId);
  if (!source || !target) return;
  if (target.papers.length >= result.sessionCapacity) {
    alert(`${posterSessionLabel(target.id)} is already full.`);
    return;
  }
  const conflictName = posterSessionPresenterConflict(target, paper);
  if (conflictName) {
    alert(`Move failed: presenter conflict for ${conflictName} in ${posterSessionLabel(target.id)}.`);
    return;
  }

  source.papers = source.papers.filter((row) => posterPaperId(row) !== String(paperId));
  source.cells = source.cells.map((cell) => (cell && posterPaperId(cell) === String(paperId) ? null : cell));
  target.papers = target.papers.concat([paper]);
  result.placements[String(paperId)] = { sessionId: target.id, cellIndex: 0 };
  result.hardPapers = (result.hardPapers || []).filter((row) => String(row.paper_id) !== String(paperId));
  reflowPosterSession(source);
  reflowPosterSession(target);
  state.poster.activeSessionId = target.id;
  state.poster.activeHardPaperId = null;
  renderPosterResults();
  alert(`Move successful: paper ${paperId} moved to ${posterSessionLabel(target.id)}.`);
}

/* ═══════════════════ Board rendering ═══════════════════ */

function posterCircleStyle(index, total) {
  const angle = (-Math.PI / 2) + ((2 * Math.PI * index) / Math.max(1, total));
  const radius = total <= 6 ? 26 : total <= 10 ? 33 : 37;
  const x = 50 + radius * Math.cos(angle);
  const y = 50 + radius * Math.sin(angle);
  return `left:${x}%;top:${y}%`;
}

function renderPosterBoardButton(sessionId, paper, cellIndex, layoutType, totalCells, rows, cols, showTitles = false) {
  const label = posterBoardLabel(cellIndex, layoutType, rows, cols);
  const body = paper
    ? `<strong>${posterPaperId(paper)}</strong>${showTitles ? `<span class="tiny">${escapeHtml(paper.title || "")}</span>` : ""}<span class="tiny">${label}</span>`
    : `<strong>${label}</strong><span class="tiny">(empty)</span>`;
  const cls = `poster-board${paper ? "" : " is-empty"}${layoutType === "circle" ? " circle-board" : ""}`;
  const style = layoutType === "circle" ? ` style="${posterCircleStyle(cellIndex, totalCells)}"` : "";
  return `<button class="${cls}" data-action="open-poster-session" data-session-id="${sessionId}" type="button"${style}>${body}</button>`;
}

function renderPosterLayout(session, showTitles = false) {
  const result = state.poster.result;
  if (!result) return "";
  const totalCells = result.sessionCapacity;
  if (result.layoutType === "circle") {
    return `
      <div class="poster-layout poster-layout-circle">
        ${Array.from({ length: totalCells }, (_, idx) => renderPosterBoardButton(session.id, session.cells[idx], idx, result.layoutType, totalCells, result.rows, result.cols, showTitles)).join("")}
      </div>
    `;
  }
  const columns = result.layoutType === "rectangle" ? result.cols : result.sessionCapacity;
  const cls = result.layoutType === "rectangle" ? "poster-layout poster-layout-rectangle" : "poster-layout poster-layout-line";
  return `
    <div class="${cls}" style="grid-template-columns: repeat(${columns}, minmax(72px, 1fr));">
      ${Array.from({ length: totalCells }, (_, idx) => renderPosterBoardButton(session.id, session.cells[idx], idx, result.layoutType, totalCells, result.rows, result.cols, showTitles)).join("")}
    </div>
  `;
}

function findPosterHardPaper(result, paperId) {
  return ((result && result.hardPapers) || []).find((row) => String(row.paper_id) === String(paperId)) || null;
}

/* ═══════════════════ Session modal ═══════════════════ */

export function renderPosterSessionModal() {
  const modal = document.getElementById("posterSessionModal");
  const title = document.getElementById("posterSessionModalTitle");
  const body = document.getElementById("posterSessionModalBody");
  const result = state.poster.result;
  const sessionId = state.poster.activeSessionId;

  if (!result || !sessionId) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const session = findPosterSession(result, sessionId);
  if (!session) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  ensureSessionMetadata(session);
  title.textContent = `${posterSessionName(session)} \u00b7 ${result.layoutType}`;
  body.innerHTML = `
    <div class="tiny">
      Papers in this session: <span class="mono">${session.papers.length}</span> / <span class="mono">${result.sessionCapacity}</span><br>
      Presenter conflict prevention: <span class="mono">${result.preventSamePresenter ? "enabled" : "disabled"}</span><br>
      Move a paper to another session; board positions are ${result.optimizeWithinLayout ? "re-optimized automatically" : "kept in simple sequential order"} inside both sessions.
    </div>
    <div class="paper-move-card">
      <div><strong>Session Metadata</strong></div>
      <div class="tiny" style="margin-top:4px">Edit the generated session title, scheduling fields, location, description, and speaker information used by the export.</div>
      <div class="tiny" style="margin-top:4px">Edit the session title, chair, scheduling, and location. Time and date changes apply to this session.</div>
      <div class="modal-field-grid">
        <div class="modal-field modal-field-span">
          <label>Session Name</label>
          <input data-poster-session-name-input="${session.id}" type="text" value="${escapeHtml(session.sessionName || "")}" placeholder="Concise academic session name">
        </div>
        <div class="modal-field">
          <label>Session Chair</label>
          <input data-poster-session-chair-input="${session.id}" type="text" value="${escapeHtml(session.sessionChair || "")}" placeholder="Leave blank or assign manually">
        </div>
        <div class="modal-field">
          <label>Track Label</label>
          <input data-poster-session-track-input="${session.id}" type="text" value="${escapeHtml(session.trackLabel || "")}" placeholder="Optional track label">
        </div>
        <div class="modal-field">
          <label>Date</label>
          <input data-poster-session-date-input="${session.id}" type="date" value="${escapeHtml(session.sessionDate || "")}">
        </div>
        <div class="modal-field">
          <label>Start Time</label>
          <input data-poster-session-start-input="${session.id}" type="time" value="${escapeHtml(session.startTime || "")}">
        </div>
        <div class="modal-field">
          <label>End Time</label>
          <input data-poster-session-end-input="${session.id}" type="time" value="${escapeHtml(session.endTime || "")}">
        </div>
        <div class="modal-field">
          <label>Room / Location</label>
          <input data-poster-session-location-input="${session.id}" type="text" value="${escapeHtml(session.location || "")}" placeholder="Optional room or venue">
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-secondary" data-action="save-poster-session" data-session-id="${session.id}" type="button">Save Session Metadata</button>
      </div>
    </div>
    <div style="margin-top:10px">${renderPosterLayout(session, true)}</div>
    <div class="modal-section">
      <div><strong>Presentations</strong></div>
      ${session.papers.map((paper) => {
        const place = result.placements[posterPaperId(paper)];
        return `
          <div class="paper-move-card">
            <div><strong>${escapeHtml(posterPaperId(paper))}</strong> - ${escapeHtml(paper.title || "")}</div>
            <div class="tiny" style="margin-top:4px">Authors: ${escapeHtml(paperAuthorsOrPresentersLabel(paper) || "Not set")}</div>
            <div class="tiny">Current board: ${place ? escapeHtml(posterBoardLabel(place.cellIndex, result.layoutType, result.rows, result.cols)) : "N/A"}</div>
            <div class="paper-move-row">
              <div class="tiny">Target session</div>
              <select data-poster-move-select="${escapeHtml(posterPaperId(paper))}">
                <option value="">Select target session</option>
                ${result.sessions
                  .filter((candidate) => candidate.id !== session.id)
                  .map((candidate) => `<option value="${candidate.id}">${escapeHtml(posterSessionName(candidate))} (${escapeHtml(posterSessionLabel(candidate.id))})</option>`)
                  .join("")}
              </select>
              <button class="btn-secondary" data-action="move-poster-paper" data-paper-id="${escapeHtml(posterPaperId(paper))}" type="button">Move</button>
            </div>
          </div>
        `;
      }).join("") || `<div class="tiny" style="margin-top:8px">No papers in this session.</div>`}
    </div>
  `;

  /* Event delegation — replace previous listener to avoid stacking */
  if (body._posterSessionHandler) body.removeEventListener("click", body._posterSessionHandler);
  body._posterSessionHandler = (e) => {
    const openBtn = e.target.closest("button[data-action='open-poster-session']");
    if (openBtn) {
      openPosterSessionModal(openBtn.getAttribute("data-session-id"));
      return;
    }

    const moveBtn = e.target.closest("button[data-action='move-poster-paper']");
    if (moveBtn) {
      const pid = moveBtn.getAttribute("data-paper-id");
      const select = body.querySelector(`select[data-poster-move-select="${pid}"]`);
      const targetSessionId = select ? select.value : "";
      if (!targetSessionId) {
        alert("Select a target session first.");
        return;
      }
      movePosterPaper(pid, targetSessionId);
      return;
    }

    const saveBtn = e.target.closest("button[data-action='save-poster-session']");
    if (saveBtn) {
      const sid = saveBtn.getAttribute("data-session-id");
      setPosterSessionFields(sid, {
        sessionName: body.querySelector(`input[data-poster-session-name-input="${sid}"]`)?.value || "",
        sessionChair: body.querySelector(`input[data-poster-session-chair-input="${sid}"]`)?.value || "",
        sessionDate: body.querySelector(`input[data-poster-session-date-input="${sid}"]`)?.value || "",
        trackLabel: body.querySelector(`input[data-poster-session-track-input="${sid}"]`)?.value || "",
        startTime: body.querySelector(`input[data-poster-session-start-input="${sid}"]`)?.value || "",
        endTime: body.querySelector(`input[data-poster-session-end-input="${sid}"]`)?.value || "",
        location: body.querySelector(`input[data-poster-session-location-input="${sid}"]`)?.value || "",
      });
    }
  };
  body.addEventListener("click", body._posterSessionHandler);

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function openPosterSessionModal(sessionId) {
  state.poster.activeSessionId = sessionId;
  renderPosterSessionModal();
}

function closePosterSessionModal() {
  state.poster.activeSessionId = null;
  renderPosterSessionModal();
}

/* ═══════════════════ Hard-paper modal ═══════════════════ */

export function renderPosterHardPaperModal() {
  const modal = document.getElementById("posterHardPaperModal");
  const title = document.getElementById("posterHardPaperModalTitle");
  const body = document.getElementById("posterHardPaperModalBody");
  const result = state.poster.result;
  const paperId = state.poster.activeHardPaperId;

  if (!result || !paperId) {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const row = findPosterHardPaper(result, paperId);
  if (!row) {
    state.poster.activeHardPaperId = null;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
    return;
  }

  const alternatives = (row.alternative_sessions || []).length
    ? row.alternative_sessions
    : result.sessions
        .filter((session) => session.id !== row.current_session_id)
        .map((session) => ({ session_id: session.id, session_name: posterSessionName(session) }));

  title.textContent = `Last-Mile: ${row.paper_id}`;
  body.innerHTML = `
    <div class="tiny">
      This paper was flagged as hard to place. Inspect the explanation and apply a last-mile move only if it improves the poster arrangement.
    </div>
    <div class="paper-move-card">
      <div><strong>${escapeHtml(row.paper_id)}</strong> - ${escapeHtml(row.title || "")}</div>
      <div class="tiny" style="margin-top:4px">Current session: ${escapeHtml(row.current_session_name || row.current_session_id || "N/A")}</div>
      <div class="tiny">Reason: ${escapeHtml(row.difficultyReason || "Low assignment confidence.")}</div>
      <div class="tiny">Suggested action: ${escapeHtml(row.suggestedAction || "Review manually.")}</div>
      <div class="paper-move-row">
        <div class="tiny">Target session</div>
        <select data-poster-hard-paper-select="${escapeHtml(row.paper_id)}">
          <option value="">Keep current assignment</option>
          ${alternatives.map((alt) => `<option value="${alt.session_id}">${escapeHtml(alt.session_name || alt.session_id)}</option>`).join("")}
        </select>
        <button class="btn-secondary" data-action="apply-poster-hard-paper" data-paper-id="${escapeHtml(row.paper_id)}" type="button">Apply</button>
      </div>
      <div class="modal-actions">
        <button class="btn-muted" data-action="open-poster-hard-paper-session" data-session-id="${escapeHtml(row.current_session_id || "")}" type="button">Open Current Session</button>
      </div>
    </div>
  `;

  /* Event delegation — replace previous listener to avoid stacking */
  if (body._posterHardPaperHandler) body.removeEventListener("click", body._posterHardPaperHandler);
  body._posterHardPaperHandler = (e) => {
    const applyBtn = e.target.closest("button[data-action='apply-poster-hard-paper']");
    if (applyBtn) {
      const currentPaperId = applyBtn.getAttribute("data-paper-id");
      const select = body.querySelector(`select[data-poster-hard-paper-select="${currentPaperId}"]`);
      const targetSessionId = select ? select.value : "";
      if (!targetSessionId) {
        alert("Select a target session if you want to change this assignment.");
        return;
      }
      movePosterPaper(currentPaperId, targetSessionId);
      return;
    }

    const sessionBtn = e.target.closest("button[data-action='open-poster-hard-paper-session']");
    if (sessionBtn) {
      const sid = sessionBtn.getAttribute("data-session-id");
      if (!sid) return;
      closePosterHardPaperModal();
      openPosterSessionModal(sid);
    }
  };
  body.addEventListener("click", body._posterHardPaperHandler);

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function openPosterHardPaperModal(paperId) {
  state.poster.activeHardPaperId = paperId;
  renderPosterHardPaperModal();
}

function closePosterHardPaperModal() {
  state.poster.activeHardPaperId = null;
  renderPosterHardPaperModal();
}

/* ═══════════════════ Render results ═══════════════════ */

export function renderPosterResults() {
  const summary = document.getElementById("posterSummary");
  const gridPanel = document.getElementById("posterGridPanel");
  const editorPanel = document.getElementById("posterEditorPanel");
  const lastMilePanel = document.getElementById("posterLastMilePanel");
  const exportBtn = document.getElementById("exportPosterBtn");
  const result = state.poster.result;
  const loadingBanner = "";  /* Progress shown in toolbar spinner */
  posterLayoutInputState();
  renderPosterCapacityNotice();
  if (exportBtn) exportBtn.disabled = state.poster.isRunning || !result;

  if (!result) {
    const paperCount = state.poster.demoInfo && !state.poster.demoInfo.error ? state.poster.demoInfo.paperCount : "\u2026";
    summary.innerHTML = `
      <div class="metric"><div class="label">Papers</div><div class="value">${paperCount}</div></div>
      <div class="metric"><div class="label">Layout</div><div class="value">${state.poster.layoutType}</div></div>
      <div class="metric"><div class="label">Sessions</div><div class="value">${state.poster.sessionCount}</div></div>
      <div class="metric"><div class="label">Boards / Session</div><div class="value">${posterSessionCapacity()}</div></div>
    `;
    gridPanel.innerHTML = `${loadingBanner}<div class="tiny">${state.poster.isRunning ? "Waiting for the poster organizer to finish..." : "Run poster organization to generate the session floor-plan view."}</div>`;
    editorPanel.innerHTML = `<div class="tiny">${state.poster.isRunning ? "Please wait. The poster result panel will refresh automatically when the run finishes." : "After the run, click any poster board or session card to inspect a session, edit session metadata, and move papers."}</div>`;
    if (lastMilePanel) {
      lastMilePanel.innerHTML = `<div class="tiny">${state.poster.isRunning ? "Hard-to-assign papers will be analyzed after the poster schedule is generated." : "The last-mile modification panel will list the papers the system considers hard to place."}</div>`;
    }
    renderPosterSessionModal();
    renderPosterHardPaperModal();
    return;
  }

  summary.innerHTML = `
    <div class="metric"><div class="label">Papers</div><div class="value">${result.papers.length}</div></div>
    <div class="metric"><div class="label">Layout</div><div class="value">${result.layoutType}</div></div>
    <div class="metric"><div class="label">Sessions</div><div class="value">${result.sessions.length}</div></div>
    <div class="metric"><div class="label">Hard Papers</div><div class="value">${(result.hardPapers || []).length}</div></div>
  `;

  gridPanel.innerHTML = `${loadingBanner}
    <div class="poster-grid-shell">
      <div class="poster-session-grid">
        ${result.sessions.map((session) => {
          const metaText = [
            `${posterSessionLabel(session.id)} \u00b7 ${session.papers.length} papers`,
            sessionTimeLabel(session) ? sessionTimeLabel(session) : "",
            session.location ? `Location: ${session.location}` : "",
          ].filter(Boolean).join(" \u00b7 ");
          const detailList = state.poster.detailMode === "detailed"
            ? `<div class="tiny" style="padding:0 12px 12px">${session.papers.slice(0, 3).map((paper) => `${escapeHtml(posterPaperId(paper))}: ${escapeHtml(paper.title || "")}`).join("<br>")}</div>`
            : "";
          return `
            <div class="poster-session-card">
              <div class="poster-session-head">
                <div>
                  <h3>${escapeHtml(posterSessionName(session))}</h3>
                  <div class="tiny">${escapeHtml(metaText)}</div>
                </div>
                <span class="badge ${session.papers.length >= result.sessionCapacity ? "badge-warn" : "badge-ok"}">${session.papers.length}/${result.sessionCapacity}</span>
              </div>
              <div class="poster-layout-shell">${renderPosterLayout(session, state.poster.detailMode === "detailed")}</div>
              ${detailList}
              <div class="poster-legend">
                <div class="tiny">Adjacency score: <span class="mono">${formatNum(session.adjacencyScore || 0, 3)}</span></div>
                <button class="btn-muted" data-action="open-poster-session" data-session-id="${session.id}" type="button">Open Session</button>
              </div>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;

  editorPanel.innerHTML = `
    <h3>Manual Modification</h3>
    <div class="tiny">
      Click any session or board to open the session detail window. Moving a paper to another session checks the optional presenter constraint and then ${result.optimizeWithinLayout ? "re-optimizes board positions inside both affected sessions" : "updates the target and source sessions without adjacency optimization"}.
      The schedule view switcher toggles between concise cards and a detailed preview with paper titles.
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
          <button class="last-mile-tile" data-action="open-poster-hard-paper" data-paper-id="${escapeHtml(row.paper_id)}" type="button">
            <strong>${escapeHtml(row.paper_id)}</strong>
            <div class="tiny">Current: ${escapeHtml(row.current_session_name || row.current_session_id || "N/A")}</div>
            <div class="tiny">Alternatives: ${escapeHtml(String((row.alternative_sessions || []).length || 0))}</div>
            ${state.poster.detailMode === "detailed" ? `<div class="tiny">${escapeHtml(row.title || "")}</div>` : ""}
            ${state.poster.detailMode === "detailed" ? `<div class="tiny">${escapeHtml(row.suggestedAction || "Review manually.")}</div>` : ""}
          </button>
        `).join("") || `<div class="tiny">No hard-to-assign poster papers were flagged for last-mile modification.</div>`}
      </div>
    `;
    lastMilePanel.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-action='open-poster-hard-paper']");
      if (btn) openPosterHardPaperModal(btn.getAttribute("data-paper-id"));
    });
  }

  gridPanel.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action='open-poster-session']");
    if (btn) openPosterSessionModal(btn.getAttribute("data-session-id"));
  });

  renderPosterSessionModal();
  renderPosterHardPaperModal();
}

/* ═══════════════════ Export ═══════════════════ */

function posterSessionAnchorId(session) {
  return `poster-session-${String(session.id || "").replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
}

export function buildPosterExportHtml() {
  const result = state.poster.result;
  if (!result) return "";
  const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(result.sessions.length))));
  const rows = [];
  for (let idx = 0; idx < result.sessions.length; idx += columns) {
    const chunk = result.sessions.slice(idx, idx + columns);
    rows.push(`
      <tr>
        ${chunk.map((session) => `
          <td>
            <a class="schedule-link" href="#${posterSessionAnchorId(session)}">
              <strong>${escapeHtml(posterSessionName(session))}</strong>
              <span>${escapeHtml(posterSessionLabel(session.id))} \u00b7 ${session.papers.length} papers</span>
            </a>
          </td>
        `).join("")}
        ${Array.from({ length: Math.max(0, columns - chunk.length) }, () => "<td></td>").join("")}
      </tr>
    `);
  }
  const sessionAnchors = result.sessions.map(s => posterSessionAnchorId(s));
  const sections = result.sessions.map((session, sIdx) => {
    const prevAnchor = sIdx > 0 ? sessionAnchors[sIdx - 1] : null;
    const nextAnchor = sIdx < result.sessions.length - 1 ? sessionAnchors[sIdx + 1] : null;
    const navLinks = [
      `<a href="#top">\u2191 Overview</a>`,
      prevAnchor ? `<a href="#${prevAnchor}">\u2190 Prev</a>` : "",
      nextAnchor ? `<a href="#${nextAnchor}">Next \u2192</a>` : "",
    ].filter(Boolean).join("");

    return `
    <section id="${posterSessionAnchorId(session)}" class="session-card">
      <div class="session-head">
        <div>
          <h3>${escapeHtml(posterSessionName(session))}</h3>
          <div class="session-kicker">${escapeHtml(posterSessionLabel(session.id))} \u00b7 ${escapeHtml(result.layoutType)} \u00b7 ${session.papers.length} papers</div>
        </div>
        <div class="session-nav">${navLinks}</div>
      </div>
      <div class="meta-grid">
        ${exportMetaCard("Date", session.sessionDate)}
        ${exportMetaCard("Time", sessionTimeLabel(session))}
        ${exportMetaCard("Track", session.trackLabel || posterSessionLabel(session.id))}
        ${exportMetaCard("Room / Location", session.location)}
        ${exportMetaCard("Chair", session.sessionChair)}
      </div>
      <div class="paper-list">
        ${(session.cells || []).map((paper, idx) => {
          const label = posterBoardLabel(idx, result.layoutType, result.rows, result.cols);
          if (!paper) {
            return `
              <div class="paper-item">
                <strong>${escapeHtml(label)}</strong>
                <span class="paper-authors">Empty board</span>
              </div>
            `;
          }
          return `
            <div class="paper-item">
              <strong>${escapeHtml(label)} \u00b7 ${escapeHtml(posterPaperId(paper))} \u00b7 ${escapeHtml(paper.title || "")}</strong>
              <span class="paper-authors">Authors: ${escapeHtml(paperAuthorsOrPresentersLabel(paper) || "Not set")}</span>
              ${paper.abstract ? `<details><summary>Show abstract</summary><div class="paper-abstract">${escapeHtml(paper.abstract)}</div></details>` : ""}
            </div>
          `;
        }).join("")}
      </div>
    </section>`;
  }).join("");

  const totalPapers = result.papers ? result.papers.length : result.sessions.reduce((s, sess) => s + (sess.papers ? sess.papers.length : 0), 0);
  const summaryHtml = [
    exportSummaryChip("Papers", totalPapers),
    exportSummaryChip("Sessions", result.sessions.length),
    exportSummaryChip("Layout", result.layoutType),
    exportSummaryChip("Boards / Session", result.sessionCapacity),
  ].join("");
  return buildStyledExportHtml({
    title: "Poster Session Schedule",
    subtitle: `${result.sessions.length} poster sessions using ${escapeHtml(result.layoutType)} layout with ${result.sessionCapacity} boards per session.`,
    conference: state.poster.conference,
    summaryHtml,
    headerHtml: `<tr>${Array.from({ length: columns }, (_, idx) => `<th>Column ${idx + 1}</th>`).join("")}</tr>`,
    rowsHtml: rows.join(""),
    sectionsHtml: sections,
  });
}

export function buildPosterExportCsv() {
  const result = state.poster.result;
  if (!result) return "";
  const rows = [[
    "*Date",
    "*Time Start",
    "*Time End",
    "Tracks",
    "*Session Title",
    "Room/Location",
    "Description",
    "Speakers",
    "Authors",
    "Session or Sub-session(Sub)",
  ]];
  result.sessions.forEach((session) => {
    ensureSessionMetadata(session);
    rows.push([
      session.sessionDate || "",
      session.startTime || "",
      session.endTime || "",
      session.trackLabel || "",
      posterSessionName(session),
      session.location || "",
      "",
      session.sessionChair || "",
      "",
      "",
    ]);
  });
  return rows.map((row) => row.map(csvEscape).join(",")).join("\n");
}

/* ═══════════════════ Event setup ═══════════════════ */

export function setupPosterEvents() {
  document.getElementById("runPosterBtn").addEventListener("click", runPosterOrganization);
  document.getElementById("savePosterProgressBtn").addEventListener("click", openPosterSaveModal);
  document.getElementById("loadPosterProgressBtn").addEventListener("click", openPosterLoadModal);
  document.getElementById("posterConferenceSelect").addEventListener("change", (e) => {
    state.poster.conference = e.target.value;
    state.poster.result = null;
    state.poster.activeSessionId = null;
    state.poster.activeHardPaperId = null;
    /* Sync sidebar workspace select */
    const wsSel = document.getElementById("workspaceSelect");
    if (wsSel) wsSel.value = e.target.value;
    void loadPosterDemoInfo();
  });
  const posterInputHandler = () => {
    state.poster.layoutCategory = document.getElementById("posterLayoutCategorySelect").value;
    state.poster.linearLayoutType = document.getElementById("posterLinearLayoutSelect").value;
    state.poster.layoutType = state.poster.layoutCategory === "rectangle" ? "rectangle" : state.poster.linearLayoutType;
    state.poster.boardCount = Math.max(1, Number(document.getElementById("posterBoardCountInput").value) || 1);
    state.poster.rows = Math.max(1, Number(document.getElementById("posterRowsInput").value) || 1);
    state.poster.cols = Math.max(1, Number(document.getElementById("posterColsInput").value) || 1);
    state.poster.sessionCount = Math.max(1, Number(document.getElementById("posterSessionCountInput").value) || 1);
    state.poster.preventSamePresenter = Boolean(document.getElementById("posterPresenterConflictInput").checked);
    state.poster.optimizeWithinLayout = Boolean(document.getElementById("posterWithinFloorplanInput").checked);
    renderPosterCapacityNotice();
    posterLayoutInputState();
  };
  [
    "posterLayoutCategorySelect", "posterLinearLayoutSelect", "posterBoardCountInput",
    "posterRowsInput", "posterColsInput", "posterSessionCountInput",
    "posterPresenterConflictInput", "posterWithinFloorplanInput",
  ].forEach((id) => {
    document.getElementById(id).addEventListener("input", posterInputHandler);
    document.getElementById(id).addEventListener("change", posterInputHandler);
  });
  document.getElementById("exportPosterBtn").addEventListener("click", async () => {
    if (!state.poster.result) {
      alert("Run poster organization first.");
      return;
    }
    const format = document.getElementById("posterExportFormatSelect").value;
    if (format === "excel") {
      try {
        const result = state.poster.result;
        const resp = await fetch(`${API_BASE}/poster/export-excel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessions: result.sessions.map((s) => ({
              sessionName: s.sessionName || "",
              sessionChair: s.sessionChair || "",
              sessionDate: s.sessionDate || "",
              startTime: s.startTime || "",
              endTime: s.endTime || "",
              trackLabel: s.trackLabel || "",
              track: s.track || 0,
              location: s.location || "",
            })),
            trackNames: result.trackNames || [],
          }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "poster_schedule.xlsx"; a.click();
        URL.revokeObjectURL(url);
      } catch (e) { alert("Excel export failed: " + e.message); }
      return;
    }
    if (format === "csv") {
      downloadFile("poster_session_schedule.csv", buildPosterExportCsv(), "text/csv;charset=utf-8");
      return;
    }
    downloadFile("poster_session_schedule.html", buildPosterExportHtml(), "text/html;charset=utf-8");
  });
  document.getElementById("posterSessionModalClose").addEventListener("click", closePosterSessionModal);
  document.getElementById("posterSessionModal").addEventListener("click", (e) => {
    if (e.target.id === "posterSessionModal") closePosterSessionModal();
  });
  document.getElementById("posterHardPaperModalClose").addEventListener("click", closePosterHardPaperModal);
  document.getElementById("posterHardPaperModal").addEventListener("click", (e) => {
    if (e.target.id === "posterHardPaperModal") closePosterHardPaperModal();
  });

  /* Reload poster data when workspace changes */
  onWorkspaceSwitch(() => {
    state.poster.result = null;
    state.poster.activeSessionId = null;
    state.poster.activeHardPaperId = null;
    void loadPosterDemoInfo();
    renderPosterResults();
  });
}
