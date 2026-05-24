// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

async function openModelSyncModal() {
  const modal = document.getElementById('modelSyncModal');
  const body = document.getElementById('modelSyncModalBody');
  if (!modal || !body) return;
  body.innerHTML = '<div class="muted small-text">Checking provider model info...</div>';
  modal.hidden = false;
  try {
    const result = await api('/v1/models/provider-status');
    _modelSyncData = result.models || [];
    renderModelSyncModal();
  } catch(e) {
    body.innerHTML = '<div class="muted small-text">Failed to load: ' + escapeHtml(e.message) + '</div>';
  }
}

function renderModelSyncModal() {
  const body = document.getElementById('modelSyncModalBody');
  const applyAllBtn = document.getElementById('applyAllModelSync');
  if (!body) return;
  const mismatches = _modelSyncData.filter(m => m.mismatch && (m.mismatch.context_window || m.mismatch.max_output_tokens));
  if (!mismatches.length) {
    body.innerHTML = '<div class="ok-text">All models are in sync with their providers.</div>';
    if (applyAllBtn) applyAllBtn.style.display = 'none';
    return;
  }
  if (applyAllBtn) applyAllBtn.style.display = '';
  body.innerHTML = mismatches.map(m => {
    const suggested = m.suggested || {};
    const ctxMismatch = m.mismatch?.context_window;
    const outMismatch = m.mismatch?.max_output_tokens;
    return `<div class="pack-summary" style="margin-bottom:.75rem">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <b>${escapeHtml(m.name)}</b>
        <button class="ghost-button mini-button" onclick="applyModelSync('${escapeHtml(m.name)}')">Apply Fix</button>
      </div>
      <div class="small-text muted">Provider: ${escapeHtml(m.provider || '-')}</div>
      ${ctxMismatch ? `<div><span class="warn-text">Context window:</span> stored ${m.stored?.context_window}, provider ${m.provider_info?.context_length || '?'} → suggest <b>${suggested.context_window || '-'}</b></div>` : ''}
      ${outMismatch ? `<div><span class="warn-text">Max output:</span> stored ${m.stored?.max_output_tokens}, provider ${m.provider_info?.context_length ? Math.floor(m.provider_info.context_length/4) : '?'} → suggest <b>${suggested.max_output_tokens || '-'}</b></div>` : ''}
    </div>`;
  }).join('');
}

async function applyModelSync(modelName) {
  const m = _modelSyncData.find(x => x.name === modelName);
  if (!m) return;
  const suggested = m.suggested || {};
  try {
    await api(`/v1/models/${modelName}`, {method:'PATCH', body: JSON.stringify({
      context_window: suggested.context_window,
      max_output_tokens: suggested.max_output_tokens
    })});
    _modelSyncData = _modelSyncData.filter(x => x.name !== modelName);
    renderModelSyncModal();
    renderModels();
  } catch(e) {
    alert('Failed to update ' + modelName + ': ' + e.message);
  }
}

async function applyAllModelSync() {
  const mismatches = _modelSyncData.filter(m => m.mismatch && (m.mismatch.context_window || m.mismatch.max_output_tokens));
  for (const m of mismatches) {
    await applyModelSync(m.name);
  }
  closeModelSyncModal();
  renderModels();
}

function closeModelSyncModal() {
  const modal = document.getElementById('modelSyncModal');
  if (modal) modal.hidden = true;
  _modelSyncData = [];
}

function modelSyncBadge(name) {
  const m = _modelSyncData.find(x => x.name === name);
  if (!m || !m.mismatch) return '';
  const parts = [];
  if (m.mismatch.context_window) parts.push(`ctx: ${m.stored?.context_window}→${m.provider_info?.context_length}`);
  if (m.mismatch.max_output_tokens) parts.push(`out: ${m.stored?.max_output_tokens}→${m.provider_info?.context_length ? Math.floor(m.provider_info.context_length/4) : '?'}`);
  if (!parts.length) return '';
  return ` <span class="warn-pill" title="Mismatch: ${parts.join(', ')}">⚠️</span>`;
}
