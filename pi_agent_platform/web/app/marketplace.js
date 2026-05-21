// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

async function checkSourceOnlineUpdates(){
  const status = document.getElementById('sourceUpdateStatus');
  const box = document.getElementById('sourceOnlineUpdates');
  if (status) status.textContent = 'Checking pac-labs/packages…';
  if (box) box.innerHTML = '<div class="muted">Checking online source module repository…</div>';
  const result = await runWithPaneError(() => api('/v1/sources/online-updates'), 'Source module update check failed');
  if (!result) return;
  if (status) status.textContent = result.ok ? `${result.update_count || 0} update(s) available` : 'check failed';
  renderSourceOnlineUpdates(result);
  emitUiEvent(result.ok ? 'source_online_updates_checked' : 'source_online_updates_failed', result.ok ? `Source module updates checked: ${result.update_count || 0} available` : 'Source module update check failed', result);
}

function renderSourceOnlineUpdates(result){
  const box = document.getElementById('sourceOnlineUpdates');
  if (!box) return;
  if (!result.ok) {
    box.innerHTML = `<div class="pack-summary warn-summary">Could not check source modules</div><div class="muted small-text">${escapeHtml(result.error || 'Unknown error')}</div>`;
    return;
  }
  const updates = result.updates || [];
  const repo = result.repository || 'pac-labs/packages';
  const checked = result.checked_at ? new Date(result.checked_at).toLocaleString() : 'now';
  if (!updates.length) {
    box.innerHTML = `<div class="pack-summary strong-summary">Source modules are current</div><div class="muted small-text">Checked ${escapeHtml(repo)} at ${escapeHtml(checked)}.</div>`;
    return;
  }
  const rows = updates.map(u => `<tr><td><code>${escapeHtml(u.source_path || u.id || '-')}</code><div class="muted small-text">${escapeHtml(u.description || '')}</div></td><td>${escapeHtml(u.local_version || 'not installed')}</td><td>${escapeHtml(u.remote_version || result.packages_version || 'latest')}</td><td><span class="pill ${u.status === 'new' ? 'ok-pill' : 'warn-pill'}">${escapeHtml(u.status || 'update')}</span></td></tr>`).join('');
  box.innerHTML = `<div class="pack-summary strong-summary">${updates.length} source module update(s) available</div><div class="muted small-text">Checked ${escapeHtml(repo)} at ${escapeHtml(checked)}. Apply by downloading/importing the packages release or seed zip.</div><table class="compact-table"><thead><tr><th>Module</th><th>Local</th><th>Online</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderMarketplaceResults(data) {
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  const results = data?.results || [];
  marketplaceResultCache = results;
  if (!results.length) {
    el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
    return;
  }
  el.innerHTML = results.map(item => {
    const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
    const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
    return `<button class="marketplace-card marketplace-card-button" data-marketplace-source-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
  }).join('');
  el.querySelectorAll('[data-marketplace-source-model]').forEach(btn => btn.onclick = async () => {
    const modelId = btn.dataset.marketplaceSourceModel || '';
    const input = document.getElementById('marketplaceModalQuery');
    if (input) input.value = modelId;
    openMarketplaceModal();
    const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(modelId)}`);
    renderMarketplaceModalDetail(detail);
  });
}

function openMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = false;
  const input = document.getElementById('marketplaceModalQuery');
  if (input) input.value = document.getElementById('marketplaceQuery')?.value || input.value || '';
  renderMarketplaceModalDetail();
  if (input && input.value.trim()) searchMarketplaceModal().catch(e=>paneError('Marketplace search failed', e.message));
}

function closeMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = true;
}

function preferredMarketplaceProvider(detail) {
  return (detail.provider_scores || []).find(entry => entry.can_run && entry.provider?.name)?.provider?.name
    || (detail.provider_scores || []).find(entry => entry.provider?.type === 'lmstudio')?.provider?.name
    || (detail.provider_scores || [])[0]?.provider?.name
    || '';
}

async function downloadMarketplaceModel(detail) {
  const provider = preferredMarketplaceProvider(detail);
  if (!provider) throw new Error('No compatible provider is configured for marketplace download');
  const score = (detail.provider_scores || []).find(entry => entry.provider?.name === provider) || {};
  const quantization = score.quant_recommended || (detail.available_quants || [])[0] || 'Q4_K_M';
  const result = await api('/v1/models/marketplace/download', {
    method:'POST',
    body: JSON.stringify({model: detail.model_id, provider, quantization}),
  });
  showInline('modelFormResult', {marketplace_download: result, provider, model: detail.model_id, quantization});
  await loadGlobalEvents(true).catch(()=>{});
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
    return `<tr><td><code>${escapeHtml(provider.name || '-')}</code></td><td>${escapeHtml(provider.type || '-')}</td><td>${escapeHtml(entry.quant_recommended || '-')}</td><td><span class="pill ${entry.can_run === true ? 'ok-pill' : (entry.can_run === false ? 'warn-pill' : '')}">${escapeHtml(entry.can_run === true ? 'fits' : (entry.can_run === false ? 'no fit' : 'unknown'))}</span> ${escapeHtml(entry.reason || '-')}</td></tr>`;
  }).join('');
  const quants = (detail.available_quants || []).slice(0, 8).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
  const hasLmStudio = (detail.provider_scores || []).some(entry => entry.provider?.type === 'lmstudio');
  body.innerHTML = `<div class="muted small-text">Author: ${escapeHtml(detail.author || 'unknown')} • Downloads: ${escapeHtml(String(detail.downloads || 0))}</div><div class="marketplace-meta" style="margin:.6rem 0">${Object.entries(detail.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('')}${quants}</div><table class="compact-table"><thead><tr><th>Provider</th><th>Type</th><th>Quant</th><th>Fit</th></tr></thead><tbody>${providers || '<tr><td colspan="4" class="muted">No providers configured yet.</td></tr>'}</tbody></table><div class="button-row" style="margin-top:.75rem"><button id="configureMarketplaceModel">Configure as model</button>${hasLmStudio ? '<button id="downloadMarketplaceModel" class="ghost-button">Download to LM Studio</button>' : ''}</div>`;
  const configureBtn = document.getElementById('configureMarketplaceModel');
  if (configureBtn) configureBtn.onclick = () => {
    const preferred = preferredMarketplaceProvider(detail);
    closeMarketplaceModal();
    openModelDraft(preferred, detail.model_id || '');
    setModalStatus('modelModalStatus', 'Marketplace model copied into the PAC model form.');
  };
  const downloadBtn = document.getElementById('downloadMarketplaceModel');
  if (downloadBtn) downloadBtn.onclick = () => downloadMarketplaceModel(detail).catch(e=>paneError('Marketplace download failed', e.message));
}

async function searchMarketplaceModal() {
  const query = document.getElementById('marketplaceModalQuery')?.value?.trim() || '';
  const capability = document.getElementById('marketplaceModalCapability')?.value || '';
  const sort = document.getElementById('marketplaceModalSort')?.value || 'downloads';
  const el = document.getElementById('marketplaceModalResults');
  if (!el) return;
  el.textContent = 'Searching marketplace...';
  try {
    const params = new URLSearchParams({q: query, limit: '18', sort});
    if (capability) params.set('capability', capability);
    const data = await api(`/v1/models/marketplace/search?${params.toString()}`);
    const results = data?.results || [];
    marketplaceResultCache = results;
    if (!results.length) {
      el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
      renderMarketplaceModalDetail();
      return;
    }
    el.innerHTML = results.map(item => {
      const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
      const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
      return `<button class="marketplace-card marketplace-card-button" data-marketplace-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
    }).join('');
    el.querySelectorAll('[data-marketplace-model]').forEach(btn => btn.onclick = async () => {
      const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(btn.dataset.marketplaceModel || '')}`);
      renderMarketplaceModalDetail(detail);
    });
  } catch (e) {
    el.textContent = e.message || String(e);
  }
}

function marketplaceFitSummary(item) {
    const fit = item?.preferred_fit || null;
    const fitProvider = fit?.provider?.name || '';
    const fitLabel = fit?.can_run === true ? 'fits configured provider' : (fit?.can_run === false ? 'no provider fit' : (fitProvider ? 'compatibility unknown' : 'no provider data'));
    const fitClass = fit?.can_run === true ? 'ok-pill' : (fit?.can_run === false ? 'warn-pill' : '');
    const fitDetail = fitProvider ? `${fitProvider}${fit?.quant_recommended ? ` • ${fit.quant_recommended}` : ''}` : '';
    return { fitLabel, fitClass, fitDetail };
}

function renderMarketplaceResults(data) {
    const el = document.getElementById('marketplaceResults');
    if (!el) return;
    const results = data?.results || [];
    marketplaceResultCache = results;
    if (!results.length) {
        el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
        return;
    }
    el.innerHTML = results.map(item => {
        const caps = Object.entries(item.capabilities || {}).filter(([, v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
        const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
        const fit = marketplaceFitSummary(item);
        return `<button class="marketplace-card marketplace-card-button" data-marketplace-source-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="button-row" style="margin:.35rem 0 .2rem 0"><span class="pill ${fit.fitClass}">${escapeHtml(fit.fitLabel)}</span><span class="muted small-text">${escapeHtml(fit.fitDetail)}</span></div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
    }).join('');
    el.querySelectorAll('[data-marketplace-source-model]').forEach(btn => btn.onclick = async () => {
        const modelId = btn.dataset.marketplaceSourceModel || '';
        const input = document.getElementById('marketplaceModalQuery');
        if (input) input.value = modelId;
        openMarketplaceModal();
        try {
            const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(modelId)}`);
            renderMarketplaceModalDetail(detail);
        } catch (e) {
            paneError('Marketplace details failed', e.message || String(e));
        }
    });
}

async function searchMarketplaceModal() {
    const query = document.getElementById('marketplaceModalQuery')?.value?.trim() || '';
    const capability = document.getElementById('marketplaceModalCapability')?.value || '';
    const sort = document.getElementById('marketplaceModalSort')?.value || 'downloads';
    const el = document.getElementById('marketplaceModalResults');
    if (!el) return;
    el.textContent = 'Searching marketplace...';
    try {
        const params = new URLSearchParams({q: query, limit: '18', sort});
        if (capability) params.set('capability', capability);
        const data = await api(`/v1/models/marketplace/search?${params.toString()}`);
        const results = data?.results || [];
        marketplaceResultCache = results;
        if (!results.length) {
            el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
            renderMarketplaceModalDetail();
            return;
        }
        el.innerHTML = results.map(item => {
            const caps = Object.entries(item.capabilities || {}).filter(([, v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
            const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
            const fit = marketplaceFitSummary(item);
            return `<button class="marketplace-card marketplace-card-button" data-marketplace-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="button-row" style="margin:.35rem 0 .2rem 0"><span class="pill ${fit.fitClass}">${escapeHtml(fit.fitLabel)}</span><span class="muted small-text">${escapeHtml(fit.fitDetail)}</span></div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
        }).join('');
        el.querySelectorAll('[data-marketplace-model]').forEach(btn => btn.onclick = async () => {
            try {
                const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(btn.dataset.marketplaceModel || '')}`);
                renderMarketplaceModalDetail(detail);
            } catch (e) {
                paneError('Marketplace details failed', e.message || String(e));
            }
        });
    } catch (e) {
        el.textContent = e.message || String(e);
    }
}

