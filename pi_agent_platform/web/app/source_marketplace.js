// Marketplace search and inspection helpers.
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
