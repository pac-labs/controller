// Source tool catalog and open-file payload helpers.
function inferredToolFromSourcePath() {
  const path = String(selectedSourcePath || selectedSourceFolder || selectedSourceEntry || '').replace(/\\/g, '/');
  const match = /^plugins\/([^/]+)/.exec(path);
  return match?.[1] || '';
}
function sourcePathExistsInTree(path='') {
  const normalized = String(path || '').replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+$/, '');
  if (!normalized) return false;
  if (sourceTreeCache.has(normalized)) return true;
  const rootData = sourceTreeCache.get('') || {items: []};
  let items = rootData.items || [];
  if (!items.length && Array.isArray(rootData.top_level) && rootData.top_level.length) {
    items = rootData.top_level.map((name) => ({name, path: name, type: 'dir'}));
  }
  let current = '';
  for (const part of normalized.split('/').filter(Boolean)) {
    const nextPath = current ? `${current}/${part}` : part;
    const match = (items || []).find((item) => String(item.path || item.name || '').replace(/\\/g, '/') === nextPath || String(item.name || '') === part);
    if (!match || match.type !== 'dir') return false;
    if (nextPath === normalized) return true;
    current = nextPath;
    items = (sourceTreeCache.get(current) || {}).items || [];
  }
  return false;
}
function sourceToolEntries() {
  const pluginMap = config.plugins || {};
  const toolMap = config.tools || {};
  const ids = Array.from(new Set([...Object.keys(toolMap), ...Object.keys(pluginMap)])).sort((a, b) => a.localeCompare(b));
  return ids.map((name) => {
    const plugin = pluginMap[name] || {};
    const tool = toolMap[name] || {};
    const sourcePath = `plugins/${name}`;
    return {
      id: name,
      kind: plugin.kind || 'tool',
      description: plugin.description || tool.description || '',
      requiresTools: Array.isArray(plugin.requires_tools) ? plugin.requires_tools : [],
      binaries: Array.isArray(tool.binaries) ? tool.binaries : [],
      documentation: plugin.documentation || '',
      sourcePath,
      sourceAvailable: sourcePathExistsInTree(sourcePath),
      enabled: plugin.enabled !== false && tool.enabled !== false,
    };
  });
}
function selectedSourceToolIds() {
  const inferred = inferredToolFromSourcePath();
  const chosen = sourceSelectedToolId || inferred;
  return chosen ? [chosen] : [];
}
function sourceToolPayload(limit = 2) {
  return selectedSourceToolIds().slice(0, limit).map((toolId) => {
    const entry = sourceToolEntries().find(item => item.id === toolId);
    return entry ? {
      id: entry.id,
      kind: entry.kind,
      description: entry.description,
      requires_tools: entry.requiresTools,
      source_path: entry.sourcePath,
      documentation: entry.documentation,
    } : null;
  }).filter(Boolean);
}
function renderSourceToolCatalog() {
  const toolsEl = document.getElementById('sourceCodingTools');
  const statusEl = document.getElementById('sourceCodingToolStatus');
  if (!toolsEl || !statusEl) return;
  const entries = sourceToolEntries();
  const inferred = inferredToolFromSourcePath();
  const current = sourceSelectedToolId || inferred;
  if (!current && inferred) sourceSelectedToolId = inferred;
  statusEl.textContent = current
    ? `Selected tool: ${current}. If plugins/${current} exists, its source is attached live from the trusted workspace.`
    : 'Select a tool or open a file under plugins/<tool> to attach that tool context to the coding session.';
  if (!entries.length) {
    toolsEl.textContent = 'No agent tools are configured yet.';
    return;
  }
  toolsEl.innerHTML = entries.map((item) => {
    const selected = item.id === (sourceSelectedToolId || inferred);
    const requires = item.requiresTools.length ? item.requiresTools.join(', ') : 'none';
    const runtimeBinaries = item.binaries.length ? item.binaries.join(', ') : 'none';
    return `
      <div class="inline-browser-row ${selected ? 'selected' : ''}">
        <div>
          <b>${escapeHtml(item.id)}</b> <span class="pill">${escapeHtml(item.kind)}</span>
          ${!item.enabled ? '<span class="pill warning">disabled</span>' : ''}
          ${item.sourceAvailable ? '<span class="pill ok">source attached</span>' : '<span class="pill">no source tree</span>'}
          <div class="muted small-text">${escapeHtml(item.description || 'Agent tool source')}</div>
          <div class="muted small-text">source: ${escapeHtml(item.sourcePath)}</div>
          <div class="muted small-text">runtime binaries: ${escapeHtml(runtimeBinaries)}</div>
          <div class="muted small-text">requires: ${escapeHtml(requires)}</div>
        </div>
        <div class="button-row compact-actions">
          <button class="ghost-button source-tool-open" data-tool-open="${escapeHtml(item.id)}"${item.sourceAvailable ? '' : ' disabled'}>Open source</button>
          ${item.sourceAvailable ? '' : `<button class="ghost-button source-tool-create" data-tool-create="${escapeHtml(item.id)}">Create source</button>`}
          <button class="ghost-button source-tool-select" data-tool-select="${escapeHtml(item.id)}">${selected ? 'Attached' : 'Use in session'}</button>
        </div>
      </div>
    `;
  }).join('');
}
async function createSourceToolScaffold(toolId='') {
  const id = String(toolId || '').trim();
  if (!id) throw new Error('Tool id is required');
  const base = `plugins/${id}`;
  if (ideUsesSessionWorkspace()) {
    await api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/entry`, {method:'POST', body: JSON.stringify({path: base, type: 'dir'})});
  } else {
    await api('/v1/sources/entry', {method:'POST', body: JSON.stringify({path: base, type: 'dir'})});
  }
  const readme = `# ${id}\n\nAgent tool source for \`${id}\`.\n\nUse this folder for prompts, helper code, docs, or endpoint-side source related to this tool.\n`;
  if (ideUsesSessionWorkspace()) {
    await api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/content`, {method:'PUT', body: JSON.stringify({path: `${base}/README.md`, content: readme})});
  } else {
    await api('/v1/sources/content', {method:'PUT', body: JSON.stringify({path: `${base}/README.md`, content: readme})});
  }
  sourceExpandedDirs.add('plugins');
  sourceExpandedDirs.add(base);
  sourceTreeCache.clear();
  await renderSources(selectedSourceFolder || '');
  renderSourceToolCatalog();
}
function sourceOpenFilePayload(limit = 3, maxChars = 4000) {
  const files = [];
  for (const path of sourceOpenTabs.slice(0, limit)) {
    const state = sourceFileState.get(path) || {};
    let content = String(state.content || '');
    if (!content && path === selectedSourcePath) {
      const editor = document.getElementById('sourceEditor');
      content = String(editor?.value || '');
    }
    if (content.length > maxChars) content = `${content.slice(0, maxChars)}\n...[truncated]`;
    files.push({
      path,
      label: sourceFileLabel(path),
      content,
      dirty: !!state.dirty,
      active: path === selectedSourcePath,
    });
  }
  return files;
}
