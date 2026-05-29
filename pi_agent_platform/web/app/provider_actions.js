// Provider and LM Studio action handlers.

async function discoverLocalProviders() {
  const panel = document.getElementById('localProviderDiscovery') || document.getElementById('providerFormResult');
  if (panel) panel.innerHTML = '<div class="muted small-text">Checking common LM Studio endpoints…</div>';
  const result = await api('/v1/local-inference/lmstudio/discover');
  const candidates = result.candidates || [];
  if (!panel) return result;
  if (!candidates.length) {
    panel.innerHTML = '<div class="muted small-text">No LM Studio endpoints were checked.</div>';
    return result;
  }
  panel.innerHTML = `<section class="card inset-panel"><div class="section-heading compact-heading"><div><h3>Detected local inference</h3><p class="muted small-text">PAC checks LM Studio as an external local provider. Register a healthy endpoint to use zero-cost local inference.</p></div><span class="pill ${result.ok ? 'ok-pill' : 'warn-pill'}">${result.ok ? 'found' : 'not found'}</span></div>${candidates.map((item, index) => {
    const models = item.models || [];
    const summary = item.ok ? `${models.length} model${models.length === 1 ? '' : 's'} · ${models.slice(0,3).map(m => m.id || m.name).join(', ') || 'no models returned'}` : (item.error || 'not reachable');
    return `<div class="inline-browser-row"><div><b>${escapeHtml(item.openai_base_url || item.base_url)}</b><div class="muted small-text">${escapeHtml(summary)} · ${escapeHtml(item.source || 'probe')} · ${escapeHtml(String(item.response_ms ?? '-'))} ms</div></div><div class="button-row inline-browser-group">${item.ok ? `<button class="mini-button" data-register-lmstudio="${index}">Register</button>` : `<button class="ghost-button mini-button" data-health-lmstudio="${index}">Check</button>`}</div></div>`;
  }).join('')}</section>`;
  panel.querySelectorAll('[data-register-lmstudio]').forEach(btn => {
    btn.onclick = async () => {
      const item = candidates[Number(btn.dataset.registerLmstudio || 0)];
      const name = prompt('Provider name', 'lmstudio');
      if (name === null) return;
      const registered = await api('/v1/local-inference/lmstudio/register', {method:'POST', body:JSON.stringify({name:name || 'lmstudio', base_url:item.base_url || item.openai_base_url, enabled:true, create_models:true})});
      showInline('providerFormResult', registered);
      await loadConfig();
      await discoverLocalProviders().catch(()=>{});
    };
  });
  panel.querySelectorAll('[data-health-lmstudio]').forEach(btn => {
    btn.onclick = async () => {
      const item = candidates[Number(btn.dataset.healthLmstudio || 0)];
      const checked = await api('/v1/local-inference/lmstudio/health', {method:'POST', body:JSON.stringify({base_url:item.base_url || item.openai_base_url})});
      showInline('providerFormResult', checked);
    };
  });
  return result;
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
