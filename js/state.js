/**
 * state.js — Central application state object.
 */

export const state = {
  activeTask: "overview",
  assignment: {
    info: null,
    mode: "demo",
    conference: "sigir2025",
    availableConferences: [],
    submissions: [],
    reviewers: [],
    metaReviewers: [],
    coi: new Set(),
    uploadNames: {
      submissions: "",
      reviewers: "",
      metaReviewers: "",
      coi: ""
    },
    reviewerWorkload: 4,
    reviewerCoverage: 3,
    metaReviewerWorkload: 8,
    isRunning: false,
    result: null,
    viewMode: "paper",
    selected: null
  },
  discovery: {
    disabled: true
  },
  oral: {
    demoInfo: null,
    conference: "sigir2025",
    availableConferences: [],
    parallelSessions: 7,
    maxPerSession: 4,
    minPerSession: 3,
    timeSlots: 19,
    detailMode: "concise",
    isRunning: false,
    result: null,
    activeSessionId: null,
    activeHardPaperId: null
  },
  poster: {
    demoInfo: null,
    conference: "sigir2025",
    availableConferences: [],
    layoutCategory: "rectangle",
    layoutType: "rectangle",
    linearLayoutType: "line",
    boardCount: 12,
    rows: 3,
    cols: 4,
    sessionCount: 44,
    preventSamePresenter: false,
    optimizeWithinLayout: true,
    detailMode: "concise",
    isRunning: false,
    result: null,
    activeSessionId: null,
    activeHardPaperId: null
  }
};
