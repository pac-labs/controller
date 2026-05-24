// Source variables, secrets, and PAC RAM helpers.
function fillSecretForm(secretId='') {
  const select = document.getElementById('sourceSecretSelect');
  if (select && secretId) select.value = secretId;
  const item = ((window.__pacSecrets || []).find(s => s.id === secretId)) || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceSecretId', secretId);
  set('sourceSecretValue', '');
  set('sourceSecretMeta', JSON.stringify(item.meta || {}, null, 2));
}
async function loadSourceSecrets() {
  const select = document.getElementById('sourceSecretSelect');
  const audit = document.getElementById('sourceSecretAudit');
  if (!select || !audit) return;
  const [secretData, auditData] = await Promise.all([api('/v1/secrets'), api('/v1/secrets/audit?limit=12')]);
  window.__pacSecrets = secretData.secrets || [];
  const current = select.value || document.getElementById('sourceSecretId')?.value || '';
  select.innerHTML = '<option value="">Select secret</option>' + (window.__pacSecrets || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}</option>`).join('');
  if ((window.__pacSecrets || []).some(item => item.id === current)) select.value = current;
  audit.textContent = (auditData.items || []).length ? (auditData.items || []).map(item => `${item.created_at}  ${item.event}  ${item.secret_id}`).join('\n') : 'No secret audit events loaded yet.';
}
function fillSourceVariableForm(variableId='') {
  const select = document.getElementById('sourceVariableSelect');
  if (select && variableId) select.value = variableId;
  const item = ((window.__pacSourceVariables || []).find(v => v.id === variableId)) || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceVariableId', variableId);
  set('sourceVariableDescription', item.description || '');
  set('sourceVariableTags', Array.isArray(item.tags) ? item.tags.join(', ') : '');
  set('sourceVariableValue', item.value || '');
}
async function loadSourceVariables() {
  const select = document.getElementById('sourceVariableSelect');
  const list = document.getElementById('sourceVariableList');
  if (!select || !list) return;
  const data = await api('/v1/source-variables');
  window.__pacSourceVariables = data.variables || [];
  const current = select.value || document.getElementById('sourceVariableId')?.value || '';
  select.innerHTML = '<option value="">Select variable</option>' + (window.__pacSourceVariables || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}</option>`).join('');
  if ((window.__pacSourceVariables || []).some(item => item.id === current)) select.value = current;
  list.textContent = (window.__pacSourceVariables || []).length
    ? (window.__pacSourceVariables || []).map(item => `${item.id}${item.tags?.length ? ` [${item.tags.join(', ')}]` : ''}`).join('\n')
    : 'No source variables loaded yet.';
}
async function saveSourceVariableFromForm() {
  try {
    const variableId = document.getElementById('sourceVariableId')?.value?.trim();
    const value = document.getElementById('sourceVariableValue')?.value ?? '';
    if (!variableId) throw new Error('Variable ID is required');
    const description = document.getElementById('sourceVariableDescription')?.value?.trim() || '';
    const tags = String(document.getElementById('sourceVariableTags')?.value || '').split(',').map(v => v.trim()).filter(Boolean);
    await api(`/v1/source-variables/${encodeURIComponent(variableId)}`, {method:'PUT', body: JSON.stringify({value, description, tags})});
    await loadSourceVariables();
    fillSourceVariableForm(variableId);
    await resolveCurrentSourceContext().catch(()=>{});
  } catch (e) {
    paneError('Source variable could not be saved', e.message || String(e));
  }
}
async function deleteSourceVariableFromForm() {
  const variableId = document.getElementById('sourceVariableId')?.value?.trim() || document.getElementById('sourceVariableSelect')?.value || '';
  if (!variableId) return paneError('Select a source variable first');
  if (!confirm(`Delete source variable ${variableId}?`)) return;
  await api(`/v1/source-variables/${encodeURIComponent(variableId)}`, {method:'DELETE'});
  await loadSourceVariables();
  fillSourceVariableForm('');
  await resolveCurrentSourceContext().catch(()=>{});
}
async function loadPacRam() {
  const kind = document.getElementById('pacRamKind')?.value || 'profile';
  const key = document.getElementById('pacRamKey')?.value?.trim() || '';
  const content = document.getElementById('pacRamContent');
  const summary = document.getElementById('pacRamSummary');
  if (!key) return paneError('PAC RAM key is required');
  const data = await api(`/v1/pac-ram/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`);
  if (content) content.value = data.content || '';
  if (summary) summary.textContent = `${data.kind}:${data.key}\n${data.path}\nUpdated ${data.updated_at || '-'}`;
}
async function loadPacRamIndex() {
  const summary = document.getElementById('pacRamSummary');
  if (!summary) return;
  const data = await api('/v1/pac-ram/list');
  const lines = [
    `profiles: ${(data.profiles || []).join(', ') || '-'}`,
    `users: ${(data.users || []).join(', ') || '-'}`,
    `workspaces: ${(data.workspaces || []).join(', ') || '-'}`,
  ];
  if (!document.getElementById('pacRamContent')?.value?.trim()) summary.textContent = lines.join('\n');
}
async function savePacRamFromForm() {
  try {
    const kind = document.getElementById('pacRamKind')?.value || 'profile';
    const key = document.getElementById('pacRamKey')?.value?.trim() || '';
    const content = document.getElementById('pacRamContent')?.value ?? '';
    const summary = document.getElementById('pacRamSummary');
    if (!key) throw new Error('PAC RAM key is required');
    const data = await api(`/v1/pac-ram/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`, {method:'PUT', body: JSON.stringify({content})});
    if (summary) summary.textContent = `${data.kind}:${data.key}\n${data.path}\nUpdated ${data.updated_at || '-'}`;
    await loadPacRamIndex().catch(()=>{});
  } catch (e) {
    paneError('PAC RAM could not be saved', e.message || String(e));
  }
}
async function saveSourceSecretFromForm() {
  try {
    const secretId = document.getElementById('sourceSecretId')?.value?.trim();
    const value = document.getElementById('sourceSecretValue')?.value ?? '';
    if (!secretId) throw new Error('Secret ID is required');
    if (!value) throw new Error('Secret value is required when saving');
    const meta = parseJsonObject(document.getElementById('sourceSecretMeta')?.value, 'Secret meta');
    await api(`/v1/secrets/${encodeURIComponent(secretId)}`, {method:'PUT', body: JSON.stringify({value, meta})});
    await loadSourceSecrets();
    fillSecretForm(secretId);
  } catch (e) {
    paneError('Secret could not be saved', e.message || String(e));
  }
}
async function deleteSourceSecretFromForm() {
  const secretId = document.getElementById('sourceSecretId')?.value?.trim() || document.getElementById('sourceSecretSelect')?.value || '';
  if (!secretId) return paneError('Select a secret first');
  if (!confirm(`Delete secret ${secretId}?`)) return;
  await api(`/v1/secrets/${encodeURIComponent(secretId)}`, {method:'DELETE'});
  await loadSourceSecrets();
  fillSecretForm('');
}
