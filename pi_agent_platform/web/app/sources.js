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
      else rows.push(`<div class="muted source-empty-folder nested" style="--source-depth:${(depth + 1) * 14}px">Loading…</div>`);
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


function selectedBuildFolder(kind) {
  const path = selectedSourceFolder || '';
  if (!path) return '';
  const parts = path.split('/').filter(Boolean);
  if (!parts.length) return '';
  if (kind === 'container' && parts[0] !== 'containers') return '';
  if (kind === 'binary' && parts[0] !== 'binaries') return '';
  return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : '';
}
function sourceBuildKindForPath(path) {
  const parts = (path || '').split('/').filter(Boolean);
  if (parts.length < 2) return '';
  if (parts[0] === 'containers') return 'container';
  if (parts[0] === 'binaries') return 'binary';
  return '';
}
function updateSourceActions() {
  const hint = document.getElementById('sourceActionHint');
  const cf = selectedBuildFolder('container');
  const bf = selectedBuildFolder('binary');
  const ideWorkspace = currentIdeWorkspace();
  if (hint) hint.textContent = ideUsesSessionWorkspace()
    ? `Browsing ${currentIdeSession()?.name || 'coding session'} in ${ideWorkspace?.name || ideWorkspace?.workspace_profile || 'workspace'}`
    : (bf ? `Viewing source: ${bf}. Build it from the IDE row.` : (cf ? `Container source: ${cf}. Build it from the IDE row.` : 'Filter by binary source folder.'));
  const title = document.getElementById('sourceBuildPanelTitle');
  if (title) title.textContent = 'Downloads';
}
function renderSourceBuildPanel(data={}) {
  const hintBox = document.getElementById('sourceBuildResult');
  if (hintBox && !hintBox.dataset.busy) hintBox.textContent = 'Available downloads are listed by version.';
  updateSourceActions();
}

async function syncDownloadsWithSourcePath(path='') {
  const parts = String(path || '').split('/').filter(Boolean);
  let project = selectedBinaryArtifactFilter || '';
  if (parts[0] === 'binaries') {
    project = parts[1] || '';
  }
  selectedBinaryArtifactFilter = project;
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts(project).catch(e=>paneError('Binary downloads unavailable', e.message));
}

function setBinaryFolderFilterValue(value) {
  const filter = document.getElementById('binaryFolderFilter');
  if (filter && filter.value !== value) filter.value = value || '';
}
async function loadBinaryFolderFilters() {
  const filter = document.getElementById('binaryFolderFilter');
  if (!filter) return;
  try {
    const data = await api('/v1/sources?path=binaries');
    const folders = (data.items || []).filter(i => i.type === 'dir').map(i => i.name).sort((a,b)=>a.localeCompare(b));
    const current = selectedBinaryArtifactFilter || '';
    filter.innerHTML = ['<option value="">All binary folders</option>'].concat(folders.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)).join('');
    filter.value = folders.includes(current) ? current : '';
    selectedBinaryArtifactFilter = filter.value;
  } catch(e) {
    filter.innerHTML = '<option value="">Binary folders unavailable</option>';
  }
}
function binaryVersionFromName(name) {
  const text = String(name || '');
  const match = text.match(/(?:^|[-_])v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)(?=$|[-_])/);
  return match ? match[1] : 'unversioned';
}
function binaryPlatformFromName(name, project) {
  let text = String(name || '');
  if (project && text.startsWith(project + '-')) text = text.slice(project.length + 1);
  text = text.replace(/^[0-9]+\.[0-9]+\.[0-9]+[-_]?/, '');
  const match = text.match(/(linux|darwin|windows|freebsd|openbsd|netbsd)[-_](amd64|arm64|arm|386|ppc64le|s390x)/i);
  return match ? match[0].replace('_', '/') : text;
}
function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (!n) return '0 bytes';
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function renderBinaryDownloads(projects) {
  const el = document.getElementById('sourceBinaryArtifacts');
  if (!el) return;
  const grouped = new Map();
  (projects || []).forEach(project => {
    (project.artifacts || []).forEach(a => {
      const version = a.version || (binaryVersionFromName(a.name) === 'unversioned' ? (project.source_version || 'unversioned') : binaryVersionFromName(a.name));
      const key = `${project.project}::${version}`;
      if (!grouped.has(key)) grouped.set(key, {project: project.project, version, artifacts: [], sourceVersion: project.source_version || ''});
      grouped.get(key).artifacts.push(a);
    });
  });
  const groups = Array.from(grouped.values()).sort((a,b) => {
    const projectCmp = a.project.localeCompare(b.project);
    if (projectCmp) return projectCmp;
    return b.version.localeCompare(a.version, undefined, {numeric:true});
  });
  if (!groups.length) {
    el.innerHTML = '<span class="muted">No downloads available yet for this category. Build binaries from the IDE row.</span>';
    return;
  }
  el.innerHTML = groups.map(group => {
    const links = group.artifacts
      .sort((a,b)=>String(a.name).localeCompare(String(b.name), undefined, {numeric:true}))
      .map(a => `<span class="download-artifact"><a class="download-pill" href="${a.download_url}" download title="${escapeHtml(a.name)}"><span>${escapeHtml(binaryPlatformFromName(a.name, group.project))}</span><small>${escapeHtml(formatBytes(a.size))}</small></a><button class="icon-button delete-artifact" data-project="${escapeHtml(group.project)}" data-filename="${escapeHtml(a.name)}" title="Delete this binary">×</button></span>`)
      .join('');
    return `<div class="download-version-group"><div class="download-version-title"><b>${escapeHtml(group.project)}</b><span>binary v${escapeHtml(group.version)}</span></div><div class="download-pill-list">${links}</div></div>`;
  }).join('');
  el.querySelectorAll('.delete-artifact').forEach(btn => {
    btn.onclick = () => deleteBinaryArtifact(btn.dataset.project || '', btn.dataset.filename || '').catch(e => paneError('Delete binary failed', e.message));
  });
}

async function deleteBinaryArtifact(project, filename) {
  if (!project || !filename) return;
  if (!confirm(`Delete binary ${filename}?`)) return;
  const result = await api(`/v1/sources/binary-artifacts/${encodeURIComponent(project)}/${encodeURIComponent(filename)}`, {method:'DELETE'});
  setSourceBuildHint(`Deleted ${result.deleted || filename}.`, false);
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter || '').catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}

async function pruneBinaryArtifacts(dryRun=false) {
  const project = selectedBinaryArtifactFilter || '';
  const label = project ? project : 'all binary folders';
  if (!dryRun && !confirm(`Keep only the newest binary version for ${label} and delete older versions?`)) return;
  const result = await api('/v1/sources/binary-artifacts/prune', {method:'POST', body:JSON.stringify({project, keep_versions:1, dry_run:dryRun})});
  const bytes = formatBytes(result.deleted_bytes || 0);
  setSourceBuildHint(dryRun ? `Prune preview: ${result.deleted_count || 0} old file(s), ${bytes}.` : `Pruned ${result.deleted_count || 0} old file(s), ${bytes}.`, false);
  await loadSourceBinaryArtifacts(project).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}
async function loadSourceBinaryArtifacts(project='') {
  const el = document.getElementById('sourceBinaryArtifacts');
  if (!el) return;
  try {
    const effectiveProject = project !== undefined && project !== null ? project : selectedBinaryArtifactFilter;
    setBinaryFolderFilterValue(effectiveProject || '');
    const qs = effectiveProject ? `?project=${encodeURIComponent(effectiveProject)}` : '';
    const data = await api(`/v1/sources/binary-artifacts${qs}`);
    renderBinaryDownloads(data.projects || []);
  } catch(e) { el.textContent = `Could not load downloads: ${e.message}`; }
}
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
function updateSourceCodingPanel() {
  const defaults = sourceCodingDefaults();
  const endpointName = (window.__pacEndpoints || []).find(r => r.id === defaults.endpointId)?.name || defaults.endpointId || '-';
  const contextSummary = document.getElementById('sourceCodingContextSummary');
  const workspaceSummary = defaults.workspaceName || defaults.workspaceProfile || defaults.workspacePath || 'workspace';
  const targetLabel = defaults.contextName ? `${defaults.contextName} (${workspaceSummary})` : workspaceSummary;
  if (contextSummary) {
    contextSummary.textContent = defaults.existingSession?.id
      ? `Attached to ${defaults.existingSession.name || defaults.existingSession.id} for ${targetLabel} on ${endpointName}.`
      : (selectedIdeContextId || selectedIdeWorkspaceId
        ? `Ready to start a coding session for ${targetLabel} on ${endpointName}.`
        : (sourceResolvedContext?.name
          ? `Ready to start a coding session for ${sourceResolvedContext.name} on ${endpointName}.`
          : `Select a context or workspace, then start a coding session on ${endpointName}.`));
  }
  const focusEl = document.getElementById('sourceCodingFocus');
  if (focusEl) {
    const openFiles = sourceOpenTabs.length ? sourceOpenTabs.map(sourceFileLabel).join(', ') : 'none';
    const sessionName = defaults.existingSession?.name || (sourceCodingSessionId ? 'attached session' : 'not started');
    focusEl.textContent = `Stack ${defaults.stack} • endpoint ${endpointName} • profile ${defaults.profileName || 'main-pi-dev'} • model ${defaults.modelName || '-'} • session ${sessionName} • open files ${openFiles}`;
  }
  const startBtn = document.getElementById('bootstrapSourceCodingSession');
  if (startBtn) startBtn.textContent = defaults.existingSession?.id ? 'Reopen coding session' : 'Start coding session';
  const sendBtn = document.getElementById('askSourceCodingSession');
  if (sendBtn) sendBtn.textContent = defaults.existingSession?.id ? 'Send to coding session' : 'Start and send';
  const openBtn = document.getElementById('openSourceCodingSession');
  if (openBtn) openBtn.disabled = !defaults.existingSession?.id && !sourceCodingSessionId;
  renderSourceToolCatalog();
  sourceCodingSessionId = defaults.existingSession?.id || selectedIdeSessionId || sourceCodingSessionId || '';
  if (sourceCodingSessionId) startSourceCodingPoll();
  else stopSourceCodingPoll();
  refreshSourceCodingActivity().catch(()=>{});
}
function sourceCodingLatestAssistantText(snapshot = {}) {
  const events = normalizeSourceCodingSnapshot(snapshot);
  const candidates = events.filter((event) => {
    const t = String(event?.type || '').toLowerCase();
    return t === 'result' || t === 'final' || t.includes('assistant_message');
  });
  for (let i = candidates.length - 1; i >= 0; i -= 1) {
    const text = resultEventText(candidates[i]);
    if (text) return normalizeAssistantText(text);
  }
  return '';
}
function sourceCodingLatestTask(snapshot = {}) {
  const events = normalizeSourceCodingSnapshot(snapshot);
  const tasks = new Map();
  for (const event of events) {
    const taskId = String(event?.task_id || '').trim();
    if (!taskId) continue;
    let item = tasks.get(taskId);
    if (!item) {
      item = {taskId, events: [], latestAt: 0};
      tasks.set(taskId, item);
    }
    item.events.push(event);
    const ts = sessionEventDate(event).getTime();
    if (ts > item.latestAt) item.latestAt = ts;
  }
  return Array.from(tasks.values()).sort((a, b) => b.latestAt - a.latestAt)[0] || null;
}
function normalizeSourceCodingSnapshot(snapshot = {}) {
  if (Array.isArray(snapshot)) return snapshot.slice();
  if (Array.isArray(snapshot.items)) return snapshot.items.slice();
  return [];
}
function isSelectedSessionSourceCodingSession() {
  return !!(sourceCodingSessionId && selectedSession?.id && selectedSession.id === sourceCodingSessionId);
}
function renderSourceCodingActivityFromSnapshot(snapshot = {}) {
  const liveEl = document.getElementById('sourceCodingLiveStatus');
  const summaryEl = document.getElementById('sourceCodingLiveSummary');
  const metaEl = document.getElementById('sourceCodingLiveMeta');
  const replyEl = document.getElementById('sourceCodingLatestReply');
  if (!liveEl || !summaryEl || !metaEl || !replyEl) return;
  const latestTask = sourceCodingLatestTask(snapshot);
  if (!latestTask) {
    liveEl.className = 'source-coding-live idle';
    summaryEl.textContent = sourceCodingSessionId ? 'No active coding task.' : 'No coding task running.';
    metaEl.textContent = sourceCodingSessionId ? 'Send a prompt from the IDE composer or open the session for full history.' : 'Start a coding session or send a prompt from the IDE.';
    replyEl.textContent = 'No coding reply yet.';
    return;
  }
  const internalItems = latestTask.events
    .filter((event) => isInternalSessionEvent(event))
    .map((event) => ({event, block: normalizeTimelineBlock(event)}));
  const lastInternal = internalItems[internalItems.length - 1]?.event || latestTask.events[latestTask.events.length - 1];
  const lastType = String(lastInternal?.type || '').toLowerCase();
  const summary = sessionThinkingSummary(lastInternal, normalizeTimelineBlock(lastInternal)) || 'Working';
  const stepInfo = lastInternal?.data?.step != null ? `step ${lastInternal.data.step}` : '';
  const approval = lastType.includes('approval_required') ? 'needs approval' : '';
  const toolCount = internalItems.filter((item) => String(item.event?.type || '').toLowerCase().includes('tool')).length;
  const toolInfo = toolCount ? `${toolCount} ${toolCount === 1 ? 'tool step' : 'tool steps'}` : '';
  const metaBits = [stepInfo, toolInfo, approval].filter(Boolean);
  const latestReply = sourceCodingLatestAssistantText(snapshot);
  const completed = latestTask.events.some((event) => {
    const t = String(event?.type || '').toLowerCase();
    return t.includes('task_completed') || t === 'result' || t === 'final';
  });
  liveEl.className = `source-coding-live ${approval ? 'attention' : completed ? 'done' : 'active'}`;
  summaryEl.textContent = summary;
  metaEl.textContent = metaBits.length ? metaBits.join(' • ') : (completed ? 'Last coding task completed.' : 'Coding session is working.');
  replyEl.textContent = latestReply || (completed ? 'The last coding task completed without a readable reply body.' : 'No coding reply yet.');
}
async function refreshSourceCodingActivity() {
  if (!sourceCodingSessionId) {
    renderSourceCodingActivityFromSnapshot([]);
    return;
  }
  if (isSelectedSessionSourceCodingSession()) return;
  const snapshot = await api(`/v1/sessions/${encodeURIComponent(sourceCodingSessionId)}/events/snapshot?latest=true&limit=80`);
  renderSourceCodingActivityFromSnapshot(snapshot || []);
}
function startSourceCodingPoll() {
  stopSourceCodingPoll();
  sourceCodingPoll = setInterval(() => {
    if (!sourceCodingSessionId) return;
    if (isSelectedSessionSourceCodingSession()) return;
    refreshSourceCodingActivity().catch(()=>{});
  }, 2000);
}
function stopSourceCodingPoll() {
  if (sourceCodingPoll) clearInterval(sourceCodingPoll);
  sourceCodingPoll = null;
}
async function ensureSourceCodingSession() {
  const defaults = sourceCodingDefaults();
  const toolIds = selectedSourceToolIds();
  const toolPaths = toolIds.map((id) => `plugins/${id}`);
  if (!defaults.contextId && !defaults.workspaceId && !defaults.workspaceProfile && !defaults.workspacePath) throw new Error('Select a context, workspace, or source context first.');
  if (!defaults.endpointId) throw new Error('No online endpoint is available for the coding session.');
  if (defaults.existingSession?.id) {
    sourceCodingSessionId = defaults.existingSession.id;
    selectedIdeSessionId = defaults.existingSession.id;
    return defaults.existingSession;
  }
  if (defaults.contextId) {
    const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(defaults.contextId)}/session`, {method:'POST'});
    const session = ensured.session;
    sourceCodingSessionId = session.id;
    selectedIdeSessionId = session.id;
    if (ensured.context?.workspace_id) selectedIdeWorkspaceId = ensured.context.workspace_id;
    await loadWorkspaceCatalogs().catch(()=>{});
    await loadSessions();
    updateSourceCodingPanel();
    sourceTreeCache.clear();
    await renderSources('');
    return session;
  }
  if (defaults.workspaceId) {
    const ensured = await api(`/v1/my-workspaces/${encodeURIComponent(defaults.workspaceId)}/session`, {method:'POST'});
    const session = ensured.session;
    sourceCodingSessionId = session.id;
    selectedIdeSessionId = session.id;
    await loadWorkspaceCatalogs().catch(()=>{});
    await loadSessions();
    updateSourceCodingPanel();
    sourceTreeCache.clear();
    await renderSources('');
    return session;
  }
  const sessionNameBase = defaults.workspaceProfile || sourceResolvedContext?.name || sourceFileLabel(selectedSourceFolder || selectedSourcePath || 'ide');
  const payload = {
    name: `code-${String(sessionNameBase).replace(/[^A-Za-z0-9._-]+/g, '-').toLowerCase()}`,
    agent_profile: defaults.profileName || null,
    model: defaults.modelName || null,
    workspace: defaults.workspaceProfile ? {type: 'profile', profile: defaults.workspaceProfile} : {type: 'local', path: defaults.workspacePath},
    metadata: {
      preferred_endpoint: defaults.endpointId,
      endpoint_locked: true,
      agent_enabled: true,
      execution_mode: 'pi.dev',
      preferred_execution_mode: 'container',
      container_image: defaults.containerImage,
      ide_mode: true,
      ide_stack: defaults.stack,
      ide_source_path: selectedSourceFolder || selectedSourcePath || '',
      ide_open_files: sourceOpenTabs.slice(),
      source_context_name: defaults.contextName || null,
      workspace_profile: defaults.workspaceProfile || null,
      agent_tool_ids: toolIds,
      agent_tool_paths: toolPaths,
      tool_source_mode: 'jit-workspace',
      workspace_trusted: true,
    },
  };
  const session = await api('/v1/sessions', {method:'POST', body: JSON.stringify(payload)});
  sourceCodingSessionId = session.id;
  selectedIdeSessionId = session.id;
  startSourceCodingPoll();
  await loadSessions();
  updateSourceCodingPanel();
  sourceTreeCache.clear();
  await renderSources('');
  return session;
}
function buildSourceCodingPrompt(userPrompt='') {
  const prompt = String(userPrompt || '').trim();
  const currentFile = selectedSourcePath || '';
  const openFiles = sourceOpenTabs.slice();
  const filePayload = sourceOpenFilePayload();
  const toolPayload = sourceToolPayload();
  const parts = [
    'You are working from the PAC IDE coding workbench.',
    'Focus on code, build failures, runtime errors, tests, and direct fixes in the selected workspace.',
    `Current source path: ${selectedSourceEntry || selectedSourceFolder || currentFile || '-'}.`,
    `Open files: ${openFiles.length ? openFiles.join(', ') : 'none'}.`,
  ];
  if (currentFile) parts.push(`Current file: ${currentFile}.`);
  if (sourceResolvedContext?.name) parts.push(`Resolved source context: ${sourceResolvedContext.name}.`);
  if (toolPayload.length) {
    parts.push('', 'Selected agent tools live in the same trusted workspace and should be used as live source context:');
    toolPayload.forEach((tool) => {
      parts.push(`Tool: ${tool.id} (${tool.kind}) at ${tool.source_path}`);
      if (tool.description) parts.push(tool.description);
      if (tool.requires_tools?.length) parts.push(`Requires runtime tools: ${tool.requires_tools.join(', ')}`);
      if (tool.documentation) parts.push(`Notes: ${tool.documentation}`);
      parts.push('');
    });
  }
  if (filePayload.length) {
    parts.push('', 'Open file context:');
    filePayload.forEach((item) => {
      parts.push(`File: ${item.path}${item.active ? ' [active]' : ''}${item.dirty ? ' [dirty]' : ''}`);
      parts.push(item.content || '[file is open but its contents are not loaded]');
      parts.push('');
    });
  }
  if (prompt) parts.push('', prompt);
  else parts.push('', 'Inspect the current workspace and help with the open files.');
  return parts.join('\n');
}
async function sendPromptToSourceCodingSession(promptText) {
  const session = await ensureSourceCodingSession();
  const defaults = sourceCodingDefaults();
  const openFilePayload = sourceOpenFilePayload();
  const toolIds = selectedSourceToolIds();
  const toolPayload = sourceToolPayload();
  const status = document.getElementById('sourceCodingStatus');
  const liveEl = document.getElementById('sourceCodingLiveStatus');
  const summaryEl = document.getElementById('sourceCodingLiveSummary');
  const metaEl = document.getElementById('sourceCodingLiveMeta');
  if (status) { status.hidden = false; status.textContent = 'Submitting coding task…'; }
  if (liveEl && summaryEl && metaEl) {
    liveEl.className = 'source-coding-live active';
    summaryEl.textContent = 'Submitting coding task';
    metaEl.textContent = 'Waiting for the coding session to accept the new request.';
  }
  const payload = {
    prompt: buildSourceCodingPrompt(promptText),
    metadata: {
      execution_mode: 'container',
      container_image: defaults.containerImage,
      open_files: sourceOpenTabs.slice(),
      open_file_payload: openFilePayload,
      agent_tool_ids: toolIds,
      agent_tool_payload: toolPayload,
      current_file: selectedSourcePath || '',
      source_context_name: sourceResolvedContext?.name || null,
    },
  };
  await api(`/v1/sessions/${encodeURIComponent(session.id)}/tasks`, {method:'POST', body: JSON.stringify(payload)});
  if (status) status.textContent = 'Coding task submitted.';
  await refreshSourceCodingActivity().catch(()=>{});
}
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
function renderMarketplaceResults(data) {
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  const results = data?.results || [];
  if (!results.length) {
    el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
    return;
  }
  el.innerHTML = results.map(item => {
    const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
    const quants = (item.available_quants || []).slice(0, 5).map(q => `<span class="marketplace-pill">${escapeHtml(q.toUpperCase())}</span>`).join('');
    return `<article class="marketplace-card"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></article>`;
  }).join('');
}
async function searchMarketplace() {
  const query = document.getElementById('marketplaceQuery')?.value?.trim() || '';
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  el.textContent = 'Searching marketplace…';
  try {
    const data = await api(`/v1/models/marketplace/search?q=${encodeURIComponent(query)}&limit=12`);
    renderMarketplaceResults(data);
  } catch (e) {
    el.textContent = e.message || String(e);
  }
}
function openMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = false;
  const input = document.getElementById('marketplaceModalQuery');
  if (input) input.value = document.getElementById('marketplaceQuery')?.value || '';
  renderMarketplaceModalDetail();
}
function closeMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = true;
}
function renderMarketplaceModalDetail(detail=null) {
  const title = document.getElementById('marketplaceDetailTitle');
  const version = document.getElementById('marketplaceDetailVersion');
  const body = document.getElementById('marketplaceDetailBody');
  if (!title || !version || !body) return;
  if (!detail) {
    title.textContent = 'Model details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Select a marketplace result to inspect provider fit and configure it as a PAC model.</div>';
    return;
  }
  title.textContent = detail.model_id || 'Model details';
  version.textContent = detail.params_b ? `${detail.params_b}B` : '';
  const providers = (detail.provider_scores || []).map(entry => {
    const provider = entry.provider || {};
    return `<tr><td><code>${escapeHtml(provider.name || '-')}</code></td><td>${escapeHtml(provider.type || '-')}</td><td>${escapeHtml(entry.quant_recommended || '-')}</td><td>${escapeHtml(entry.reason || '-')}</td></tr>`;
  }).join('');
  body.innerHTML = `<div class="muted small-text">Author: ${escapeHtml(detail.author || 'unknown')} • Downloads: ${escapeHtml(String(detail.downloads || 0))}</div><div class="marketplace-meta" style="margin:.6rem 0">${Object.entries(detail.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('')}</div><table class="compact-table"><thead><tr><th>Provider</th><th>Type</th><th>Quant</th><th>Fit</th></tr></thead><tbody>${providers || '<tr><td colspan="4" class="muted">No providers configured yet.</td></tr>'}</tbody></table><div class="button-row" style="margin-top:.75rem"><button id="configureMarketplaceModel">Configure as model</button></div>`;
  const btn = document.getElementById('configureMarketplaceModel');
  if (btn) btn.onclick = () => {
    const preferred = (detail.provider_scores || []).find(entry => entry.can_run && entry.provider?.name)?.provider?.name
      || (detail.provider_scores || [])[0]?.provider?.name
      || '';
    closeMarketplaceModal();
    openModelModal();
    if (preferred && modelProvider) modelProvider.value = preferred;
    if (modelId) modelId.value = detail.model_id || '';
    if (modelName) modelName.value = String(detail.model_id || '').replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
  };
}
async function searchMarketplaceModal() {
  const query = document.getElementById('marketplaceModalQuery')?.value?.trim() || '';
  const el = document.getElementById('marketplaceModalResults');
  if (!el) return;
  el.textContent = 'Searching marketplace...';
  try {
    const data = await api(`/v1/models/marketplace/search?q=${encodeURIComponent(query)}&limit=18`);
    const results = data?.results || [];
    if (!results.length) {
      el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
      return;
    }
    el.innerHTML = results.map(item => {
      const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
      return `<button class="marketplace-card marketplace-card-button" data-marketplace-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads</div></button>`;
    }).join('');
    el.querySelectorAll('[data-marketplace-model]').forEach(btn => btn.onclick = async () => {
      const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(btn.dataset.marketplaceModel || '')}`);
      renderMarketplaceModalDetail(detail);
    });
  } catch (e) {
    el.textContent = e.message || String(e);
  }
}
function formatBuildCommand(command) {
  return Array.isArray(command) ? command.join(' ') : String(command || '');
}
function setSourceBuildHint(text, busy=false) {
  const box = document.getElementById('sourceBuildResult');
  if (!box) return;
  box.dataset.busy = busy ? '1' : '';
  box.textContent = text || 'Available downloads are listed by version.';
}
function renderSourceBuildResult(result) {
  if (!result) { setSourceBuildHint(); return; }
  if (result.kind === 'binary') {
    const count = (result.artifacts || []).length;
    setSourceBuildHint(result.ok ? `${count} file${count === 1 ? '' : 's'} ready to download.` : 'Build failed. Open Events for details.', false);
  } else if (result.kind === 'container') {
    setSourceBuildHint(result.ok ? `Container image built: ${result.image || result.folder || ''}` : 'Container build failed. Open Events for details.', false);
  } else {
    setSourceBuildHint('Build finished. Open Events for details.', false);
  }
}
async function buildSelectedContainerSource() {
  const folder = selectedBuildFolder('container');
  if (!folder) return paneError('Select a buildable folder under containers first');
  setSourceBuildHint(`Building ${folder} from the folder root…`, true);
  emitUiEvent('source_container_build_started', `Container build started: ${folder}`, {path: folder});
  const result = await runWithPaneError(() => api('/v1/sources/build-container', {method:'POST', body:JSON.stringify({path:folder})}), 'Container build failed');
  if (result) { renderSourceBuildResult(result); emitUiEvent(result.ok ? 'source_container_built' : 'source_container_build_failed', result.ok ? `Container build completed: ${result.image || folder}` : `Container build failed: ${folder}`, result); }
  await loadGlobalEvents(true).catch(()=>{});
}
async function buildSelectedBinarySource() {
  const folder = selectedBuildFolder('binary');
  if (!folder) return paneError('Select a buildable folder under binaries first');
  setSourceBuildHint(`Building ${folder} for supported OS/architecture targets…`, true);
  emitUiEvent('source_binary_build_started', `Binary build started: ${folder}`, {path: folder});
  const result = await runWithPaneError(() => api('/v1/sources/build-binary', {method:'POST', body:JSON.stringify({path:folder, server_url:(config.server?.public_url || '').replace(/\/$/, '')})}), 'Binary build failed');
  if (result) { renderSourceBuildResult(result); emitUiEvent(result.ok ? 'source_binary_built' : 'source_binary_build_failed', result.ok ? `Binary build completed: ${folder}` : `Binary build failed: ${folder}`, result); }
  if (folder === 'binaries/zed-binary') await loadMcpBuildStatus().catch(()=>{});
  selectedBinaryArtifactFilter = folder.split('/')[1] || '';
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}
