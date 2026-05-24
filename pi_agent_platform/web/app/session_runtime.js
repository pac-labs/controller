// Session list loading, selection, event stream attachment, and task event append

async function loadSessions() {
  const sessions = await api('/v1/sessions');
  window.__pacSessions = sessions;
  if (selectedIdeSessionId && !sessions.some((session) => session.id === selectedIdeSessionId)) selectedIdeSessionId = '';
  if (sourceCodingSessionId && !sessions.some((session) => session.id === sourceCodingSessionId)) sourceCodingSessionId = '';
  ensureSessionWorkspaceChrome();
  const dashboard = document.getElementById('sessions');
  const picker = document.getElementById('sessionTopSelect');
  if (dashboard) dashboard.innerHTML = '';
  if (picker) picker.innerHTML = '<option value="">Select session</option>';
  if (!sessions.length) {
    selectedSession = null;
    activeSessionTaskId = null;
    if (dashboard) dashboard.innerHTML = '<div class="muted">No sessions yet. Create one from the Sessions page.</div>';
    if (picker) picker.innerHTML = '<option value="">No sessions yet</option>';
    syncSessionPermissionQuick();
  updateComposerChrome();
    refreshSessionRunButton().catch(()=>{});
    renderModelActiveSessionsPanel();
    renderProfileUsagePanel();
    renderWorkspaceActivityPanel();
    renderSessionSidebar([]);
    const composerContext = document.getElementById('composerAgentContext');
    if (composerContext) composerContext.value = selectedIdeContextId || '';
    renderIdeWorkspaceSelectors();
    updateSourceCodingPanel();
    return;
  }
  sessions.slice().reverse().forEach(s => {
    if (picker) {
      const label = `${s.name || s.id} · ${s.agent_profile || 'profile'} · ${s.model || 'model'}`;
      opt(picker, s.id, label);
    }
    if (dashboard) {
      const row = document.createElement('div'); row.className='row session-row';
      row.innerHTML = `<div><b>${s.name || s.id}</b> <span class="pill">${s.status || 'created'}</span><br><span class="muted">${s.agent_profile || '-'} / ${s.model} / ${s.permission_profile}</span><br><span class="muted">${s.workspace_path || ''}</span></div>`;
      const b=document.createElement('button'); b.textContent='Open'; b.onclick=()=>{ switchToTab('sessions-tab'); selectSession(s.id); };
      row.appendChild(b); dashboard.appendChild(row);
    }
  });
  if (picker && selectedSession?.id) picker.value = selectedSession.id;
  renderSessionSidebar(sessions);
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  renderModelActiveSessionsPanel();
  renderProfileUsagePanel();
  renderWorkspaceActivityPanel();
  updateSourceCodingPanel();
}

async function selectSession(id) {
  ensureSessionWorkspaceChrome();
  sessionHydrationToken += 1;
  selectedSession = await api(`/v1/sessions/${id}`);
  const preferredEndpoint = selectedSession.metadata?.preferred_endpoint || '';
  const currentContextId = window.selectedSessionContextId?.() || '';
  renderSelectedSessionSummary(selectedSession);
  if (document.getElementById('sessionTopSelect')) sessionTopSelect.value = selectedSession.id;
  if (document.getElementById('composerAgentContext')) composerAgentContext.value = currentContextId || '';
  if (document.getElementById('taskRunner')) taskRunner.value = preferredEndpoint || '';
  syncSessionPermissionQuick();
  updateComposerChrome();
  const timeline = document.getElementById('events');
  if (timeline) timeline.innerHTML = '<div class="empty-timeline">Waiting for session events.</div>';
  renderComposerThinkingStatus(null);
  updateComposerChrome();
  resetSessionTimelineState();
  renderSessionSidebar(window.__pacSessions || []);
  updateSourceCodingPanel();
  try {
    const snapshot = await api(`/v1/sessions/${id}/events/snapshot?latest=true&limit=220`);
    renderSessionSnapshotFast(snapshot, id);
  } catch (_) {
    suppressSessionAutoScroll = false;
  }
  if (source) {
    source.close();
    source = null;
  }
  if (authStatus?.enabled) {
    startSessionPolling(id);
    pollSessionEvents(id).catch(()=>{});
  } else {
    source = new EventSource(`/v1/sessions/${id}/events`);
    source.onerror = () => {
      if (source) {
        source.close();
        source = null;
      }
      startSessionPolling(id);
    };
    source.onmessage = (e) => { try { appendEvent('message', JSON.parse(e.data)); } catch { appendEvent('message', e.data); } };
    ['user_message','agent_routing','agent_intent','agent_plan','task_queued','stdout','stderr','task_started','task_completed','task_failed','approval_required','task_approved','task_rejected','session_created','agent_loop_started','agent_thinking','model_response','tool_call','tool_result','result','final','full_control_enabled','subagent_started'].forEach((t) => source.addEventListener(t, (e) => { try { appendEvent(t, JSON.parse(e.data)); } catch { appendEvent(t, e.data); } }));
    stopSessionPolling();
  }
  await refreshSessionRunButton().catch(()=>{});
}

function appendEvent(type, payload) {
  const event = normalizeEvent(type, payload);
  if (selectedSession?.id && sessionHydrationActiveFor === selectedSession.id) {
    sessionHydrationBufferedEvents.push(event);
  }
  renderSessionTimelineEvent(event);
  renderGlobalEvent(event);
  if (selectedSession?.id && selectedSession.id === event.session_id) {
    const eventType = String(event?.type || '').toLowerCase();
    if (eventType.includes('result') || eventType.includes('task_completed') || eventType.includes('task_failed')) refreshComposerThinkingStatusForTask(event.task_id);
  }
  const eventType = String(event?.type || type || '').toLowerCase();
  if (
    eventType.includes('approval') ||
    eventType.includes('task_queued') ||
    eventType.includes('task_started') ||
    eventType.includes('task_completed') ||
    eventType.includes('task_failed') ||
    eventType.includes('result') ||
    eventType.includes('agent_stop')
  ) {
    loadApprovals().catch(()=>{});
    refreshSessionRunButton().catch(()=>{});
  }
}

async function loadApprovals() {
  if (approvalsRequest) return approvalsRequest;
  approvalsRequest = (async () => {
    const tasks = await api('/v1/tasks/pending-approvals');
    const el = document.getElementById('approvals'); el.innerHTML = '';
    tasks.forEach(t => {
      const row=document.createElement('div'); row.className='row';
      row.innerHTML=`<div><b>${t.command || t.prompt}</b><br><span class="muted">${t.session_id}</span></div>`;
      const a=document.createElement('button'); a.textContent='Approve'; a.onclick=async()=>{await resolveSessionApproval(t.id, true);};
      const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await resolveSessionApproval(t.id, false);};
      row.append(a,r); el.appendChild(row);
    });
  })();
  try {
    return await approvalsRequest;
  } finally {
    approvalsRequest = null;
  }
}
