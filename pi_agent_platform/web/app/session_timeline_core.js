// Session timeline core helpers, approval rows, workspace chrome, and scroll state.

function timelineText(event, block) {
  if (block) {
    const parts = [block.title, block.summary].filter(Boolean);
    if (Array.isArray(block.steps)) parts.push(...block.steps.map(s => [s.label || s.title, s.detail || s.message].filter(Boolean).join(': ')));
    if (block.output || block.code || block.diff) parts.push(block.output || block.code || block.diff);
    return parts.filter(Boolean).join('\n');
  }
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  if (event.message) lines.push(event.message);
  if (typeof data.message === 'string' && data.message.trim()) lines.push(data.message);
  if (typeof data.text === 'string' && data.text.trim()) lines.push(data.text);
  if (typeof data.content === 'string' && data.content.trim()) lines.push(data.content);
  if (typeof data.response === 'string' && data.response.trim()) lines.push(data.response);
  if (typeof data.answer === 'string' && data.answer.trim()) lines.push(data.answer);
  if (typeof data.output_text === 'string' && data.output_text.trim()) lines.push(data.output_text);
  if (data.result && typeof data.result === 'object') {
    if (typeof data.result.message === 'string' && data.result.message.trim()) lines.push(data.result.message);
    if (typeof data.result.output === 'string' && data.result.output.trim()) lines.push(data.result.output);
    if (typeof data.result.response === 'string' && data.result.response.trim()) lines.push(data.result.response);
  }
  if (Array.isArray(data.content)) {
    const contentText = data.content.map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') return item.text || item.content || item.value || '';
      return '';
    }).filter(Boolean).join('\n');
    if (contentText) lines.push(contentText);
  }
  if (data.command) lines.push(`$ ${data.command}`);
  if (data.tool) lines.push(`tool: ${data.tool}`);
  if (data.output) lines.push(String(data.output));
  if (data.summary && !lines.includes(String(data.summary))) lines.push(String(data.summary));
  if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
  if (data.exit_code != null) lines.push(`exit code: ${data.exit_code}`);
  return [...new Set(lines.map((line) => String(line || '').trim()).filter(Boolean))].join('\n').trim();
}

function sessionEventDate(event) {
  try { return new Date(event?.created_at || Date.now()); } catch { return new Date(); }
}

function formatDurationMs(ms) {
  const safe = Math.max(0, Number(ms) || 0);
  const totalSeconds = Math.floor(safe / 1000);
  if (totalSeconds < 1) return '0s';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function sessionEventMetaLines(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  const model = data.model || data.session_model || selectedSession?.model;
  const endpoint = data.endpoint_name || endpointDisplayName(data.endpoint_id || data.runner_id || selectedSession?.metadata?.preferred_endpoint);
  const profile = data.agent_profile || selectedSession?.agent_profile;
  if (model) lines.push(`Model: ${model}`);
  if (endpoint) lines.push(`Endpoint: ${endpoint}`);
  if (profile) lines.push(`Profile: ${profile}`);
  if (data.execution_mode) lines.push(`Execution: ${data.execution_mode}`);
  if (data.command) lines.push(`Command: ${data.command}`);
  if (event?.task_id) lines.push(`Task: ${event.task_id}`);
  return lines;
}

function removePendingRow(taskId) {
  if (!taskId) return;
  const group = sessionThinkingGroups.get(taskId);
  if (group?.events?.length || group?.closed) {
    sessionPendingRows.delete(taskId);
    return;
  }
  const row = sessionPendingRows.get(taskId);
  if (row && row.parentElement) row.remove();
  sessionPendingRows.delete(taskId);
}

function removeSessionApprovalRow(taskId) {
  if (!taskId) return;
  const row = sessionApprovalRows.get(taskId);
  if (row && row.parentElement) row.remove();
  sessionApprovalRows.delete(taskId);
}

async function refreshSessionRunButton() {
  const btn = document.getElementById('runTask');
  if (!btn) return;
  if (!selectedSession?.id) {
    activeSessionTaskId = null;
    btn.dataset.mode = 'send';
    btn.textContent = '➤';
    btn.title = 'Send';
    btn.setAttribute('aria-label', 'Send');
    btn.classList.remove('stop-mode');
    btn.disabled = false;
    return;
  }
  if (sessionRunButtonRequest) return sessionRunButtonRequest;
  sessionRunButtonRequest = (async () => {
    try {
      const tasks = await api(`/v1/sessions/${selectedSession.id}/tasks`);
      const ordered = (tasks || []).slice().sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
      const latest = ordered[0] || null;
      const latestStatus = String(latest?.status || '');
      const latestIsActive = ['queued', 'running', 'approval_required'].includes(latestStatus);
      activeSessionTaskId = latestIsActive ? (latest?.id || null) : null;
      if (activeSessionTaskId) {
        btn.dataset.mode = 'stop';
        btn.textContent = '■';
        btn.title = 'Stop';
        btn.setAttribute('aria-label', 'Stop');
        btn.classList.add('stop-mode');
      } else {
        btn.dataset.mode = 'send';
        btn.textContent = '➤';
        btn.title = 'Send';
        btn.setAttribute('aria-label', 'Send');
        btn.classList.remove('stop-mode');
      }
      btn.disabled = false;
    } catch (_) {
    } finally {
      sessionRunButtonRequest = null;
    }
  })();
  return sessionRunButtonRequest;
}

async function stopActiveSessionTask() {
  if (!selectedSession?.id) return;
  if (!activeSessionTaskId) {
    await refreshSessionRunButton().catch(()=>{});
  }
  if (!activeSessionTaskId) return;
  await api(`/v1/tasks/${activeSessionTaskId}/stop`, {method:'POST'});
  await pollSessionEvents(selectedSession.id).catch(()=>{});
  await loadSessions().catch(()=>{});
  await refreshSessionRunButton().catch(()=>{});
}

function approvalPurpose(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  return data.command || data.path || data.url || data.query || event?.message || 'Requested action';
}

function renderSessionApprovalRow(event) {
  const el = document.getElementById('events');
  const taskId = event?.task_id || '';
  if (!el || !taskId || sessionApprovalRows.has(taskId)) return;
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const reason = data.reason || '';
  const row = document.createElement('article');
  row.className = 'chat-message-row system approval-row';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble warning approval-bubble';
  bubble.innerHTML = `<div class="chat-bubble-meta"><span>Permission needed</span><span>${escapeHtml(formatEventTime(event.created_at))}</span></div>
    <div class="chat-bubble-text">
      <div class="approval-purpose">${escapeHtml(approvalPurpose(event))}</div>
      ${reason ? `<div class="approval-reason">${escapeHtml(reason)}</div>` : ''}
    </div>`;
  const actions = document.createElement('div');
  actions.className = 'approval-actions';
  const approve = document.createElement('button');
  approve.type = 'button';
  approve.className = 'thought-action approve';
  approve.textContent = 'Approve';
  approve.onclick = async () => { approve.disabled = true; reject.disabled = true; await resolveSessionApproval(taskId, true); };
  const reject = document.createElement('button');
  reject.type = 'button';
  reject.className = 'thought-action reject';
  reject.textContent = 'Reject';
  reject.onclick = async () => { approve.disabled = true; reject.disabled = true; await resolveSessionApproval(taskId, false); };
  actions.append(approve, reject);
  bubble.appendChild(actions);
  row.appendChild(bubble);
  sessionApprovalRows.set(taskId, row);
  el.appendChild(row);
  scrollSessionToBottom();
}

function syncSessionPermissionQuick() {
  const select = document.getElementById('sessionPermissionQuick');
  const button = document.getElementById('applySessionPermission');
  const usageButton = document.getElementById('downloadSessionUsage');
  const diagButton = document.getElementById('downloadSessionDiagnostics');
  if (usageButton) usageButton.disabled = !selectedSession?.id;
  if (diagButton) diagButton.disabled = !selectedSession?.id;
  if (!select || !button) return;
  const profiles = Object.keys(config?.permission_profiles || {});
  select.innerHTML = '';
  if (!selectedSession) {
    opt(select, '', 'No session');
    select.disabled = true;
    button.disabled = true;
    return;
  }
  profiles.forEach((name) => opt(select, name, name));
  select.value = selectedSession.permission_profile || profiles[0] || '';
  select.disabled = !profiles.length;
  button.disabled = !profiles.length || select.value === (selectedSession.permission_profile || '');
}

function ensureSessionWorkspaceChrome() {
  const layout = document.querySelector('#sessions-tab .session-chat-layout');
  const main = document.querySelector('#sessions-tab .session-chat-main');
  if (!layout || !main) return;
  layout.classList.remove('single');
  layout.classList.add('with-sidebar');
  let sidebar = document.querySelector('#sessions-tab .sessions-list-card');
  if (!sidebar) {
    sidebar = document.createElement('aside');
    sidebar.className = 'sessions-list-card';
    sidebar.innerHTML = `<div class="section-heading compact-heading sidebar-heading"><div><h3>Sessions</h3><p class="muted">Select or reopen a session quickly.</p></div><div class="sidebar-heading-actions"></div></div><div id="sessionSidebarList" class="session-sidebar-list muted">No sessions yet.</div>`;
    layout.insertBefore(sidebar, main);
  }
  const pickerWrap = document.querySelector('#sessions-tab .session-picker-wrap');
  if (pickerWrap) pickerWrap.style.display = 'none';
  const sessionMeta = document.querySelector('#sessions-tab .session-session-meta');
  if (sessionMeta) sessionMeta.style.display = 'none';
  const sidebarActions = sidebar.querySelector('.sidebar-heading-actions');
  const openButton = document.getElementById('openSessionModal');
  if (sidebarActions && openButton && openButton.parentElement !== sidebarActions) {
    sidebarActions.appendChild(openButton);
    openButton.classList.add('sidebar-create-session');
  }
  const topQuick = document.querySelector('#sessions-tab .session-quick-controls');
  if (topQuick) topQuick.style.display = 'none';
  const controls = document.querySelector('#sessions-tab .composer-controls.integrated.editor-like');
  const permissionSelect = document.getElementById('sessionPermissionQuick');
  const permissionApply = document.getElementById('applySessionPermission');
  const composerLeftActions = document.querySelector('#sessions-tab .composer-left-actions');
  if (controls && permissionSelect && permissionApply && composerLeftActions && permissionSelect.parentElement !== composerLeftActions) {
    composerLeftActions.appendChild(permissionSelect);
    composerLeftActions.appendChild(permissionApply);
    permissionSelect.title = 'Permissions';
    permissionSelect.classList.add('composer-permission-select');
    permissionApply.classList.add('mini-apply-button', 'composer-mini-button');
  }
  if (!document.getElementById('composerFileInput')) {
    const input = document.createElement('input');
    input.id = 'composerFileInput';
    input.type = 'file';
    input.multiple = true;
    input.hidden = true;
    main.appendChild(input);
  }
  if (!document.getElementById('composerDirectoryInput')) {
    const input = document.createElement('input');
    input.id = 'composerDirectoryInput';
    input.type = 'file';
    input.multiple = true;
    input.hidden = true;
    input.setAttribute('webkitdirectory', '');
    input.setAttribute('directory', '');
    main.appendChild(input);
  }
  const fileInput = document.getElementById('composerFileInput');
  if (fileInput && !fileInput.dataset.bound) {
    fileInput.addEventListener('change', async (ev) => {
      const input = ev.currentTarget;
      const files = Array.from(input.files || []);
      if (files.length) await appendSelectedFilesToPrompt(files, 'Attached files');
      input.value = '';
      input.accept = '';
    });
    fileInput.dataset.bound = '1';
  }
  const dirInput = document.getElementById('composerDirectoryInput');
  if (dirInput && !dirInput.dataset.bound) {
    dirInput.addEventListener('change', async (ev) => {
      const input = ev.currentTarget;
      const files = Array.from(input.files || []);
      if (files.length) await appendSelectedFilesToPrompt(files, 'Attached directory files');
      input.value = '';
    });
    dirInput.dataset.bound = '1';
  }
}

function sessionTimelineNearBottom(el, threshold = 88) {
  if (!el) return true;
  return (el.scrollHeight - el.scrollTop - el.clientHeight) <= threshold;
}

function updateSessionAutoScrollState() {
  const el = document.getElementById('events');
  if (!el) return;
  sessionAutoScrollPinned = sessionTimelineNearBottom(el);
}

function scrollSessionToBottom(force = false) {
  const el = document.getElementById('events');
  if (!el) return;
  if (force || suppressSessionAutoScroll || sessionAutoScrollPinned) el.scrollTop = el.scrollHeight;
  updateSessionAutoScrollState();
}

function bindSessionTimelineScroll() {
  const el = document.getElementById('events');
  if (!el || el.dataset.autoscrollBound) return;
  el.addEventListener('scroll', () => updateSessionAutoScrollState());
  el.dataset.autoscrollBound = '1';
  updateSessionAutoScrollState();
}

function resetSessionTimelineState() {
  sessionThinkingGroups = new Map();
  sessionEventSeen = new Set();
  sessionMessageSeen = new Set();
  sessionPendingRows = new Map();
  sessionApprovalRows = new Map();
  sessionLatestEventId = null;
  sessionHydrationBufferedEvents = [];
}

function getThinkingGroup(taskId) {
  if (taskId && sessionThinkingGroups.has(taskId)) return sessionThinkingGroups.get(taskId);
  const groups = Array.from(sessionThinkingGroups.values());
  return groups.length ? groups[groups.length - 1] : null;
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
