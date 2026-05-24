// Provider/model helper functions shared by provider, model, profile, and workspace UI modules.
function modelAvailability(name) {
  const m = config.models?.[name];
  if (!m) return {ok:false, reason:'not configured'};
  const p = config.providers?.[m.provider];
  if (!p) return {ok:false, reason:`missing provider ${m.provider}`};
  if (p.enabled === false || p.status === 'disabled' || p.status === 'failed') return {ok:false, reason:`provider ${p.status || 'disabled'}`};
  const live = p.cached_models || [];
  if (live.length) {
    const wanted = String(m.model || name);
    const ids = live.map(x => String(x.id || x.name || x.model || '')).filter(Boolean);
    if (!ids.includes(wanted)) return {ok:false, reason:`not returned by provider (${wanted})`};
  }
  return {ok:true, reason:'available'};
}

function providerIsSessionCapable(provider) {
  const type = String(provider?.type || '');
  return ['openai','openai-codex','openai-compatible','lmstudio','vllm','groq','openrouter','deepseek','mistral','ollama'].includes(type);
}

function csv(value) { return (value || '').split(',').map(x => x.trim()).filter(Boolean); }
function modelSummaryLine(model) {
  const bits = [];
  if (model.object) bits.push(model.object);
  if (model.owned_by) bits.push(`owner: ${model.owned_by}`);
  if (model.size) bits.push(`size: ${model.size}`);
  return bits.join(' · ');
}

function compactTokenNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return String(value || '-');
  if (n >= 1000000) return `${(n / 1000000).toFixed(n % 1000000 === 0 ? 0 : 1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k`;
  return String(n);
}
function modelPill(label, value='', tone='') {
  const text = value ? `${label}: ${value}` : label;
  return `<span class="pill model-info-pill ${escapeHtml(tone)}" title="${escapeHtml(text)}">${escapeHtml(text)}</span>`;
}
function modelStatusGlyph(ok) {
  return ok ? '●' : '▲';
}
function pricePill(label, value) {
  if (value === undefined || value === null || value === '') return '';
  return modelPill(label, `$${value}/1M`, 'price-pill');
}
function modelDisplayName(name, model) {
  return String(model?.display_name || model?.extra?.display_name || name || '').trim();
}
function modelStableId(name, model) {
  return String(model?.id || name || '').trim();
}
function newPacModelKey() {
  const id = (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `model-${id.replace(/[^a-zA-Z0-9-]/g, '')}`;
}
function modelLiveMetaPills(model) {
  const bits = [];
  if (model.object) bits.push(modelPill(model.object));
  if (model.owned_by) bits.push(modelPill('owner', model.owned_by));
  if (model.size) bits.push(modelPill('size', model.size));
  if (model.architecture) bits.push(modelPill('arch', model.architecture));
  if (model.quantization) bits.push(modelPill('quant', model.quantization));
  return bits.join('');
}
function modelCapabilityPills(model) {
  return [
    model.capabilities?.supports_chat ? ['chat', 'general chat and instruction following'] : null,
    model.capabilities?.supports_tools ? ['tools', 'function and tool invocation'] : null,
    model.capabilities?.supports_vision ? ['vision', 'image input'] : null,
    model.capabilities?.supports_json ? ['json', 'structured output'] : null,
    model.capabilities?.supports_streaming ? ['streaming', 'streaming output'] : null,
    model.capabilities?.reasoning && model.capabilities.reasoning !== 'none' ? [`reasoning ${model.capabilities.reasoning}`, 'reasoning-oriented model'] : null,
  ].filter(Boolean).map(([label, title]) => `<span class="pill model-cap-pill" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`).join('');
}
async function fetchProviderModels(name) {
  try { return await api(`/v1/providers/${name}/models`); }
  catch (e) { return {ok:false, error:e.message, models:[]}; }
}
function configuredModelMatchesProviderModel(providerName, modelId) {
  return !!findConfiguredModelByProviderModel(providerName, modelId);
}
function normalizedProviderModelCandidates(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return [];
  const clean = raw.replace(/\\/g, '/');
  const base = clean.includes('/') ? clean.split('/').pop() : clean;
  const compact = clean.replace(/[^a-z0-9]+/g, '');
  const baseCompact = base.replace(/[^a-z0-9]+/g, '');
  return Array.from(new Set([raw, clean, base, compact, baseCompact].filter(Boolean)));
}
function findConfiguredModelByProviderModel(providerName, modelId, excludeName='') {
  const candidates = new Set(normalizedProviderModelCandidates(modelId));
  return Object.entries(config.models || {}).find(([name, item]) => {
    if (excludeName && name === excludeName) return false;
    if (item.provider !== providerName) return false;
    const values = [
      name,
      item.model || '',
      providerModelKey(item.provider, item.model || ''),
      providerModelKey(item.provider, name),
    ];
    return values.some(value => normalizedProviderModelCandidates(value).some(candidate => candidates.has(candidate)));
  }) || null;
}

function providerLabel(providerName) {
  const provider = config.providers?.[providerName];
  return provider ? `${providerName} (${provider.type || 'provider'})` : providerName;
}
function sanitizeModelKeySegment(value) {
  return String(value || '').split('/').filter(Boolean).pop()?.replace(/[^a-zA-Z0-9_.-]+/g,'-').replace(/^-+|-+$/g,'').toLowerCase() || '';
}
function inferModelFunction(providerName, modelId) {
  const text = String(modelId || '').toLowerCase();
  if (text.includes('embed')) return 'embedding';
  if (text.includes('vision') || text.includes('vl') || text.includes('llava')) return 'vision';
  if (text.includes('reason')) return 'reasoning';
  if (text.includes('coder') || text.includes('code')) return 'coding';
  return 'general';
}
function providerModelKey(providerName, modelId, modelFunction='') {
  const prefix = (modelFunction && modelFunction !== 'general') ? modelFunction : providerName;
  const suffix = sanitizeModelKeySegment(modelId);
  return `${sanitizeModelKeySegment(prefix)}/${suffix}`.replace(/^\/+|\/+$/g,'');
}
function syncSuggestedModelKey(force=false) {
  if (!modelName) return;
  const provider = modelProvider?.value || '';
  const modelIdValue = modelId?.value || '';
  const modelFunction = document.getElementById('modelFunction')?.value || 'general';
  if (!provider || !modelIdValue) return;
  const suggested = providerModelKey(provider, modelIdValue, modelFunction);
  if (force || !modelName.value.trim() || modelName.dataset.auto === 'true') {
    modelName.value = suggested;
    modelName.dataset.auto = 'true';
  }
}
function openModelDraft(providerName, providerModelId, source='provider') {
  openModelModal();
  const providerDisplay = document.getElementById('modelProviderDisplay'); if (providerDisplay) providerDisplay.textContent = providerName;
  const providerSelect = document.getElementById('modelProvider'); if (providerSelect) providerSelect.value = providerName;
  modelId.value = providerModelId;
  const manualOverride = document.getElementById('modelManualIdOverride'); if (manualOverride) manualOverride.checked = false;
  if (typeof setModelIdSource === 'function') setModelIdSource(source, providerName || 'selected model');
  const modelFunction = document.getElementById('modelFunction');
  if (modelFunction) modelFunction.value = inferModelFunction(providerName, providerModelId);
  modelName.value = providerModelKey(providerName, providerModelId, modelFunction?.value || 'general') || sanitizeModelKeySegment(providerModelId);
  modelName.dataset.auto = 'true';
  modelRunsOn.value = '';
  fillModelChunkingFields({});
  refreshModelProviderCandidates(providerName).catch(()=>{});
  setModalStatus('modelModalStatus', 'Provider model ID was selected from discovery. Review PAC-specific settings and save.');
}
