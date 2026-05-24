// Agent context list rendering and form actions.
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
