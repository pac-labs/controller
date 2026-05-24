// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

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
