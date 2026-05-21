// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

function selectedMultiValues(fieldId) {
  const el = document.getElementById(fieldId);
  if (!el) return [];
  return Array.from(el.selectedOptions || []).map((o) => o.value).filter(Boolean);
}

function setSelectedMultiValues(fieldId, values = []) {
  const wanted = new Set(values || []);
  const el = document.getElementById(fieldId);
  if (!el) return;
  Array.from(el.options || []).forEach((o) => { o.selected = wanted.has(o.value); });
}

function storageNameById(id) {
  const item = (sharedStorages || []).find((entry) => entry.id === id);
  return item ? item.name : (id || '-');
}

function renderSharedStorages() {
  const listEl = document.getElementById('sharedStorageList');
  const selectIds = [
    'userWorkspaceSharedStorage',
    'agentContextSharedStorage',
    'workspaceSharedStorage',
    'sourceStorageSelect',
  ];
  const options = (sharedStorages || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  selectIds.forEach((fieldId) => {
    const el = document.getElementById(fieldId);
    if (!el) return;
    const current = el.value;
    el.innerHTML = `<option value="">none</option>${options}`;
    if (current && (sharedStorages || []).some((item) => item.id === current)) el.value = current;
  });
  if (!listEl) return;
  listEl.innerHTML = (sharedStorages || []).map((item) => `
    <div class="workspace-card clickable-row" data-shared-storage="${escapeHtml(item.id)}">
      <div class="workspace-card-title"><b>${escapeHtml(item.name)}</b><span>${escapeHtml(item.driver || 'custom')}</span></div>
      <div class="workspace-card-grid">
        <div><small>controller</small><b>${escapeHtml(item.controller_path || '-')}</b></div>
        <div><small>network</small><b>${escapeHtml(item.network_path || '-')}</b></div>
        <div><small>mount</small><b>${escapeHtml(item.mount_path || '/workspace')}</b></div>
        <div><small>mode</small><b>${item.writable ? 'rw' : 'ro'}</b></div>
      </div>
      <code>${escapeHtml(item.description || '')}${item.description ? '\n' : ''}selector: ${escapeHtml(item.endpoint_selector || '-')}\ndefault subpath: ${escapeHtml(item.default_subpath || '-')}</code>
    </div>`).join('') || '<div class="muted">No shared storage defined yet.</div>';
  listEl.querySelectorAll('[data-shared-storage]').forEach((row) => {
    row.onclick = () => fillSharedStorageForm(row.getAttribute('data-shared-storage') || '');
  });
}

function fillSharedStorageForm(id = '') {
  const item = (sharedStorages || []).find((entry) => entry.id === id);
  const set = (fieldId, value='') => { const el = document.getElementById(fieldId); if (el) el.value = value ?? ''; };
  set('sharedStorageSelect', item?.id || '');
  set('sharedStorageName', item?.name || '');
  set('sharedStorageDescription', item?.description || '');
  set('sharedStorageDriver', item?.driver || 'nfs');
  set('sharedStorageNetworkPath', item?.network_path || '');
  set('sharedStorageControllerPath', item?.controller_path || '');
  set('sharedStorageMountPath', item?.mount_path || '/workspace');
  set('sharedStorageEndpointSelector', item?.endpoint_selector || '');
  set('sharedStorageEndpointIds', (item?.endpoint_ids || []).join(', '));
  set('sharedStorageDefaultSubpath', item?.default_subpath || '');
  const writable = document.getElementById('sharedStorageWritable'); if (writable) writable.checked = item?.writable !== false;
}

function sharedStorageFormPayload() {
  return {
    name: (document.getElementById('sharedStorageName')?.value || '').trim(),
    description: (document.getElementById('sharedStorageDescription')?.value || '').trim() || null,
    driver: document.getElementById('sharedStorageDriver')?.value || 'nfs',
    network_path: (document.getElementById('sharedStorageNetworkPath')?.value || '').trim() || null,
    controller_path: (document.getElementById('sharedStorageControllerPath')?.value || '').trim() || null,
    mount_path: (document.getElementById('sharedStorageMountPath')?.value || '').trim() || '/workspace',
    endpoint_selector: (document.getElementById('sharedStorageEndpointSelector')?.value || '').trim() || null,
    endpoint_ids: csv(document.getElementById('sharedStorageEndpointIds')?.value || ''),
    writable: !!document.getElementById('sharedStorageWritable')?.checked,
    default_subpath: (document.getElementById('sharedStorageDefaultSubpath')?.value || '').trim() || null,
  };
}

async function saveSharedStorageFromForm() {
  const payload = sharedStorageFormPayload();
  if (!payload.name) return alert('Shared storage name is required');
  const existingId = document.getElementById('sharedStorageSelect')?.value || '';
  const path = existingId ? `/v1/shared-storages/${encodeURIComponent(existingId)}` : '/v1/shared-storages';
  const method = existingId ? 'PUT' : 'POST';
  const result = await api(path, {method, body: JSON.stringify(payload)});
  await loadWorkspaceCatalogs();
  fillSharedStorageForm(result.storage?.id || '');
  renderSharedStorages();
  showInline('sharedStorageFormResult', `Saved shared storage ${payload.name}`);
}

async function deleteSharedStorageFromForm() {
  const id = document.getElementById('sharedStorageSelect')?.value || '';
  if (!id) return alert('Select an existing shared storage first');
  if (!confirm('Delete this shared storage?')) return;
  await api(`/v1/shared-storages/${encodeURIComponent(id)}`, {method:'DELETE'});
  await loadWorkspaceCatalogs();
  fillSharedStorageForm('');
  renderSharedStorages();
  showInline('sharedStorageFormResult', 'Shared storage deleted');
}

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

function renderAgentContexts() {
  const listEl = document.getElementById('agentContexts');
  const selectEl = document.getElementById('agentContextSelect');
  const sessionSelect = document.getElementById('sessionAgentContext');
  const composerSelect = document.getElementById('composerAgentContext');
  const ideSelect = document.getElementById('ideContextSelect');
  const workspaceSelect = document.getElementById('agentContextWorkspace');
  const templateSelect = document.getElementById('agentContextTemplate');
  const storageSelect = document.getElementById('agentContextSharedStorage');
  const endpointSelect = document.getElementById('agentContextEndpoint');
  const profileSelect = document.getElementById('agentContextProfile');
  const permissionSelect = document.getElementById('agentContextPermission');
  const executorSelect = document.getElementById('agentContextExecutorModel');
  const plannerSelect = document.getElementById('agentContextPlannerModel');
  const reviewerSelect = document.getElementById('agentContextReviewerModel');
  const retrievalSelect = document.getElementById('agentContextRetrievalModel');
  const toolsSelect = document.getElementById('agentContextTools');
  const groupsSelect = document.getElementById('agentContextUseGroups');
  const editorsSelect = document.getElementById('agentContextEditorGroups');
  const contexts = ideContexts();
  const contextOptions = contexts.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (selectEl) {
    if (selectedIdeContextId && contexts.some((item) => item.id === selectedIdeContextId)) selectEl.value = selectedIdeContextId;
  }
  if (sessionSelect) sessionSelect.innerHTML = `<option value="">none</option>${contextOptions}`;
  if (composerSelect) {
    composerSelect.innerHTML = `<option value="">agent context</option>${contextOptions}`;
    composerSelect.value = selectedSessionContextId() || (!selectedSession ? (selectedIdeContextId || '') : '');
  }
  if (ideSelect) {
    ideSelect.innerHTML = `<option value="">Select context</option>${contextOptions}`;
    if (selectedIdeContextId && contexts.some((item) => item.id === selectedIdeContextId)) ideSelect.value = selectedIdeContextId;
  }
  if (workspaceSelect) {
    workspaceSelect.innerHTML = `<option value="">none</option>` + ideWorkspaces().map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (templateSelect) {
    templateSelect.innerHTML = `<option value="">none</option>` + workspaceTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (storageSelect) {
    storageSelect.innerHTML = `<option value="">none</option>` + (sharedStorages || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (endpointSelect) {
    endpointSelect.innerHTML = `<option value="">auto</option>`;
    (window.__pacEndpoints || []).forEach((runner) => opt(endpointSelect, runner.id, `${runner.name || runner.id} (${runner.status || 'unknown'})`));
  }
  const fillModelSelect = (el, empty='default') => {
    if (!el) return;
    el.innerHTML = `<option value="">${escapeHtml(empty)}</option>`;
    Object.keys(config.models || {}).forEach((name) => opt(el, name));
  };
  if (profileSelect) {
    profileSelect.innerHTML = '<option value="">default</option>';
    Object.entries(config.agent_profiles || {}).forEach(([name]) => opt(profileSelect, name));
  }
  if (permissionSelect) {
    permissionSelect.innerHTML = '<option value="">default</option>';
    Object.keys(config.permission_profiles || {}).forEach((name) => opt(permissionSelect, name));
  }
  fillModelSelect(executorSelect, 'default');
  fillModelSelect(plannerSelect, 'none');
  fillModelSelect(reviewerSelect, 'none');
  fillModelSelect(retrievalSelect, 'none');
  if (toolsSelect) {
    toolsSelect.innerHTML = '';
    Object.keys(config.tools || {}).forEach((name) => opt(toolsSelect, name));
  }
  const groups = window.__pacGroups || [];
  const fillGroupSelect = (el) => {
    if (!el) return;
    el.innerHTML = '';
    groups.forEach((group) => opt(el, group.id, group.name || group.id));
  };
  fillGroupSelect(groupsSelect);
  fillGroupSelect(editorsSelect);
  if (listEl) {
    listEl.innerHTML = contexts.map((item) => {
      const workspace = contextWorkspaceLabel(item);
      const runtime = contextRuntimeLabel(item);
      const storage = item.shared_storage?.name || storageNameById(item.shared_storage_id);
      const models = [item.executor_model, item.planner_model, item.reviewer_model, item.retrieval_model].filter(Boolean).length;
      const badges = [
        item.system_context ? '<span>system</span>' : '',
        item.pinned ? '<span>pinned</span>' : '',
        `<span>${escapeHtml(item.kind || 'coding')}</span>`,
      ].filter(Boolean).join('');
      return `<div class="workspace-card clickable-row ${item.id === selectedIdeContextId ? 'selected' : ''}" data-agent-context="${escapeHtml(item.id)}">
        <div class="workspace-card-title"><b>${escapeHtml(item.name)}</b><div class="workspace-card-badges">${badges}</div></div>
        <div class="workspace-card-grid">
          <div><small>workspace</small><b>${escapeHtml(workspace)}</b></div>
          <div><small>storage</small><b>${escapeHtml(storage || '-')}</b></div>
          <div><small>runtime</small><b>${escapeHtml(runtime)}</b></div>
          <div><small>profile</small><b>${escapeHtml(item.agent_profile || 'default')}</b></div>
          <div><small>models</small><b>${escapeHtml(String(models || 1))}</b></div>
        </div>
        <code>${escapeHtml(item.description || '')}${item.description ? '\n' : ''}executor: ${escapeHtml(item.executor_model || '-')}\nplanner: ${escapeHtml(item.planner_model || '-')}\nstorage path: ${escapeHtml(item.storage_subpath || '-')}\ntools: ${escapeHtml((item.tools || []).join(', ') || '-')}</code>
        <div class="workspace-card-actions">
          <button type="button" data-context-open="${escapeHtml(item.id)}">Open session</button>
          <button type="button" class="ghost-button" data-context-edit="${escapeHtml(item.id)}">Edit</button>
          ${isProtectedAgentContext(item) ? '' : `<button type="button" class="ghost-button" data-context-delete="${escapeHtml(item.id)}">Delete</button>`}
        </div>
      </div>`;
    }).join('') || '<div class="muted">No agent contexts yet. Use + to create one, then select it in Sessions or IDE.</div>';
    listEl.querySelectorAll('[data-agent-context]').forEach((row) => {
      row.onclick = (ev) => {
        if (ev.target.closest('button')) return;
        fillAgentContextForm(row.getAttribute('data-agent-context') || '');
      };
    });
    listEl.querySelectorAll('[data-context-edit]').forEach((button) => {
      button.onclick = (ev) => {
        ev.stopPropagation();
        openAgentContextWizard(button.getAttribute('data-context-edit') || '');
      };
    });
    listEl.querySelectorAll('[data-context-open]').forEach((button) => {
      button.onclick = async (ev) => {
        ev.stopPropagation();
        fillAgentContextForm(button.getAttribute('data-context-open') || '');
        await openAgentContextSessionFromForm();
      };
    });
    listEl.querySelectorAll('[data-context-delete]').forEach((button) => {
      button.onclick = async (ev) => {
        ev.stopPropagation();
        fillAgentContextForm(button.getAttribute('data-context-delete') || '');
        await deleteAgentContextFromForm();
      };
    });
  }
  renderAgentContextUsageCard(contexts.find((item) => item.id === selectedIdeContextId) || null);
}

function fillAgentContextForm(id='') {
  const item = ideContexts().find((context) => context.id === id);
  selectedIdeContextId = item?.id || '';
  const set = (fieldId, value='') => {
    const el = document.getElementById(fieldId);
    if (el) el.value = value ?? '';
  };
  set('agentContextSelect', item?.id || '');
  set('agentContextName', item?.name || '');
  set('agentContextDescription', item?.description || '');
  set('agentContextKind', item?.kind || 'coding');
  set('agentContextWorkspace', item?.workspace_id || '');
  set('agentContextTemplate', item?.workspace_template_id || '');
  set('agentContextControllerWorkdir', item?.controller_workdir || '');
  set('agentContextSharedStorage', item?.shared_storage_id || '');
  set('agentContextStorageSubpath', item?.storage_subpath || '');
  set('agentContextStorageMountPath', item?.storage_mount_path || '');
  set('agentContextEndpoint', item?.endpoint_id || '');
  set('agentContextContainerImage', item?.container_image || '');
  set('agentContextProfile', item?.agent_profile || '');
  set('agentContextPermission', item?.permission_profile || '');
  set('agentContextExecutorModel', item?.executor_model || '');
  set('agentContextPlannerModel', item?.planner_model || '');
  set('agentContextReviewerModel', item?.reviewer_model || '');
  set('agentContextRetrievalModel', item?.retrieval_model || '');
  set('agentContextMode', item?.context_mode || '');
  const pinned = document.getElementById('agentContextPinned'); if (pinned) pinned.checked = !!item?.pinned;
  const requiresContainer = document.getElementById('agentContextRequiresContainer'); if (requiresContainer) requiresContainer.checked = item?.requires_container !== false;
  setSelectedMultiValues('agentContextTools', item?.tools || []);
  setSelectedMultiValues('agentContextUseGroups', item?.use_groups || []);
  setSelectedMultiValues('agentContextEditorGroups', item?.editor_groups || []);
  applyIdeContextSelection(item?.id || '');
  applyAgentContextFieldLocks(item || null);
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
}

function applyAgentContextFieldLocks(item) {
  const system = isProtectedAgentContext(item);
  ['agentContextName', 'agentContextKind', 'agentContextWorkspace', 'agentContextTemplate', 'agentContextControllerWorkdir', 'agentContextSharedStorage', 'agentContextStorageSubpath', 'agentContextStorageMountPath', 'agentContextRequiresContainer'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') el.disabled = system;
    else if (id === 'agentContextControllerWorkdir') el.readOnly = system;
    else el.disabled = system;
  });
  const deleteBtn = document.getElementById('deleteAgentContext');
  if (deleteBtn) deleteBtn.hidden = system || !item?.id;
}

function agentContextFormPayload() {
  return {
    name: (document.getElementById('agentContextName')?.value || '').trim(),
    description: (document.getElementById('agentContextDescription')?.value || '').trim() || null,
    kind: document.getElementById('agentContextKind')?.value || 'coding',
    workspace_id: document.getElementById('agentContextWorkspace')?.value || null,
    workspace_template_id: document.getElementById('agentContextTemplate')?.value || null,
    controller_workdir: (document.getElementById('agentContextControllerWorkdir')?.value || '').trim() || null,
    shared_storage_id: document.getElementById('agentContextSharedStorage')?.value || null,
    storage_subpath: (document.getElementById('agentContextStorageSubpath')?.value || '').trim() || null,
    storage_mount_path: (document.getElementById('agentContextStorageMountPath')?.value || '').trim() || null,
    endpoint_id: document.getElementById('agentContextEndpoint')?.value || null,
    container_image: (document.getElementById('agentContextContainerImage')?.value || '').trim() || null,
    agent_profile: document.getElementById('agentContextProfile')?.value || null,
    permission_profile: document.getElementById('agentContextPermission')?.value || null,
    context_mode: document.getElementById('agentContextMode')?.value || null,
    executor_model: document.getElementById('agentContextExecutorModel')?.value || null,
    planner_model: document.getElementById('agentContextPlannerModel')?.value || null,
    reviewer_model: document.getElementById('agentContextReviewerModel')?.value || null,
    retrieval_model: document.getElementById('agentContextRetrievalModel')?.value || null,
    requires_container: !!document.getElementById('agentContextRequiresContainer')?.checked,
    pinned: !!document.getElementById('agentContextPinned')?.checked,
    tools: selectedMultiValues('agentContextTools'),
    use_groups: selectedMultiValues('agentContextUseGroups'),
    editor_groups: selectedMultiValues('agentContextEditorGroups'),
  };
}

async function saveAgentContextFromForm() {
  const payload = agentContextFormPayload();
  if (!payload.name) return alert('Context name is required');
  const existingId = document.getElementById('agentContextSelect')?.value || '';
  const path = existingId ? `/v1/agent-contexts/${encodeURIComponent(existingId)}` : '/v1/agent-contexts';
  const method = existingId ? 'PUT' : 'POST';
  const result = await api(path, {method, body: JSON.stringify(payload)});
  await loadWorkspaceCatalogs();
  const item = result.context || null;
  selectedIdeContextId = item?.id || selectedIdeContextId;
  fillAgentContextForm(selectedIdeContextId || '');
  renderAgentContexts();
  showInline('agentContextFormResult', `Saved context ${payload.name}`);
  closeAgentContextWizard();
}

async function deleteAgentContextFromForm() {
  const id = document.getElementById('agentContextSelect')?.value || '';
  if (!id) return alert('Select an existing context first');
  if (!confirm('Delete this agent context?')) return;
  await api(`/v1/agent-contexts/${encodeURIComponent(id)}`, {method:'DELETE'});
  await loadWorkspaceCatalogs();
  selectedIdeContextId = '';
  fillAgentContextForm('');
  renderAgentContexts();
  showInline('agentContextFormResult', 'Context deleted');
  closeAgentContextWizard();
}

async function openAgentContextSessionFromForm() {
  const id = document.getElementById('agentContextSelect')?.value || selectedIdeContextId || '';
  if (!id) return alert('Select a context first');
  const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(id)}/session`, {method:'POST'});
  selectedIdeContextId = ensured.context?.id || id;
  if (ensured.context?.workspace_id) selectedIdeWorkspaceId = ensured.context.workspace_id;
  sourceCodingSessionId = ensured.session?.id || sourceCodingSessionId;
  selectedIdeSessionId = ensured.session?.id || selectedIdeSessionId;
  await loadWorkspaceCatalogs();
  await loadSessions();
  switchToTab('sessions-tab');
  if (ensured.session?.id) await selectSession(ensured.session.id);
}

function renderAgentContextWizardProgress() {
  const progressEl = document.getElementById('agentContextWizardProgress');
  if (!progressEl) return;
  progressEl.innerHTML = AGENT_CONTEXT_WIZARD_STEPS.map((step, index) => `<button type="button" class="ghost-button ${index === agentContextWizardStepIndex ? 'active' : ''}" data-agent-context-step="${index}">${escapeHtml(step.label)}</button>`).join('');
  progressEl.querySelectorAll('[data-agent-context-step]').forEach((button) => {
    button.onclick = () => {
      agentContextWizardStepIndex = Number(button.getAttribute('data-agent-context-step') || 0);
      renderAgentContextWizard();
    };
  });
}

function renderAgentContextWizard() {
  renderAgentContextWizardProgress();
  AGENT_CONTEXT_WIZARD_STEPS.forEach((step, index) => {
    const el = document.getElementById(step.id);
    if (el) el.hidden = index !== agentContextWizardStepIndex;
  });
  const existingId = document.getElementById('agentContextSelect')?.value || '';
  const saveBtn = document.getElementById('saveAgentContext');
  const nextBtn = document.getElementById('agentContextWizardNext');
  const backBtn = document.getElementById('agentContextWizardBack');
  if (saveBtn) saveBtn.textContent = existingId ? 'Save changes' : 'Create context';
  if (nextBtn) nextBtn.hidden = agentContextWizardStepIndex >= AGENT_CONTEXT_WIZARD_STEPS.length - 1;
  if (backBtn) backBtn.disabled = agentContextWizardStepIndex <= 0;
}

function openAgentContextWizard(id = '') {
  fillAgentContextForm(id);
  agentContextWizardStepIndex = 0;
  renderAgentContextWizard();
  const modal = document.getElementById('agentContextWizardModal');
  if (modal) modal.hidden = false;
}

function closeAgentContextWizard() {
  const modal = document.getElementById('agentContextWizardModal');
  if (modal) modal.hidden = true;
}

function renderSessionSidebar(sessions = window.__pacSessions || []) {
  const list = document.getElementById('sessionSidebarList');
  if (!list) return;
  if (!sessions.length) {
    list.innerHTML = '<div class="muted">No sessions yet.</div>';
    return;
  }
  list.innerHTML = '';
  sessions.slice().reverse().forEach((s) => {
    const contextName = String(s?.metadata?.agent_context_name || '').trim();
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `session-sidebar-item${selectedSession?.id === s.id ? ' active' : ''}`;
    item.innerHTML = `<strong>${escapeHtml(s.name || s.id)}</strong><div class="session-sidebar-meta">${escapeHtml(s.agent_profile || '-')} · ${escapeHtml(s.model || '-')} · ${escapeHtml(s.permission_profile || '-')}</div>${contextName ? `<div class="session-sidebar-meta">${escapeHtml(contextName)}</div>` : ''}<div class="session-sidebar-meta">${escapeHtml(s.workspace_path || '')}</div>`;
    const del = document.createElement('button');
    del.className = 'session-delete-btn';
    del.title = 'Delete session';
    del.textContent = '×';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (!confirm(`Delete session '${s.name || s.id}'?`)) return;
      const r = await api(`/v1/sessions/${s.id}`, {method:'DELETE', body: JSON.stringify({remove_workspace: false})});
      if (r?.ok) {
        if (selectedSession?.id === s.id) switchSession(null);
        renderSessionSidebar();
      } else {
        alert(r?.error || 'Delete failed');
      }
    };
    item.appendChild(del);
    item.onclick = () => { switchToTab('sessions-tab'); selectSession(s.id); };
    list.appendChild(item);
  });
}

function applyAgentContextFieldLocks(item) {
  const system = isProtectedAgentContext(item);
  const disableIds = [
    'agentContextName',
    'agentContextDescription',
    'agentContextKind',
    'agentContextWorkspace',
    'agentContextTemplate',
    'agentContextControllerWorkdir',
    'agentContextSharedStorage',
    'agentContextStorageSubpath',
    'agentContextStorageMountPath',
    'agentContextEndpoint',
    'agentContextContainerImage',
    'agentContextRequiresContainer',
    'agentContextProfile',
    'agentContextPermission',
    'agentContextUseGroups',
    'agentContextEditorGroups',
  ];
  disableIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if ('disabled' in el) el.disabled = system;
    if ('readOnly' in el && id === 'agentContextControllerWorkdir') el.readOnly = system;
  });
  const deleteBtn = document.getElementById('deleteAgentContext');
  if (deleteBtn) deleteBtn.hidden = system || !item?.id;
}

function renderAgentContexts() {
  const listEl = document.getElementById('agentContexts');
  const selectEl = document.getElementById('agentContextSelect');
  const sessionSelect = document.getElementById('sessionAgentContext');
  const composerSelect = document.getElementById('composerAgentContext');
  const ideSelect = document.getElementById('ideContextSelect');
  const workspaceSelect = document.getElementById('agentContextWorkspace');
  const templateSelect = document.getElementById('agentContextTemplate');
  const storageSelect = document.getElementById('agentContextSharedStorage');
  const endpointSelect = document.getElementById('agentContextEndpoint');
  const profileSelect = document.getElementById('agentContextProfile');
  const permissionSelect = document.getElementById('agentContextPermission');
  const executorSelect = document.getElementById('agentContextExecutorModel');
  const plannerSelect = document.getElementById('agentContextPlannerModel');
  const reviewerSelect = document.getElementById('agentContextReviewerModel');
  const retrievalSelect = document.getElementById('agentContextRetrievalModel');
  const toolsSelect = document.getElementById('agentContextTools');
  const groupsSelect = document.getElementById('agentContextUseGroups');
  const editorsSelect = document.getElementById('agentContextEditorGroups');
  const contexts = ideContexts().slice().sort((a, b) => {
    const aRank = isProtectedAgentContext(a) ? 0 : (a?.pinned ? 1 : 2);
    const bRank = isProtectedAgentContext(b) ? 0 : (b?.pinned ? 1 : 2);
    if (aRank !== bRank) return aRank - bRank;
    return String(a?.name || '').localeCompare(String(b?.name || ''));
  });
  const contextOptions = contexts.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (selectEl && selectedIdeContextId && contexts.some((item) => item.id === selectedIdeContextId)) selectEl.value = selectedIdeContextId;
  if (sessionSelect) sessionSelect.innerHTML = `<option value="">none</option>${contextOptions}`;
  if (composerSelect) {
    composerSelect.innerHTML = `<option value="">agent context</option>${contextOptions}`;
    composerSelect.value = selectedSessionContextId() || (!selectedSession ? (selectedIdeContextId || '') : '');
  }
  if (ideSelect) {
    ideSelect.innerHTML = `<option value="">Select context</option>${contextOptions}`;
    if (selectedIdeContextId && contexts.some((item) => item.id === selectedIdeContextId)) ideSelect.value = selectedIdeContextId;
  }
  if (workspaceSelect) workspaceSelect.innerHTML = `<option value="">none</option>` + ideWorkspaces().map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (templateSelect) templateSelect.innerHTML = `<option value="">none</option>` + workspaceTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (storageSelect) storageSelect.innerHTML = `<option value="">none</option>` + (sharedStorages || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if (endpointSelect) {
    endpointSelect.innerHTML = `<option value="">auto</option>`;
    (window.__pacEndpoints || []).forEach((runner) => opt(endpointSelect, runner.id, `${runner.name || runner.id} (${runner.status || 'unknown'})`));
  }
  const fillModelSelect = (el, empty='default') => {
    if (!el) return;
    el.innerHTML = `<option value="">${escapeHtml(empty)}</option>`;
    Object.keys(config.models || {}).forEach((name) => opt(el, name));
  };
  if (profileSelect) {
    profileSelect.innerHTML = '<option value="">default</option>';
    Object.entries(config.agent_profiles || {}).forEach(([name]) => opt(profileSelect, name));
  }
  if (permissionSelect) {
    permissionSelect.innerHTML = '<option value="">default</option>';
    Object.keys(config.permission_profiles || {}).forEach((name) => opt(permissionSelect, name));
  }
  fillModelSelect(executorSelect, 'default');
  fillModelSelect(plannerSelect, 'none');
  fillModelSelect(reviewerSelect, 'none');
  fillModelSelect(retrievalSelect, 'none');
  if (toolsSelect) {
    toolsSelect.innerHTML = '';
    Object.keys(config.tools || {}).forEach((name) => opt(toolsSelect, name));
  }
  const groups = window.__pacGroups || [];
  const fillGroupSelect = (el) => {
    if (!el) return;
    el.innerHTML = '';
    groups.forEach((group) => opt(el, group.id, group.name || group.id));
  };
  fillGroupSelect(groupsSelect);
  fillGroupSelect(editorsSelect);
  if (listEl) {
    listEl.innerHTML = contexts.map((item) => {
      const workspace = contextWorkspaceLabel(item);
      const runtime = contextRuntimeLabel(item);
      const models = [
        item.executor_model ? 'executor' : '',
        item.planner_model ? 'planner' : '',
        item.reviewer_model ? 'reviewer' : '',
        item.retrieval_model ? 'retrieval' : '',
      ].filter(Boolean);
      const badges = [
        isProtectedAgentContext(item) ? '<span class="agent-context-chip system">system</span>' : '',
        item.pinned ? '<span class="agent-context-chip">pinned</span>' : '',
        `<span class="agent-context-chip">${escapeHtml(item.kind || 'coding')}</span>`,
      ].filter(Boolean).join('');
      return `<article class="agent-context-card clickable-row ${item.id === selectedIdeContextId ? 'selected' : ''}" data-agent-context="${escapeHtml(item.id)}">
        <div class="agent-context-card-head">
          <div><h3>${escapeHtml(item.name)}</h3><div class="muted small-text">${escapeHtml(item.description || (isProtectedAgentContext(item) ? 'Built-in PAC product maintenance context.' : 'Reusable execution preset.'))}</div></div>
          <div class="agent-context-card-badges">${badges}</div>
        </div>
        <div class="agent-context-stat-grid">
          <div><small>workspace</small><b>${escapeHtml(workspace)}</b></div>
          <div><small>runtime</small><b>${escapeHtml(runtime)}</b></div>
          <div><small>profile</small><b>${escapeHtml(item.agent_profile || 'default')}</b></div>
          <div><small>permission</small><b>${escapeHtml(item.permission_profile || 'default')}</b></div>
          <div><small>executor</small><b>${escapeHtml(item.executor_model || '-')}</b></div>
          <div><small>support</small><b>${escapeHtml(models.filter((role) => role !== 'executor').join(', ') || '-')}</b></div>
        </div>
        <div class="agent-context-card-footer">
          <span class="muted small-text">tools ${(item.tools || []).length || 0}</span>
          <span class="muted small-text">${isProtectedAgentContext(item) ? 'admin-only' : `${(item.use_groups || []).length || 0} use group(s)`}</span>
        </div>
        <div class="workspace-card-actions">
          <button type="button" data-context-open="${escapeHtml(item.id)}">Open session</button>
          <button type="button" class="ghost-button" data-context-edit="${escapeHtml(item.id)}">Edit</button>
          ${isProtectedAgentContext(item) ? '' : `<button type="button" class="ghost-button" data-context-delete="${escapeHtml(item.id)}">Delete</button>`}
        </div>
      </article>`;
    }).join('') || '<div class="muted">No agent contexts yet. Use + to create one, then select it in Sessions or IDE.</div>';
    listEl.querySelectorAll('[data-agent-context]').forEach((row) => {
      row.onclick = (ev) => {
        if (ev.target.closest('button')) return;
        fillAgentContextForm(row.getAttribute('data-agent-context') || '');
      };
    });
    listEl.querySelectorAll('[data-context-edit]').forEach((button) => {
      button.onclick = (ev) => {
        ev.stopPropagation();
        openAgentContextWizard(button.getAttribute('data-context-edit') || '');
      };
    });
    listEl.querySelectorAll('[data-context-open]').forEach((button) => {
      button.onclick = async (ev) => {
        ev.stopPropagation();
        fillAgentContextForm(button.getAttribute('data-context-open') || '');
        await openAgentContextSessionFromForm();
      };
    });
    listEl.querySelectorAll('[data-context-delete]').forEach((button) => {
      button.onclick = async (ev) => {
        ev.stopPropagation();
        fillAgentContextForm(button.getAttribute('data-context-delete') || '');
        await deleteAgentContextFromForm();
      };
    });
  }
  renderAgentContextUsageCard(contexts.find((item) => item.id === selectedIdeContextId) || null);
}

function renderWorkspaces() {
  const el = document.getElementById('workspaces');
  const personalEl = document.getElementById('personalWorkspaces');
  const templateSelect = document.getElementById('userWorkspaceTemplate');
  const workspaceSelect = document.getElementById('userWorkspaceSelect');
  const storageSelect = document.getElementById('userWorkspaceSharedStorage');
  const endpointSelect = document.getElementById('userWorkspaceEndpoint');
  const profileSelect = document.getElementById('userWorkspaceAgentProfile');
  const modelSelect = document.getElementById('userWorkspaceModel');
  if (templateSelect) {
    templateSelect.innerHTML = '<option value="">None</option>' + workspaceTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (workspaceSelect) {
    workspaceSelect.innerHTML = '<option value="">New workspace</option>' + ideWorkspaces().map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    if (selectedIdeWorkspaceId && ideWorkspaces().some((item) => item.id === selectedIdeWorkspaceId)) workspaceSelect.value = selectedIdeWorkspaceId;
  }
  if (storageSelect) {
    storageSelect.innerHTML = '<option value="">none</option>' + (sharedStorages || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (endpointSelect) {
    endpointSelect.innerHTML = '<option value="">auto</option>';
    (window.__pacEndpoints || []).forEach((runner) => opt(endpointSelect, runner.id, `${runner.name || runner.id} (${runner.status || 'unknown'})`));
  }
  if (profileSelect) {
    profileSelect.innerHTML = '<option value="">default</option>';
    Object.entries(config.agent_profiles || {}).forEach(([name, profile]) => {
      if (profile?.model && modelAvailability(profile.model).ok) opt(profileSelect, name);
    });
  }
  if (modelSelect) {
    modelSelect.innerHTML = '<option value="">default</option>';
    Object.keys(config.models || {}).forEach((name) => { if (modelAvailability(name).ok) opt(modelSelect, name); });
  }
  if (personalEl) {
    personalEl.innerHTML = ideWorkspaces().map((item) => {
      const target = item.path || item.url || item.workspace_profile || '-';
      const templateName = item.template?.name || item.template_id || 'custom';
      const storage = item.shared_storage?.name || storageNameById(item.shared_storage_id);
      return `<div class="workspace-card clickable-row ${item.id === selectedIdeWorkspaceId ? 'selected' : ''}" data-user-workspace="${escapeHtml(item.id)}">
        <div class="workspace-card-title"><b>${escapeHtml(item.name)}</b><span>${item.pinned ? 'pinned' : templateName}</span></div>
        <div class="workspace-card-grid">
          <div><small>type</small><b>${escapeHtml(item.workspace_type || 'local')}</b></div>
          <div><small>storage</small><b>${escapeHtml(storage || '-')}</b></div>
          <div><small>endpoint</small><b>${escapeHtml(item.endpoint_id || 'auto')}</b></div>
          <div><small>profile</small><b>${escapeHtml(item.agent_profile || 'default')}</b></div>
          <div><small>session</small><b>${escapeHtml(item.last_session_id ? 'attached' : 'none')}</b></div>
        </div>
        <code>${escapeHtml(item.description || '')}${item.description ? '\n' : ''}target: ${escapeHtml(target)}\nstorage path: ${escapeHtml(item.storage_subpath || '-')}</code>
      </div>`;
    }).join('') || '<div class="muted">No personal workspaces yet. Create one from a template above.</div>';
    personalEl.querySelectorAll('[data-user-workspace]').forEach((row) => {
      row.onclick = () => fillUserWorkspaceForm(row.getAttribute('data-user-workspace') || '');
    });
  }
  if (!el) return;
  el.innerHTML = '';
  for (const [name,w] of Object.entries(config.workspaces || {})) {
    const lifecycle = w.ephemeral ? `ephemeral${w.ttl_hours ? `, ${w.ttl_hours}h TTL` : ''}` : 'persistent';
    const placement = w.endpoint_id || w.endpoint_selector || 'select at runtime';
    const data = w.data_bundle_url || w.data_bundle_path || 'none';
    const storage = storageNameById(w.shared_storage_id);
    const row = document.createElement('div');
    row.className = 'workspace-card clickable-row';
    row.innerHTML = `<div class="workspace-card-title"><b>${escapeHtml(name)}</b><span>${escapeHtml(lifecycle)}</span></div>
      <div class="workspace-card-grid">
        <div><small>type</small><b>${escapeHtml(w.type || 'local')}</b></div>
        <div><small>runtime</small><b>${escapeHtml(w.runtime || 'any')}</b></div>
        <div><small>placement</small><b>${escapeHtml(placement)}</b></div>
        <div><small>storage</small><b>${escapeHtml(storage || '-')}</b></div>
        <div><small>profile</small><b>${escapeHtml(w.default_agent_profile || '-')}</b></div>
      </div>
      <code>${escapeHtml(w.description || '')}${w.description ? '\n' : ''}path: ${escapeHtml(w.path || '-')}\nurl: ${escapeHtml(w.url || '-')}\nbranch: ${escapeHtml(w.branch || '-')}\ncontainer: ${escapeHtml(w.container_image || '-')}\nstorage subpath: ${escapeHtml(w.storage_subpath || '-')}\nmount: ${escapeHtml(w.storage_mount_path || '-')}\ndata zip: ${escapeHtml(data)}\ndata path: ${escapeHtml(w.data_mount_path || '-')}\ndefault: ${w.is_default ? 'yes' : 'no'}</code>`;
    row.onclick = () => fillWorkspaceForm(name);
    el.appendChild(row);
  }
  renderWorkspaceActivityPanel();
  if (selectedIdeWorkspaceId && !document.getElementById('userWorkspaceSelect')?.value) {
    fillUserWorkspaceForm(selectedIdeWorkspaceId);
  }
}

function fillUserWorkspaceForm(id='') {
  const item = ideWorkspaces().find((workspace) => workspace.id === id);
  selectedIdeWorkspaceId = item?.id || '';
  const set = (fieldId, value='') => { const el = document.getElementById(fieldId); if (el) el.value = value ?? ''; };
  set('userWorkspaceSelect', item?.id || '');
  set('userWorkspaceName', item?.name || '');
  set('userWorkspaceDescription', item?.description || '');
  set('userWorkspaceTemplate', item?.template_id || '');
  set('userWorkspaceType', item?.workspace_type || 'local');
  set('userWorkspaceProfile', item?.workspace_profile || '');
  set('userWorkspacePath', item?.path || '');
  set('userWorkspaceUrl', item?.url || '');
  set('userWorkspaceBranch', item?.branch || '');
  set('userWorkspaceSharedStorage', item?.shared_storage_id || '');
  set('userWorkspaceStorageSubpath', item?.storage_subpath || '');
  set('userWorkspaceStorageMountPath', item?.storage_mount_path || '');
  set('userWorkspaceEndpoint', item?.endpoint_id || '');
  set('userWorkspaceContainerImage', item?.container_image || '');
  set('userWorkspaceAgentProfile', item?.agent_profile || '');
  set('userWorkspaceModel', item?.model || '');
  const pinned = document.getElementById('userWorkspacePinned'); if (pinned) pinned.checked = !!item?.pinned;
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
}

function userWorkspaceFormPayload() {
  return {
    name: (document.getElementById('userWorkspaceName')?.value || '').trim(),
    description: (document.getElementById('userWorkspaceDescription')?.value || '').trim() || null,
    template_id: document.getElementById('userWorkspaceTemplate')?.value || null,
    workspace_type: document.getElementById('userWorkspaceType')?.value || 'local',
    workspace_profile: (document.getElementById('userWorkspaceProfile')?.value || '').trim() || null,
    path: (document.getElementById('userWorkspacePath')?.value || '').trim() || null,
    url: (document.getElementById('userWorkspaceUrl')?.value || '').trim() || null,
    branch: (document.getElementById('userWorkspaceBranch')?.value || '').trim() || null,
    shared_storage_id: document.getElementById('userWorkspaceSharedStorage')?.value || null,
    storage_subpath: (document.getElementById('userWorkspaceStorageSubpath')?.value || '').trim() || null,
    storage_mount_path: (document.getElementById('userWorkspaceStorageMountPath')?.value || '').trim() || null,
    endpoint_id: document.getElementById('userWorkspaceEndpoint')?.value || null,
    container_image: (document.getElementById('userWorkspaceContainerImage')?.value || '').trim() || null,
    agent_profile: document.getElementById('userWorkspaceAgentProfile')?.value || null,
    model: document.getElementById('userWorkspaceModel')?.value || null,
    pinned: !!document.getElementById('userWorkspacePinned')?.checked,
  };
}

async function saveUserWorkspaceFromForm() {
  const payload = userWorkspaceFormPayload();
  if (!payload.name) return alert('Workspace name is required');
  const existingId = document.getElementById('userWorkspaceSelect')?.value || '';
  const path = existingId ? `/v1/my-workspaces/${encodeURIComponent(existingId)}` : '/v1/my-workspaces';
  const method = existingId ? 'PUT' : 'POST';
  const result = await api(path, {method, body: JSON.stringify(payload)});
  await loadWorkspaceCatalogs();
  const workspace = result.workspace || null;
  selectedIdeWorkspaceId = workspace?.id || selectedIdeWorkspaceId;
  fillUserWorkspaceForm(selectedIdeWorkspaceId || '');
  renderWorkspaces();
  showInline('userWorkspaceFormResult', `Saved workspace ${payload.name}`);
}

async function deleteUserWorkspaceFromForm() {
  const id = document.getElementById('userWorkspaceSelect')?.value || '';
  if (!id) return alert('Select an existing personal workspace first');
  if (!confirm('Delete this personal workspace?')) return;
  await api(`/v1/my-workspaces/${encodeURIComponent(id)}`, {method:'DELETE'});
  await loadWorkspaceCatalogs();
  selectedIdeWorkspaceId = '';
  fillUserWorkspaceForm('');
  renderWorkspaces();
  showInline('userWorkspaceFormResult', 'Workspace deleted');
}

async function openUserWorkspaceInIde() {
  const id = document.getElementById('userWorkspaceSelect')?.value || selectedIdeWorkspaceId || '';
  if (!id) return alert('Select a personal workspace first');
  selectedIdeWorkspaceId = id;
  selectedIdeSessionId = '';
  sourceCodingSessionId = '';
  sourceTreeCache.clear();
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  switchToTab('sources-tab');
  await renderSources('');
}

function workspaceValue(id) { return document.getElementById(id)?.value?.trim() || ''; }

function workspaceChecked(id) { return !!document.getElementById(id)?.checked; }

function renderWorkspaces() {
  const el = document.getElementById('workspaces');
  if (!el) return;
  el.innerHTML = '';
  for (const [name,w] of Object.entries(config.workspaces || {})) {
    const lifecycle = w.ephemeral ? `ephemeral${w.ttl_hours ? `, ${w.ttl_hours}h TTL` : ''}` : 'persistent';
    const placement = w.endpoint_id || w.endpoint_selector || 'select at runtime';
    const data = w.data_bundle_url || w.data_bundle_path || 'none';
    const row = document.createElement('div'); row.className = 'workspace-card clickable-row';
    row.innerHTML = `<div class="workspace-card-title"><b>${escapeHtml(name)}</b><span>${escapeHtml(lifecycle)}</span></div>
      <div class="workspace-card-grid">
        <div><small>type</small><b>${escapeHtml(w.type || 'local')}</b></div>
        <div><small>runtime</small><b>${escapeHtml(w.runtime || 'any')}</b></div>
        <div><small>placement</small><b>${escapeHtml(placement)}</b></div>
        <div><small>profile</small><b>${escapeHtml(w.default_agent_profile || '-')}</b></div>
      </div>
      <code>${escapeHtml(w.description || '')}${w.description ? '\n' : ''}path: ${escapeHtml(w.path || '-')}
url: ${escapeHtml(w.url || '-')}
branch: ${escapeHtml(w.branch || '-')}
container: ${escapeHtml(w.container_image || '-')}
data zip: ${escapeHtml(data)}
data path: ${escapeHtml(w.data_mount_path || '-')}
default: ${w.is_default ? 'yes' : 'no'}</code>`;
    row.onclick = () => fillWorkspaceForm(name);
    el.appendChild(row);
  }
}

function fillWorkspaceForm(name) {
  const w = config.workspaces?.[name]; if (!w) return;
  workspaceName.value = name;
  if (document.getElementById('workspaceDescription')) workspaceDescription.value = w.description || '';
  workspaceType.value = w.type || 'local';
  if (document.getElementById('workspaceRuntime')) workspaceRuntime.value = w.runtime || 'any';
  workspacePath.value = w.path || ''; workspaceUrl.value = w.url || ''; workspaceBranch.value = w.branch || '';
  if (document.getElementById('workspaceSharedStorage')) workspaceSharedStorage.value = w.shared_storage_id || '';
  if (document.getElementById('workspaceStorageSubpath')) workspaceStorageSubpath.value = w.storage_subpath || '';
  if (document.getElementById('workspaceStorageMountPath')) workspaceStorageMountPath.value = w.storage_mount_path || '';
  if (document.getElementById('workspaceContainerImage')) workspaceContainerImage.value = w.container_image || '';
  workspaceDefaultProfile.value = w.default_agent_profile || '';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.value = w.endpoint_id || '';
  if (document.getElementById('workspaceEndpointSelector')) workspaceEndpointSelector.value = w.endpoint_selector || '';
  if (document.getElementById('workspaceDataUrl')) workspaceDataUrl.value = w.data_bundle_url || '';
  if (document.getElementById('workspaceDataPath')) workspaceDataPath.value = w.data_bundle_path || '';
  if (document.getElementById('workspaceDataMount')) workspaceDataMount.value = w.data_mount_path || '';
  if (document.getElementById('workspaceTtlHours')) workspaceTtlHours.value = w.ttl_hours || '';
  if (document.getElementById('workspaceEphemeral')) workspaceEphemeral.checked = !!w.ephemeral;
  if (document.getElementById('workspaceDeleteOnExpire')) workspaceDeleteOnExpire.checked = w.delete_on_expire !== false;
  if (document.getElementById('workspaceIsDefault')) workspaceIsDefault.checked = !!w.is_default;
}

async function saveWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name) return alert('Workspace name is required');
  const body = {
    description: workspaceValue('workspaceDescription') || null,
    type: workspaceType.value || 'local',
    runtime: workspaceValue('workspaceRuntime') || 'any',
    path: workspacePath.value.trim() || null,
    url: workspaceUrl.value.trim() || null,
    branch: workspaceBranch.value.trim() || null,
    shared_storage_id: workspaceValue('workspaceSharedStorage') || null,
    storage_subpath: workspaceValue('workspaceStorageSubpath') || null,
    storage_mount_path: workspaceValue('workspaceStorageMountPath') || null,
    container_image: workspaceValue('workspaceContainerImage') || null,
    default_agent_profile: workspaceDefaultProfile.value || null,
    endpoint_id: document.getElementById('workspaceEndpoint')?.value || null,
    endpoint_selector: workspaceValue('workspaceEndpointSelector') || null,
    data_bundle_url: workspaceValue('workspaceDataUrl') || null,
    data_bundle_path: workspaceValue('workspaceDataPath') || null,
    data_mount_path: workspaceValue('workspaceDataMount') || null,
    ephemeral: workspaceChecked('workspaceEphemeral'),
    ttl_hours: workspaceValue('workspaceTtlHours') || null,
    delete_on_expire: workspaceChecked('workspaceDeleteOnExpire'),
    is_default: !!document.getElementById('workspaceIsDefault')?.checked,
  };
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'PUT', body:JSON.stringify(body)});
  await loadConfig();
  showInline('workspaceFormResult', `Saved workspace ${name}`);
}

async function deleteWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name || !config.workspaces?.[name]) return alert('Select an existing workspace first');
  if (!confirm(`Delete workspace ${name}?`)) return;
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadConfig();
  showInline('workspaceFormResult', `Deleted workspace ${name}`);
}

