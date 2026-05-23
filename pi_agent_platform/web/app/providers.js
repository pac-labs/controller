// Provider and model catalog rendering helpers.
// Split from app.js in PAC v1.0.279 to keep the main UI bootstrap smaller.

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
function providerStatus(p) {
  if (p.enabled === false) return 'disabled';
  return p.status || 'unknown';
}
function providerStatusClass(status) {
  if (status === 'connected') return 'ok';
  if (status === 'failed') return 'failed';
  if (status === 'disabled') return '';
  return 'attention';
}
async function toggleProvider(name, enabled) {
  await api(`/v1/providers/${name}/toggle`, {method:'POST', body:JSON.stringify({enabled})});
  await loadConfig();
  const el = document.getElementById('providerFormResult');
  if (el) el.textContent = '';
}
async function deleteProvider(name) {
  if (!confirm(`Delete provider '${name}'? Models using this provider will also be removed.`)) return;
  await api(`/v1/providers/${name}`, {method:'DELETE'});
  await loadConfig();
  showInline('providerFormResult', `Deleted provider ${name}`);
}
async function inspectLmStudioProvider(name) {
  const r = await api(`/v1/providers/${name}/lmstudio/inspect`);
  showInline('providerFormResult', r);
  await loadConfig();
}
async function showLmStudioCompanionScript(name) {
  const r = await api(`/v1/providers/${name}/lmstudio/companion-script`);
  const text = r.script || '';
  const blob = new Blob([text], {type:'text/x-python'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `pac-lmstudio-companion-${name}.py`; a.click();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
  showInline('providerFormResult', `Companion script generated for ${name}. Run it manually on the LM Studio host.`);
}
async function lmStudioLoadModel(name) {
  const model = prompt('Model id to load, for example openai/gpt-oss-20b');
  if (!model) return;
  const context = prompt('Context length', '16384');
  const r = await api(`/v1/providers/${name}/lmstudio/load`, {method:'POST', body:JSON.stringify({model, context_length:Number(context||0)||undefined, flash_attention:true, echo_load_config:true})});
  showInline('providerFormResult', r);
  await loadConfig();
}
async function lmStudioUnloadModel(name) {
  const instance_id = prompt('Instance id / loaded model id to unload');
  if (!instance_id) return;
  const r = await api(`/v1/providers/${name}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id})});
  showInline('providerFormResult', r);
  await loadConfig();
}
async function lmStudioDownloadModel(name) {
  const model = prompt('Model id to download, for example ibm/granite-4-micro');
  if (!model) return;
  const r = await api(`/v1/providers/${name}/lmstudio/download`, {method:'POST', body:JSON.stringify({model})});
  showInline('providerFormResult', r);
}

function providerRuntime(p) { return p?.runtime || {}; }
function providerDevice(p) { return providerRuntime(p).device || {}; }
function providerHost(p) { return providerRuntime(p).host || {}; }
function fmtProviderDevice(p) {
  const d = providerDevice(p);
  const bits = [d.category || 'unknown'];
  if (d.vendor) bits.push(d.vendor);
  if (d.model) bits.push(d.model);
  if (d.memory_gb || d.memoryGB) bits.push(`${d.memory_gb || d.memoryGB}GB`);
  if (d.shared) bits.push('shared');
  return bits.filter(Boolean).join(' · ');
}
function providerCapabilityPills(p) {
  const r = providerRuntime(p), d = r.device || {}, h = r.host || {};
  const accelerators = Array.isArray(r.accelerators) ? r.accelerators : [];
  const pills = [r.execution_type || r.executionType || 'unknown', d.category || 'unknown-device', h.kind || 'unknown-host', ...accelerators].filter(Boolean);
  return pills.map(x => `<span class="pill provider-capability-pill">${escapeHtml(String(x))}</span>`).join('');
}
function providerHealthSummary(name, provider) {
  const health = providerHealthCache.get(name) || {};
  const inspect = health.inspect || {};
  const models = Array.isArray(health.models) ? health.models : [];
  if (provider?.enabled === false) return {pill:'disabled', klass:'warn-pill', detail:'Provider disabled'};
  if (health.ok === true) {
    const bits = [`${models.length} live model${models.length === 1 ? '' : 's'}`];
    if (provider?.type === 'lmstudio' && inspect.ok) bits.push('LM Studio responding');
    return {pill:'healthy', klass:'ok-pill', detail:bits.join(' · ')};
  }
  if (health.ok === false) {
    const reason = health.error || health.response?.error || inspect.error || provider?.last_error || 'provider check failed';
    return {pill:'failed', klass:'danger-pill', detail:reason};
  }
  return {pill:'checking', klass:'ghost-pill', detail:'Checking provider health…'};
}
async function refreshProviderHealth(name, provider) {
  try {
    const health = await api(`/v1/providers/${encodeURIComponent(name)}/test`, {method:'POST'});
    let inspect = null;
    if (provider?.type === 'lmstudio') inspect = await api(`/v1/providers/${encodeURIComponent(name)}/lmstudio/inspect`).catch(()=>null);
    providerHealthCache.set(name, {...health, inspect, checked_at:new Date().toISOString()});
  } catch (error) {
    providerHealthCache.set(name, {ok:false, error:error.message || String(error), checked_at:new Date().toISOString()});
  }
  renderProviders();
  renderModels();
}
function collectProviderRuntimeFields(existing={}) {
  const mem = Number(document.getElementById('providerDeviceMemory')?.value || 0);
  return {
    ...(existing || {}),
    execution_type: document.getElementById('providerExecutionType')?.value || 'unknown',
    provider_class: document.getElementById('providerClass')?.value.trim() || null,
    device: {
      ...((existing || {}).device || {}),
      category: document.getElementById('providerDeviceCategory')?.value || 'unknown',
      vendor: document.getElementById('providerDeviceVendor')?.value.trim() || null,
      model: document.getElementById('providerDeviceModel')?.value.trim() || null,
      memory_gb: mem || null,
      shared: !!document.getElementById('providerDeviceShared')?.checked,
    },
    host: {
      ...((existing || {}).host || {}),
      kind: document.getElementById('providerHostKind')?.value || 'unknown',
      os: document.getElementById('providerHostOs')?.value.trim() || null,
      arch: document.getElementById('providerHostArch')?.value.trim() || null,
    },
    accelerators: (document.getElementById('providerAccelerators')?.value || '').split(',').map(x=>x.trim()).filter(Boolean),
  };
}
function fillProviderRuntimeFields(runtime={}) {
  const d = runtime.device || {}, h = runtime.host || {};
  const set = (id, val) => { const el=document.getElementById(id); if (el) el.value = val ?? ''; };
  set('providerExecutionType', runtime.execution_type || runtime.executionType || 'unknown');
  set('providerClass', runtime.provider_class || runtime.providerClass || '');
  set('providerDeviceCategory', d.category || 'unknown');
  set('providerDeviceVendor', d.vendor || '');
  set('providerDeviceModel', d.model || '');
  set('providerDeviceMemory', d.memory_gb || d.memoryGB || '');
  const shared = document.getElementById('providerDeviceShared'); if (shared) shared.checked = !!d.shared;
  set('providerHostKind', h.kind || 'unknown');
  set('providerHostOs', h.os || '');
  set('providerHostArch', h.arch || '');
  set('providerAccelerators', Array.isArray(runtime.accelerators) ? runtime.accelerators.join(', ') : '');
}

function renderProviders() {
  const el = document.getElementById('providers'); if (!el) return; el.innerHTML = '';
  const entries = Object.entries(config.providers || {});
  if (!entries.length) {
    el.innerHTML = '<div class="empty-events">No providers configured yet.</div>';
    const live = document.getElementById('providersLive');
    if (live) live.innerHTML = '<div class="muted small-text">No providers configured.</div>';
    return;
  }
  for (const [name,p] of entries) {
    const status = providerStatus(p);
    const r = providerRuntime(p);
    const h = providerHost(p);
    const health = providerHealthSummary(name, p);
    const card = document.createElement('div'); card.className='provider-card';
    card.innerHTML = `
      <div class="provider-card-head">
        <div class="provider-title-block"><h3>${escapeHtml(name)}</h3><span class="muted">${escapeHtml(p.type || 'provider')}</span></div>
        <span class="pill ${providerStatusClass(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="provider-health-strip"><span class="pill ${escapeHtml(health.klass)}">${escapeHtml(health.pill)}</span><span class="small-text">${escapeHtml(health.detail)}</span></div>
      <div class="provider-device-panel">
        <b>${escapeHtml(fmtProviderDevice(p))}</b>
        <small>${escapeHtml(r.execution_type || r.executionType || 'unknown')} inference · ${escapeHtml(h.kind || 'unknown host')}${h.os ? ` · ${escapeHtml(h.os)}` : ''}${h.arch ? ` · ${escapeHtml(h.arch)}` : ''}</small>
      </div>
      <div class="provider-meta-line"><span>${escapeHtml(p.base_url || 'no base URL')}</span></div>
      <div class="provider-pill-list">${providerCapabilityPills(p)}</div>
      ${p.last_error ? `<div class="failed-text small-text">${escapeHtml(p.last_error)}</div>` : ''}
      <div class="remote-models muted" id="providerModels_${name}">${p.enabled === false ? 'provider disabled' : 'checking endpoint…'}</div>`;
    const actions = document.createElement('div'); actions.className='provider-actions button-row';
    const label = document.createElement('label'); label.className='switch'; label.title='Connect/disconnect provider';
    const input = document.createElement('input'); input.type='checkbox'; input.checked = p.enabled !== false && status === 'connected';
    const slider = document.createElement('span'); slider.className='switch-slider';
    input.onchange = async(ev)=>{ ev.stopPropagation(); input.disabled=true; try { await toggleProvider(name, input.checked); } catch(e){ alert(e.message); input.checked=false; } finally { input.disabled=false; } };
    label.appendChild(input); label.appendChild(slider);
    const probe=document.createElement('button'); probe.textContent='Check health'; probe.className='ghost-button'; probe.onclick=(ev)=>{ ev.stopPropagation(); refreshProviderHealth(name, p).catch(e=>alert(e.message)); };
    if (p.type === 'lmstudio') {
      const inspect=document.createElement('button'); inspect.textContent='Inspect'; inspect.className='ghost-button'; inspect.onclick=(ev)=>{ ev.stopPropagation(); inspectLmStudioProvider(name).catch(e=>alert(e.message)); };
      const script=document.createElement('button'); script.textContent='Companion'; script.className='ghost-button'; script.onclick=(ev)=>{ ev.stopPropagation(); showLmStudioCompanionScript(name).catch(e=>alert(e.message)); };
      const load=document.createElement('button'); load.textContent='Load'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); lmStudioLoadModel(name).catch(e=>alert(e.message)); };
      actions.appendChild(probe); actions.appendChild(inspect); actions.appendChild(script); actions.appendChild(load);
    } else {
      actions.appendChild(probe);
    }
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.onclick=(ev)=>{ ev.stopPropagation(); openProviderModal(name); };
    const del=document.createElement('button'); del.textContent='Delete'; del.className='danger-button'; del.onclick=(ev)=>{ ev.stopPropagation(); deleteProvider(name).catch(e=>alert(e.message)); };
    actions.appendChild(label); actions.appendChild(edit); actions.appendChild(del); card.appendChild(actions); el.appendChild(card);
    if (p.enabled !== false) {
      refreshProviderModelPreview(name).catch(()=>{});
      if (!providerHealthCache.has(name)) refreshProviderHealth(name, p).catch(()=>{});
    }
  }
  renderProvidersLivePanel().catch(()=>{});
}
async function refreshProviderModelPreview(name) {
  const target = document.getElementById(`providerModels_${name}`);
  if (!target) return;
  const result = await fetchProviderModels(name);
  if (!result.ok) { target.textContent = `model list unavailable: ${result.error || result.response?.error || 'unknown error'}`; return; }
  const models = result.models || [];
  target.textContent = models.length ? `server models: ${models.slice(0,5).map(m => m.id || m.name).join(', ')}${models.length > 5 ? ` +${models.length-5} more` : ''}` : 'server returned no models';
}
function renderModels() {
  const el = document.getElementById('models'); if (!el) return; el.innerHTML = '';
  const configured = document.createElement('div');
  configured.innerHTML = '<h3>Configured models</h3>';
  for (const [name,m] of Object.entries(config.models || {})) {
    const wrap=document.createElement('div'); wrap.className='model-card clickable-row';
    { const av = modelAvailability(name); wrap.innerHTML = `<code>${modelDisplayName(name,m)} ${av.ok ? '' : '[not available]'}\nPAC id: ${modelStableId(name,m)}\nprovider: ${m.provider}\nmodel id: ${m.model || '-'}\nexecution endpoint: ${endpointName(m.runs_on)}\ncontext: ${m.context_window}\nmax out: ${m.max_output_tokens}${av.ok ? '' : `\nreason: ${av.reason}`}</code>`; }
    wrap.onclick=()=>openModelModal(name);
    const actions=document.createElement('div'); actions.className='button-row';
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.onclick=(ev)=>{ ev.stopPropagation(); openModelModal(name); };
    const b=document.createElement('button'); b.textContent='Test model'; b.className='ghost-button'; b.onclick=async(ev)=>{ ev.stopPropagation(); const r=await api(`/v1/models/${name}/test`,{method:'POST'}); showInline('modelFormResult', {model:name, ...r}); };
    actions.appendChild(edit); actions.appendChild(b);
    const provider = config.providers?.[m.provider || ''];
    if (provider?.type === 'lmstudio') {
      const load=document.createElement('button'); load.textContent='Load in LM Studio'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); loadLmStudioModelByName(name).catch(e=>alert(e.message)); };
      actions.appendChild(load);
    }
    wrap.appendChild(actions); configured.appendChild(wrap);
  }
  el.appendChild(configured);
  const live = document.createElement('div');
  live.innerHTML = `<h3>Live server models</h3><div id="modelsLive" class="remote-models">${pacLoadingLineHtml('Loading live model lists…')}</div>`;
  el.appendChild(live);
  renderLiveModels().catch(()=>{});
}
async function renderLiveModels() {
  const live = document.getElementById('modelsLive');
  if (!live) return;
  const providers = Object.keys(config.providers || {});
  if (!providers.length) { live.textContent = 'No providers configured.'; return; }
  const chunks = [];
  for (const name of providers) {
    const result = await fetchProviderModels(name);
    if (!result.ok) { chunks.push(`<div class="remote-provider failed"><b>${name}</b><br><span>${result.error || result.response?.error || 'model listing failed'}</span></div>`); continue; }
    const models = result.models || [];
    const rows = models.map(m => {
      const id = m.id || m.name;
      const key = providerModelKey(name, id, inferModelFunction(name, id));
      const configured = !!config.models?.[key] || Object.values(config.models || {}).some(x => x.provider === name && (x.model || '') === id);
      return `<li><button class="link-button" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${escapeHtml(id)}</button><button class="ghost-button mini-button" data-add-live-model="1" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${configured ? 'Edit' : 'Configure'}</button><span class="muted">${escapeHtml(modelSummaryLine(m))}</span></li>`;
    }).join('');
    chunks.push(`<div class="remote-provider"><b>${escapeHtml(name)}</b> <span class="pill ${models.length ? 'ok' : ''}">${models.length} models</span><ul>${rows || '<li class="muted">No models returned</li>'}</ul></div>`);
  }
  live.innerHTML = chunks.join('');
  live.querySelectorAll('button[data-model]').forEach(btn => {
    btn.onclick = () => {
      const providerDisplay = document.getElementById('modelProviderDisplay'); if (providerDisplay) providerDisplay.textContent = btn.dataset.provider;
      const providerSelect = document.getElementById('modelProvider'); if (providerSelect) providerSelect.value = btn.dataset.provider;
      modelId.value = btn.dataset.model;
      const modelFunction = document.getElementById('modelFunction');
      if (modelFunction) modelFunction.value = inferModelFunction(btn.dataset.provider, btn.dataset.model);
      modelName.value = btn.dataset.key || providerModelKey(btn.dataset.provider, btn.dataset.model, modelFunction?.value || 'general');
      modelName.dataset.auto = 'true';
      modelRunsOn.value = '';
    };
  });
  live.querySelectorAll('button[data-add-live-model]').forEach(btn => {
    btn.onclick = async () => {
      openModelDraft(btn.dataset.provider, btn.dataset.model);
    };
  });
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
async function inspectLmStudioModelByName(name) {
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/inspect`);
  showInline('modelFormResult', {model:name, lmstudio:r});
  return r;
}
async function unloadLmStudioModelByName(name) {
  const model = config.models?.[name];
  if (!model) throw new Error('Model not found');
  const instanceId = prompt('Instance id / loaded model id to unload', model.model || name);
  if (!instanceId) return null;
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id: instanceId})});
  showInline('modelFormResult', {model:name, lmstudio_unload:r});
  await loadGlobalEvents(true).catch(()=>{});
  return r;
}
function recommendationCardHtml(level, title, body, detail = '') {
  return `<article class="recommendation-card compact ${escapeHtml(level)}"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(body)}</p>${detail ? `<div class="muted small-text">${escapeHtml(detail)}</div>` : ''}</article>`;
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
function renderModelRecommendations() {
  const panel = document.getElementById('modelsRecommendationsPanel');
  const body = document.getElementById('modelsRecommendationsBody');
  if (!panel || !body) return;
  const recommendations = [];
  const models = Object.entries(config.models || {});
  const endpoints = window.__pacEndpoints || [];
  const sessions = window.__pacSessions || [];
  if (!models.length) {
    const enabledProviders = Object.entries(config.providers || {}).filter(([_, provider]) => provider.enabled !== false);
    if (enabledProviders.length) recommendations.push(recommendationCardHtml('info', 'No configured session models', 'Create at least one model from the live provider inventory so profiles and sessions can use it.', 'Use Browse providers or Marketplace from the Models area.'));
  }
  for (const [name, model] of models) {
    const availability = modelAvailability(name);
    const provider = config.providers?.[model.provider || ''];
    const endpoint = endpoints.find(item => item.id === model.runs_on);
    const sessionCount = sessions.filter(item => item.model === name).length;
    if (!availability.ok) recommendations.push(recommendationCardHtml('warn', `${name} is not currently available`, availability.reason || 'The provider is not returning this model.', `${providerLabel(model.provider || '-')}${sessionCount ? ` - ${sessionCount} session(s) reference it` : ''}`));
    if (provider?.type === 'lmstudio') {
      const runtime = model.extra?.lmstudio_runtime || {};
      if (!runtime.gpu_offload && (endpoint?.capabilities?.gpu?.available || endpoint?.capabilities?.gpu?.devices?.length)) recommendations.push(recommendationCardHtml('info', `Tune ${name} for GPU use`, 'A GPU-capable endpoint is available, but the LM Studio runtime fields are still mostly default.', 'Review GPU offload, context, and batch sizing in the model form.'));
      if (runtime.context_length && model.context_window && Number(runtime.context_length) < Number(model.context_window)) recommendations.push(recommendationCardHtml('warn', `LM Studio load window is shorter for ${name}`, 'PAC is configured to expect a larger context window than the LM Studio runtime will load.', 'Raise the runtime context length or lower the configured model context to keep behavior consistent.'));
      if (!runtime.context_length && model.context_window) recommendations.push(recommendationCardHtml('info', `Set an explicit LM Studio load window for ${name}`, 'The model has a configured PAC context window, but the LM Studio load runtime still relies on implicit defaults.', 'Set the runtime context length so load behavior is predictable.'));
    }
  }
  const liveProviderModels = Object.entries(config.providers || {}).reduce((count, [providerName, provider]) => count + ((provider.cached_models || []).filter(model => !configuredModelMatchesProviderModel(providerName, model.id || model.name || model.model)).length), 0);
  if (liveProviderModels > 0) recommendations.push(recommendationCardHtml('info', 'Additional provider models are available', `${liveProviderModels} live model(s) are visible from connected providers but not configured in PAC yet.`, 'Browse providers to promote them into session models.'));
  const visible = recommendations.slice(0, 4);
  const hiddenCount = Math.max(0, recommendations.length - visible.length);
  body.innerHTML = (visible.join('') || '<div class="muted small-text">No adaptation recommendations right now.</div>') + (hiddenCount ? `<div class="muted small-text recommendation-summary">+ ${hiddenCount} more recommendation(s). Resolve current issues to reduce this list.</div>` : '');
  panel.hidden = false;
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
  const workspaces = Object.entries(config.workspaces || {});
  if (!workspaces.length) {
    target.innerHTML = '<div class="muted small-text">No workspaces configured.</div>';
    return;
  }
  target.innerHTML = workspaces.map(([name, workspace]) => {
    const count = sessions.filter(session => {
      const path = String(session.workspace_path || '');
      return path === String(workspace.path || '') || path.includes(name);
    }).length;
    const placement = workspace.endpoint_id || workspace.endpoint_selector || 'runtime';
    return `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${escapeHtml(workspace.type || 'local')} - ${escapeHtml(placement)}</div></div><span class="pill">${count} session(s)</span></div>`;
  }).join('');
}
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
  renderModelRecommendations();
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

