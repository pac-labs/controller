// Source browser tree, editor tabs, and file entry actions.
// Source library, IDE coding helpers, source secrets, marketplace, and build UI helpers.
function sourceDirForNewEntry() {
  if (selectedSourceEntry && sourceFileState.has(selectedSourceEntry)) return selectedSourceEntry.split('/').slice(0, -1).join('/');
  if (selectedSourceEntry && !sourceFileState.has(selectedSourceEntry)) return selectedSourceEntry;
  if (selectedSourcePath) return selectedSourcePath.split('/').slice(0, -1).join('/');
  return selectedSourceFolder || '';
}
function sourceFileLabel(path) { return (path || '').split('/').pop() || path || 'untitled'; }
function markSourceDirty(path, dirty=true) {
  const state = sourceFileState.get(path);
  if (!state) return;
  state.dirty = !!dirty;
  renderSourceTabs();
  updateSourceDirtyTreeMarkers();
}
function updateSourceDirtyTreeMarkers() {
  const tree = document.getElementById('sourceTree');
  if (!tree) return;
  tree.querySelectorAll('[data-source-path]').forEach(btn => {
    const p = btn.dataset.sourcePath || '';
    btn.classList.toggle('source-dirty', !!sourceFileState.get(p)?.dirty);
  });
}
function renderSourceTabs() {
  const tabs = document.getElementById('sourceTabs');
  if (!tabs) return;
  if (!sourceOpenTabs.length) {
    tabs.innerHTML = '<span class="muted small-text">Open a file from the tree.</span>';
    return;
  }
  tabs.innerHTML = sourceOpenTabs.map(path => {
    const state = sourceFileState.get(path) || {};
    const active = path === selectedSourcePath ? ' active' : '';
    const dirty = state.dirty ? ' dirty' : '';
    return `<button class="source-tab${active}${dirty}" data-source-tab="${escapeHtml(path)}" title="${escapeHtml(path)}"><span>${escapeHtml(sourceFileLabel(path))}</span>${state.dirty ? '<b>•</b>' : ''}<em data-source-close="${escapeHtml(path)}">×</em></button>`;
  }).join('');
  tabs.querySelectorAll('[data-source-tab]').forEach(btn => btn.onclick = (ev) => {
    if (ev.target?.dataset?.sourceClose) return;
    activateSourceTab(btn.dataset.sourceTab || '');
  });
  tabs.querySelectorAll('[data-source-close]').forEach(btn => btn.onclick = (ev) => {
    ev.stopPropagation();
    closeSourceTab(btn.dataset.sourceClose || '');
  });
}
function activateSourceTab(path) {
  const state = sourceFileState.get(path);
  const editor = document.getElementById('sourceEditor');
  if (!state || !editor) return;
  selectedSourcePath = path;
  selectedSourceEntry = path;
  selectedSourceFolder = path.split('/').slice(0, -1).join('/');
  editor.value = state.content || '';
  updateSourceActions();
  renderSourceTabs();
  updateSourceCodingPanel();
}
function closeSourceTab(path) {
  if (sourceFileState.get(path)?.dirty && !confirm(`${path} has unsaved changes. Close it anyway?`)) return;
  sourceFileState.delete(path);
  sourceOpenTabs = sourceOpenTabs.filter(p => p !== path);
  if (selectedSourcePath === path) {
    selectedSourcePath = sourceOpenTabs[sourceOpenTabs.length - 1] || null;
    if (selectedSourcePath) activateSourceTab(selectedSourcePath);
    else {
      const editor = document.getElementById('sourceEditor');
      if (editor) editor.value = '';
      renderSourceTabs();
    }
  } else renderSourceTabs();
  updateSourceDirtyTreeMarkers();
  updateSourceCodingPanel();
}
function sourceDepth(path) {
  return (path || '').split('/').filter(Boolean).length;
}
function sourceChildRows(items, depth=0) {
  const rows = [];
  (items || []).forEach(item => {
    const isDir = item.type === 'dir';
    const expanded = isDir && sourceExpandedDirs.has(item.path);
    const iconClass = isDir ? (expanded ? 'tree-icon tree-folder open' : 'tree-icon tree-folder') : 'tree-icon tree-file';
    const versionPill = item.source_version ? `<span class="source-version-pill" title="source version">v${escapeHtml(item.source_version)}</span>` : '';
    const kindLabel = item.component_kind || item.buildable_kind || '';
    const kindPill = kindLabel ? `<span class="source-kind-pill">${escapeHtml(kindLabel)}</span>` : '';
    const componentTitle = item.component_title || item.name;
    const componentHint = item.component_description ? ` title="${escapeHtml(item.component_description)}"` : '';
    const buildTitle = item.buildable_kind === 'container' ? 'Build container image' : 'Build binaries';
    const buildButton = item.buildable_kind ? `<button class="source-build-icon" data-build-kind="${escapeHtml(item.buildable_kind)}" data-build-path="${escapeHtml(item.path)}" title="${buildTitle}" aria-label="${buildTitle}">▶</button>` : '';
    const dirty = sourceFileState.get(item.path)?.dirty ? ' source-dirty' : '';
    const selected = selectedSourceEntry === item.path ? ' selected' : '';
    const indent = Math.max(0, depth) * 22;
    rows.push(`<div class="source-row-wrap ${item.buildable_kind ? 'buildable-source-row' : ''}${selected}" style="--source-depth:${indent}px"><button class="source-row ${isDir ? 'source-dir' : 'source-file'}${dirty}${selected}" data-source-path="${escapeHtml(item.path)}" data-source-type="${item.type}"${componentHint}><span class="source-name"><span class="${iconClass}" aria-hidden="true"></span>${escapeHtml(componentTitle)}${dirty ? '<b class="dirty-dot">•</b>' : ''}</span><span class="source-row-meta">${versionPill}${kindPill}</span></button>${buildButton}</div>`);
    if (isDir && expanded) {
      const cached = sourceTreeCache.get(item.path);
      if (cached?.items?.length) rows.push(...sourceChildRows(cached.items, depth + 1));
      else if (cached) rows.push(`<div class="muted source-empty-folder nested" style="--source-depth:${(depth + 1) * 14}px">No files in this folder.</div>`);
      else rows.push(`<div class="muted source-empty-folder nested pac-loading-placeholder" style="--source-depth:${(depth + 1) * 14}px">${pacLoadingLineHtml('Loading…', {size:'tiny'})}</div>`);
    }
  });
  return rows;
}
async function openSourcePath(path='', type='') {
  const p = String(path || '').trim();
  const sourceType = String(type || '').trim().toLowerCase();
  if (!p) return;
  selectedSourceEntry = p;
  if (sourceType === 'dir' || (!sourceType && !/\.[A-Za-z0-9._-]+$/.test(p.split('/').pop() || ''))) {
    selectedSourceFolder = p;
    if (sourceExpandedDirs.has(p)) sourceExpandedDirs.delete(p);
    else sourceExpandedDirs.add(p);
    await renderSources('', {preserveCache:true, focusPath:p});
  } else {
    await openSourceFile(p);
  }
  updateSourceActions();
}
function bindSourceTreeEvents(tree) {
  tree.onclick = async (ev) => {
    const btn = ev.target.closest?.('.source-row');
    if (!btn) return;
    ev.preventDefault();
    await openSourcePath(btn.dataset.sourcePath || '', btn.dataset.sourceType || '');
  };
  tree.oncontextmenu = (ev) => {
    const btn = ev.target.closest?.('.source-row');
    if (!btn) return;
    openSourceContextMenu(ev, btn.dataset.sourcePath || '', btn.dataset.sourceType || 'file');
  };
  tree.querySelectorAll('.source-build-icon').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      selectedSourceFolder = btn.dataset.buildPath || '';
      selectedSourceEntry = selectedSourceFolder;
      updateSourceActions();
      if (btn.dataset.buildKind === 'container') buildSelectedContainerSource();
      else buildSelectedBinarySource();
    };
  });
}
function normalizeSourceCachePath(path='') {
  const value = String(path || '').trim();
  return (!value || value === '.') ? '' : value.replace(/^\/+/, '');
}
async function ensureSourceDirLoaded(path='') {
  if (ideUsesSessionWorkspace()) return ensureIdeDirLoaded(path);
  const data = await api(`/v1/sources?path=${encodeURIComponent(path)}`);
  const cachePath = normalizeSourceCachePath(data.path ?? path);
  data.path = cachePath;
  sourceTreeCache.set(cachePath, data);
  return data;
}
async function renderSources(path='', options={}) {
  const tree = document.getElementById('sourceTree');
  if (!tree) return;
  try {
    renderIdeWorkspaceSelectors();
    if (ideUsesSessionWorkspace() && !currentIdeSession()) {
      tree.classList.add('muted');
      tree.innerHTML = '<div class="muted source-empty-folder">Select a workspace and start or attach a coding session to browse files here.</div>';
      sourceTreeCache.clear();
      sourceOpenTabs = [];
      sourceFileState.clear();
      selectedSourcePath = null;
      selectedSourceFolder = '';
      selectedSourceEntry = '';
      updateSourceActions();
      updateSourceCodingPanel();
      return;
    }
    const targetPath = options.focusPath !== undefined ? options.focusPath : path;
    if (!options.preserveCache || !sourceTreeCache.has('')) await ensureSourceDirLoaded('');
    if (!ideUsesSessionWorkspace()) sourceExpandedDirs.add('plugins');
    if (path && !sourceTreeCache.has(path)) await ensureSourceDirLoaded(path);
    const expanded = Array.from(sourceExpandedDirs).filter(Boolean);
    for (const dir of expanded) {
      if (!sourceTreeCache.has(dir)) await ensureSourceDirLoaded(dir);
    }
    const rootData = sourceTreeCache.get('') || {items:[]};
    let rootItems = rootData.items || [];
    if (!rootItems.length && Array.isArray(rootData.top_level) && rootData.top_level.length) {
      rootItems = rootData.top_level.map(name => ({name, path:name, type:'dir'}));
    }
    const rows = sourceChildRows(rootItems, 0);
    sourceLibraryRoot = rootData.root || sourceLibraryRoot || '';
    tree.classList.remove('muted');
    tree.innerHTML = rows.length ? rows.join('') : `<div class="muted source-empty-folder">${ideUsesSessionWorkspace() ? 'No files in this workspace yet.' : 'No source folders found.'}</div>`;
    selectedSourceFolder = selectedSourceFolder || targetPath || '';
    updateSourceActions();
    if (!ideUsesSessionWorkspace()) {
      renderSourceBuildPanel(sourceTreeCache.get(selectedSourceFolder) || rootData);
      await syncDownloadsWithSourcePath(selectedSourceFolder || '');
    }
    bindSourceTreeEvents(tree);
    resolveCurrentSourceContext().catch(()=>{});
    updateSourceCodingPanel();
  } catch (e) {
    tree.classList.add('muted');
    tree.textContent = e.message || String(e);
    paneError('Source list unavailable', e.message || String(e));
  }
}
async function openSourceFile(path) {
  const editor = document.getElementById('sourceEditor');
  if (!editor) return;
  try {
    const data = ideUsesSessionWorkspace()
      ? await api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/content?path=${encodeURIComponent(path)}`)
      : await api(`/v1/sources/content?path=${encodeURIComponent(path)}`);
    selectedSourcePath = data.path;
    selectedSourceEntry = data.path;
    selectedSourceFolder = data.path.split('/').slice(0, -1).join('/');
    if (!sourceOpenTabs.includes(data.path)) sourceOpenTabs.push(data.path);
    sourceFileState.set(data.path, {content:data.content || '', saved:data.content || '', dirty:false});
    activateSourceTab(data.path);
    updateSourceCodingPanel();
  } catch (e) {
    paneError('Source file could not be opened', e.message || String(e));
  }
}
async function saveSourceFile(path=selectedSourcePath) {
  const editor = document.getElementById('sourceEditor');
  if (!path || !editor) { paneError('No source file selected'); return; }
  if (path === selectedSourcePath) {
    const state = sourceFileState.get(path) || {};
    state.content = editor.value;
    sourceFileState.set(path, state);
  }
  const state = sourceFileState.get(path);
  const content = state ? state.content : editor.value;
  const request = () => ideUsesSessionWorkspace()
    ? api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/content`, {method:'PUT', body: JSON.stringify({path, content})})
    : api('/v1/sources/content', {method:'PUT', body: JSON.stringify({path, content})});
  const result = await runWithPaneError(request, 'Source file could not be saved');
  if (result) {
    const current = sourceFileState.get(path) || {};
    current.saved = content; current.content = content; current.dirty = false;
    sourceFileState.set(path, current);
    renderSourceTabs(); updateSourceDirtyTreeMarkers();
    emitUiEvent('source_file_saved', `Source saved: ${result.path}`, result);
  }
}
async function saveAllSourceFiles() {
  for (const path of sourceOpenTabs.slice()) if (sourceFileState.get(path)?.dirty) await saveSourceFile(path);
}
async function createSourceEntry(type) {
  const base = sourceDirForNewEntry();
  const label = type === 'dir' ? 'New folder name' : 'New file name';
  const name = prompt(label, type === 'dir' ? 'new-folder' : 'new-file.txt');
  if (!name) return;
  const path = [base, name].filter(Boolean).join('/');
  const request = () => ideUsesSessionWorkspace()
    ? api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/entry`, {method:'POST', body:JSON.stringify({path, type})})
    : api('/v1/sources/entry', {method:'POST', body:JSON.stringify({path, type})});
  const result = await runWithPaneError(request, `Source ${type} could not be created`);
  if (result) { sourceTreeCache.clear(); if (type === 'dir') sourceExpandedDirs.add(result.path); await renderSources(base); if (type !== 'dir') await openSourceFile(result.path); }
}
async function renameSelectedSourceEntry(path=selectedSourceEntry) {
  if (!path) return paneError('Select a source entry first');
  const newName = prompt('Rename to', sourceFileLabel(path));
  if (!newName || newName === sourceFileLabel(path)) return;
  const request = () => ideUsesSessionWorkspace()
    ? api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/entry/rename`, {method:'POST', body:JSON.stringify({path, new_name:newName})})
    : api('/v1/sources/entry/rename', {method:'POST', body:JSON.stringify({path, new_name:newName})});
  const result = await runWithPaneError(request, 'Source entry could not be renamed');
  if (result) {
    if (sourceFileState.has(path)) {
      const state = sourceFileState.get(path); sourceFileState.delete(path); sourceFileState.set(result.new_path, state);
      sourceOpenTabs = sourceOpenTabs.map(p => p === path ? result.new_path : p);
      if (selectedSourcePath === path) selectedSourcePath = result.new_path;
    }
    selectedSourceEntry = result.new_path;
    sourceTreeCache.clear(); await renderSources(result.new_path.split('/').slice(0,-1).join('/'));
    renderSourceTabs();
  }
}
async function deleteSelectedSourceEntry(path=selectedSourceEntry) {
  if (!path) return paneError('Select a source entry first');
  if (!confirm(`Delete ${path}?`)) return;
  const parent = path.split('/').slice(0,-1).join('/');
  const request = () => ideUsesSessionWorkspace()
    ? api(`/v1/sessions/${encodeURIComponent(currentIdeSession()?.id || '')}/files/entry?path=${encodeURIComponent(path)}`, {method:'DELETE'})
    : api(`/v1/sources/entry?path=${encodeURIComponent(path)}`, {method:'DELETE'});
  const result = await runWithPaneError(request, 'Source entry could not be deleted');
  if (result) {
    if (sourceFileState.has(path)) closeSourceTab(path);
    selectedSourceEntry = parent;
    sourceTreeCache.clear(); await renderSources(parent);
  }
}
function ensureSourceContextMenu() {
  let menu = document.getElementById('sourceContextMenu');
  if (menu) return menu;
  menu = document.createElement('div');
  menu.id = 'sourceContextMenu';
  menu.className = 'source-context-menu';
  document.body.appendChild(menu);
  document.addEventListener('click', () => { menu.hidden = true; });
  return menu;
}
function openSourceContextMenu(ev, path, type) {
  ev.preventDefault(); ev.stopPropagation();
  selectedSourceEntry = path;
  const menu = ensureSourceContextMenu();
  const buildKind = path.startsWith('binaries/') && path.split('/').length === 2 ? 'binary' : (path.startsWith('containers/') && path.split('/').length === 2 ? 'container' : '');
  menu.innerHTML = `<button data-action="rename">Rename</button>${type === 'file' ? '<button data-action="save">Save file</button>' : ''}<button data-action="delete">Delete</button>${buildKind ? '<button data-action="build">Build</button>' : ''}`;
  menu.style.left = `${ev.clientX}px`; menu.style.top = `${ev.clientY}px`; menu.hidden = false;
  menu.querySelectorAll('button').forEach(btn => btn.onclick = async (e) => {
    e.stopPropagation(); menu.hidden = true;
    const action = btn.dataset.action;
    if (action === 'rename') await renameSelectedSourceEntry(path);
    if (action === 'save') await saveSourceFile(path);
    if (action === 'delete') await deleteSelectedSourceEntry(path);
    if (action === 'build') { selectedSourceFolder = path; if (buildKind === 'container') await buildSelectedContainerSource(); else await buildSelectedBinarySource(); }
  });
}
