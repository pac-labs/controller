// Configured model inventory and live provider model list rendering.
function modelTableAction(label, icon, attrs = '', extraClass = '') {
  const classes = ['model-icon-action', extraClass].filter(Boolean).join(' ');
  return `<button type="button" class="${classes}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" ${attrs}>${icon}</button>`;
}

function renderModels() {
  const el = document.getElementById('models');
  if (!el) return;
  el.className = 'model-inventory-wrap';
  const models = Object.entries(config.models || {});
  if (!models.length) {
    el.innerHTML = '<div class="muted">No configured models yet. Add one from Marketplace or Browse providers.</div>';
  } else {
    const rows = models.map(([name, model]) => {
      const availability = modelAvailability(name);
      const provider = config.providers?.[model.provider || ''];
      const health = providerHealthSummary(model.provider || '', provider || {});
      const sessionCount = (window.__pacSessions || []).filter(item => item.model === name).length;
      const displayName = modelDisplayName(name, model);
      const stableId = modelStableId(name, model);
      const modelFunction = model.extra?.function || inferModelFunction(model.provider, model.model || displayName || name);
      const providerName = providerLabel(model.provider || '-');
      const modelId = model.model || '-';
      const reasoning = model.capabilities?.reasoning ? ` / reasoning ${model.capabilities.reasoning}` : '';
      const stateText = availability.ok ? health.detail : availability.reason;
      const actions = [
        modelTableAction('Edit model configuration', '✎', `data-edit-model="${escapeHtml(name)}"`),
        modelTableAction('Test model', '▶', `data-test-model="${escapeHtml(name)}"`),
      ];
      if (provider?.type === 'lmstudio') {
        actions.push(modelTableAction('Inspect LM Studio runtime', '◉', `data-inspect-model="${escapeHtml(name)}"`));
        actions.push(modelTableAction('Load model in LM Studio', '⇧', `data-load-model="${escapeHtml(name)}"`));
        actions.push(modelTableAction('Unload model from LM Studio', '⇩', `data-unload-model="${escapeHtml(name)}"`));
      }
      if (!model.read_only) actions.push(modelTableAction('Delete model configuration', '×', `data-delete-model="${escapeHtml(name)}"`, 'danger-action'));
      return `<tr class="${availability.ok ? '' : 'warn'}">
        <td>
          <button type="button" class="link-button model-table-name" data-edit-model="${escapeHtml(name)}" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</button>
          <div class="muted small-text" title="${escapeHtml(stableId)}">${escapeHtml(stableId)}</div>
        </td>
        <td><code title="${escapeHtml(modelId)}">${escapeHtml(modelId)}</code></td>
        <td>${escapeHtml(providerName)}</td>
        <td>${escapeHtml(`${modelFunction}${reasoning}`)}</td>
        <td>
          <span class="pill ${escapeHtml(availability.ok ? health.klass : 'warn-pill')}">${escapeHtml(availability.ok ? health.pill : 'attention')}</span>
          <div class="muted small-text" title="${escapeHtml(stateText)}">${escapeHtml(stateText)}</div>
        </td>
        <td>${escapeHtml(compactTokenNumber(model.context_window || '-'))}</td>
        <td>${escapeHtml(compactTokenNumber(model.max_output_tokens || '-'))}</td>
        <td>${escapeHtml(String(sessionCount || 0))}</td>
        <td class="model-table-actions-cell">${actions.join('')}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<table class="model-inventory-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Provider model</th>
          <th>Host</th>
          <th>Role</th>
          <th>Status</th>
          <th>Ctx</th>
          <th>Out</th>
          <th>Sessions</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
  }
  bindModelInventoryActions(el);
  renderModelRecommendations().catch(()=>{});
  renderUnconfiguredModelsPanelFromLive().catch(()=>{});
}

function bindModelInventoryActions(root) {
  root.querySelectorAll('[data-edit-model]').forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      openModelModal(btn.getAttribute('data-edit-model') || '');
    };
  });
  root.querySelectorAll('[data-test-model]').forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const modelName = btn.getAttribute('data-test-model') || '';
      const result = await api(`/v1/models/${modelName}/test`, {method:'POST'});
      showInline('modelFormResult', {model:modelName, ...result});
    };
  });
  root.querySelectorAll('[data-delete-model]').forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const modelName = btn.getAttribute('data-delete-model') || '';
      const model = config.models?.[modelName] || {};
      const label = modelDisplayName(modelName, model);
      if (!confirm(`Delete model '${label}'`)) return;
      const result = await api(`/v1/models/${modelName}`, {method:'DELETE'});
      if (result?.ok) {
        if (config.models && Object.prototype.hasOwnProperty.call(config.models, modelName)) delete config.models[modelName];
        renderModels();
        await loadGlobalEvents(true).catch(()=>{});
      } else {
        alert(result?.error || (result?.detail ? result.detail : 'Delete failed'));
      }
    };
  });
  root.querySelectorAll('[data-inspect-model]').forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      inspectLmStudioModelByName(btn.getAttribute('data-inspect-model') || '').catch(e => alert(e.message));
    };
  });
  root.querySelectorAll('[data-load-model]').forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      loadLmStudioModelByName(btn.getAttribute('data-load-model') || '').catch(e => alert(e.message));
    };
  });
  root.querySelectorAll('[data-unload-model]').forEach((btn) => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      unloadLmStudioModelByName(btn.getAttribute('data-unload-model') || '').catch(e => alert(e.message));
    };
  });
}

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
