// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

function fillProviderForm(name) {
  const p = config.providers?.[name]; if (!p) return;
  if (document.getElementById('providerPreset')) providerPreset.value='';
  providerName.value = name; providerType.value = p.type || 'openai-compatible'; providerBaseUrl.value = p.base_url || '';
  providerApiKeyEnv.value = p.api_key_env || ''; providerApiKey.value = p.api_key || ''; providerTimeout.value = p.timeout_seconds || 30; fillProviderRuntimeFields(p.runtime || {});
}
// Split from profiles_config.js during the pass20 UI cleanup.
// Kept as classic-script globals for existing inline handlers and boot wiring.

async function connectProviderFromForm() {
  await saveProviderFromForm();
  const name = providerName.value.trim();
  const r = await api(`/v1/providers/${name}/toggle`,{method:'POST', body:JSON.stringify({enabled:true})});
  await loadConfig();
  showInline('providerFormResult', r);
  if (r.synced_models?.length) showInline('modelFormResult', {provider:name, synced_models:r.synced_models, count:r.synced_models.length});
}
