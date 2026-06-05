// Cross-surface provider/model insight panels for the models and provider pages.
function groupedSessionsBy(field) {
  const rows = new Map();
  for (const session of (window.__pacSessions || [])) {
    const key = String(session?.[field] || session?.metadata?.[field] || '').trim() || '(none)';
    const current = rows.get(key) || {count:0, running:0, failed:0, items:[]};
    current.count += 1;
    if (session.status === 'running') current.running += 1;
    if (session.status === 'failed') current.failed += 1;
    current.items.push(session);
    rows.set(key, current);
  }
  return rows;
}

function recommendationCardHtml(level, title, body, detail = '') {
  return `<article class="recommendation-card compact ${escapeHtml(level)}"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(body)}</p>${detail ? `<div class="muted small-text">${escapeHtml(detail)}</div>` : ''}</article>`;
}

function codingOpportunityActionButtons(item, kind) {
  const provider = item.provider_name || item.provider?.name || '';
  const modelId = item.model_id || '';
  const quant = item.quantization || '';
  const actions = [];
  if (kind === 'public') {
    actions.push(`<button class="ghost-button mini-button model-advice-action" title="Inspect candidate" aria-label="Inspect candidate" data-open-marketplace-candidate="${escapeHtml(modelId)}">&#9432;</button>`);
    if (provider) actions.push(`<button class="mini-button model-advice-action" title="Download to ${escapeHtml(provider)}" aria-label="Download to ${escapeHtml(provider)}" data-download-marketplace-candidate="${escapeHtml(provider)}::${escapeHtml(modelId)}::${escapeHtml(quant)}">&#8595;</button>`);
  } else if (provider) {
    actions.push(`<button class="mini-button model-advice-action" title="Configure model" aria-label="Configure model" data-configure-live-candidate="${escapeHtml(provider)}::${escapeHtml(modelId)}">&#9881;</button>`);
  }
  return actions.join('');
}

function codingOpportunityRowHtml(item, kind) {
  const provider = item.provider_name || item.provider?.name || '';
  const modelId = item.model_id || '';
  const score = Number(item.score || 0);
  const quality = item.quality || 'candidate';
  const fit = item.fit_reason || item.reason || '';
  return `<tr class="${quality === 'weak' ? 'warn' : ''}">
    <td>${escapeHtml(provider || 'public')}</td>
    <td>
      <div class="model-advice-name" title="${escapeHtml(modelId)}">${escapeHtml(modelId)}</div>
      ${fit ? `<div class="muted small-text" title="${escapeHtml(fit)}">${escapeHtml(fit)}</div>` : ''}
    </td>
    <td>${escapeHtml(quality)}</td>
    <td>${Number.isFinite(score) ? score.toFixed(1) : '-'}</td>
    <td class="model-advice-actions-cell">${codingOpportunityActionButtons(item, kind) || '<span class="muted small-text">-</span>'}</td>
  </tr>`;
}

function codingOpportunityTableHtml(title, items, kind) {
  if (!items?.length) return '';
  return `<section class="model-advice-table-wrap">
    <div class="recommendation-summary"><b>${escapeHtml(title)}</b></div>
    <table class="model-advice-table">
      <thead>
        <tr>
          <th>Provider</th>
          <th>Model</th>
          <th>Fit</th>
          <th>Score</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>${items.map(item => codingOpportunityRowHtml(item, kind)).join('')}</tbody>
    </table>
  </section>`;
}

async function renderUnconfiguredModelsPanelFromLive() {
  const target = document.getElementById('unconfiguredModelsList');
  if (!target) return;
  const providerEntries = Object.entries(config.providers || {}).filter(([_, provider]) => provider.enabled !== false);
  if (!providerEntries.length) {
    target.innerHTML = '<div class="muted">No enabled providers available.</div>';
    return;
  }
  target.innerHTML = '<div class="muted small-text">Checking live providers...</div>';
  const cards = [];
  for (const [providerName, provider] of providerEntries) {
    const result = await fetchProviderModels(providerName);
    if (!result.ok) continue;
    const rows = (result.models || []).filter(model => !configuredModelMatchesProviderModel(providerName, model.id || model.name || model.model));
    if (!rows.length) continue;
    const items = rows.map(model => {
      const modelId = model.id || model.name || model.model || 'unknown';
      const draftKey = providerModelKey(providerName, modelId);
      const summary = modelSummaryLine(model) || 'live provider model';
      return `<div class="inline-browser-row">
        <div><b>${escapeHtml(modelId)}</b><div class="muted small-text">${escapeHtml(summary)}</div></div>
        <div class="button-row inline-browser-group">
          <button class="ghost-button mini-button" data-open-live-model="${escapeHtml(providerName)}::${escapeHtml(modelId)}">Configure</button>
          <button class="mini-button" data-seed-live-model="${escapeHtml(providerName)}::${escapeHtml(modelId)}">${escapeHtml(draftKey)}</button>
        </div>
      </div>`;
    }).join('');
    cards.push(`<section class="remote-provider"><div class="provider-card-head"><div><b>${escapeHtml(providerLabel(providerName))}</b><div class="muted small-text">${rows.length} unconfigured model(s)</div></div><span class="pill ${providerIsSessionCapable(provider) ? 'ok-pill' : 'warn-pill'}">${providerIsSessionCapable(provider) ? 'session-ready' : 'limited'}</span></div>${items}</section>`);
  }
  target.innerHTML = cards.join('') || '<div class="muted">All provider models are already configured in PAC.</div>';
  target.querySelectorAll('[data-open-live-model]').forEach(btn => {
    btn.onclick = () => {
      const [providerName, modelId] = String(btn.dataset.openLiveModel || '').split('::');
      openModelDraft(providerName, modelId);
    };
  });
  target.querySelectorAll('[data-seed-live-model]').forEach(btn => {
    btn.onclick = () => {
      const [providerName, modelId] = String(btn.dataset.seedLiveModel || '').split('::');
      openModelDraft(providerName, modelId);
      modelName.focus();
      modelName.select();
    };
  });
}

async function renderModelRecommendations() {
  const panel = document.getElementById('modelsRecommendationsPanel');
  const body = document.getElementById('modelsRecommendationsBody');
  if (!panel || !body) return;
  const recommendations = [];
  const models = Object.entries(config.models || {});
  if (!models.length) {
    const enabledProviders = Object.entries(config.providers || {}).filter(([_, provider]) => provider.enabled !== false);
    if (enabledProviders.length) recommendations.push(recommendationCardHtml('info', 'No configured session models', 'Create at least one model from the live provider inventory so profiles and sessions can use it.', 'Use Browse providers or Marketplace from the Models area.'));
  }
  for (const [name, model] of models) {
    const availability = modelAvailability(name);
    const provider = config.providers?.[model.provider || ''];
    if (!availability.ok) recommendations.push(recommendationCardHtml('warn', `${name} is not currently available`, availability.reason || 'The provider is not returning this model.', `${providerLabel(model.provider || '-')}`));
    if (provider?.type === 'lmstudio') {
      const runtime = model.extra?.lmstudio_runtime || {};
      if (runtime.context_length && model.context_window && Number(runtime.context_length) < Number(model.context_window)) recommendations.push(recommendationCardHtml('warn', `LM Studio load window is shorter for ${name}`, 'PAC is configured to expect a larger context window than the LM Studio runtime will load.', 'Raise the runtime context length or lower the configured model context to keep behavior consistent.'));
      if (!runtime.context_length && model.context_window) recommendations.push(recommendationCardHtml('info', `Set an explicit LM Studio load window for ${name}`, 'The model has a configured PAC context window, but the LM Studio load runtime still relies on implicit defaults.', 'Set the runtime context length so load behavior is predictable.'));
    }
  }
  let advisor = null;
  try {
    advisor = await api('/v1/model-advisors/coding-opportunities');
  } catch (error) {
    advisor = {ok:false, error:error.message || String(error)};
  }
  if (advisor?.warning?.summary) {
    recommendations.unshift(recommendationCardHtml(
      advisor.warning.level || 'info',
      advisor.warning.title || 'Coding model advice',
      advisor.warning.summary || '',
      advisor?.llmfit?.ok ? 'Backed by llmfit-aware selection.' : 'Using PAC model-fit heuristics.'
    ));
  }
  const localTable = codingOpportunityTableHtml('Better local options', (advisor?.local_candidates || []).slice(0, 4), 'local');
  const publicTable = codingOpportunityTableHtml('Public coding models worth adding', (advisor?.public_candidates || []).slice(0, 5), 'public');
  const visible = recommendations.slice(0, 4);
  const hiddenCount = Math.max(0, recommendations.length - visible.length);
  body.innerHTML = [
    visible.join('') || '<div class="muted small-text">No adaptation recommendations right now.</div>',
    localTable,
    publicTable,
    hiddenCount ? `<div class="muted small-text recommendation-summary">+ ${hiddenCount} more recommendation(s). Resolve current issues to reduce this list.</div>` : '',
  ].filter(Boolean).join('');
  panel.hidden = false;
  body.querySelectorAll('[data-open-marketplace-candidate]').forEach(btn => {
    btn.onclick = async () => {
      const modelId = btn.dataset.openMarketplaceCandidate || '';
      const input = document.getElementById('marketplaceModalQuery');
      if (input) input.value = modelId;
      openMarketplaceModal();
      try {
        const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(modelId)}`);
        renderMarketplaceModalDetail(detail);
      } catch (e) {
        paneError('Marketplace details failed', e.message || String(e));
      }
    };
  });
  body.querySelectorAll('[data-download-marketplace-candidate]').forEach(btn => {
    btn.onclick = async () => {
      const [provider, modelId, quantization] = String(btn.dataset.downloadMarketplaceCandidate || '').split('::');
      try {
        const result = await api('/v1/models/marketplace/download', {
          method:'POST',
          body: JSON.stringify({model: modelId, provider, quantization: quantization || undefined}),
        });
        showInline('modelFormResult', {marketplace_download: result, provider, model: modelId, quantization});
      } catch (e) {
        paneError('Marketplace download failed', e.message || String(e));
      }
    };
  });
  body.querySelectorAll('[data-configure-live-candidate]').forEach(btn => {
    btn.onclick = () => {
      const [providerName, modelId] = String(btn.dataset.configureLiveCandidate || '').split('::');
      openModelDraft(providerName, modelId);
    };
  });
}

function renderModelActiveSessionsPanel() {
  const target = document.getElementById('modelsActiveSessions');
  if (!target) return;
  const grouped = groupedSessionsBy('model');
  if (!grouped.size) {
    target.innerHTML = '<div class="muted small-text">No active or historical sessions yet.</div>';
    return;
  }
  target.innerHTML = Array.from(grouped.entries()).sort((a,b) => b[1].count - a[1].count).map(([name, info]) => `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${info.running} running - ${info.failed} failed</div></div><span class="pill">${info.count} session(s)</span></div>`).join('');
}

async function renderProvidersLivePanel() {
  const target = document.getElementById('providersLive');
  if (!target) return;
  const providers = Object.entries(config.providers || {});
  if (!providers.length) {
    target.innerHTML = '<div class="muted small-text">No providers configured.</div>';
    return;
  }
  const sections = [];
  for (const [name, provider] of providers) {
    const result = await fetchProviderModels(name);
    const models = result.ok ? (result.models || []) : [];
    const summary = models.length ? models.slice(0, 4).map(model => model.id || model.name || model.model).join(', ') : (result.ok ? 'No models returned' : (result.error || 'Model listing failed'));
    sections.push(`<div class="inline-browser-row"><div><b>${escapeHtml(providerLabel(name))}</b><div class="muted small-text">${escapeHtml(summary)}</div></div><span class="pill ${result.ok ? 'ok-pill' : 'warn-pill'}">${result.ok ? `${models.length} live` : 'error'}</span></div>`);
  }
  target.innerHTML = sections.join('');
}

function renderProfileUsagePanel() {
  const target = document.getElementById('profilesUsage');
  if (!target) return;
  const grouped = groupedSessionsBy('agent_profile');
  const profiles = Object.entries(config.agent_profiles || {});
  if (!profiles.length) {
    target.innerHTML = '<div class="muted small-text">No profiles configured.</div>';
    return;
  }
  target.innerHTML = profiles.map(([name, profile]) => {
    const usage = grouped.get(name) || {count:0, running:0, failed:0};
    const display = profile.display_name || name;
    const contextProfile = profile.context_profile || profile.context_mode || 'medium';
    const visibility = profile.visibility || ((profile.allowed_groups || []).length ? 'group' : 'global');
    return `<div class="inline-browser-row"><div><b>${escapeHtml(display)}</b><div class="muted small-text">${escapeHtml(contextProfile)} - ${escapeHtml(profile.permission_profile || '-')} - ${escapeHtml(visibility)}</div></div><span class="pill">${usage.count} session(s)</span></div>`;
  }).join('');
}

function renderWorkspaceActivityPanel() {
  const target = document.getElementById('workspacesActive');
  if (!target) return;
  const sessions = window.__pacSessions || [];
  const agents = window.__pacWorkspaceAgents || [];
  const workspaces = Object.entries(config.workspaces || {});
  const agentCards = agents.map((agent) => {
    const metrics = agent.metrics || agent.metadata?.metrics || {};
    const memory = metrics.memory || {};
    const usedRatio = typeof memory.used_ratio === 'number' ? `${Math.round(memory.used_ratio * 100)}% memory` : 'metrics pending';
    const load = typeof metrics.load_1m === 'number' ? `load ${Number(metrics.load_1m).toFixed(2)}` : usedRatio;
    const statusClass = agent.status === 'online' ? 'ready' : agent.status === 'degraded' ? 'attention' : 'muted';
    return `<div class="inline-browser-row"><div><b>${escapeHtml(agent.name || agent.workspace_id)}</b><div class="muted small-text">${escapeHtml(agent.status || 'unknown')} - ${escapeHtml(agent.root || '-')} - ${escapeHtml(load)}</div></div><div class="row-actions"><button class="ghost-button mini-button" data-workspace-terminal="${escapeHtml(agent.workspace_id)}">Terminal</button><span class="pill ${statusClass}">agent</span></div></div>`;
  });
  const profileCards = workspaces.map(([name, workspace]) => {
    const count = sessions.filter(session => {
      const path = String(session.workspace_path || '');
      return path === String(workspace.path || '') || path.includes(name);
    }).length;
    const placement = workspace.endpoint_id || workspace.endpoint_selector || 'runtime';
    return `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${escapeHtml(workspace.type || 'local')} - ${escapeHtml(placement)}</div></div><span class="pill">${count} session(s)</span></div>`;
  });
  const cards = [...agentCards, ...profileCards];
  target.innerHTML = cards.join('') || '<div class="muted small-text">No workspaces configured or online.</div>';
  target.querySelectorAll('[data-workspace-terminal]').forEach((btn) => {
    btn.onclick = () => openWorkspaceLiveTerminal(btn.getAttribute('data-workspace-terminal') || '');
  });
}
