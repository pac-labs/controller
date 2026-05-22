// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

// Legacy profile rendering and form helpers were removed when profiles became
// behavior/context/access cards instead of model/tool presets. The active
// profile UI now lives in /ui/app/profiles_page.js.

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

function endpointName(id) {
  if (!id) return 'PAC/local';
  const r = (window.__pacEndpoints || []).find(x => x.id === id);
  return r ? `${r.name || r.id} (${r.status || 'unknown'})` : id;
}

function selectedRunnerToolNames() {
  const sel = document.getElementById('runnerTools');
  if (!sel) return [];
  return Array.from(sel.selectedOptions || []).map(o => o.value).filter(Boolean);
}

function selectedWizardToolNames() {
  const sel = document.getElementById('wizardRunnerTools');
  if (!sel) return [];
  return Array.from(sel.selectedOptions || []).map(o => o.value).filter(Boolean);
}

function setSelectedRunnerToolNames(names) {
  const sel = document.getElementById('runnerTools');
  if (!sel) return;
  const wanted = new Set(names || []);
  Array.from(sel.options || []).forEach(o => { o.selected = wanted.has(o.value); });
  updateRunnerToolPackagePreview();
}

function setSelectedWizardToolNames(names) {
  const sel = document.getElementById('wizardRunnerTools');
  if (!sel) return;
  const wanted = new Set(names || []);
  Array.from(sel.options || []).forEach(o => { o.selected = wanted.has(o.value); });
  updateWizardToolPackagePreview();
}

function packageNamesForTools(names) {
  const selected = new Set(names || []);
  return Object.entries(config?.tool_packages || {}).filter(([_,pkg]) => (pkg.tools || []).length && (pkg.tools || []).every(t => selected.has(t))).map(([name]) => name);
}

function endpointPiContainer(r) {
  return r.metadata?.agent_runtime?.pi_container || r.capabilities?.pi_container || {};
}

function endpointFeatureChips(r, effectiveTools = []) {
  const caps = r.capabilities || {};
  const tools = caps.tools || {};
  const pi = endpointPiContainer(r) || {};
  const enablement = r.metadata?.agent_enablement || {};
  const chips = [];
  const add = (label, state, required=false, title='') => {
    const cls = state === 'available' ? 'ok-pill' : (required ? 'required-missing-pill' : 'optional-missing-pill');
    const text = state === 'available' ? label : `${label} missing`;
    chips.push(`<span class="pill feature-pill ${cls}" title="${escapeHtml(title || text)}">${escapeHtml(text)}</span>`);
  };
  add('commands', (r.status === 'online' || r.metadata?.local_control_plane) ? 'available' : 'missing', true, 'Endpoint must be reachable for queued commands.');
  add('workspace', r.metadata?.default_workspace ? 'available' : 'missing', true, 'Every endpoint should have a default workspace.');
  add('pi.dev', pi.available ? 'available' : 'missing', true, pi.reason || 'Required for pi.dev container sessions on this endpoint.');
  if ((pi.image_available || pi.available) && !pi.available) add('pi.dev image', 'available', false, 'The harness image is installed, but the runtime is not healthy yet.');
  add('PAC wrapper', (enablement.node_available && enablement.pi_available) ? 'available' : 'missing', !!(enablement.requested || enablement.required), enablement.detail || 'Required when this endpoint runs pi.dev workloads.');
  add('container runtime', (caps.container_runtimes || []).length ? 'available' : 'missing', true, 'Required to build/run the pi.dev and containerized tooling.');
  if (caps.gpu?.available || (caps.gpu?.devices || []).length) add('GPU', 'available', false, 'Detected endpoint hardware.');
  (effectiveTools || []).slice(0, 8).forEach(name => {
    const toolState = tools[name]?.available ? 'available' : 'missing';
    add(name, toolState, true, `Configured endpoint tool: ${name}`);
  });
  if ((effectiveTools || []).length > 8) chips.push(`<span class="pill feature-pill">+${(effectiveTools || []).length - 8} tools</span>`);
  return chips.join('');
}

function endpointRuntimeLines(r) {
  const runtime = r.metadata?.agent_runtime || {};
  const lines = [];
  lines.push(`state: ${runtime.status || r.status || 'unknown'}`);
  if (runtime.kind) lines.push(`kind: ${runtime.kind}`);
  if (runtime.version || r.metadata?.runner_version || r.metadata?.endpoint_version) lines.push(`version: ${runtime.version || r.metadata?.runner_version || r.metadata?.endpoint_version}`);
  if (runtime.detail) lines.push(`detail: ${runtime.detail}`);
  const pi = endpointPiContainer(r);
  if (pi) {
    lines.push(`pi image: ${pi.image || '-'}`);
    lines.push(`pi image present: ${(pi.image_available || pi.available) ? 'yes' : 'no'}`);
    lines.push(`pi runtime ready: ${pi.available ? 'yes' : 'no'}`);
    if (pi.runtime) lines.push(`container runtime: ${pi.runtime}`);
    if (pi.reason) lines.push(`reason: ${pi.reason}`);
    if (pi.hint) lines.push(`hint: ${pi.hint}`);
    if (pi.build_command) lines.push(`build: ${pi.build_command}`);
  }
  return lines.join('\n');
}

function updateRunnerToolPackagePreview() {
  const el = document.getElementById('runnerToolPackagePreview');
  if (!el) return;
  const names = selectedRunnerToolNames();
  const packages = packageNamesForTools(names);
  const toolPills = names.map(n => `<span class="pill ok-pill">${escapeHtml(n)}</span>`).join('');
  const packagePills = packages.map(n => `<span class="pill ok-pill">${escapeHtml(n)} package</span>`).join('');
  el.innerHTML = packagePills + toolPills || '<span class="muted">No endpoint tools selected.</span>';
}

function updateWizardToolPackagePreview() {
  const el = document.getElementById('wizardToolPackagePreview');
  if (!el) return;
  const names = selectedWizardToolNames();
  const packages = packageNamesForTools(names);
  const toolPills = names.map(n => `<span class="pill ok-pill">${escapeHtml(n)}</span>`).join('');
  const packagePills = packages.map(n => `<span class="pill ok-pill">${escapeHtml(n)} package</span>`).join('');
  el.innerHTML = packagePills + toolPills || '<span class="muted">No endpoint tools selected.</span>';
}

function fillModelEndpointOptions(endpoints = window.__pacEndpoints || []) {
  const sel = document.getElementById('modelRunsOn');
  if (!sel || sel.tagName !== 'SELECT') return;
  const current = sel.value;
  sel.innerHTML = '<option value="">provider default</option>';
  (endpoints || []).forEach(r => opt(sel, r.id, `${r.name || r.id} (${r.status || 'unknown'})`));
  if (current && !Array.from(sel.options).some(o => o.value === current)) opt(sel, current, current);
  sel.value = current || '';
}

function setModalStatus(id, value='') {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function setModelIdSource(source='manual', detail='') {
  const input = document.getElementById('modelId');
  const hint = document.getElementById('modelIdSourceHint');
  const manual = document.getElementById('modelManualIdOverride');
  if (!input) return;
  const normalized = source || 'manual';
  input.dataset.source = normalized;
  input.dataset.sourceDetail = detail || '';
  const manualAllowed = normalized === 'manual' || !!manual?.checked;
  input.readOnly = !manualAllowed;
  input.classList.toggle('readonly-source-field', !manualAllowed);
  input.classList.toggle('manual-source-field', manualAllowed);
  if (hint) {
    if (normalized === 'provider') {
      hint.textContent = detail ? `Discovered from provider: ${detail}.` : 'Discovered from the provider inventory.';
    } else if (normalized === 'marketplace') {
      hint.textContent = detail ? `Selected from marketplace: ${detail}.` : 'Selected from the model marketplace.';
    } else if (normalized === 'configured') {
      hint.textContent = detail ? `Stored configured model ID for ${detail}.` : 'Stored configured model ID.';
    } else {
      hint.textContent = 'Manual provider model ID override is enabled. Prefer selecting from provider inventory or marketplace when possible.';
    }
  }
}

function refreshModelIdManualOverrideState() {
  const manual = document.getElementById('modelManualIdOverride');
  const input = document.getElementById('modelId');
  if (!manual || !input) return;
  if (manual.checked) setModelIdSource('manual');
  else setModelIdSource(input.dataset.source || (input.value.trim() ? 'configured' : 'manual'), input.dataset.sourceDetail || '');
}

function openProviderModal(name='') {
  if (name) fillProviderForm(name); else {
    providerName.value=''; if (document.getElementById('providerPreset')) providerPreset.value='custom-openai'; providerType.value='openai-compatible'; providerBaseUrl.value=''; providerApiKeyEnv.value=''; providerApiKey.value=''; providerTimeout.value=30; fillProviderRuntimeFields({});
  }
  setModalStatus('providerModalStatus');
  const modal = document.getElementById('providerModal');
  if (modal) modal.hidden = false;
  setTimeout(()=>document.getElementById('providerName')?.focus(), 0);
}

function closeProviderModal() { const modal = document.getElementById('providerModal'); if (modal) modal.hidden = true; }

function openModelModal(name='') {
  fillModelEndpointOptions();
  if (name) { fillModelForm(name); }
  else {
    modelName.value=''; modelName.dataset.originalKey=''; modelName.dataset.pacModelId=''; modelId.value=''; modelRunsOn.value=''; modelContextWindow.value=4096; modelMaxOutput.value=1024;
    const manualOverride = document.getElementById('modelManualIdOverride'); if (manualOverride) manualOverride.checked = true;
    setModelIdSource('manual');
    const modelFunction = document.getElementById('modelFunction'); if (modelFunction) modelFunction.value='general';
    modelName.dataset.auto = 'true';
    modelSupportsChat.checked=true; modelSupportsTools.checked=false; modelSupportsVision.checked=false; modelSupportsJson.checked=false; modelSupportsStreaming.checked=true; modelReasoning.value='none'; modelInputPrice.value=''; modelOutputPrice.value=''; fillLmStudioRuntimeFields({});
    fillModelChunkingFields({});
    const defaultProvider = modelProvider?.options?.[0]?.value || '';
    if (modelProvider) modelProvider.value = defaultProvider;
    const providerDisplay = document.getElementById('modelProviderDisplay'); if (providerDisplay) providerDisplay.textContent = defaultProvider;
    refreshModelProviderCandidates(defaultProvider).catch(()=>{});
  }
  updateLmStudioModelControls();
  setModalStatus('modelModalStatus');
  const modal = document.getElementById('modelModal');
  if (modal) modal.hidden = false;
  setTimeout(()=>document.getElementById('modelName')?.focus(), 0);
}

function closeModelModal() { const modal = document.getElementById('modelModal'); if (modal) modal.hidden = true; }

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

function fillProviderForm(name) {
  const p = config.providers?.[name]; if (!p) return;
  if (document.getElementById('providerPreset')) providerPreset.value='';
  providerName.value = name; providerType.value = p.type || 'openai-compatible'; providerBaseUrl.value = p.base_url || '';
  providerApiKeyEnv.value = p.api_key_env || ''; providerApiKey.value = p.api_key || ''; providerTimeout.value = p.timeout_seconds || 30; fillProviderRuntimeFields(p.runtime || {});
}

function fillModelForm(name) {
  const m = config.models?.[name]; if (!m) return;
  modelName.value=(typeof modelDisplayName === 'function' ? modelDisplayName(name, m) : (m.display_name || name));
  modelName.dataset.originalKey = name;
  modelName.dataset.pacModelId = m.id || name;
  const providerDisplay = document.getElementById('modelProviderDisplay'); if (providerDisplay) providerDisplay.textContent = m.provider || '(none)'; modelId.value=m.model || ''; modelRunsOn.value=m.runs_on || '';
  const manualOverride = document.getElementById('modelManualIdOverride'); if (manualOverride) manualOverride.checked = false;
  setModelIdSource('configured', name);
  const providerSelect = document.getElementById('modelProvider'); if (providerSelect) { providerSelect.value = m.provider || ''; }
  const modelFunction = document.getElementById('modelFunction'); if (modelFunction) modelFunction.value = m.extra?.function || inferModelFunction(m.provider, m.model || name);
  modelName.dataset.auto = 'false';
  modelContextWindow.value=m.context_window || 4096; modelMaxOutput.value=m.max_output_tokens || 1024;
  modelSupportsChat.checked=m.capabilities?.supports_chat !== false; modelSupportsTools.checked=!!m.capabilities?.supports_tools; modelSupportsVision.checked=!!m.capabilities?.supports_vision; modelSupportsJson.checked=!!m.capabilities?.supports_json;
  modelSupportsStreaming.checked=m.capabilities?.supports_streaming !== false;
  modelReasoning.value=m.capabilities?.reasoning || 'none';
  modelInputPrice.value=m.input_price_per_million ?? '';
  modelOutputPrice.value=m.output_price_per_million ?? '';
  fillLmStudioRuntimeFields(m.extra?.lmstudio_runtime || {});
  fillModelChunkingFields(m.extra || {});
  refreshModelProviderCandidates(m.provider || '').catch(()=>{});
  updateLmStudioModelControls();
}

function currentModelProvider() {
  return config.providers?.[modelProvider?.value || ''] || null;
}

async function refreshModelProviderCandidates(providerName) {
  const list = document.getElementById('modelProviderModelOptions');
  if (!list) return;
  list.innerHTML = '';
  if (!providerName) return;
  try {
    const result = await api(`/v1/providers/${encodeURIComponent(providerName)}/models`);
    const models = result?.models || [];
    models.forEach((item) => {
      const id = item?.id || item?.name || item?.model;
      if (!id) return;
      const option = document.createElement('option');
      option.value = id;
      option.label = modelSummaryLine(item);
      list.appendChild(option);
    });
    const currentId = document.getElementById('modelId')?.value?.trim();
    if (currentId && models.some((item) => currentId === String(item?.id || item?.name || item?.model || ''))) {
      const manualOverride = document.getElementById('modelManualIdOverride'); if (manualOverride) manualOverride.checked = false;
      setModelIdSource('provider', providerName);
    }
  } catch (_) {
    // Leave the field usable even if live provider model listing fails.
  }
}

function updateLmStudioModelControls() {
  const box = document.getElementById('lmStudioModelControls');
  if (!box) return;
  const provider = currentModelProvider();
  box.hidden = !provider || provider.type !== 'lmstudio';
}

function numberOrNull(value) {
  if (value === undefined || value === null || String(value).trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fillLmStudioRuntimeFields(runtime) {
  const r = runtime || {};
  if (document.getElementById('lmModelContextLength')) lmModelContextLength.value = r.context_length || '';
  if (document.getElementById('lmModelGpuOffload')) lmModelGpuOffload.value = r.gpu_offload ?? '';
  if (document.getElementById('lmModelEvalBatch')) lmModelEvalBatch.value = r.eval_batch_size || '';
  if (document.getElementById('lmModelTemperature')) lmModelTemperature.value = r.temperature ?? '';
  if (document.getElementById('lmModelTopP')) lmModelTopP.value = r.top_p ?? '';
  if (document.getElementById('lmModelSeed')) lmModelSeed.value = r.seed ?? '';
  if (document.getElementById('lmModelFlashAttention')) lmModelFlashAttention.checked = r.flash_attention !== false;
  if (document.getElementById('lmModelKvGpu')) lmModelKvGpu.checked = r.offload_kv_cache_to_gpu !== false;
  if (document.getElementById('lmModelEchoLoadConfig')) lmModelEchoLoadConfig.checked = r.echo_load_config !== false;
}

function fillModelChunkingFields(extra) {
  const chunking = extra?.chunking || {};
  if (document.getElementById('modelDirectReadFraction')) modelDirectReadFraction.value = chunking.direct_read_fraction ?? '';
  if (document.getElementById('modelMinimumChunkTokens')) modelMinimumChunkTokens.value = chunking.minimum_chunk_tokens ?? '';
}

function collectLmStudioRuntimeFields() {
  const runtime = {
    context_length: numberOrNull(document.getElementById('lmModelContextLength')?.value),
    gpu_offload: numberOrNull(document.getElementById('lmModelGpuOffload')?.value),
    eval_batch_size: numberOrNull(document.getElementById('lmModelEvalBatch')?.value),
    temperature: numberOrNull(document.getElementById('lmModelTemperature')?.value),
    top_p: numberOrNull(document.getElementById('lmModelTopP')?.value),
    seed: numberOrNull(document.getElementById('lmModelSeed')?.value),
    flash_attention: !!document.getElementById('lmModelFlashAttention')?.checked,
    offload_kv_cache_to_gpu: !!document.getElementById('lmModelKvGpu')?.checked,
    echo_load_config: !!document.getElementById('lmModelEchoLoadConfig')?.checked,
  };
  Object.keys(runtime).forEach(k => { if (runtime[k] === null) delete runtime[k]; });
  return runtime;
}

function collectModelChunkingFields() {
  const chunking = {};
  const directReadFraction = numberOrNull(document.getElementById('modelDirectReadFraction')?.value);
  const minimumChunkTokens = numberOrNull(document.getElementById('modelMinimumChunkTokens')?.value);
  if (directReadFraction !== null) chunking.direct_read_fraction = directReadFraction;
  if (minimumChunkTokens !== null) chunking.minimum_chunk_tokens = minimumChunkTokens;
  return Object.keys(chunking).length ? chunking : null;
}

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

async function connectProviderFromForm() {
  await saveProviderFromForm();
  const name = providerName.value.trim();
  const r = await api(`/v1/providers/${name}/toggle`,{method:'POST', body:JSON.stringify({enabled:true})});
  await loadConfig();
  showInline('providerFormResult', r);
  if (r.synced_models?.length) showInline('modelFormResult', {provider:name, synced_models:r.synced_models, count:r.synced_models.length});
}

async function ensureModelSavedForLmStudio() {
  await saveModelFromForm();
  const name = modelName.value.trim();
  const provider = config.providers?.[modelProvider.value];
  if (!provider || provider.type !== 'lmstudio') throw new Error('This model is not backed by an LM Studio provider.');
  return name;
}

async function loadLmStudioModelByName(name) {
  const m = config.models?.[name];
  if (!m) throw new Error('Model not found');
  const runtime = m.extra?.lmstudio_runtime || {};
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/load`, {method:'POST', body:JSON.stringify({model:m.model, ...runtime})});
  showInline('modelFormResult', {model:name, lmstudio_load:r});
  await loadGlobalEvents(true).catch(()=>{});
  return r;
}

async function loadLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const runtime = collectLmStudioRuntimeFields();
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/load`, {method:'POST', body:JSON.stringify({model:modelId.value.trim(), ...runtime})});
  showInline('modelFormResult', {model:name, lmstudio_load:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio load requested' : 'LM Studio load failed');
  await loadGlobalEvents(true).catch(()=>{});
}

async function unloadLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const instance_id = prompt('Instance id / loaded model id to unload', modelId.value.trim() || name);
  if (!instance_id) return;
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id})});
  showInline('modelFormResult', {model:name, lmstudio_unload:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio unload requested' : 'LM Studio unload failed');
  await loadGlobalEvents(true).catch(()=>{});
}

async function inspectLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/inspect`);
  showInline('modelFormResult', {model:name, lmstudio:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio server reachable' : 'LM Studio inspect failed');
}

async function testModelFromForm() {
  await saveModelFromForm();
  const name = modelName.value.trim();
  const r = await api(`/v1/models/${name}/test`,{method:'POST'});
  showInline('modelFormResult', {model:name, ...r});
}
