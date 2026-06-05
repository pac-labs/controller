// Configured model card grid and live provider model list rendering.
function renderModels() {
  const el = document.getElementById('models');
  if (!el) return;
  el.className = 'model-card-grid model-card-grid-compact';
  const models = Object.entries(config.models || {});
  if (!models.length) {
    el.innerHTML = '<div class="muted">No configured models yet. Add one from Marketplace or Browse providers.</div>';
  } else {
    el.innerHTML = '';
    for (const [name, model] of models) {
      const availability = modelAvailability(name);
      const provider = config.providers?.[model.provider || ''];
      const health = providerHealthSummary(model.provider || '', provider || {});
      const sessionCount = (window.__pacSessions || []).filter(item => item.model === name).length;
      const card = document.createElement('article');
      card.className = 'model-card model-overview-card model-overview-compact clickable-row';
      const runtime = model.extra?.lmstudio_runtime || {};
      const caps = modelCapabilityPills(model);
      const displayName = modelDisplayName(name, model);
      const stableId = modelStableId(name, model);
      const modelFunction = model.extra?.function || inferModelFunction(model.provider, model.model || displayName || name);
      const providerName = providerLabel(model.provider || '-');
      const modelId = model.model || '-';
      const identityPills = [
        modelPill(modelStatusGlyph(availability.ok), availability.ok ? 'available' : 'attention', availability.ok ? 'ok-pill' : 'warn-pill'),
        provider?.type ? modelPill('provider', provider.type) : '',
        modelPill('role', modelFunction),
        modelPill('sessions', sessionCount || 0),
      ].filter(Boolean).join('');
      const capacityPills = [
        modelPill('ctx', compactTokenNumber(model.context_window)),
        modelPill('out', compactTokenNumber(model.max_output_tokens)),
        model.capabilities?.reasoning ? modelPill('reasoning', model.capabilities.reasoning) : '',
        modelPill('provider', providerName),
        pricePill('in', model.input_price_per_million),
        pricePill('out$', model.output_price_per_million),
      ].filter(Boolean).join('');
      card.innerHTML = `<div class="provider-card-head model-card-head-compact"><div class="provider-title-block model-title-block"><h3 title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</h3><span class="muted" title="${escapeHtml(stableId)}">PAC id: ${escapeHtml(stableId)}</span><span class="muted" title="${escapeHtml(providerLabel(model.provider || '-'))}">${escapeHtml(providerLabel(model.provider || '-'))}</span></div><span class="model-status-icon ${availability.ok ? 'ok-text' : 'warn-text'}" title="${escapeHtml(availability.ok ? 'Available' : availability.reason)}">${modelStatusGlyph(availability.ok)}</span></div>
        <div class="model-id-line"><span class="model-id-label">provider id</span><code title="${escapeHtml(modelId)}">${escapeHtml(modelId)}</code></div>
        <div class="provider-pill-list model-identity-pills">${identityPills}</div>
        <div class="provider-health-strip model-provider-health"><span class="pill ${escapeHtml(health.klass)}">${escapeHtml(health.pill)}</span><span class="small-text" title="${escapeHtml(health.detail)}">${escapeHtml(health.detail)}</span></div>
        ${caps ? `<div class="provider-pill-list model-cap-list">${caps}</div>` : ''}
        <div class="provider-pill-list model-capacity-pills">${capacityPills}</div>
        <div class="muted small-text model-card-note">${escapeHtml(availability.ok ? `Configured for ${modelFunction} work.` : `Issue: ${availability.reason}`)}</div>
        ${provider?.type === 'lmstudio' ? `<div class="model-runtime-strip compact-runtime-strip"><span>LM Studio</span><span>ctx ${escapeHtml(compactTokenNumber(runtime.context_length || model.context_window || '-'))}</span><span>gpu ${escapeHtml(runtime.gpu_offload || 'default')}</span><span>batch ${escapeHtml(runtime.eval_batch_size || runtime.batch_size || 'default')}</span><span>temp ${escapeHtml(runtime.temperature ?? 'default')}</span></div>` : ''}`;
      card.onclick = () => openModelModal(name);
      const actions = document.createElement('div');
      actions.className = 'model-card-actions compact-model-actions model-card-icon-actions';
      const makeIconAction = (label, icon, className, handler) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `model-icon-action ${className || ''}`.trim();
        button.setAttribute('aria-label', label);
        button.title = label;
        button.textContent = icon;
        button.onclick = handler;
        return button;
      };
      const edit = makeIconAction('Edit model configuration', '✎', '', ev => { ev.stopPropagation(); openModelModal(name); });
      const test = makeIconAction('Test model', '▶', '', async ev => { ev.stopPropagation(); const r = await api(`/v1/models/${name}/test`, {method:'POST'}); showInline('modelFormResult', {model:name, ...r}); });
      actions.appendChild(edit);
      actions.appendChild(test);
      if (!model.read_only) {
        const del = makeIconAction('Delete model configuration', '×', 'danger-action', async ev => {
          ev.stopPropagation();
          if (!confirm(`Delete model '${displayName}'`)) return;
          const r = await api(`/v1/models/${name}`, {method:'DELETE'});
          if (r?.ok) {
            if (config.models && Object.prototype.hasOwnProperty.call(config.models, name)) delete config.models[name];
            card.classList.add('is-removing');
            setTimeout(() => { renderModels(); }, 120);
            await loadGlobalEvents(true).catch(()=>{});
          } else {
            alert(r?.error || (r?.detail ? r.detail : 'Delete failed'));
          }
        });
        actions.appendChild(del);
      }
      if (provider?.type === 'lmstudio') {
        const inspect = makeIconAction('Inspect LM Studio model runtime', '◉', '', ev => { ev.stopPropagation(); inspectLmStudioModelByName(name).catch(e => alert(e.message)); });
        const load = makeIconAction('Load model in LM Studio', '⇧', '', ev => { ev.stopPropagation(); loadLmStudioModelByName(name).catch(e => alert(e.message)); });
        const unload = makeIconAction('Unload model from LM Studio', '⇩', '', ev => { ev.stopPropagation(); unloadLmStudioModelByName(name).catch(e => alert(e.message)); });
        actions.appendChild(inspect);
        actions.appendChild(load);
        actions.appendChild(unload);
      }
      card.appendChild(actions);
      el.appendChild(card);
    }
  }
  equalizeModelCardHeights();
  requestAnimationFrame(equalizeModelCardHeights);
  renderModelRecommendations().catch(()=>{});
  renderUnconfiguredModelsPanelFromLive().catch(()=>{});
}
function equalizeModelCardHeights() {
  const cards = Array.from(document.querySelectorAll('#models .model-overview-card'));
  if (!cards.length) return;
  cards.forEach(card => { card.style.minHeight = ''; });
  const maxHeight = Math.ceil(Math.max(...cards.map(card => card.getBoundingClientRect().height)));
  if (maxHeight > 0) cards.forEach(card => { card.style.minHeight = `${maxHeight}px`; });
}
window.addEventListener('resize', () => {
  clearTimeout(window.__pacModelCardHeightTimer);
  window.__pacModelCardHeightTimer = setTimeout(equalizeModelCardHeights, 120);
});
async function renderLiveModels() {
  const live = document.getElementById('modelsLive');
  if (!live) return;
  const providers = Object.keys(config.providers || {});
  if (!providers.length) { live.textContent = 'No providers configured.'; return; }
  const chunks = [];
  for (const name of providers) {
    const result = await fetchProviderModels(name);
    if (!result.ok) {
      chunks.push(`<div class="remote-provider failed compact-live-provider"><div class="provider-card-head"><b>${escapeHtml(name)}</b><span class="pill warn-pill">error</span></div><span>${escapeHtml(result.error || result.response?.error || 'model listing failed')}</span></div>`);
      continue;
    }
    const models = result.models || [];
    const rows = models.map(model => {
      const id = model.id || model.name || model.model || 'unknown';
      const key = providerModelKey(name, id);
      const configured = !!config.models?.[key] || Object.values(config.models || {}).some(item => item.provider === name && (item.model || '') === id);
      const meta = modelLiveMetaPills(model);
      return `<div class="live-model-row ${configured ? 'configured' : ''}"><button class="link-button live-model-name" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}" title="${escapeHtml(id)}">${escapeHtml(id)}</button><div class="provider-pill-list live-model-meta">${meta || '<span class="muted small-text">live provider model</span>'}</div><button class="ghost-button mini-button" data-add-live-model="1" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${configured ? 'Edit' : 'Configure'}</button></div>`;
    }).join('');
    chunks.push(`<section class="remote-provider compact-live-provider"><div class="provider-card-head"><div class="provider-title-block"><h3>${escapeHtml(providerLabel(name))}</h3><span class="muted small-text">Live provider inventory</span></div><span class="pill ${models.length ? 'ok-pill' : ''}">${models.length} models</span></div><div class="live-model-list">${rows || '<div class="muted small-text">No models returned</div>'}</div></section>`);
  }
  live.innerHTML = chunks.join('');
  live.querySelectorAll('button[data-model]').forEach(btn => {
    btn.onclick = () => openModelDraft(btn.dataset.provider, btn.dataset.model);
  });
  live.querySelectorAll('button[data-add-live-model]').forEach(btn => {
    btn.onclick = async () => openModelDraft(btn.dataset.provider, btn.dataset.model);
  });
}
