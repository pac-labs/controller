// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

function deriveComposerThinkingState(events) {
    const rows = Array.isArray(events) ? events : [];
    const byTask = new Map();
    rows.forEach((event) => {
        const taskId = String(event?.task_id || '').trim();
        if (!taskId) return;
        if (!byTask.has(taskId)) byTask.set(taskId, []);
        byTask.get(taskId).push(event);
    });
    const preferredTaskId = activeSessionTaskId && byTask.has(activeSessionTaskId) ? activeSessionTaskId : Array.from(byTask.keys()).at(-1);
    if (!preferredTaskId) return null;
    const taskEvents = (byTask.get(preferredTaskId) || []).slice().sort((a, b) => new Date(a?.created_at || 0).getTime() - new Date(b?.created_at || 0).getTime());
    const internal = taskEvents.filter((event) => isInternalSessionEvent(event) || looksLikeInternalResultMessage(event, timelineText(event, normalizeTimelineBlock(event))));
    if (!internal.length) return {active: true, summary: 'Thinking about your latest request', startedAt: taskEvents[0]?.created_at, toolCount: 0, approvalPending: false, planSteps: []};
    let summary = '';
    let latestIntermediate = '';
    let approvalPending = false;
    let toolCount = 0;
    let planSteps = [];
    for (const event of internal) {
        if (typeof modelIntermediateResponseText === 'function') {
            const intermediate = modelIntermediateResponseText(event, normalizeTimelineBlock(event));
            if (intermediate) latestIntermediate = intermediate;
        }
        const type = String(event?.type || '').toLowerCase();
        if (type.includes('tool_call')) toolCount += 1;
        if (type.includes('approval_required')) approvalPending = true;
        if (type.includes('agent_intent') || type.includes('agent_routing') || type.includes('model_request_config') || type.includes('approval_required')) {
            planSteps = [];
        }
        const next = typeof sessionIntentSummary === 'function' && (type.includes('agent_intent') || type.includes('agent_routing') || type.includes('model_request_config') || type.includes('approval_required'))
            ? sessionIntentSummary(event, normalizeTimelineBlock(event))
            : sessionThinkingSummary(event, normalizeTimelineBlock(event));
        if (next) summary = next;
        else if (!summary && (type.includes('tool_result') || type.includes('result'))) summary = String(event?.message || '').trim();
    }
    return {
        active: true,
        summary: summary || 'Thinking about your latest request',
        startedAt: internal[0]?.created_at || taskEvents[0]?.created_at,
        toolCount,
        approvalPending,
        planSteps,
        latestIntermediate,
    };
}

function renderComposerThinkingStatus(state) {
    const el = document.getElementById('composerThinkingStatus');
    if (!el) return;
    if (!state || (!state.active && !state.closed)) {
        el.hidden = true;
        el.innerHTML = '';
        el.classList.remove('closed', 'active');
        el.onclick = null;
        el.onkeydown = null;
        return;
    }
    const endAt = state.closed ? (state.endedAt || new Date().toISOString()) : new Date().toISOString();
    const duration = formatDurationMs(Math.max(0, (new Date(endAt).getTime() - new Date(state.startedAt || new Date().toISOString()).getTime())));
    const summary = state.summary || (state.closed ? 'Done.' : 'Thinking');
    const meta = state.approvalPending ? '<span class="composer-thinking-meta">Awaiting approval</span>' : '';
    const update = state.latestIntermediate ? `<span class="composer-thinking-update"><span>Model update</span>${escapeHtml(state.latestIntermediate)}</span>` : '';
    const plan = '';
    el.hidden = false;
    el.classList.toggle('closed', !!state.closed);
    el.classList.toggle('active', !state.closed);
    const opener = state.onOpen ? ' role="button" tabindex="0"' : '';
    el.innerHTML = `<span class="composer-thinking-entry"${opener}><span class="composer-thinking-heading">${escapeHtml(state.closed ? `Thought for ${duration}` : `Thinking for ${duration}`)} <span class="composer-thinking-chevron">›</span></span><span class="composer-thinking-summary">${escapeHtml(summary)}</span>${update}${meta}${plan}</span>`;
    if (state.onOpen) {
        const open = () => state.onOpen();
        el.onclick = open;
        el.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } };
    } else {
        el.onclick = null;
        el.onkeydown = null;
    }
}

