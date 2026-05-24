(function () {
function setBackupDetail(meta=null) {
  const title = document.getElementById('backupDetailTitle');
  const version = document.getElementById('backupDetailVersion');
  const body = document.getElementById('backupDetailBody');
  if (!title || !version || !body) return;
  if (!meta) {
    title.textContent = 'Backup details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Select a preserved backup to inspect downloads, local-change summary, or restore the controller.</div>';
    return;
  }
  title.textContent = meta.title || 'Backup details';
  version.textContent = meta.version ? `v${meta.version}` : '';
  body.innerHTML = meta.html_body ? `<div class="muted small-text">${meta.html_body}</div>` : (meta.body ? `<div class="muted small-text">${escapeHtml(meta.body)}</div>` : '<div class="muted small-text">No additional details available.</div>');
}

function renderLocalDiffs(data) {
  const list = document.getElementById('localDiffList');
  const status = document.getElementById('localDiffStatus');
  const input = document.getElementById('localDiffVersion');
  if (input && !input.value) input.value = data?.suggested_version || '';
  if (status) status.textContent = data?.suggested_version ? `Suggested release diff version: v${data.suggested_version}` : '';
  if (!list) return;
  const diffs = data?.diffs || [];
  if (!diffs.length) {
    list.innerHTML = '<div class="muted small-text">No generated local diffs yet. Generate one from the current workspace to prepare an online update or release patch.</div>';
    return;
  }
  list.innerHTML = diffs.map((item) => {
    const size = Number(item.size || 0).toLocaleString();
    const modified = item.modified_at ? formatEventTime(item.modified_at) : '';
    return `<button class="update-archive-row" data-local-diff="${escapeHtml(item.version)}"><b>v${escapeHtml(item.version)}</b><span class="muted small-text">${escapeHtml(size)} bytes${modified ? ` • ${escapeHtml(modified)}` : ''}</span></button>`;
  }).join('');
  list.querySelectorAll('[data-local-diff]').forEach(btn => btn.onclick = async () => {
    const version = btn.dataset.localDiff || '';
    const link = `/v1/updates/diff/${encodeURIComponent(version)}`;
    setUpdatesDetail({
      title: 'Generated local diff',
      version,
      body: `Use this diff as the source patch for the next PAC release/update packaging flow.`,
      html_body: `Download: <a href="${link}">v${escapeHtml(version)}.diff</a>`,
    });
  });
}

async function loadLocalDiffs() {
  const data = await api('/v1/updates/local-diffs');
  renderLocalDiffs(data);
  return data;
}

async function generateLocalDiffNow() {
  const input = document.getElementById('localDiffVersion');
  const status = document.getElementById('localDiffStatus');
  const button = document.getElementById('generateLocalDiff');
  const version = String(input?.value || '').trim().replace(/^v/i, '');
  if (!version) return paneError('A version is required to generate a local diff');
  if (!confirm(`Generate .pac/diffs/v${version}.diff from the current local PAC workspace?`)) return;
  if (button) { button.disabled = true; button.textContent = 'Generating…'; }
  if (status) status.textContent = 'Generating local diff…';
  try {
    const result = await api(`/v1/updates/generate-local-diff?version=${encodeURIComponent(version)}`, {method:'POST'});
    if (result.ok && result.status === 'written') {
      if (status) status.textContent = `Generated v${version}.diff`;
      setUpdatesDetail({
        title: 'Generated local diff',
        version,
        body: `The local workspace diff is ready for the release/update pipeline.`,
        html_body: `Download: <a href="/v1/updates/diff/${encodeURIComponent(version)}">v${escapeHtml(version)}.diff</a>`,
      });
      await loadLocalDiffs().catch(()=>{});
      return;
    }
    if (result.ok && result.status === 'no_diff') {
      if (status) status.textContent = 'No local differences found.';
      setUpdatesDetail({title:'Generated local diff', version, body:'No local differences were found against upstream main.'});
      await loadLocalDiffs().catch(()=>{});
      return;
    }
    if (status) status.textContent = result.error || 'Local diff generation failed.';
  } catch (e) {
    if (status) status.textContent = e.message || String(e);
    throw e;
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Generate local diff'; }
  }
}

function renderUpdateArchives(data) {
  const list = document.getElementById('updateArchivesList');
  const hint = document.getElementById('updateArchiveHint');
  const modalHint = document.getElementById('backupsModalHint');
  const badge = document.getElementById('pacArchiveStatus');
  const current = document.getElementById('pacCurrentVersion');
  if (current) current.textContent = `v${data?.current_version || config.setup_status?.version || '?'}`;
  if (!list || !badge) return;
  const archives = data?.archives || [];
  badge.textContent = archives.length ? `${archives.length} archived` : 'none yet';
  badge.className = `pac-status-badge ${archives.length ? 'current-badge' : ''}`.trim();
  if (hint) hint.textContent = archives.length ? `Latest archive: ${archives[0].stamp}` : 'No preserved controller archives yet.';
  if (modalHint) modalHint.textContent = archives.length ? `${archives.length} preserved backup(s) available.` : 'No preserved controller backups yet.';
  if (!archives.length) {
    list.innerHTML = '<div class="muted small-text">No update archives available yet. Archives will appear after PAC app updates are applied.</div>';
    setBackupDetail();
    return;
  }
  list.innerHTML = archives.map(item => {
    const summary = item.summary?.file_count || {};
    return `<button class="update-archive-row" data-update-archive="${escapeHtml(item.stamp)}"><b>${escapeHtml(item.stamp)}</b><span class="muted small-text">modified ${escapeHtml(String(summary.modified || 0))} • added ${escapeHtml(String(summary.added || 0))} • removed ${escapeHtml(String(summary.removed || 0))}</span></button>`;
  }).join('');
  list.querySelectorAll('[data-update-archive]').forEach(btn => btn.onclick = async () => {
    const stamp = btn.dataset.updateArchive;
    const detail = await api(`/v1/updates/archives/${encodeURIComponent(stamp)}`);
    const summary = detail.summary || {};
    const fileCount = summary.file_count || {};
    const links = [
      detail.archive_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=archive">backup.tar.gz</a>` : '',
      detail.diff_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=diff">user diff</a>` : '',
      detail.summary_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=summary">summary json</a>` : '',
    ].filter(Boolean).join(' • ');
    setBackupDetail({
      title: 'Preserved local changes',
      version: '',
      html_body: `${escapeHtml(stamp)}<br>modified: ${escapeHtml(String(fileCount.modified || 0))}<br>added: ${escapeHtml(String(fileCount.added || 0))}<br>removed: ${escapeHtml(String(fileCount.removed || 0))}${links ? `<br><br>Downloads: ${links}` : ''}<br><br><button id="restoreBackupArchive" class="ghost-button">Restore this backup</button>`,
    });
    const restoreBtn = document.getElementById('restoreBackupArchive');
    if (restoreBtn) restoreBtn.onclick = () => restoreBackupArchive(stamp).catch(e=>paneError('Backup restore failed', e.message));
  });
}

async function loadUpdateArchives() {
  const data = await api('/v1/updates/status');
  renderUpdateArchives(data);
  const notes = await api('/v1/updates/release-notes').catch(()=>null);
  const fallbackBody = data?.latest_archive?.summary ? 'Latest preserved local change summary is available through Backups.' : '';
  setUpdatesDetail({
    title:'Current release',
    version:data?.current_version || config.version || config.setup_status?.version || '',
    entries:notes?.entries || [],
    body:notes?.body || fallbackBody,
    html_body:notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
  });
  if (!window.__pacReleaseMeta) checkPacRelease().catch(()=>{});
  setBackupDetail();
}

function openBackupsModal() {
  const modal = document.getElementById('backupsModal');
  if (modal) modal.hidden = false;
}

function closeBackupsModal() {
  const modal = document.getElementById('backupsModal');
  if (modal) modal.hidden = true;
}

async function restoreBackupArchive(stamp) {
  if (!stamp) return;
  if (!confirm(`Restore PAC from backup ${stamp}? The current app state will be preserved first, then PAC will restart.`)) return;
  const result = await api(`/v1/updates/archives/${encodeURIComponent(stamp)}/restore?restart_after_restore=true`, {method:'POST'});
  setBackupDetail({title:'Backup restore scheduled', body:`PAC scheduled a restart after restoring backup ${stamp}. Current app state was preserved before the restore.`});
  if (result.restart_scheduled) scheduleHiddenReloadAfterRestart();
}


  window.setBackupDetail = setBackupDetail;
  window.renderLocalDiffs = renderLocalDiffs;
  window.loadLocalDiffs = loadLocalDiffs;
  window.generateLocalDiffNow = generateLocalDiffNow;
  window.renderUpdateArchives = renderUpdateArchives;
  window.loadUpdateArchives = loadUpdateArchives;
  window.openBackupsModal = openBackupsModal;
  window.closeBackupsModal = closeBackupsModal;
  window.restoreBackupArchive = restoreBackupArchive;
})();
