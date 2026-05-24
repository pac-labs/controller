// Source coding session activity and prompt helpers.
function updateSourceCodingPanel() {
  const defaults = sourceCodingDefaults();
  const endpointName = (window.__pacEndpoints || []).find(r => r.id === defaults.endpointId)?.name || defaults.endpointId || '-';
  const contextSummary = document.getElementById('sourceCodingContextSummary');
  const workspaceSummary = defaults.workspaceName || defaults.workspaceProfile || defaults.workspacePath || 'workspace';
  const targetLabel = defaults.contextName ? `${defaults.contextName} (${workspaceSummary})` : workspaceSummary;
  if (contextSummary) {
    contextSummary.textContent = defaults.existingSession?.id
      ? `Attached to ${defaults.existingSession.name || defaults.existingSession.id} for ${targetLabel} on ${endpointName}.`
      : (selectedIdeContextId || selectedIdeWorkspaceId
        ? `Ready to start a coding session for ${targetLabel} on ${endpointName}.`
        : (sourceResolvedContext?.name
          ? `Ready to start a coding session for ${sourceResolvedContext.name} on ${endpointName}.`
          : `Select a context or workspace, then start a coding session on ${endpointName}.`));
  }
  const focusEl = document.getElementById('sourceCodingFocus');
  if (focusEl) {
    const openFiles = sourceOpenTabs.length ? sourceOpenTabs.map(sourceFileLabel).join(', ') : 'none';
    const sessionName = defaults.existingSession?.name || (sourceCodingSessionId ? 'attached session' : 'not started');
    focusEl.textContent = `Stack ${defaults.stack} • endpoint ${endpointName} • profile ${defaults.profileName || 'main-pi-dev'} • model ${defaults.modelName || '-'} • session ${sessionName} • open files ${openFiles}`;
  }
  const startBtn = document.getElementById('bootstrapSourceCodingSession');
  if (startBtn) startBtn.textContent = defaults.existingSession?.id ? 'Reopen coding session' : 'Start coding session';
  const sendBtn = document.getElementById('askSourceCodingSession');
  if (sendBtn) sendBtn.textContent = defaults.existingSession?.id ? 'Send to coding session' : 'Start and send';
  const openBtn = document.getElementById('openSourceCodingSession');
  if (openBtn) openBtn.disabled = !defaults.existingSession?.id && !sourceCodingSessionId;
  renderSourceToolCatalog();
  sourceCodingSessionId = defaults.existingSession?.id || selectedIdeSessionId || sourceCodingSessionId || '';
  if (sourceCodingSessionId) startSourceCodingPoll();
  else stopSourceCodingPoll();
  refreshSourceCodingActivity().catch(()=>{});
}
function sourceCodingLatestAssistantText(snapshot = {}) {
  const events = normalizeSourceCodingSnapshot(snapshot);
  const candidates = events.filter((event) => {
    const t = String(event?.type || '').toLowerCase();
    return t === 'result' || t === 'final' || t.includes('assistant_message');
  });
  for (let i = candidates.length - 1; i >= 0; i -= 1) {
    const text = resultEventText(candidates[i]);
    if (text) return normalizeAssistantText(text);
  }
  return '';
}
function sourceCodingLatestTask(snapshot = {}) {
  const events = normalizeSourceCodingSnapshot(snapshot);
  const tasks = new Map();
  for (const event of events) {
    const taskId = String(event?.task_id || '').trim();
    if (!taskId) continue;
    let item = tasks.get(taskId);
    if (!item) {
      item = {taskId, events: [], latestAt: 0};
      tasks.set(taskId, item);
    }
    item.events.push(event);
    const ts = sessionEventDate(event).getTime();
    if (ts > item.latestAt) item.latestAt = ts;
  }
  return Array.from(tasks.values()).sort((a, b) => b.latestAt - a.latestAt)[0] || null;
}
function normalizeSourceCodingSnapshot(snapshot = {}) {
  if (Array.isArray(snapshot)) return snapshot.slice();
  if (Array.isArray(snapshot.items)) return snapshot.items.slice();
  return [];
}
function isSelectedSessionSourceCodingSession() {
  return !!(sourceCodingSessionId && selectedSession?.id && selectedSession.id === sourceCodingSessionId);
}
function renderSourceCodingActivityFromSnapshot(snapshot = {}) {
  const liveEl = document.getElementById('sourceCodingLiveStatus');
  const summaryEl = document.getElementById('sourceCodingLiveSummary');
  const metaEl = document.getElementById('sourceCodingLiveMeta');
  const replyEl = document.getElementById('sourceCodingLatestReply');
  if (!liveEl || !summaryEl || !metaEl || !replyEl) return;
  const latestTask = sourceCodingLatestTask(snapshot);
  if (!latestTask) {
    liveEl.className = 'source-coding-live idle';
    summaryEl.textContent = sourceCodingSessionId ? 'No active coding task.' : 'No coding task running.';
    metaEl.textContent = sourceCodingSessionId ? 'Send a prompt from the IDE composer or open the session for full history.' : 'Start a coding session or send a prompt from the IDE.';
    replyEl.textContent = 'No coding reply yet.';
    return;
  }
  const internalItems = latestTask.events
    .filter((event) => isInternalSessionEvent(event))
    .map((event) => ({event, block: normalizeTimelineBlock(event)}));
  const lastInternal = internalItems[internalItems.length - 1]?.event || latestTask.events[latestTask.events.length - 1];
  const lastType = String(lastInternal?.type || '').toLowerCase();
  const summary = sessionThinkingSummary(lastInternal, normalizeTimelineBlock(lastInternal)) || 'Working';
  const stepInfo = lastInternal?.data?.step != null ? `step ${lastInternal.data.step}` : '';
  const approval = lastType.includes('approval_required') ? 'needs approval' : '';
  const toolCount = internalItems.filter((item) => String(item.event?.type || '').toLowerCase().includes('tool')).length;
  const toolInfo = toolCount ? `${toolCount} ${toolCount === 1 ? 'tool step' : 'tool steps'}` : '';
  const metaBits = [stepInfo, toolInfo, approval].filter(Boolean);
  const latestReply = sourceCodingLatestAssistantText(snapshot);
  const completed = latestTask.events.some((event) => {
    const t = String(event?.type || '').toLowerCase();
    return t.includes('task_completed') || t === 'result' || t === 'final';
  });
  liveEl.className = `source-coding-live ${approval ? 'attention' : completed ? 'done' : 'active'}`;
  summaryEl.textContent = summary;
  metaEl.textContent = metaBits.length ? metaBits.join(' • ') : (completed ? 'Last coding task completed.' : 'Coding session is working.');
  replyEl.textContent = latestReply || (completed ? 'The last coding task completed without a readable reply body.' : 'No coding reply yet.');
}
async function refreshSourceCodingActivity() {
  if (!sourceCodingSessionId) {
    renderSourceCodingActivityFromSnapshot([]);
    return;
  }
  if (isSelectedSessionSourceCodingSession()) return;
  const snapshot = await api(`/v1/sessions/${encodeURIComponent(sourceCodingSessionId)}/events/snapshot?latest=true&limit=80`);
  renderSourceCodingActivityFromSnapshot(snapshot || []);
}
function startSourceCodingPoll() {
  stopSourceCodingPoll();
  sourceCodingPoll = setInterval(() => {
    if (!sourceCodingSessionId) return;
    if (isSelectedSessionSourceCodingSession()) return;
    refreshSourceCodingActivity().catch(()=>{});
  }, 2000);
}
function stopSourceCodingPoll() {
  if (sourceCodingPoll) clearInterval(sourceCodingPoll);
  sourceCodingPoll = null;
}
async function ensureSourceCodingSession() {
  const defaults = sourceCodingDefaults();
  const toolIds = selectedSourceToolIds();
  const toolPaths = toolIds.map((id) => `plugins/${id}`);
  if (!defaults.contextId && !defaults.workspaceId && !defaults.workspaceProfile && !defaults.workspacePath) throw new Error('Select a context, workspace, or source context first.');
  if (!defaults.endpointId) throw new Error('No online endpoint is available for the coding session.');
  if (defaults.existingSession?.id) {
    sourceCodingSessionId = defaults.existingSession.id;
    selectedIdeSessionId = defaults.existingSession.id;
    return defaults.existingSession;
  }
  if (defaults.contextId) {
    const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(defaults.contextId)}/session`, {method:'POST'});
    const session = ensured.session;
    sourceCodingSessionId = session.id;
    selectedIdeSessionId = session.id;
    if (ensured.context?.workspace_id) selectedIdeWorkspaceId = ensured.context.workspace_id;
    await loadWorkspaceCatalogs().catch(()=>{});
    await loadSessions();
    updateSourceCodingPanel();
    sourceTreeCache.clear();
    await renderSources('');
    return session;
  }
  if (defaults.workspaceId) {
    const ensured = await api(`/v1/my-workspaces/${encodeURIComponent(defaults.workspaceId)}/session`, {method:'POST'});
    const session = ensured.session;
    sourceCodingSessionId = session.id;
    selectedIdeSessionId = session.id;
    await loadWorkspaceCatalogs().catch(()=>{});
    await loadSessions();
    updateSourceCodingPanel();
    sourceTreeCache.clear();
    await renderSources('');
    return session;
  }
  const sessionNameBase = defaults.workspaceProfile || sourceResolvedContext?.name || sourceFileLabel(selectedSourceFolder || selectedSourcePath || 'ide');
  const payload = {
    name: `code-${String(sessionNameBase).replace(/[^A-Za-z0-9._-]+/g, '-').toLowerCase()}`,
    agent_profile: defaults.profileName || null,
    model: defaults.modelName || null,
    workspace: defaults.workspaceProfile ? {type: 'profile', profile: defaults.workspaceProfile} : {type: 'local', path: defaults.workspacePath},
    metadata: {
      preferred_endpoint: defaults.endpointId,
      endpoint_locked: true,
      agent_enabled: true,
      execution_mode: 'pi.dev',
      preferred_execution_mode: 'container',
      container_image: defaults.containerImage,
      ide_mode: true,
      ide_stack: defaults.stack,
      ide_source_path: selectedSourceFolder || selectedSourcePath || '',
      ide_open_files: sourceOpenTabs.slice(),
      source_context_name: defaults.contextName || null,
      workspace_profile: defaults.workspaceProfile || null,
      agent_tool_ids: toolIds,
      agent_tool_paths: toolPaths,
      tool_source_mode: 'jit-workspace',
      workspace_trusted: true,
    },
  };
  const session = await api('/v1/sessions', {method:'POST', body: JSON.stringify(payload)});
  sourceCodingSessionId = session.id;
  selectedIdeSessionId = session.id;
  startSourceCodingPoll();
  await loadSessions();
  updateSourceCodingPanel();
  sourceTreeCache.clear();
  await renderSources('');
  return session;
}
function buildSourceCodingPrompt(userPrompt='') {
  const prompt = String(userPrompt || '').trim();
  const currentFile = selectedSourcePath || '';
  const openFiles = sourceOpenTabs.slice();
  const filePayload = sourceOpenFilePayload();
  const toolPayload = sourceToolPayload();
  const parts = [
    'You are working from the PAC IDE coding workbench.',
    'Focus on code, build failures, runtime errors, tests, and direct fixes in the selected workspace.',
    `Current source path: ${selectedSourceEntry || selectedSourceFolder || currentFile || '-'}.`,
    `Open files: ${openFiles.length ? openFiles.join(', ') : 'none'}.`,
  ];
  if (currentFile) parts.push(`Current file: ${currentFile}.`);
  if (sourceResolvedContext?.name) parts.push(`Resolved source context: ${sourceResolvedContext.name}.`);
  if (toolPayload.length) {
    parts.push('', 'Selected agent tools live in the same trusted workspace and should be used as live source context:');
    toolPayload.forEach((tool) => {
      parts.push(`Tool: ${tool.id} (${tool.kind}) at ${tool.source_path}`);
      if (tool.description) parts.push(tool.description);
      if (tool.requires_tools?.length) parts.push(`Requires runtime tools: ${tool.requires_tools.join(', ')}`);
      if (tool.documentation) parts.push(`Notes: ${tool.documentation}`);
      parts.push('');
    });
  }
  if (filePayload.length) {
    parts.push('', 'Open file context:');
    filePayload.forEach((item) => {
      parts.push(`File: ${item.path}${item.active ? ' [active]' : ''}${item.dirty ? ' [dirty]' : ''}`);
      parts.push(item.content || '[file is open but its contents are not loaded]');
      parts.push('');
    });
  }
  if (prompt) parts.push('', prompt);
  else parts.push('', 'Inspect the current workspace and help with the open files.');
  return parts.join('\n');
}
async function sendPromptToSourceCodingSession(promptText) {
  const session = await ensureSourceCodingSession();
  const defaults = sourceCodingDefaults();
  const openFilePayload = sourceOpenFilePayload();
  const toolIds = selectedSourceToolIds();
  const toolPayload = sourceToolPayload();
  const status = document.getElementById('sourceCodingStatus');
  const liveEl = document.getElementById('sourceCodingLiveStatus');
  const summaryEl = document.getElementById('sourceCodingLiveSummary');
  const metaEl = document.getElementById('sourceCodingLiveMeta');
  if (status) { status.hidden = false; status.textContent = 'Submitting coding task…'; }
  if (liveEl && summaryEl && metaEl) {
    liveEl.className = 'source-coding-live active';
    summaryEl.textContent = 'Submitting coding task';
    metaEl.textContent = 'Waiting for the coding session to accept the new request.';
  }
  const payload = {
    prompt: buildSourceCodingPrompt(promptText),
    metadata: {
      execution_mode: 'container',
      container_image: defaults.containerImage,
      open_files: sourceOpenTabs.slice(),
      open_file_payload: openFilePayload,
      agent_tool_ids: toolIds,
      agent_tool_payload: toolPayload,
      current_file: selectedSourcePath || '',
      source_context_name: sourceResolvedContext?.name || null,
    },
  };
  await api(`/v1/sessions/${encodeURIComponent(session.id)}/tasks`, {method:'POST', body: JSON.stringify(payload)});
  if (status) status.textContent = 'Coding task submitted.';
  await refreshSourceCodingActivity().catch(()=>{});
}
