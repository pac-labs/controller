// Session, timeline, approval, composer, and session-file UI helpers extracted from app.js.

let composerAttachedItems = [];

// Session text rendering, reply actions, timeline classifiers, and thinking modal helpers
// live in focused session_* modules loaded before this coordinator.





// Session timeline rendering lives in session_timeline_rendering.js.

// Session create modal, wizard review, and permission quick controls lives in session_create_modal.js.

// Session list loading, selection, event stream attachment, and task event append lives in session_runtime.js.

// Header, theme, user-menu, settings, and setup-wizard bindings lives in session_shell_bindings.js.

// Session creation submit handler, composer submit path, and quick selectors lives in session_task_controls.js.

// Composer controls and diagnostics live in session_composer_controls.js.

// Session source-context bootstrap helpers lives in session_source_bootstrap.js.

// Combined access-request and task approval list rendering lives in session_approvals.js.

function resetSessionTimelineState() {
    sessionThinkingGroups = new Map();
    sessionEventSeen = new Set();
    sessionMessageSeen = new Set();
    sessionPendingRows = new Map();
    sessionApprovalRows = new Map();
    sessionLatestEventId = null;
    sessionHydrationBufferedEvents = [];
    sessionTaskPrompts = new Map();
    latestAssistantReplyState = null;
    renderComposerReplyActions();
}

function refreshComposerThinkingStatusForTask(taskId='') {
  const group = getThinkingGroup(taskId);
  if (group && Array.isArray(group.events) && group.events.length && !group.closed) {
    const state = deriveComposerThinkingState(group.events.map(item => item?.event).filter(Boolean)) || {};
    state.closed = false;
    state.active = true;
    state.startedAt = group.startedAt || state.startedAt;
    state.summary = group.summary || state.summary || 'Working on the request';
    state.toolCount = thinkingGroupToolCount(group);
    state.approvalPending = thinkingGroupNeedsApproval(group);
    state.planSteps = [];
    state.onOpen = () => openSessionThinkingModal(group);
    renderComposerThinkingStatus(state);
    return;
  }
  renderComposerThinkingStatus(null);
  updateComposerChrome();
}

try { bindSessionEventModalChrome(); } catch (_) {}
