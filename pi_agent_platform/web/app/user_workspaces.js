// User workspace catalog rendering and workspace form actions.
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
    Object.entries(config.agent_profiles || {}).forEach(([name]) => opt(profileSelect, name));
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
