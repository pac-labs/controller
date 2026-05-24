// Agent context label helpers and session summary rendering.
function ideContexts() {
  return (agentContexts || []).slice().sort((a, b) => {
    if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
    if (!!a.system_context !== !!b.system_context) return a.system_context ? -1 : 1;
    return String(a.name || '').localeCompare(String(b.name || ''));
  });
}

function isProtectedAgentContext(item) {
  return !!(item?.protected || item?.system_context || item?.metadata?.system_context || item?.metadata?.builtin_kind === 'pac_admin_base');
}

function selectedSessionContextId() {
  return String(selectedSession?.metadata?.agent_context_id || '').trim();
}

window.selectedSessionContextId = selectedSessionContextId;

function systemContextWorkspaceLabel(item) {
  return item?.workspace_label || item?.metadata?.workspace_label || 'PAC';
}

function contextWorkspaceLabel(item) {
  if (isProtectedAgentContext(item)) return systemContextWorkspaceLabel(item);
  return item?.workspace?.name || item?.workspace_template?.name || item?.controller_workdir || 'none';
}

function contextRuntimeLabel(item) {
  if (!item) return 'auto';
  if (isProtectedAgentContext(item)) return item?.runtime_label || item?.metadata?.runtime_label || item?.endpoint_id || 'local-PAC';
  if (item.controller_workdir) return item.endpoint_id || 'controller';
  return item.endpoint_id || item.endpoint_selector || 'auto';
}

function sessionContextLabel(session = selectedSession) {
  return String(session?.metadata?.agent_context_name || '').trim();
}

function renderSelectedSessionSummary(session = selectedSession) {
  if (!session) return;
  const preferredEndpoint = session.metadata?.preferred_endpoint || '';
  const endpointName = (window.__pacEndpoints || []).find((e) => e.id === preferredEndpoint)?.name || preferredEndpoint || 'PAC/local';
  const contextName = sessionContextLabel(session);
  const summaryEl = document.getElementById('selectedSession');
  if (summaryEl) {
    summaryEl.innerHTML = `<span class="session-lock-dot"></span><span>Profile: ${escapeHtml(session.agent_profile || 'default')}</span><span>Permissions: ${escapeHtml(session.permission_profile || '-')}</span><span>Endpoint: ${escapeHtml(endpointName)}</span><span>Mode: ${escapeHtml(session.metadata?.execution_mode || (session.metadata?.agent_enabled === false ? 'direct model' : 'pi.dev'))}</span>${contextName ? `<span>Context: ${escapeHtml(contextName)}</span>` : ''}<span>Model: ${escapeHtml(session.model || '')}</span><span>${escapeHtml(session.workspace_path || '')}</span>`;
  }
  const lockEl = document.getElementById('sessionEndpointLock');
  if (lockEl) {
    lockEl.textContent = `Profile: ${session.agent_profile || 'default'} · permissions: ${session.permission_profile || '-'} · endpoint: ${endpointName}${contextName ? ` · context: ${contextName}` : ''} · model: ${session.model || 'session default'}`;
  }
}

function renderAgentContextUsageCard(item) {
  const usageEl = document.getElementById('agentContextUsage');
  if (!usageEl) return;
  if (!item) {
    usageEl.innerHTML = '<div class="muted small-text">Pick a context in Sessions or IDE to launch work with the right workspace, profile, tools, and models.</div>';
    return;
  }
  const groups = (item.use_groups || []).length ? item.use_groups.join(', ') : 'all allowed users';
  usageEl.innerHTML = `<div class="source-sidecard">
    <div class="section-heading compact-heading"><div><h3>${escapeHtml(item.name)}</h3><p class="muted">${escapeHtml(item.description || 'No description yet.')}</p></div></div>
    <div class="workspace-card-grid">
      <div><small>kind</small><b>${escapeHtml(item.kind || 'coding')}</b></div>
      <div><small>workspace</small><b>${escapeHtml(contextWorkspaceLabel(item))}</b></div>
      <div><small>runtime</small><b>${escapeHtml(contextRuntimeLabel(item))}</b></div>
      <div><small>profile</small><b>${escapeHtml(item.agent_profile || 'default')}</b></div>
      <div><small>executor</small><b>${escapeHtml(item.executor_model || '-')}</b></div>
      <div><small>groups</small><b>${escapeHtml(groups)}</b></div>
    </div>
  </div>`;
}

function applyIdeContextSelection(contextId = '') {
  const item = ideContexts().find((context) => context.id === contextId);
  selectedIdeContextId = item?.id || '';
  if (item?.workspace_id) selectedIdeWorkspaceId = item.workspace_id;
  if (!item) {
    renderAgentContextUsageCard(null);
    return;
  }
  const set = (fieldId, value='') => {
    const el = document.getElementById(fieldId);
    if (el) el.value = value ?? '';
  };
  set('sessionAgentContext', item.id);
  set('composerAgentContext', item.id);
  set('agentProfile', item.agent_profile || '');
  set('workspaceProfile', item.workspace?.workspace_profile || item.workspace_template?.workspace_profile || '');
  set('sessionEndpoint', item.endpoint_id || '');
  set('modelOverride', item.executor_model || '');
  set('permissionOverride', item.permission_profile || '');
  set('contextMode', item.context_mode || '');
  renderAgentContextUsageCard(item);
}
