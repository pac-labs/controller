// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

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
