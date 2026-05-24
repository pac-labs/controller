// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

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
