// IDE workspace/session context helpers for source browsing.
function detectSourceTech(paths = sourceOpenTabs) {
  const counts = new Map();
  for (const path of (paths || [])) {
    const match = /\.[A-Za-z0-9]+$/.exec(String(path || '').toLowerCase());
    const key = match ? match[0] : '';
    const spec = SOURCE_TECH_MAP[key];
    if (!spec) continue;
    counts.set(spec.stack, (counts.get(spec.stack) || 0) + 1);
  }
  const winner = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] || 'workspace';
  const byStack = Object.values(SOURCE_TECH_MAP).find(item => item.stack === winner);
  return {stack: winner, ...(byStack || {container: 'localhost/python-dev:latest', profileHints: ['coder']})};
}
function guessProfileForTech(stackSpec) {
  const ctxProfile = sourceResolvedContext?.context?.profile;
  if (ctxProfile && config.agent_profiles?.[ctxProfile]) return ctxProfile;
  const hints = stackSpec?.profileHints || ['coder'];
  const entries = Object.entries(config.agent_profiles || {});
  for (const [name] of entries) {
    const lower = String(name || '').toLowerCase();
    if (hints.some(h => lower.includes(h))) return name;
  }
  for (const [name] of entries) {
    const lower = String(name || '').toLowerCase();
    if (lower.includes('coder') || lower.includes('coding') || lower.includes('code') || lower.includes('dev')) return name;
  }
  if (config.agent_profiles?.['main-pi-dev']) return 'main-pi-dev';
  return entries[0]?.[0] || '';
}
function guessModelForTech(stackSpec, profileName='') {
  const entries = Object.entries(config.models || {}).filter(([name, model]) => {
    const av = modelAvailability(name);
    return av.ok && (model.capabilities?.supports_tools || model.capabilities?.supports_chat);
  });
  const hints = [...(stackSpec?.profileHints || []), 'coder', 'code'];
  for (const [name] of entries) {
    const lower = String(name || '').toLowerCase();
    if (hints.some(h => lower.includes(h))) return name;
  }
  return entries[0]?.[0] || '';
}
function defaultEndpointForSource() {
  const ctxEndpoint = sourceResolvedContext?.context?.preferred_endpoint;
  if (ctxEndpoint) return ctxEndpoint;
  const sessionEndpoint = selectedSession?.metadata?.preferred_endpoint;
  if (sessionEndpoint) return sessionEndpoint;
  return (window.__pacEndpoints || []).find(r => r.status === 'online')?.id || '';
}
function codingSessions() {
  return (window.__pacSessions || []).filter((session) => {
    const meta = session.metadata || {};
    return !!(meta.ide_mode || meta.coding_session);
  });
}
function ideWorkspaces() {
  return Array.isArray(personalWorkspaces) ? personalWorkspaces.slice() : [];
}
function currentIdeWorkspace() {
  const id = selectedIdeWorkspaceId || '';
  if (!id) return null;
  return ideWorkspaces().find((item) => item.id === id) || null;
}
function currentIdeSession() {
  const workspace = currentIdeWorkspace();
  const id = selectedIdeSessionId || sourceCodingSessionId || workspace?.last_session_id || '';
  if (!id) return null;
  return codingSessions().find((session) => session.id === id) || null;
}
function workspaceProfileForIdeSession(session) {
  const meta = session?.metadata || {};
  return String(meta.workspace_profile || '').trim();
}
function userWorkspaceForIdeSession(session) {
  const meta = session?.metadata || {};
  const workspaceId = String(meta.user_workspace_id || '').trim();
  if (workspaceId) return ideWorkspaces().find((item) => item.id === workspaceId) || null;
  return null;
}
function currentIdeContext() {
  return ideContexts().find((item) => item.id === selectedIdeContextId) || null;
}

function renderIdeWorkspaceSelectors() {
  const contextSelect = document.getElementById('ideContextSelect');
  const workspaceSelect = document.getElementById('ideWorkspaceSelect');
  const sessionSelect = document.getElementById('ideSessionSelect');
  if (!workspaceSelect || !sessionSelect) return;
  const contexts = ideContexts();
  const workspaces = ideWorkspaces();
  if (!selectedIdeContextId && contexts.length) {
    selectedIdeContextId = contexts.find((item) => item.pinned)?.id || contexts[0].id;
  }
  if (!selectedIdeWorkspaceId && selectedIdeSessionId) {
    const activeSession = codingSessions().find((session) => session.id === selectedIdeSessionId);
    const activeWorkspace = userWorkspaceForIdeSession(activeSession);
    if (activeWorkspace?.id) selectedIdeWorkspaceId = activeWorkspace.id;
  }
  const activeContext = currentIdeContext();
  if (activeContext?.workspace_id && !selectedIdeWorkspaceId) selectedIdeWorkspaceId = activeContext.workspace_id;
  if (contextSelect) {
    contextSelect.innerHTML = '<option value="">Select context</option>' + contexts.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    if (selectedIdeContextId && contexts.some((item) => item.id === selectedIdeContextId)) contextSelect.value = selectedIdeContextId;
  }
  if (!selectedIdeWorkspaceId && workspaces.length) {
    selectedIdeWorkspaceId = workspaces.find((item) => item.pinned)?.id || workspaces[0].id;
  }
  workspaceSelect.innerHTML = '<option value="">Select workspace</option>' + workspaces.map((item) => {
    const location = item.path || item.url || item.workspace_profile || '';
    return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}${location ? ` - ${escapeHtml(location)}` : ''}</option>`;
  }).join('');
  if (selectedIdeWorkspaceId && workspaces.some((item) => item.id === selectedIdeWorkspaceId)) workspaceSelect.value = selectedIdeWorkspaceId;
  const sessionEntries = codingSessions().filter((session) => {
    if (!selectedIdeWorkspaceId) return true;
    return String(session?.metadata?.user_workspace_id || '') === selectedIdeWorkspaceId;
  });
  sessionSelect.innerHTML = '<option value="">Select coding session</option>' + sessionEntries.map((session) => `<option value="${escapeHtml(session.id)}">${escapeHtml(session.name || session.id)}</option>`).join('');
  const activeSessionId = selectedIdeSessionId || sourceCodingSessionId || '';
  if (activeSessionId && sessionEntries.some((session) => session.id === activeSessionId)) sessionSelect.value = activeSessionId;
}
function sourceWorkspaceAbsolutePath() {
  const workspace = currentIdeWorkspace();
  if (workspace) {
    const ideSession = currentIdeSession();
    return String(ideSession?.workspace_path || workspace.path || workspace.workspace_profile || '').replace(/\\/g, '/');
  }
  const ctx = sourceResolvedContext?.context || {};
  const rel = ctx.path_prefix || selectedSourceFolder || selectedSourcePath || '';
  if (!rel) return sourceLibraryRoot || '';
  if (/^[A-Za-z]:[\\/]/.test(rel) || rel.startsWith('/')) return rel;
  if (!sourceLibraryRoot) return rel;
  return `${String(sourceLibraryRoot).replace(/[\\/]+$/, '')}/${String(rel).replace(/^[\\/]+/, '')}`.replace(/\\/g, '/');
}
function findCodingSessionForSource(workspacePath, endpointId, workspaceProfile='') {
  return codingSessions().find((session) => {
    const meta = session.metadata || {};
    const sessionWorkspaceId = String(meta.user_workspace_id || '').trim();
    if (selectedIdeWorkspaceId) {
      return sessionWorkspaceId === selectedIdeWorkspaceId;
    }
    const sessionWorkspaceProfile = String(meta.workspace_profile || '').trim();
    if (workspaceProfile) return sessionWorkspaceProfile === workspaceProfile && String(meta.preferred_endpoint || '') === String(endpointId || '');
    return !!meta.ide_mode && String(session.workspace_path || '') === String(workspacePath || '') && String(meta.preferred_endpoint || '') === String(endpointId || '');
  }) || null;
}
function sourceCodingDefaults() {
  const stackSpec = detectSourceTech();
  const contextEntry = currentIdeContext();
  const workspaceEntry = currentIdeWorkspace();
  const workspaceTemplate = workspaceEntry?.template || null;
  const workspaceProfile = workspaceEntry?.workspace_profile && config.workspaces?.[workspaceEntry.workspace_profile]
    ? config.workspaces[workspaceEntry.workspace_profile]
    : null;
  const endpointId = contextEntry?.endpoint_id || workspaceEntry?.endpoint_id || workspaceTemplate?.endpoint_id || workspaceProfile?.endpoint_id || defaultEndpointForSource();
  const profileName = contextEntry?.agent_profile || workspaceEntry?.agent_profile || workspaceTemplate?.agent_profile || workspaceProfile?.default_agent_profile || guessProfileForTech(stackSpec);
  const modelName = contextEntry?.executor_model || workspaceEntry?.model || guessModelForTech(stackSpec, profileName);
  const ctx = sourceResolvedContext?.context || {};
  const workspacePath = sourceWorkspaceAbsolutePath();
  const existing = contextEntry?.last_session_id
    ? ((window.__pacSessions || []).find((session) => session.id === contextEntry.last_session_id) || null)
    : workspaceEntry?.last_session_id
    ? ((window.__pacSessions || []).find((session) => session.id === workspaceEntry.last_session_id) || null)
    : findCodingSessionForSource(workspacePath, endpointId, workspaceEntry?.workspace_profile || '');
  return {
    stack: stackSpec.stack,
    containerImage: contextEntry?.container_image || workspaceEntry?.container_image || workspaceTemplate?.container_image || workspaceProfile?.container_image || ctx.container_image || stackSpec.container,
    endpointId,
    profileName,
    modelName,
    workspacePath,
    workspaceId: workspaceEntry?.id || '',
    workspaceName: workspaceEntry?.name || '',
    workspaceProfile: workspaceEntry?.workspace_profile || '',
    contextId: contextEntry?.id || '',
    contextName: contextEntry?.name || sourceResolvedContext?.name || '',
    contextPermission: contextEntry?.permission_profile || '',
    contextTools: contextEntry?.tools || [],
    existingSession: existing,
  };
}
function ideUsesSessionWorkspace() {
  return !!(selectedIdeWorkspaceId || selectedIdeSessionId || sourceCodingSessionId);
}
function ideFsBasePath(path='') {
  const value = String(path || '').trim().replace(/\\/g, '/');
  if (!value || value === '.' || value === '/') return '';
  return value.replace(/^\/+/, '').replace(/\/+$/, '');
}
async function ensureIdeDirLoaded(path='') {
  const session = currentIdeSession();
  if (!session) throw new Error('Select or start a coding session for a workspace first.');
  const relPath = ideFsBasePath(path);
  const qs = relPath ? `?path=${encodeURIComponent(relPath)}` : '';
  const data = await api(`/v1/sessions/${encodeURIComponent(session.id)}/files${qs}`);
  const cachePath = ideFsBasePath(data.path ?? relPath);
  const normalizedItems = Array.isArray(data.items) ? data.items.map((item) => ({
    ...item,
    path: ideFsBasePath(item.path || (cachePath ? `${cachePath}/${item.name}` : item.name)),
  })) : [];
  const normalized = {path: cachePath, items: normalizedItems, type: data.type || 'dir'};
  sourceTreeCache.set(cachePath, normalized);
  return normalized;
}
function sourceOpenFilesSummaryHtml() {
  const files = sourceOpenTabs.slice();
  if (!files.length) return 'No open files yet.';
  return files.map(path => `<div class="inline-browser-row"><div><b>${escapeHtml(sourceFileLabel(path))}</b><div class="muted small-text">${escapeHtml(path)}</div></div></div>`).join('');
}
