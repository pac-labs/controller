// Source context form and context resolution helpers.
function parseJsonObject(text, label) {
  const raw = String(text || '').trim();
  if (!raw) return {};
  let value;
  try { value = JSON.parse(raw); } catch (e) { throw new Error(`${label} must be valid JSON`); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be a JSON object`);
  return value;
}
function fillSourceContextForm(ctxName='') {
  const entry = (config.source_contexts || {})[ctxName] || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceContextName', ctxName);
  set('sourceContextPathPrefix', entry.path_prefix);
  set('sourceContextCustomerId', entry.customer_id);
  set('sourceContextUserScope', entry.user_scope);
  set('sourceContextProfile', entry.profile);
  set('sourceContextWorkspaceProfile', entry.workspace_profile);
  set('sourceContextEndpoint', entry.preferred_endpoint);
  set('sourceContextContainerImage', entry.container_image);
  set('sourceContextDescription', entry.description);
  set('sourceContextNotes', entry.notes);
  set('sourceContextConfigVars', JSON.stringify(entry.config_vars || {}, null, 2));
  set('sourceContextSecretRefs', JSON.stringify(entry.secret_refs || {}, null, 2));
  if (entry.profile && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'profile';
    document.getElementById('pacRamKey').value = entry.profile;
  } else if (entry.user_scope && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'user';
    document.getElementById('pacRamKey').value = entry.user_scope;
  } else if (entry.workspace_profile && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'workspace';
    document.getElementById('pacRamKey').value = entry.workspace_profile;
  }
}
function renderSourceContexts() {
  const select = document.getElementById('sourceContextSelect');
  if (!select) return;
  const contexts = Object.entries(config.source_contexts || {}).sort((a,b)=>a[0].localeCompare(b[0]));
  const current = select.value || document.getElementById('sourceContextName')?.value || '';
  select.innerHTML = '<option value="">Select context</option>' + contexts.map(([name, ctx]) => `<option value="${escapeHtml(name)}">${escapeHtml(name)} (${escapeHtml(ctx.path_prefix || '-')})</option>`).join('');
  if (contexts.some(([name]) => name === current)) select.value = current;
}
async function saveSourceContextFromForm() {
  try {
    const name = document.getElementById('sourceContextName')?.value?.trim();
    if (!name) throw new Error('Context name is required');
    const body = {
      description: document.getElementById('sourceContextDescription')?.value?.trim() || null,
      path_prefix: document.getElementById('sourceContextPathPrefix')?.value?.trim() || '',
      customer_id: document.getElementById('sourceContextCustomerId')?.value?.trim() || null,
      user_scope: document.getElementById('sourceContextUserScope')?.value?.trim() || null,
      profile: document.getElementById('sourceContextProfile')?.value?.trim() || null,
      workspace_profile: document.getElementById('sourceContextWorkspaceProfile')?.value?.trim() || null,
      preferred_endpoint: document.getElementById('sourceContextEndpoint')?.value?.trim() || null,
      container_image: document.getElementById('sourceContextContainerImage')?.value?.trim() || null,
      config_vars: parseJsonObject(document.getElementById('sourceContextConfigVars')?.value, 'Config vars'),
      secret_refs: parseJsonObject(document.getElementById('sourceContextSecretRefs')?.value, 'Secret refs'),
      notes: document.getElementById('sourceContextNotes')?.value?.trim() || null,
    };
    await api(`/v1/source-contexts/${encodeURIComponent(name)}`, {method:'PUT', body: JSON.stringify(body)});
    await loadConfig();
    document.getElementById('sourceContextSelect').value = name;
    fillSourceContextForm(name);
    await resolveCurrentSourceContext();
  } catch (e) {
    paneError('Source context could not be saved', e.message || String(e));
  }
}
async function deleteSourceContextFromForm() {
  const name = document.getElementById('sourceContextName')?.value?.trim() || document.getElementById('sourceContextSelect')?.value || '';
  if (!name) return paneError('Select a source context first');
  if (!confirm(`Delete source context ${name}?`)) return;
  await api(`/v1/source-contexts/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadConfig();
  fillSourceContextForm('');
  const out = document.getElementById('sourceContextResolved');
  if (out) out.textContent = 'Select a source context to inspect the resolved environment bundle.';
}
async function resolveCurrentSourceContext() {
  const out = document.getElementById('sourceContextResolved');
  if (!out) return;
  const explicitName = document.getElementById('sourceContextSelect')?.value || document.getElementById('sourceContextName')?.value?.trim() || '';
  const path = selectedSourceEntry || selectedSourcePath || selectedSourceFolder || '';
  if (!explicitName && !path) {
    sourceResolvedContext = null;
    out.textContent = 'Select a context or a source path first.';
    updateSourceCodingPanel();
    return;
  }
  try {
    const qs = explicitName ? `name=${encodeURIComponent(explicitName)}` : `path=${encodeURIComponent(path)}`;
    const data = await api(`/v1/source-contexts/resolve?${qs}&include_secrets=false`);
    sourceResolvedContext = data || null;
    out.textContent = JSON.stringify(data, null, 2);
    if (data?.name) {
      const select = document.getElementById('sourceContextSelect');
      if (select) select.value = data.name;
      fillSourceContextForm(data.name);
    }
  } catch (e) {
    sourceResolvedContext = null;
    out.textContent = e.message || String(e);
  } finally {
    updateSourceCodingPanel();
  }
}
const SOURCE_TECH_MAP = {
  '.cs': {stack: 'csharp', container: 'localhost/dotnet-dev:latest', profileHints: ['dotnet', 'csharp', 'c#']},
  '.csproj': {stack: 'csharp', container: 'localhost/dotnet-dev:latest', profileHints: ['dotnet', 'csharp', 'c#']},
  '.sln': {stack: 'csharp', container: 'localhost/dotnet-dev:latest', profileHints: ['dotnet', 'csharp', 'c#']},
  '.py': {stack: 'python', container: 'localhost/python-dev:latest', profileHints: ['python', 'py']},
  '.js': {stack: 'node', container: 'localhost/node-dev:latest', profileHints: ['node', 'javascript', 'js']},
  '.ts': {stack: 'node', container: 'localhost/node-dev:latest', profileHints: ['node', 'typescript', 'ts']},
  '.tsx': {stack: 'node', container: 'localhost/node-dev:latest', profileHints: ['node', 'typescript', 'ts']},
  '.go': {stack: 'go', container: 'localhost/go-dev:latest', profileHints: ['go', 'golang']},
  '.c': {stack: 'c', container: 'localhost/c-dev:latest', profileHints: ['c', 'cpp']},
  '.cc': {stack: 'c', container: 'localhost/c-dev:latest', profileHints: ['c', 'cpp']},
  '.cpp': {stack: 'c', container: 'localhost/c-dev:latest', profileHints: ['c', 'cpp']},
  '.h': {stack: 'c', container: 'localhost/c-dev:latest', profileHints: ['c', 'cpp']},
  '.hpp': {stack: 'c', container: 'localhost/c-dev:latest', profileHints: ['c', 'cpp']},
  '.md': {stack: 'docs', container: 'localhost/docs-search:latest', profileHints: ['doc', 'docs', 'reader']},
  '.adoc': {stack: 'docs', container: 'localhost/docs-search:latest', profileHints: ['doc', 'docs', 'reader']},
};
