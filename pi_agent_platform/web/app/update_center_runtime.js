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
    if (meta.has_update) {
      text('pacReleaseSummary', `v${meta.latest_version || 'available'}`);
      text('pacReleaseSummaryHint', 'New release is ready to preview');
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
    if (document.getElementById('releaseAssetsList')) loadReleaseAssets().catch(()=>{});
    if (document.getElementById('storageHealthList')) loadStorageHealth().catch(()=>{});
    if (document.getElementById('updateEnvironmentPlan')) loadUpdateEnvironmentPlan().catch(()=>{});
  }

  window.PacUpdateCenter = {refreshFromVersionInfo, refreshArchives, refreshRelease, loadReleaseAssets, renderReleaseAssets, loadBinaryManifest, renderBinaryManifest, loadStorageHealth, renderStorageHealth, loadUpdateEnvironmentPlan, renderUpdateEnvironment, runUpdateEnvironment};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
