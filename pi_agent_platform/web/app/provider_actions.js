// Provider and LM Studio action handlers.
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
