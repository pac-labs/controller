// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing boot wiring continues to work.

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
    const updateMode = result.update_mode === 'changed_files' ? 'Changed-files patch' : 'Full app package';
    const actionText = result.update_mode === 'changed_files' ? 'merge touched files + restart' : 'install + restart';
    const fileCount = Number(result.files || result.components?.[0]?.files || 0);
    box.innerHTML = `<div class="pack-summary strong-summary">PAC application update ready</div><div class="muted small-text">${escapeHtml(result.filename || 'upload')} updates the controller from ${escapeHtml(fromVersion)} to ${escapeHtml(toVersion)}. ${escapeHtml(updateMode)} will ${escapeHtml(actionText)}.</div><table class="compact-table"><thead><tr><th>Update</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody><tr><td><code>${escapeHtml(updateMode)}</code></td><td>${escapeHtml(fromVersion)}</td><td>${escapeHtml(toVersion)}</td><td>${escapeHtml(actionText)}</td></tr></tbody></table><div class="muted small-text">Files in package: ${escapeHtml(String(fileCount || '-'))}</div><div class="update-delta-heading">Changes included</div>${changeHtml}${source}`;
    setUpdatesDetail({title:'Previewed update', version:toVersion, entries:delta, body:`${result.filename || 'upload'} updates PAC from ${fromVersion} to ${toVersion} as a ${updateMode}.`});
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

function renderPacReleaseStatus(meta=null) {
  const applyBtn = document.getElementById('applyPacRelease');
  const status = document.getElementById('pacReleaseStatus');
  if (!status) return;
  window.PacUpdateCenter?.refreshRelease?.(meta);
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

function formatPiDevCheck(result) {
  const check = result?.pi_dev_check;
  if (!check) return '';
  const lines = [
    `pi.dev verification: ${check.ok ? 'healthy' : 'needs attention'}`,
    `Session: ${check.session_ok ? 'ok' : 'failed'}`,
    `Wrapper: ${check.wrapper_running ? 'running' : 'not running'}`,
    `Daemon: ${check.daemon_running ? 'running' : 'not running'}`,
  ];
  const logErrors = Array.isArray(check.detected_errors) ? check.detected_errors.filter(Boolean) : [];
  if (logErrors.length) {
    lines.push('');
    lines.push('Recent runtime log errors:');
    logErrors.slice(-5).forEach((entry) => lines.push(`- ${entry}`));
  }
  return lines.join('\n');
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
        body: `PAC scheduled a restart after applying the latest release.\n\nPreservation archive: ${result.preservation_archive?.archive_path || '-'}\nUser diff: ${result.preservation_diff?.diff_path || '-'}${formatPiDevCheck(result) ? `\n\n${formatPiDevCheck(result)}` : ''}${result.environment_update ? `\n\nEnvironment update: ${result.environment_update.status || 'completed'} (${(result.environment_update.stages || []).length} stage(s))` : ''}`
      });
      await loadUpdateArchives().catch(()=>{});
      if (result.environment_update) window.PacUpdateCenter?.renderUpdateEnvironment?.(result.environment_update);
    } else if (result.pi_dev_check) {
      setUpdatesDetail({
        title: 'Release applied',
        version: result.latest_version || '',
        body: `PAC scheduled a restart after applying the latest release.\n\n${formatPiDevCheck(result)}${result.environment_update ? `\n\nEnvironment update: ${result.environment_update.status || 'completed'} (${(result.environment_update.stages || []).length} stage(s))` : ''}`
      });
      if (result.environment_update) window.PacUpdateCenter?.renderUpdateEnvironment?.(result.environment_update);
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
  window.__pacRestartCountdownTimer = window.__pacRestartCountdownTimer || null;
  if (window.__pacRestartReloadTimer) clearTimeout(window.__pacRestartReloadTimer);
  if (window.__pacRestartCountdownTimer) clearInterval(window.__pacRestartCountdownTimer);
  const totalSeconds = Math.max(5, Number(seconds) || 18);
  const result = document.getElementById('stagePackageResult');
  if (result) result.textContent += `

PAC is restarting. This page will refresh automatically in ${totalSeconds} seconds.`;
  const meta = window.__pacReleaseMeta || {};
  setUpdateConfirmOverlayRestarting(meta.latest_version || config?.version || config?.setup_status?.version || '', totalSeconds);
  const start = Date.now();
  updateRestartCountdown(totalSeconds);
  window.__pacRestartCountdownTimer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - start) / 1000);
    updateRestartCountdown(Math.max(0, totalSeconds - elapsed));
  }, 1000);
  window.__pacRestartReloadTimer = setTimeout(() => {
    if (window.__pacRestartCountdownTimer) clearInterval(window.__pacRestartCountdownTimer);
    window.location.reload();
  }, totalSeconds * 1000);
}

async function uploadStagePackageFromForm() {
  const input = document.getElementById('stagePackageFile');
  const result = document.getElementById('stagePackageResult');
  if (!input || !input.files || !input.files[0]) return alert('Choose a PAC package (.pac or .zip) first');
  const fd = new FormData();
  fd.append('file', input.files[0]);
  const apply = document.getElementById('stageApplyNow')?.checked !== false;
  const restartAfterUpdate = true;
  if (window.PACLoading) PACLoading.status(result, 'Uploading package…'); else result.textContent = 'Uploading package…';
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
    box.textContent = 'Could not load pacctl MCP status: ' + e.message;
  }
}

async function buildMcpBridgeFromUi() {
  switchToTab('sources-tab');
  await renderSources('binaries/pacctl');
  selectedSourceFolder = 'binaries/pacctl';
  updateSourceActions();
  await buildSelectedBinarySource();
}

async function refreshDashboardMetricsOnStartup() {
  for (const delay of [0, 300, 900, 1800, 3500]) {
    setTimeout(() => loadDashboardMetrics().catch(e => { if (delay === 0) paneError('Dashboard metrics could not load', e.message || String(e)); }), delay);
  }
}


