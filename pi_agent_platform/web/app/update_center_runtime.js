(function () {
  function text(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setState(key, state) {
    const card = document.querySelector(`[data-update-summary="${key}"]`);
    if (!card) return;
    card.dataset.state = state || 'neutral';
  }

  function refreshFromVersionInfo(versionInfo) {
    if (!versionInfo) return;
    const backend = versionInfo.version || 'unknown';
    const ui = versionInfo.ui_build || 'unknown';
    text('pacCurrentVersion', `v${backend}`);
    text('pacUiBuildVersion', ui);
    text('pacVersionHint', versionInfo.git_commit ? `commit ${String(versionInfo.git_commit).slice(0, 12)}` : 'Running controller build');
    text('pacUiBuildHint', versionInfo.ui_updated_at ? `updated ${versionInfo.ui_updated_at}` : 'Loaded shell bundle');
    setState('version', backend === 'unknown' ? 'warn' : 'ok');
    setState('ui', ui === 'unknown' ? 'warn' : 'ok');
  }

  function refreshArchives(data) {
    const archives = Array.isArray(data?.archives) ? data.archives : [];
    text('pacArchiveStatus', archives.length ? `${archives.length} backup${archives.length === 1 ? '' : 's'}` : 'none');
    text('pacArchiveHintSummary', archives.length ? `latest ${archives[0]?.stamp || 'available'}` : 'Created after app updates');
    setState('archives', archives.length ? 'ok' : 'neutral');
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (!value) return '';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  }

  function renderReleaseAssets(payload) {
    const box = document.getElementById('releaseAssetsList');
    if (!box) return;
    if (!payload?.ok) {
      box.innerHTML = `<div class="muted">${window.escapeHtml?.(payload?.message || 'Release assets are not available yet.') || 'Release assets are not available yet.'}</div>`;
      return;
    }
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const labels = {
      release_binaries: 'Endpoint binaries',
      release_binaries_manifest: 'Binary JSON manifest',
      release_manifest: 'Release JSON manifest',
      changelog: 'PAC changelog JSON',
      full: 'Full server zip',
      patch: 'Patch server zip',
      packages_seed: 'Packages seed zip',
      update_diff: 'Update diff',
    };
    const cacheEntries = Array.isArray(payload.cache) ? payload.cache : [];
    const cacheByKey = new Map(cacheEntries.map((item) => [item.asset_key, item]));
    const entries = Object.entries(payload.assets || {}).filter(([, asset]) => asset?.download_url);
    if (!entries.length) {
      box.innerHTML = '<div class="muted">No release assets were listed by GitHub yet.</div>';
      return;
    }
    const mirroredKeys = new Set(['release_binaries', 'release_binaries_manifest', 'release_manifest', 'changelog']);
    box.innerHTML = `<div class="release-assets-grid">${entries.map(([key, asset]) => {
      const mirrored = mirroredKeys.has(key);
      const href = mirrored ? `/v1/updates/release-assets/${encodeURIComponent(key)}/download` : asset.download_url;
      const cache = cacheByKey.get(key) || {};
      const cacheStatus = mirrored ? ` · ${esc(cache.status || 'available')}${cache.sha256 ? ` · sha256:${esc(String(cache.sha256).slice(0, 12))}` : ''}` : '';
      const source = mirrored ? 'controller cached' : 'GitHub release';
      return `<a class="release-asset-link" data-state="${esc(cache.status || (mirrored ? 'available' : 'remote'))}" href="${esc(href)}" target="_blank" rel="noreferrer"><b>${esc(labels[key] || asset.name || key)}</b><span>${esc(asset.name || key)} ${asset.size ? `· ${formatBytes(asset.size)}` : ''} · ${source}${cacheStatus}</span></a>`;
    }).join('')}</div>`;
  }


  function renderBinaryManifest(manifest) {
    const box = document.getElementById('releaseBinaryManifest');
    if (!box) return;
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const binaries = Array.isArray(manifest?.binaries) ? manifest.binaries : [];
    if (!binaries.length) {
      box.innerHTML = '<div class="muted">No endpoint binary manifest entries were found for this release.</div>';
      return;
    }
    const grouped = new Map();
    binaries.forEach((item) => {
      const project = item.project || 'binary';
      if (!grouped.has(project)) grouped.set(project, []);
      grouped.get(project).push(item);
    });
    box.innerHTML = `<div><b>Endpoint binary manifest</b><span class="muted"> · v${esc(manifest.version || '?')} · ${binaries.length} target(s)</span></div><div class="release-binary-manifest-grid">${Array.from(grouped.entries()).map(([project, items]) => {
      const lines = items.map((item) => `${esc(item.target || '?')} · ${formatBytes(item.size)} · sha256:${esc(String(item.sha256 || '').slice(0, 12))}`).join('<br>');
      return `<div class="release-binary-manifest-card"><b>${esc(project)}</b><span>${lines}</span></div>`;
    }).join('')}</div>`;
  }

  async function loadBinaryManifest() {
    const box = document.getElementById('releaseBinaryManifest');
    if (!box) return;
    box.textContent = 'Loading binary manifest…';
    try {
      const manifest = await api('/v1/updates/release-assets/release_binaries_manifest/json');
      renderBinaryManifest(manifest);
    } catch (error) {
      box.textContent = `Binary manifest not available yet: ${error.message || error}`;
    }
  }



  function renderHousekeepingStatus(payload) {
    const box = document.getElementById('housekeepingStatus');
    if (!box) return;
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const last = payload?.last_result || null;
    const status = payload?.status || {};
    const roots = status.roots || {};
    const rootCards = Object.entries(roots).filter(([, entry]) => entry?.exists).map(([key, entry]) => {
      const details = [formatBytes(entry.size_bytes), entry.zip_count !== undefined ? `${entry.zip_count} zip(s)` : '', entry.backup_count !== undefined ? `${entry.backup_count} backup(s)` : '', entry.extracted_count !== undefined ? `${entry.extracted_count} extracted` : ''].filter(Boolean).join(' · ');
      return `<div class="release-binary-manifest-card"><b>${esc(key.replaceAll('_', ' '))}</b><span>${esc(details || entry.path || '')}</span></div>`;
    }).join('');
    const lastLine = last ? `<div class="muted small-text">Last run: ${esc(last.generated_at || last.started_at || 'unknown')} · ${esc(String(last.deleted_count || 0))} item(s) · ${esc(formatBytes(last.deleted_bytes || 0) || '0 B')} reclaimed${payload.running ? ' · running' : ''}</div>` : `<div class="muted small-text">No housekeeping run has been recorded in this process yet.</div>`;
    box.innerHTML = `${lastLine}${rootCards ? `<div class="release-binary-manifest-grid">${rootCards}</div>` : '<div class="muted">No generated storage roots found yet.</div>'}`;
  }

  function renderHousekeepingResult(result, label='Housekeeping') {
    const box = document.getElementById('housekeepingStatus');
    if (!box) return;
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const categories = Object.entries(result?.categories || {}).sort((a,b) => Number(b[1]?.bytes || 0) - Number(a[1]?.bytes || 0));
    const cards = categories.map(([category, entry]) => `<div class="release-binary-manifest-card"><b>${esc(category.replaceAll('_', ' '))}</b><span>${esc(String(entry.count || 0))} item(s) · ${esc(formatBytes(entry.bytes || 0) || '0 B')}</span></div>`).join('');
    box.innerHTML = `<div><b>${esc(label)}</b><span class="muted"> · ${esc(String(result?.deleted_count || 0))} item(s) · ${esc(formatBytes(result?.deleted_bytes || 0) || '0 B')} ${result?.dry_run ? 'would be reclaimed' : 'reclaimed'}</span></div>${cards ? `<div class="release-binary-manifest-grid">${cards}</div>` : '<div class="muted small-text">No generated files matched the cleanup policy.</div>'}`;
  }

  async function loadHousekeepingStatus() {
    const box = document.getElementById('housekeepingStatus');
    if (!box) return;
    box.textContent = 'Loading housekeeping status…';
    try {
      const payload = await api('/v1/updates/housekeeping');
      renderHousekeepingStatus(payload);
    } catch (error) {
      box.textContent = `Could not load housekeeping status: ${error.message || error}`;
    }
  }

  async function runHousekeeping(dryRun=false) {
    const box = document.getElementById('housekeepingStatus');
    const button = document.getElementById(dryRun ? 'previewHousekeeping' : 'runHousekeeping');
    if (!dryRun && !confirm('Clean generated PAC update/download/debug/build artifacts now? Newest rollback/download/debug items are kept.')) return;
    if (button) button.disabled = true;
    if (box) box.textContent = dryRun ? 'Previewing generated-file cleanup…' : 'Cleaning generated PAC files…';
    try {
      const result = await api('/v1/updates/housekeeping', {method:'POST', body: JSON.stringify({dry_run: dryRun})});
      renderHousekeepingResult(result, dryRun ? 'Housekeeping preview' : 'Housekeeping complete');
      if (typeof window.loadGlobalEvents === 'function') window.loadGlobalEvents(true).catch(()=>{});
    } catch (error) {
      if (box) box.textContent = `Housekeeping failed: ${error.message || error}`;
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderStorageHealth(payload) {
    const box = document.getElementById('storageHealthList');
    if (!box) return;
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const stores = payload?.stores || {};
    const entries = Object.entries(stores);
    if (!entries.length) {
      box.innerHTML = '<div class="muted">No storage status is available yet.</div>';
      return;
    }
    box.innerHTML = `<div class="release-binary-manifest-grid">${entries.map(([key, store]) => {
      const tableRows = store.tables ? Object.entries(store.tables).filter(([, count]) => count !== null).map(([table, count]) => `${esc(table)}:${esc(count)}`).join(' · ') : '';
      const detail = [store.kind || 'store', formatBytes(store.size_bytes), tableRows || (store.files !== undefined ? `${store.files} files` : ''), store.journal_mode ? `journal ${store.journal_mode}` : ''].filter(Boolean).join(' · ');
      return `<div class="release-binary-manifest-card" data-state="${store.ok === false ? 'warn' : 'ok'}"><b>${esc(key)}</b><span>${esc(detail || store.path || '')}</span></div>`;
    }).join('')}</div>`;
  }

  async function loadStorageHealth() {
    const box = document.getElementById('storageHealthList');
    if (!box) return;
    box.textContent = 'Loading storage health…';
    try {
      const payload = await api('/v1/system/storage');
      renderStorageHealth(payload);
    } catch (error) {
      box.textContent = error?.status === 404 ? 'Storage health is not available from the active backend yet. The UI may be newer than the running controller; apply/restart PAC, then reload.' : `Could not load storage health: ${error.message || error}`;
    }
  }

  async function loadReleaseAssets() {
    const box = document.getElementById('releaseAssetsList');
    if (box) box.textContent = 'Loading release assets…';
    try {
      const payload = await api('/v1/updates/release-assets');
      renderReleaseAssets(payload);
      await loadBinaryManifest();
    } catch (error) {
      if (box) box.textContent = `Could not load release assets: ${error.message || error}`;
    }
  }

  function refreshRelease(meta) {
    if (!meta) return;
    if (!meta.ok) {
      text('pacReleaseSummary', 'check failed');
      text('pacReleaseSummaryHint', meta.error || 'Release check failed');
      setState('release', 'warn');
      return;
    }
    if (meta.has_update || meta.can_apply_update) {
      text('pacReleaseSummary', `v${meta.latest_version || 'available'}`);
      const hint = meta.version_comparison === 'local_version_ahead'
        ? 'Release channel sync is available even though local dev version is higher'
        : (meta.update_reason || 'New release is ready to preview');
      text('pacReleaseSummaryHint', hint);
      setState('release', 'attention');
      return;
    }
    text('pacReleaseSummary', 'up to date');
    text('pacReleaseSummaryHint', meta.latest_version ? `latest v${meta.latest_version}` : 'No newer release found');
    setState('release', 'ok');
  }


  function renderUpdateEnvironment(payload) {
    const box = document.getElementById('updateEnvironmentPlan');
    if (!box) return;
    const esc = window.escapeHtml || ((value) => String(value ?? ''));
    const stages = Array.isArray(payload?.stages) ? payload.stages : [];
    if (!stages.length) {
      box.innerHTML = '<div class="muted">No update orchestration stages are available yet.</div>';
      return;
    }
    box.innerHTML = `<div class="release-binary-manifest-grid">${stages.map((stage) => {
      const state = stage.status === 'ok' ? 'ok' : (stage.status === 'failed' ? 'warn' : (stage.status === 'warn' ? 'attention' : 'neutral'));
      return `<div class="release-binary-manifest-card" data-state="${esc(state)}"><b>${esc(stage.name || 'stage')}</b><span>${esc(stage.status || 'planned')} · ${esc(stage.message || '')}</span></div>`;
    }).join('')}</div>`;
  }

  async function loadUpdateEnvironmentPlan() {
    const box = document.getElementById('updateEnvironmentPlan');
    if (!box) return;
    box.textContent = 'Loading update orchestration plan…';
    try {
      const payload = await api('/v1/updates/environment-plan');
      renderUpdateEnvironment(payload);
    } catch (error) {
      box.textContent = `Could not load environment plan: ${error.message || error}`;
    }
  }

  async function runUpdateEnvironment() {
    const box = document.getElementById('updateEnvironmentPlan');
    const button = document.getElementById('runUpdateEnvironment');
    if (button) { button.disabled = true; button.textContent = 'Refreshing…'; }
    if (box) box.textContent = 'Resolving release binaries and refreshing PAC tool instructions…';
    try {
      const payload = await api('/v1/updates/environment/apply', {method: 'POST'});
      renderUpdateEnvironment(payload);
    } catch (error) {
      if (box) box.textContent = `Environment refresh failed: ${error.message || error}`;
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Run environment refresh'; }
    }
  }

  function bind() {
    refreshFromVersionInfo(window.currentVersionInfo);
    document.getElementById('reloadReleaseAssets')?.addEventListener('click', loadReleaseAssets);
    document.getElementById('reloadStorageHealth')?.addEventListener('click', loadStorageHealth);
    document.getElementById('runUpdateEnvironment')?.addEventListener('click', runUpdateEnvironment);
    document.getElementById('previewHousekeeping')?.addEventListener('click', () => runHousekeeping(true));
    document.getElementById('runHousekeeping')?.addEventListener('click', () => runHousekeeping(false));
    if (document.getElementById('releaseAssetsList')) loadReleaseAssets().catch(()=>{});
    if (document.getElementById('storageHealthList')) loadStorageHealth().catch(()=>{});
    if (document.getElementById('housekeepingStatus')) loadHousekeepingStatus().catch(()=>{});
    if (document.getElementById('updateEnvironmentPlan')) loadUpdateEnvironmentPlan().catch(()=>{});
  }

  window.PacUpdateCenter = {refreshFromVersionInfo, refreshArchives, refreshRelease, loadReleaseAssets, renderReleaseAssets, loadBinaryManifest, renderBinaryManifest, loadStorageHealth, renderStorageHealth, loadHousekeepingStatus, renderHousekeepingStatus, renderHousekeepingResult, loadUpdateEnvironmentPlan, renderUpdateEnvironment, runUpdateEnvironment};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
