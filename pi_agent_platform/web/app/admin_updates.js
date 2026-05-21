// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

async function loadProxyRoutes() {
  try {
    const routes = await api('/v1/proxy-routes');
    _proxyRoutesCache = Array.isArray(routes) ? routes : [];
    renderProxyRoutes();
  } catch(e) {
    console.error('Failed to load proxy routes:', e);
  }
}

function renderProxyRoutes() {
  const el = document.getElementById('proxyRoutesList');
  if (!el) return;
  if (!_proxyRoutesCache.length) {
    el.innerHTML = '<div class="muted small-text">No proxy routes configured.</div>';
    return;
  }
  el.innerHTML = _proxyRoutesCache.map(route => {
    const allowed = (route.allowed || []).join(', ') || '(all profiles)';
    return `<div class="provider-card model-overview-card">
      <div class="provider-card-head">
        <div class="provider-title-block"><h3>${escapeHtml(route.name)}</h3></div>
      </div>
      <div class="provider-health-strip small-text">
        <span>target: <code>${escapeHtml(route.target)}</code></span>
      </div>
      <div class="model-card-subline">${escapeHtml(route.description || '')}</div>
      <div class="small-text muted">allowed: ${escapeHtml(allowed)}</div>
      <div class="button-row" style="margin-top:.5rem">
        <button class="ghost-button mini-button" onclick="testProxyRoute('${escapeHtml(route.name)}')">Test</button>
        <button class="ghost-button mini-button" onclick="editProxyRoute('${escapeHtml(route.name)}')">Edit</button>
        <button class="ghost-button mini-button danger-button" onclick="deleteProxyRoute('${escapeHtml(route.name)}')">Delete</button>
      </div>
      <div id="proxyRouteTestResult_${escapeHtml(route.name)}" class="inline-result" hidden></div>
    </div>`;
  }).join('');
}

function openProxyRouteForm(route) {
  const details = document.getElementById('proxyRouteFormDetails');
  const nameIn = document.getElementById('proxyRouteName');
  const targetIn = document.getElementById('proxyRouteTarget');
  const descIn = document.getElementById('proxyRouteDescription');
  const allowedIn = document.getElementById('proxyRouteAllowed');
  if (!details || !nameIn) return;
  if (route) {
    nameIn.value = route.name || '';
    nameIn.disabled = true;
    targetIn.value = route.target || '';
    descIn.value = route.description || '';
    allowedIn.value = (route.allowed || []).join(', ');
  } else {
    nameIn.value = '';
    nameIn.disabled = false;
    targetIn.value = '';
    descIn.value = '';
    allowedIn.value = '';
  }
  details.open = true;
}

async function testProxyRoute(name) {
  const resultEl = document.getElementById('proxyRouteTestResult_' + name);
  if (!resultEl) return;
  resultEl.hidden = false;
  resultEl.className = 'inline-result';
  resultEl.textContent = 'Testing...';
  try {
    const r = await api('/v1/proxy-routes/' + name + '/test', {method:'POST'});
    if (r.reachable) {
      resultEl.className = 'inline-result ok-text';
      resultEl.textContent = 'Reachable (status ' + r.status + ')';
    } else {
      resultEl.className = 'inline-result warn-text';
      resultEl.textContent = 'Unreachable: ' + (r.error || 'unknown');
    }
  } catch(e) {
    resultEl.className = 'inline-result warn-text';
    resultEl.textContent = 'Error: ' + e.message;
  }
  setTimeout(() => { if (resultEl) resultEl.hidden = true; }, 5000);
}

async function deleteProxyRoute(name) {
  if (!confirm('Delete proxy route ' + name + '?')) return;
  try {
    await api('/v1/proxy-routes/' + name, {method:'DELETE'});
    await loadProxyRoutes();
  } catch(e) {
    alert('Delete failed: ' + e.message);
  }
}

function editProxyRoute(name) {
  const route = _proxyRoutesCache.find(r => r.name === name);
  if (route) openProxyRouteForm(route);
}

async function saveProxyRoute() {
  const name = document.getElementById('proxyRouteName')?.value?.trim();
  const target = document.getElementById('proxyRouteTarget')?.value?.trim();
  const description = document.getElementById('proxyRouteDescription')?.value?.trim();
  const allowed = document.getElementById('proxyRouteAllowed')?.value?.split(',').map(s => s.trim()).filter(Boolean);
  if (!name || !target) {
    showInline('proxyRouteFormResult', 'Name and target are required', 'warn');
    return;
  }
  try {
    const isUpdate = _proxyRoutesCache.some(r => r.name === name);
    if (isUpdate) {
      await api('/v1/proxy-routes/' + name, {method:'PUT', body: JSON.stringify({target, description, allowed})});
      showInline('proxyRouteFormResult', 'Route updated', 'ok');
    } else {
      await api('/v1/proxy-routes', {method:'POST', body: JSON.stringify({name, target, description, allowed})});
      showInline('proxyRouteFormResult', 'Route created', 'ok');
    }
    document.getElementById('proxyRouteFormDetails').open = false;
    await loadProxyRoutes();
  } catch(e) {
    showInline('proxyRouteFormResult', 'Error: ' + e.message, 'warn');
  }
}

function cancelProxyRoute() {
  const details = document.getElementById('proxyRouteFormDetails');
  if (details) details.open = false;
}

function renderFeaturePackPreview(result) {
  const box = document.getElementById('featurePackPreview');
  const apply = document.getElementById('applyFeaturePack');
  if (!box) return;
  if (!result || !result.components) {
    box.innerHTML = '<div class="muted">Upload a PAC patch/full zip or source update zip to preview versions.</div>';
    setUpdatesDetail();
    if (apply) apply.disabled = true;
    return;
  }
  window.pendingFeaturePackUploadId = result.upload_id;
  if (apply) apply.disabled = !result.upload_id || !result.components.length;
  if (result.package_type === 'pac_app_update') {
    const fromVersion = result.current_version || result.components?.[0]?.from_version || '-';
    const toVersion = result.target_version || result.root_version || result.components?.[0]?.to_version || '-';
    const delta = result.changelog?.delta || result.changes || [];
    const changeHtml = delta.length
      ? `<div class="update-delta-list">${delta.map(entry => `<div class="update-delta-version"><div class="update-delta-title">${escapeHtml(entry.title || ('PAC v' + entry.version))}</div><ul>${(entry.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul></div>`).join('')}</div>`
      : '<div class="muted small-text">No version notes were found inside this zip. The update can still be applied.</div>';
    const source = result.changelog?.source ? `<span class="muted small-text">Change notes: ${escapeHtml(result.changelog.source)}</span>` : '';
    box.innerHTML = `<div class="pack-summary strong-summary">PAC application update ready</div><div class="muted small-text">${escapeHtml(result.filename || 'upload')} updates the controller from ${escapeHtml(fromVersion)} to ${escapeHtml(toVersion)}. Apply will install the app patch and restart PAC.</div><table class="compact-table"><thead><tr><th>Update</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody><tr><td><code>PAC app</code></td><td>${escapeHtml(fromVersion)}</td><td>${escapeHtml(toVersion)}</td><td>install + restart</td></tr></tbody></table><div class="update-delta-heading">Changes included</div>${changeHtml}${source}`;
    setUpdatesDetail({title:'Previewed update', version:toVersion, entries:delta, body:`${result.filename || 'upload'} updates PAC from ${fromVersion} to ${toVersion}.`});
    return;
  }
  const rows = result.components.map(c => `<tr><td><code>${escapeHtml(c.path)}</code></td><td>${escapeHtml(c.kind)}</td><td>${escapeHtml(c.from_version || 'new')}</td><td>${escapeHtml(c.to_version || '-')}</td><td>${escapeHtml(c.status || '')}</td></tr>`).join('');
  box.innerHTML = `<div class="pack-summary">${result.component_count || result.components.length} source folder(s) ready from ${escapeHtml(result.filename || 'upload')}</div><table class="compact-table"><thead><tr><th>Source folder</th><th>Kind</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table>`;
  setUpdatesDetail({title:'Feature pack preview', version:result.root_version || '', body:`${result.component_count || result.components.length} source folder(s) are ready to apply.`});
}

function setUpdatesDetail(meta=null) {
  const title = document.getElementById('updatesDetailTitle');
  const version = document.getElementById('updatesDetailVersion');
  const body = document.getElementById('updatesDetailBody');
  const formatDetailBody = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const lines = raw.split('\n');
    const parts = [];
    let listItems = [];
    const flushList = () => {
      if (!listItems.length) return;
      parts.push(`<ul>${listItems.join('')}</ul>`);
      listItems = [];
    };
    const linkify = (text) => escapeHtml(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noreferrer">$1</a>');
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushList();
        return;
      }
      if (/^#{1,6}\s+/.test(trimmed)) {
        flushList();
        parts.push(`<div class="update-delta-title">${linkify(trimmed.replace(/^#{1,6}\s+/, ''))}</div>`);
        return;
      }
      const quoteLink = trimmed.match(/^"?([^":]+)"?:\s*(https?:\/\/\S+)$/);
      if (quoteLink) {
        flushList();
        const [, label, url] = quoteLink;
        parts.push(`<div><b>${escapeHtml(label)}</b>: <a href="${url}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a></div>`);
        return;
      }
      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        listItems.push(`<li>${linkify(trimmed.slice(2).trim())}</li>`);
        return;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        listItems.push(`<li>${linkify(trimmed.replace(/^\d+\.\s+/, ''))}</li>`);
        return;
      }
      flushList();
      parts.push(`<div>${linkify(trimmed)}</div>`);
    });
    flushList();
    return `<div class="small-text updates-detail-copy">${parts.join('')}</div>`;
  };
  if (!title || !version || !body) return;
  if (!meta) {
    title.textContent = 'Release details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Preview a PAC update or select an archive to inspect local preservation details.</div>';
    return;
  }
  title.textContent = meta.title || 'Release details';
  version.textContent = meta.version ? `v${meta.version}` : '';
  const entries = meta.entries || [];
  const bodyHtml = meta.html_body || null;
  const formattedBody = meta.body ? formatDetailBody(meta.body) : '';
  const linkBlock = bodyHtml ? `<div class="muted small-text updates-detail-links">${bodyHtml}</div>` : '';
  if (entries.length) {
    body.innerHTML = `${formattedBody}${formattedBody ? '<div class="updates-detail-divider"></div>' : ''}<div class="update-delta-list">${entries.map(entry => `<div class="update-delta-version"><div class="update-delta-title">${escapeHtml(entry.title || ('PAC v' + (entry.version || '')))}</div><ul>${(entry.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul></div>`).join('')}</div>${linkBlock ? `<div style="margin-top:.6rem">${linkBlock}</div>` : ''}`;
  } else {
    body.innerHTML = `${formattedBody || '<div class="muted small-text">No additional details available.</div>'}${linkBlock ? `<div style="margin-top:.6rem">${linkBlock}</div>` : ''}`;
  }
}

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

function renderPacReleaseStatus(meta=null) {
  const applyBtn = document.getElementById('applyPacRelease');
  const status = document.getElementById('pacReleaseStatus');
  if (!status) return;
  if (!meta || !meta.ok) {
    status.textContent = meta?.error || 'GitHub release checks have not run yet.';
    if (applyBtn) applyBtn.disabled = true;
    return;
  }
    if (meta.has_update) {
      status.textContent = `Latest release: v${meta.latest_version}`;
      if (applyBtn) applyBtn.disabled = false;
      const currentVersion = meta.current_version || config?.version || config?.setup_status?.version || '';
      api(`/v1/updates/release-notes?from_version=${encodeURIComponent(currentVersion)}&to_version=${encodeURIComponent(meta.latest_version || '')}`)
        .then((notes) => {
          const fallbackChanges = (notes?.compare_changes || []).length ? (notes.compare_changes || []) : ((meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []));
          setUpdatesDetail({
            title:'Available release',
            version:meta.latest_version,
            entries:(notes?.entries || []).length ? (notes.entries || []) : (fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : []),
            body: notes?.body || meta.body || '',
            html_body: notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
          });
        })
        .catch(() => {
          const fallbackChanges = (meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []);
          setUpdatesDetail({title:'Available release', version:meta.latest_version, entries:fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : [], body: meta.body || ''});
        });
      return;
  }
  status.textContent = `PAC is up to date${meta.latest_version ? ` at v${meta.latest_version}` : ''}.`;
  if (applyBtn) applyBtn.disabled = true;
  if (meta.latest_version) {
    const currentVersion = meta.current_version || config?.version || config?.setup_status?.version || meta.latest_version;
    api(`/v1/updates/release-notes?from_version=0.0.0&to_version=${encodeURIComponent(meta.latest_version || '')}`)
      .then((notes) => {
        const fallbackChanges = (notes?.compare_changes || []).length ? (notes.compare_changes || []) : ((meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []));
        setUpdatesDetail({
          title:'Current release',
          version:meta.latest_version,
          entries:(notes?.entries || []).length ? (notes.entries || []) : (fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : []),
          body: notes?.body || meta.body || '',
          html_body: notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
        });
      })
      .catch(() => {
        const fallbackChanges = (meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []);
        setUpdatesDetail({title:'Current release', version:meta.latest_version, entries:fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : [], body: meta.body || ''});
      });
  }
}

async function checkPacRelease() {
  const meta = await api('/v1/updates/check');
  window.__pacReleaseMeta = meta;
  renderPacReleaseStatus(meta);
}

async function applyPacRelease() {
  const meta = window.__pacReleaseMeta || {};
  if (!meta.has_update) return paneError('No PAC release update is currently available');
  const btn = document.getElementById('applyPacRelease');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  if (proceed) { proceed.disabled = true; proceed.textContent = 'Applying…'; }
  if (cancel) cancel.hidden = true;
  try {
    const result = await api('/v1/updates/apply?restart_after_update=true', {method:'POST'});
    renderPacReleaseStatus({ok:true, has_update:false, latest_version:result.latest_version, body:'The selected PAC release has been applied and a restart was scheduled.'});
    if (result.preservation_archive || result.preservation_diff) {
      setUpdatesDetail({
        title: 'Release applied',
        version: result.latest_version || '',
        body: `PAC scheduled a restart after applying the latest release.\n\nPreservation archive: ${result.preservation_archive?.archive_path || '-'}\nUser diff: ${result.preservation_diff?.diff_path || '-'}`
      });
      await loadUpdateArchives().catch(()=>{});
    }
    if (result.restart_scheduled) {
      setUpdateConfirmOverlayRestarting(result.latest_version || meta.latest_version || '', 18);
      scheduleHiddenReloadAfterRestart(18);
    } else {
      closeUpdateConfirmOverlay(true);
    }
  } finally {
    if (btn) {
      btn.textContent = 'Apply latest release';
      btn.disabled = false;
    }
    if (!window.__pacRestartReloadTimer) {
      if (proceed) {
        proceed.disabled = false;
        proceed.textContent = 'Apply and restart';
      }
      if (cancel) cancel.hidden = false;
    }
  }
}

async function inspectFeaturePack() {
  const input = document.getElementById('featurePackFile');
  if (!input || !input.files || !input.files[0]) { paneError('Choose a feature update zip first'); return; }
  const fd = new FormData();
  fd.append('file', input.files[0]);
  emitUiEvent('feature_pack_inspect_started', `Feature update inspection started: ${input.files[0].name}`);
  const result = await runWithPaneError(() => api('/v1/sources/feature-pack/inspect', {method:'POST', body: fd}), 'Feature update could not be inspected');
  if (result) { renderFeaturePackPreview(result); emitUiEvent('feature_pack_inspected', result.package_type === 'pac_app_update' ? `PAC app update inspected: ${result.target_version || result.root_version || ''}` : `Feature update inspected: ${(result.components || []).length} source folders`, result); }
}

async function applyFeaturePack() {
  const uploadId = window.pendingFeaturePackUploadId;
  if (!uploadId) { paneError('Inspect a feature update zip first'); return; }
  emitUiEvent('feature_pack_apply_started', 'Feature update apply started', {upload_id: uploadId});
  const result = await runWithPaneError(() => api('/v1/sources/feature-pack/apply', {method:'POST', body: JSON.stringify({upload_id: uploadId})}), 'Feature update could not be applied');
  if (result) {
    renderFeaturePackPreview(null);
    const input = document.getElementById('featurePackFile'); if (input) input.value = '';
    if (result.preservation_archive || result.preservation_diff) {
      setUpdatesDetail({
        title: 'Update applied',
        version: result.preview?.target_version || result.preview?.root_version || '',
        body: `PAC scheduled a restart after applying this update.\n\nPreservation archive: ${result.preservation_archive?.archive_path || '-'}\nUser diff: ${result.preservation_diff?.diff_path || '-'}`
      });
      loadUpdateArchives().catch(()=>{});
    }
    emitUiEvent('feature_pack_applied', result.package_type === 'pac_app_update' ? 'PAC app update applied; restart scheduled' : `Feature update applied: ${(result.components || []).length} source folders`, result);
    if (result.package_type !== 'pac_app_update') await renderSources(selectedSourceFolder || '');
  }
}

function scheduleHiddenReloadAfterRestart(seconds = 18) {
  window.__pacRestartReloadTimer = window.__pacRestartReloadTimer || null;
  if (window.__pacRestartReloadTimer) clearTimeout(window.__pacRestartReloadTimer);
  const result = document.getElementById('stagePackageResult');
  if (result) result.textContent += `

PAC is restarting. This page will refresh automatically in ${seconds} seconds.`;
  const meta = window.__pacReleaseMeta || {};
  setUpdateConfirmOverlayRestarting(meta.latest_version || config?.version || config?.setup_status?.version || '', seconds);
  window.__pacRestartReloadTimer = setTimeout(() => window.location.reload(), seconds * 1000);
}

async function uploadStagePackageFromForm() {
  const input = document.getElementById('stagePackageFile');
  const result = document.getElementById('stagePackageResult');
  if (!input || !input.files || !input.files[0]) return alert('Choose a PAC package (.pac or .zip) first');
  const fd = new FormData();
  fd.append('file', input.files[0]);
  const apply = document.getElementById('stageApplyNow')?.checked !== false;
  const restartAfterUpdate = true;
  result.textContent = 'Uploading package...';
  let r = await fetch(`/v1/admin/stage-package?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
    method: 'POST',
    headers: tokenHeaders(),
    body: fd,
  });
  if (r.status === 404) {
    result.textContent = 'Primary upload endpoint returned 404; retrying compatibility endpoint...';
    r = await fetch(`/v1/update/upload?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
      method: 'POST',
      headers: tokenHeaders(),
      body: fd,
    });
  }
  const text = await r.text();
  if (!r.ok) throw new Error(`${r.status}: ${text}`);
  let payload;
  try { payload = JSON.parse(text); } catch { payload = text; }
  result.textContent = typeof payload === 'string' ? payload : (payload.message || payload.status || 'Package uploaded. Details are in Events.'); if (typeof payload !== 'string') emitUiEvent('package_upload_completed', result.textContent, payload);
  if (apply && payload && typeof payload === 'object' && payload.restart_scheduled) scheduleHiddenReloadAfterRestart(18);
  await loadGlobalEvents(true).catch(()=>{});
}

async function restartPacFromForm() {
  if (!confirm('Restart PAC now? If this was started manually, it will exit and you must start it again.')) return;
  const result = document.getElementById('stagePackageResult');
  result.textContent = 'Restart requested...';
  const r = await api('/v1/admin/restart', {method:'POST'});
  result.textContent = r.message || r.status || 'Restart requested. Details are in Events.'; emitUiEvent('pac_restart_requested', result.textContent, r);
  scheduleHiddenReloadAfterRestart(18);
}

async function loadMcpBuildStatus() {
  const box = document.getElementById('mcpBuildStatus');
  if (!box) return;
  try {
    const status = await api('/v1/mcp/build/status');
    const artifacts = status.artifacts || [];
    const links = artifacts.map(a => `<li><a href="${a.download_url}" download>${a.name}</a> <span class="muted">(${a.size || 0} bytes)</span></li>`).join('');
    box.innerHTML = `<b>Status:</b> ${status.status || 'unknown'}<br><b>Message:</b> ${escapeHtml(status.message || '')}<br><b>Version:</b> ${status.version || ''}${artifacts.length ? `<br><b>Downloads:</b><ul>${links}</ul>` : '<br><span class="muted">No binaries available yet.</span>'}<br><span class="muted">Build details are recorded in Events.</span>`;
  } catch (e) {
    box.textContent = 'Could not load Zed binary status: ' + e.message;
  }
}

async function buildMcpBridgeFromUi() {
  switchToTab('sources-tab');
  await renderSources('binaries/zed-binary');
  selectedSourceFolder = 'binaries/zed-binary';
  updateSourceActions();
  await buildSelectedBinarySource();
}

async function refreshDashboardMetricsOnStartup() {
  for (const delay of [0, 300, 900, 1800, 3500]) {
    setTimeout(() => loadDashboardMetrics().catch(e => { if (delay === 0) paneError('Dashboard metrics could not load', e.message || String(e)); }), delay);
  }
}

