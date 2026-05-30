// Source build/download browser helpers.
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
function downloadFilterTokens() {
  const input = document.getElementById('downloadFilterText');
  return String(input?.value || '').toLowerCase().split(/\s+/).map(token => token.trim()).filter(Boolean);
}
function updateDownloadsSummary(groups) {
  const el = document.getElementById('downloadsSummary');
  if (!el) return;
  const list = groups || [];
  const projectCount = new Set(list.map(group => group.project).filter(Boolean)).size;
  const versionCount = list.length;
  const fileCount = list.reduce((sum, group) => sum + (group.artifacts || []).length, 0);
  const totalBytes = list.reduce((sum, group) => sum + (group.artifacts || []).reduce((n, item) => n + Number(item.size || 0), 0), 0);
  const filterText = downloadFilterTokens().join(' ');
  el.textContent = `${projectCount} project${projectCount === 1 ? '' : 's'} • ${versionCount} version group${versionCount === 1 ? '' : 's'} • ${fileCount} file${fileCount === 1 ? '' : 's'} • ${formatBytes(totalBytes)}${filterText ? ` • filtered by "${filterText}"` : ''}`;
}
function filteredDownloadGroups(groups) {
  const tokens = downloadFilterTokens();
  if (!tokens.length) return groups;
  return (groups || []).map(group => {
    const artifacts = (group.artifacts || []).filter(item => {
      const haystack = [
        group.project,
        group.version,
        group.sourceVersion,
        item.name,
        binaryPlatformFromName(item.name, group.project),
      ].join(' ').toLowerCase();
      return tokens.every(token => haystack.includes(token));
    });
    return artifacts.length ? {...group, artifacts} : null;
  }).filter(Boolean);
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
  const visibleGroups = filteredDownloadGroups(groups);
  updateDownloadsSummary(visibleGroups);
  if (!groups.length) {
    el.innerHTML = '<div class="download-empty-state">No downloads available yet for this category. Build binaries from the IDE row.</div>';
    return;
  }
  if (!visibleGroups.length) {
    el.innerHTML = '<div class="download-empty-state">No downloads matched the current filter.</div>';
    return;
  }
  el.innerHTML = visibleGroups.map(group => {
    const links = group.artifacts
      .sort((a,b)=>String(a.name).localeCompare(String(b.name), undefined, {numeric:true}))
      .map(a => {
        const installLink = a.install_script_url
          ? `<a class="download-pill download-pill-secondary" href="${a.install_script_url}" download title="Download PowerShell install/update script for ${escapeHtml(a.name)}"><span>install script</span><small>.ps1</small></a>`
          : '';
        return `<span class="download-artifact"><a class="download-pill" href="${a.download_url}" download title="${escapeHtml(a.name)}"><span>${escapeHtml(binaryPlatformFromName(a.name, group.project))}</span><small>${escapeHtml(formatBytes(a.size))}</small></a>${installLink}<button class="icon-button delete-artifact" data-project="${escapeHtml(group.project)}" data-filename="${escapeHtml(a.name)}" title="Delete this binary">&times;</button></span>`;
      })
      .join('');
    const totalSize = group.artifacts.reduce((sum, item) => sum + Number(item.size || 0), 0);
    return `<div class="download-version-group"><div class="download-version-head"><div><div class="download-version-title"><b>${escapeHtml(group.project)}</b><span>binary v${escapeHtml(group.version)}</span></div><div class="download-version-meta">${escapeHtml(String(group.artifacts.length))} file(s) • ${escapeHtml(formatBytes(totalSize))}${group.sourceVersion ? ` • source ${escapeHtml(group.sourceVersion)}` : ''}</div></div><div class="download-version-actions"><button class="ghost-button delete-version-group" data-project="${escapeHtml(group.project)}" data-version="${escapeHtml(group.version)}" title="Delete all binaries in this version group">Delete version</button></div></div><div class="download-pill-list">${links}</div></div>`;
  }).join('');
  el.querySelectorAll('.delete-artifact').forEach(btn => {
    btn.onclick = () => deleteBinaryArtifact(btn.dataset.project || '', btn.dataset.filename || '').catch(e => paneError('Delete binary failed', e.message));
  });
  el.querySelectorAll('.delete-version-group').forEach(btn => {
    btn.onclick = () => deleteBinaryArtifactVersionGroup(btn.dataset.project || '', btn.dataset.version || '').catch(e => paneError('Delete version failed', e.message));
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
  if (!dryRun && !confirm(`Clean generated binary downloads for ${label}? This keeps the newest build per version/platform and removes stale deprecated artifacts.`)) return;
  const result = await api('/v1/sources/binary-artifacts/prune', {method:'POST', body:JSON.stringify({project, keep_versions:1, dry_run:dryRun})});
  const bytes = formatBytes(result.deleted_bytes || 0);
  const noteText = (result.notes || []).length ? ` Notes: ${(result.notes || []).join('; ')}` : '';
  setSourceBuildHint(dryRun ? `Cleanup preview: ${result.deleted_count || 0} old file(s), ${bytes}.${noteText}` : `Cleaned ${result.deleted_count || 0} old file(s), ${bytes}.${noteText}`, false);
  await loadSourceBinaryArtifacts(project).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}
async function deleteBinaryArtifactVersionGroup(project, version) {
  if (!project || !version) return;
  const data = await api(`/v1/sources/binary-artifacts?project=${encodeURIComponent(project)}`);
  const projectEntry = (data.projects || []).find(item => String(item.project || '') === String(project));
  const artifacts = (projectEntry?.artifacts || []).filter(item => {
    const itemVersion = item.version || (binaryVersionFromName(item.name) === 'unversioned' ? (projectEntry.source_version || 'unversioned') : binaryVersionFromName(item.name));
    return String(itemVersion) === String(version);
  });
  if (!artifacts.length) {
    setSourceBuildHint(`No binaries found for ${project} v${version}.`, false);
    return;
  }
  if (!confirm(`Delete ${artifacts.length} binary file(s) for ${project} v${version}?`)) return;
  for (const artifact of artifacts) {
    await api(`/v1/sources/binary-artifacts/${encodeURIComponent(project)}/${encodeURIComponent(artifact.name)}`, {method:'DELETE'});
  }
  setSourceBuildHint(`Deleted ${artifacts.length} binary file(s) for ${project} v${version}.`, false);
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter || '').catch(()=>{});
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
    sourceBinaryArtifactProjects = data.projects || [];
    renderBinaryDownloads(sourceBinaryArtifactProjects);
  } catch(e) { el.textContent = `Could not load downloads: ${e.message}`; }
}
