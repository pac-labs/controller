// Focused session UI helpers extracted from sessions.js.

function openSessionThinkingModal(group) {
  const modal = document.getElementById('sessionEventModal');
  if (!modal || !group) return;
  const title = document.getElementById('sessionEventModalTitle');
  const body = document.getElementById('sessionEventModalBody');
  const duration = formatDurationMs(((group.endedAt || new Date()).getTime()) - (group.startedAt || new Date()).getTime());
  if (title) title.textContent = group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`;
  if (body) {
    body.className = 'modal-scroll-output tool-activity-modal';
    const planSteps = deriveThinkingPlanSteps(group);
    const summary = escapeHtml(group.summary || (group.closed ? 'Completed' : 'Working on the request'));
    body.innerHTML = `
      <div class="thought-modal-summary">
        <div class="thought-modal-kicker">${escapeHtml(group.closed ? 'Completed thought process' : 'Current thought process')}</div>
        <div class="thought-modal-title">${summary}</div>
        <div class="thought-modal-meta">
          <span>${thinkingGroupToolCount(group)} ${thinkingGroupToolCount(group) === 1 ? 'tool/event' : 'tool/events'}</span>
          <span>${escapeHtml(thinkingGroupNeedsApproval(group) ? 'Awaiting approval' : group.closed ? 'Completed' : 'Active')}</span>
        </div>
      </div>
      ${planSteps.length ? `<div class="thought-modal-plan"><div class="thought-modal-section-title">Work plan</div>${planSteps.map((step, index) => `<div class="thought-modal-plan-item ${escapeHtml(step.status)}"><span class="thought-modal-plan-index">${index + 1}</span><span class="thought-modal-plan-label">${escapeHtml(step.label)}</span><span class="thought-modal-plan-state">${escapeHtml(step.status === 'running' ? 'Active' : step.status === 'attention' ? 'Needs approval' : step.status === 'failed' ? 'Failed' : step.status === 'planned' ? 'Planned' : 'Done')}</span></div>`).join('')}</div>` : ''}
      ${sessionThinkingDetailsHtml(group.events || [])}`;
  }
  bindSessionEventModalChrome();
  modal.hidden = false;
}

function thinkingGroupToolCount(group) {
  return (group?.events || []).filter((item) => {
    const t = String(item?.event?.type || '').toLowerCase();
    return t.includes('tool') || t.includes('command') || t.includes('stdout') || t.includes('stderr') || t.includes('web_');
  }).length;
}

function thinkingGroupNeedsApproval(group) {
  const event = group?.lastEvent;
  return !!event && String(event.type || '').toLowerCase().includes('approval_required');
}

function extractWorkPlanStepsFromText(text) {
  const raw = String(text || '').trim();
  if (!raw) return [];
  const normalized = raw.replace(/\r/g, '');
  const candidates = [];
  normalized.split('\n').forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const match = trimmed.match(/^(?:[-*•]|\d+[.)]|\[[ xX-]\])\s*(.+)$/);
    if (match && match[1]) candidates.push(match[1].trim());
  });
  if (!candidates.length && /\b\d+[.)]\s+/.test(normalized)) {
    const inline = normalized.split(/(?=\b\d+[.)]\s+)/g)
      .map((part) => part.replace(/^\d+[.)]\s*/, '').trim())
      .filter(Boolean);
    candidates.push(...inline);
  }
  return candidates
    .map((label) => label.replace(/^(plan|step|task)\s*[:：-]\s*/i, '').trim())
    .filter((label) => label && label.length > 3)
    .slice(0, 8)
    .map((label) => ({label, status: 'planned', time: ''}));
}

function deriveThinkingPlanSteps(group) {
  const rows = Array.isArray(group?.events) ? group.events : [];
  const planEvents = rows.filter((item) => String(item?.event?.type || '').toLowerCase().includes('agent_plan'));
  const steps = [];
  planEvents.forEach((item) => {
    const data = item?.event?.data && typeof item.event.data === 'object' ? item.event.data : {};
    const explicit = Array.isArray(data.steps) ? data.steps : Array.isArray(data.plan_steps) ? data.plan_steps : [];
    explicit.forEach((step) => {
      if (typeof step === 'string') steps.push({label: step.trim(), status: 'planned', time: item.event?.created_at || ''});
      else if (step && typeof step === 'object') steps.push({label: String(step.label || step.title || step.summary || '').trim(), status: String(step.status || 'planned').toLowerCase(), time: item.event?.created_at || ''});
    });
    const text = String(data.plan || data.summary || item?.event?.message || timelineText(item.event, item.block) || '').trim();
    extractWorkPlanStepsFromText(text).forEach((step) => steps.push({...step, time: item.event?.created_at || ''}));
  });
  const deduped = [];
  const seen = new Set();
  for (const step of steps) {
    const label = String(step.label || '').trim();
    if (!label) continue;
    const key = label.toLowerCase().replace(/\s+/g, ' ');
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push({label, status: step.status || 'planned', time: step.time || ''});
  }
  return deduped.slice(0, 8);
}

async function resolveSessionApproval(taskId, approved) {
  if (!taskId) return;
  if (approved) await api(`/v1/tasks/${taskId}/approve`, {method:'POST'});
  else await api(`/v1/tasks/${taskId}/reject?reason=Rejected`, {method:'POST'});
  removeSessionApprovalRow(taskId);
  if (approved) addPendingRow(taskId);
  await loadSessions().catch(()=>{});
  if (selectedSession?.id) await pollSessionEvents(selectedSession.id).catch(()=>{});
  await loadApprovals().catch(()=>{});
}

function updateSessionThinkingRow(group) {
  if (!group?.row) return;
  const event = group.lastIntentEvent || group.lastEvent || group.events?.[group.events.length - 1]?.event;
  const endAt = group.endedAt || new Date();
  const startAt = group.startedAt || sessionEventDate(event) || new Date();
  const duration = formatDurationMs(endAt.getTime() - startAt.getTime());
  const approvalPending = thinkingGroupNeedsApproval(group);
  const taskId = event?.task_id || group.taskId || '';
  const headline = group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`;
  const currentIntent = group.summary || sessionIntentSummary(event, null) || '';
  const latestIntermediate = group.closed ? null : thinkingGroupLatestIntermediate(group);
  const prompt = taskId ? sessionTaskPrompts.get(taskId) : '';
  const fallbackMessage = currentIntent || prompt || (group.closed ? 'Finished working on the request.' : 'Working on the request.');
  const workMessage = currentIntent || latestIntermediate?.text || fallbackMessage;
  const lateScope = sessionReplyScopeInfo(event);
  group.row.className = 'chat-message-row assistant thought-history-row assistant-work-row';
  group.row.innerHTML = '';
  const bubble = document.createElement('div');
  bubble.className = `thought-history-line assistant-work-progress ${group.closed ? 'closed' : 'active'}`;
  bubble.innerHTML = `
    ${lateScope ? `<div class="reply-scope-notice compact"><span>${escapeHtml(lateScope.label)}</span><small>${escapeHtml(lateScope.prompt)}</small></div>` : ''}
    <div class="assistant-work-message">${escapeHtml(workMessage)}</div>
    ${currentIntent ? `<div class="assistant-work-intent">${escapeHtml(currentIntent)}</div>` : ''}
    <button type="button" class="thought-history-main assistant-work-disclosure" aria-label="Open thought details" title="Open thought details">
      <span class="thought-history-dot">${group.closed ? '✓' : (window.pacLoaderIconHtml ? pacLoaderIconHtml('tiny', 'Thinking') : '<span class="tiny-spinner square" aria-hidden="true"></span>')}</span>
      <span class="thought-history-intent">${escapeHtml(headline)}</span>
      <span class="composer-thinking-chevron">›</span>
    </button>
    ${approvalPending ? '<div class="thought-history-note attention">Awaiting approval</div>' : ''}`;
  const main = bubble.querySelector('.thought-history-main');
  if (main) {
    main.onclick = () => openSessionThinkingModal(group);
    main.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openSessionThinkingModal(group); } };
  }
  group.row.appendChild(bubble);
  if (approvalPending && taskId) {
    const actions = document.createElement('div');
    actions.className = 'thought-actions';
    const approve = document.createElement('button');
    approve.type = 'button';
    approve.className = 'thought-action approve';
    approve.textContent = 'Approve';
    approve.onclick = async (ev) => {
      ev.stopPropagation();
      await resolveSessionApproval(taskId, true);
    };
    const reject = document.createElement('button');
    reject.type = 'button';
    reject.className = 'thought-action reject';
    reject.textContent = 'Reject';
    reject.onclick = async (ev) => {
      ev.stopPropagation();
      await resolveSessionApproval(taskId, false);
    };
    actions.append(approve, reject);
    bubble.appendChild(actions);
  }
}

function ensureSessionThinkingGroup(event) {
  const taskId = event?.task_id || '';
  let group = getThinkingGroup(taskId);
  if (!group || group.closed || (taskId && group.taskId !== taskId)) {
    const el = document.getElementById('events');
    const row = document.createElement('article');
    row.className = 'chat-message-row assistant thought-history-row';
    if (el) el.appendChild(row);
    group = {events: [], startedAt: taskStartEventForThinking(event) ? sessionEventDate(event) : null, endedAt: null, row, closed: false, taskId, summary: ''};
  }
  if (!group.startedAt && taskStartEventForThinking(event)) group.startedAt = sessionEventDate(event);
  if (!group.startedAt) group.startedAt = sessionEventDate(event);
  if (!group.taskId && taskId) group.taskId = taskId;
  if (taskId) sessionThinkingGroups.set(taskId, group);
  removePendingRow(taskId);
  return group;
}

function flushSessionThinkingGroup(endEvent) {
  const group = getThinkingGroup(endEvent?.task_id || '');
  if (!group || group.closed) return;
  if (!group.events.length && endEvent) {
    group.events.push({event: endEvent, block: normalizeTimelineBlock(endEvent)});
    group.lastEvent = endEvent;
  }
  if (!group.events.length) return;
  group.closed = true;
  group.endedAt = endEvent ? sessionEventDate(endEvent) : new Date();
  updateSessionThinkingRow(group);
}

function openSessionEventModal(event, block) {
  const modal = document.getElementById('sessionEventModal');
  if (!modal) return;
  const title = document.getElementById('sessionEventModalTitle');
  const body = document.getElementById('sessionEventModalBody');
  if (title) title.textContent = prettyEventType(event?.type || 'reply details');
  if (body) {
    body.className = 'modal-scroll-output';
    body.textContent = sessionEventDetailsText(event, block);
  }
  bindSessionEventModalChrome();
  modal.hidden = false;
}

function closeSessionEventModal() {
  const modal = document.getElementById('sessionEventModal');
  if (modal) modal.hidden = true;
}

function bindSessionEventModalChrome() {
  const modal = document.getElementById('sessionEventModal');
  const closeButton = document.getElementById('closeSessionEventModal');
  if (closeButton && !closeButton.dataset.sessionCloseBound) {
    closeButton.dataset.sessionCloseBound = '1';
    closeButton.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      closeSessionEventModal();
    });
  }
  if (modal && !modal.dataset.sessionBackdropBound) {
    modal.dataset.sessionBackdropBound = '1';
    modal.addEventListener('click', (ev) => {
      if (ev.target === modal) closeSessionEventModal();
    });
  }
  if (!window.__pacSessionEventEscapeBound) {
    window.__pacSessionEventEscapeBound = true;
    window.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && modal && !modal.hidden) closeSessionEventModal();
    });
  }
}

