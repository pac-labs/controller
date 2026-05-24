// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

function renderTools() {
  const pkgEl = document.getElementById('toolPackagesOverview');
  if (pkgEl) {
    pkgEl.innerHTML = Object.entries(config.tool_packages || {}).map(([name,p]) => `<div class="row"><div><b>${escapeHtml(name)}</b> <span class="pill ${p.enabled !== false ? 'ok-pill' : ''}">${p.enabled !== false ? 'enabled':'disabled'}</span><br><span class="muted">${escapeHtml(p.description || '')}</span><br><span class="muted">tools: ${escapeHtml((p.tools || []).join(', ') || '-')}</span></div></div>`).join('') || '<div class="muted">No tool packages configured.</div>';
  }
  const pluginEl = document.getElementById('pluginsOverview');
  if (pluginEl) {
    pluginEl.innerHTML = Object.entries(config.plugins || {}).map(([name,p]) => `<div class="row"><div><b>${escapeHtml(name)}</b> <span class="pill">${escapeHtml(p.kind || 'plugin')}</span><br><span class="muted">${escapeHtml(p.description || '')}</span><br><span class="muted">requires: ${escapeHtml((p.requires_tools || []).join(', ') || '-')}</span></div></div>`).join('') || '<div class="muted">No plugins configured.</div>';
  }
  const el = document.getElementById('toolsOverview'); if (!el) return; el.innerHTML = '';
  for (const [name,t] of Object.entries(config.tools || {})) {
    const row=document.createElement('div'); row.className='row clickable-row';
    row.innerHTML = `<div><b>${escapeHtml(name)}</b> <span class="pill ${t.enabled ? 'ok-pill' : ''}">${t.enabled ? 'enabled':'disabled'}</span>${t.package ? ` <span class="pill">${escapeHtml(t.package)}</span>` : ''}<br><span class="muted">${escapeHtml(t.description || '')}</span><br><span class="muted">binaries: ${escapeHtml((t.binaries || []).join(', ') || '-')}</span><br><span class="muted">approval: ${escapeHtml((t.approval_required_patterns || []).join(', ') || '-')}</span></div>`;
    row.onclick=()=>fillToolForm(name);
    el.appendChild(row);
  }
}
// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

function fillToolForm(name) {
  const t = config.tools?.[name]; if (!t) return;
  toolName.value=name; toolDescription.value=t.description || ''; toolBinaries.value=(t.binaries || []).join(', ');
  toolApprovalPatterns.value=(t.approval_required_patterns || []).join(', '); toolSocket.value=t.socket || ''; if (document.getElementById('toolPackage')) toolPackage.value=t.package || ''; if (document.getElementById('toolInstallHint')) toolInstallHint.value=t.install_hint || ''; toolEnabled.checked=t.enabled !== false;
}

async function persistConfigAndReload(messageId, message) {
  await api('/v1/config',{method:'PUT',body:JSON.stringify({config})});
  await loadConfig();
  showInline(messageId, message || 'Saved');
}

async function saveProviderFromForm() {
  if (!providerName.value.trim()) return alert('Provider name is required');
  config.providers = config.providers || {};
  let providerBase = providerBaseUrl.value.trim();
  if ((providerType.value === 'lmstudio' || providerType.value === 'vllm') && providerBase && !providerBase.replace(/\/$/, '').endsWith('/v1')) providerBase = providerBase.replace(/\/$/, '') + '/v1';
  if ((providerType.value === 'anthropic-compatible' || providerType.value === 'minimax') && providerBase && !providerBase.replace(/\/$/, '').endsWith('/v1')) providerBase = providerBase.replace(/\/$/, '') + '/v1';
  const pname = providerName.value.trim();
  const existing = config.providers?.[pname] || {};
  config.providers[pname] = {
    ...existing,
    type: providerType.value,
    base_url: providerBase || null,
    api_key_env: providerApiKeyEnv.value.trim() || null,
    api_key: providerApiKey.value.trim() || null,
    timeout_seconds: Number(providerTimeout.value || 30),
    default_headers: existing.default_headers || {},
    enabled: existing.enabled ?? false,
    status: existing.status || 'disabled',
    runtime: collectProviderRuntimeFields(existing.runtime || {}),
  };
  await persistConfigAndReload('providerFormResult', `Saved provider ${providerName.value.trim()}`);
  setModalStatus('providerModalStatus', 'Saved');
}

async function saveModelFromForm() {
  if (!modelName.value.trim()) return alert('Display name is required');
  if (!modelProvider.value) return alert('Provider is required');
  config.models = config.models || {};
  const originalKey = modelName.dataset.originalKey || '';
  const targetKey = originalKey || (typeof newPacModelKey === 'function' ? newPacModelKey() : `model-${Date.now()}`);
  const existingModel = originalKey ? (config.models[originalKey] || {}) : {};
  const duplicate = findConfiguredModelByProviderModel(modelProvider.value, modelId.value.trim() || modelName.value.trim(), targetKey);
  if (duplicate) return alert(`This provider model is already configured as '${duplicate[0]}'. Edit that entry instead of creating a duplicate.`);
  const chunking = collectModelChunkingFields();
  config.models[targetKey] = {
    ...existingModel,
    id: existingModel.id || modelName.dataset.pacModelId || targetKey,
    display_name: modelName.value.trim(),
    provider: modelProvider.value,
    model: modelId.value.trim() || null,
    runs_on: modelRunsOn.value.trim() || null,
    context_window: Number(modelContextWindow.value || 4096),
    max_output_tokens: Number(modelMaxOutput.value || 1024),
    input_price_per_million: numberOrNull(modelInputPrice.value),
    output_price_per_million: numberOrNull(modelOutputPrice.value),
    capabilities: {
      supports_chat: !!modelSupportsChat.checked,
      supports_tools: !!modelSupportsTools.checked,
      supports_vision: !!modelSupportsVision.checked,
      supports_json: !!modelSupportsJson.checked,
      supports_streaming: !!modelSupportsStreaming.checked,
      reasoning: modelReasoning.value || 'none'
    },
    extra: {
      ...(currentModelProvider()?.type === 'lmstudio' ? {lmstudio_runtime: collectLmStudioRuntimeFields()} : {}),
      function: document.getElementById('modelFunction')?.value || 'general',
      ...(chunking ? {chunking} : {}),
    },
  };
  const savedName = modelName.value.trim();
  const savedKey = targetKey;
  modelName.dataset.originalKey = savedKey;
  await persistConfigAndReload(null, null);
  showInline('modelFormResult', {model: savedName, pac_model_id: savedKey, provider: modelProvider.value, model_id: modelId.value.trim() || null, preferred_endpoint: modelRunsOn.value.trim() || null});
  setModalStatus('modelModalStatus', 'Saved');
}

// saveProfileFromForm/deleteProfileFromForm are implemented in
// /ui/app/profiles_page.js.

async function saveToolFromForm() {
  if (!toolName.value.trim()) return alert('Tool name is required');
  config.tools = config.tools || {};
  config.tools[toolName.value.trim()] = {
    enabled: !!toolEnabled.checked,
    description: toolDescription.value.trim() || null,
    approval_required_patterns: csv(toolApprovalPatterns.value),
    binaries: csv(toolBinaries.value),
    socket: toolSocket.value.trim() || null,
    package: document.getElementById('toolPackage')?.value || null,
    install_hint: document.getElementById('toolInstallHint')?.value.trim() || null,
  };
  await persistConfigAndReload('toolFormResult', `Saved tool ${toolName.value.trim()}`);
}

async function deleteToolFromForm() {
  const name = toolName.value.trim();
  if (!name || !config.tools?.[name]) return alert('Select an existing tool first');
  if (!confirm(`Delete tool ${name}? Profiles using it may need updates.`)) return;
  delete config.tools[name];
  await persistConfigAndReload('toolFormResult', `Deleted tool ${name}`);
}
