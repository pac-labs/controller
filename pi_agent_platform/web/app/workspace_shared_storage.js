// Shared storage rendering and form actions for workspace configuration.
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
