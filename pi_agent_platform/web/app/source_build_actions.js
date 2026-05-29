// Source build action helpers for containers and binaries.
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
  if (folder === 'binaries/pacctl') await loadMcpBuildStatus().catch(()=>{});
  selectedBinaryArtifactFilter = folder.split('/')[1] || '';
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}
