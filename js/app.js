/**
 * TaxoConf Workspace — Application entry point
 *
 * Imports all modules and initializes the application.
 * This is the single <script type="module"> loaded by index.html.
 */

// Foundation
import { state } from './state.js';
import { setupNavEvents, switchTask } from './router.js';
import { setupWorkspaceEvents, loadWorkspaces } from './workspace.js';

// Views
import { renderAssignmentResults, setupAssignmentEvents, loadAssignmentInfo } from './views/assignment.js';
import { setupDiscoveryEvents } from './views/discovery.js';
import { renderOralResults, setupOralEvents, loadOralDemoInfo } from './views/oral.js';
import { renderPosterResults, setupPosterEvents, loadPosterDemoInfo } from './views/poster.js';
import { setupTokenStatsEvents } from './views/tokens-page.js';
import { setupSettingsEvents } from './views/settings.js';
import { setupOverviewEvents } from './views/overview.js';

function init() {
  // Bind all event listeners
  setupNavEvents();
  setupWorkspaceEvents();
  setupOverviewEvents();
  setupAssignmentEvents();
  setupDiscoveryEvents();
  setupOralEvents();
  setupPosterEvents();
  setupTokenStatsEvents();
  setupSettingsEvents();

  // Initial renders
  renderAssignmentResults();
  renderOralResults();
  renderPosterResults();

  // Async data loads (fire-and-forget)
  void loadWorkspaces();
  void loadAssignmentInfo();
  void loadOralDemoInfo();
  void loadPosterDemoInfo();
}

init();
