function hideSetupWizard() {
  const modal = document.getElementById('setupWizard');
  if (modal) modal.hidden = true;
}
function openSetupWizard() {
  const modal = document.getElementById('setupWizard');
  if (modal) modal.hidden = false;
}
function setupWizardIssue(id) {
  return (setupStatus?.required_issues || []).find(issue => issue.id === id) || null;
}
function setupWizardHasIssue(id) {
  return !!setupWizardIssue(id);
}
function setupWizardProviderNames() {
  return Object.keys(config?.providers || {});
}
function setupWizardModelNames() {
  return Object.keys(config?.models || {});
}
function setupWizardProfileNames() {
  return Object.keys(config?.agent_profiles || {});
}
function setupWizardPermissionNames() {
  return Object.keys(config?.permission_profiles || {});
}
function setupWizardStatusMessage(message, tone='') {
  const cls = tone === 'warn' ? 'warn-text' : tone === 'ok' ? 'ok-text' : 'muted';
  return `<div id="setupWizardStepResult" class="inline-result ${cls}">${escapeHtml(message || '')}</div>`;
}
function setupWizardConnectionHtml() {
  const showToken = !!(config?.auth?.enabled && config?.auth?.mode === 'dev-token');
  return `<div class="stacked-output">
    <div class="pack-summary strong-summary">Configure how endpoints and agents connect back to this PAC controller.</div>
    <label>Controller public URL<input id="setupPublicUrl" value="${escapeHtml(config?.server?.public_url || '')}" placeholder="https://pac.example.com:8444" /></label>
    <label class="checkbox-row"><input id="setupMdnsEnabled" type="checkbox" ${config?.mdns?.enabled !== false ? 'checked' : ''}/> Advertise this controller over mDNS when possible</label>
    ${showToken ? `<label>Dev bearer token<input id="setupDevToken" value="${escapeHtml(config?.auth?.dev_token || '')}" placeholder="replace change-me" /></label><div class="muted small-text">Only shown because PAC is currently using dev-token mode.</div>` : ''}
    ${setupWizardIssue('dev_token_default') ? '<div class="pack-summary warn-summary"><b>Security warning</b><div class="muted small-text">The default bearer token is still in use. Replace it before exposing PAC broadly.</div></div>' : ''}
    ${setupWizardStatusMessage('')}
  </div>`;
}
function setupWizardProviderHtml() {
  const providers = setupWizardProviderNames();
  const first = providers[0] || '';
  return `<div class="stacked-output">
    <div class="pack-summary strong-summary">Add or adjust one provider PAC can use for agent-backed sessions.</div>
    <label>Existing provider<select id="setupProviderExisting"><option value="">New provider</option>${providers.map(name => `<option value="${escapeHtml(name)}" ${name === first ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
    <label>Provider name<input id="setupProviderName" value="${escapeHtml(first)}" placeholder="m5" /></label>
    <label>Provider type<select id="setupProviderType">
      ${['lmstudio','openai','openai-codex','openai-compatible','anthropic','anthropic-compatible','minimax','gemini','ollama','vllm','groq','openrouter','deepseek','mistral','cohere'].map(name => `<option value="${name}">${name}</option>`).join('')}
    </select></label>
    <label>Base URL<input id="setupProviderBaseUrl" placeholder="http://host:1234/v1" /></label>
    <div class="two-column-grid">
      <label>API key env<input id="setupProviderApiKeyEnv" placeholder="OPENAI_API_KEY" /></label>
      <label>API key<input id="setupProviderApiKey" placeholder="optional" /></label>
    </div>
    <label class="checkbox-row"><input id="setupProviderEnabled" type="checkbox" checked /> Enable this provider for use</label>
    <div class="button-row"><button id="setupProviderTest" type="button" class="ghost-button">Test provider</button></div>
    ${setupWizardStatusMessage('')}
  </div>`;
}
function setupWizardModelHtml() {
  const models = setupWizardModelNames();
  const providers = setupWizardProviderNames();
  const profiles = setupWizardProfileNames();
  const firstModel = models[0] || '';
  return `<div class="stacked-output">
    <div class="pack-summary strong-summary">Configure at least one session-capable model PAC can run through a provider.</div>
    <label>Existing model<select id="setupModelExisting"><option value="">New model</option>${models.map(name => `<option value="${escapeHtml(name)}" ${name === firstModel ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
    <label>PAC model key<input id="setupModelName" value="${escapeHtml(firstModel)}" placeholder="coding/glm-4.7-flash" /></label>
    <div class="two-column-grid">
      <label>Function<input id="setupModelFunction" value="general" placeholder="coding / planner / explainer" /></label>
      <label>Provider<select id="setupModelProvider"><option value="">Select provider</option>${providers.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('')}</select></label>
    </div>
    <label>Provider model ID<input id="setupModelId" placeholder="zai-org/glm-4.7-flash" /></label>
    <div class="two-column-grid">
      <label>Context window<input id="setupModelContext" type="number" value="32768" /></label>
      <label>Max output tokens<input id="setupModelOutput" type="number" value="4096" /></label>
    </div>
    <div class="two-column-grid">
      <label class="checkbox-row"><input id="setupModelChat" type="checkbox" checked /> Chat</label>
      <label class="checkbox-row"><input id="setupModelTools" type="checkbox" /> Tool use</label>
      <label class="checkbox-row"><input id="setupModelJson" type="checkbox" /> JSON output</label>
      <label class="checkbox-row"><input id="setupModelStreaming" type="checkbox" checked /> Streaming</label>
    </div>
    ${profiles.length ? `<div class="muted small-text">This model can later be assigned to one or more agent profiles for coding, planning, or explanation work.</div>` : ''}
    ${setupWizardStatusMessage('')}
  </div>`;
}
function setupWizardControllerHtml() {
  const models = setupWizardModelNames();
  const profiles = setupWizardProfileNames();
  const perms = setupWizardPermissionNames();
  const h = config?.controller_harness || {};
  return `<div class="stacked-output">
    <div class="pack-summary strong-summary">Configure the built-in PAC controller session and local wrapper runtime.</div>
    <label class="checkbox-row"><input id="setupHarnessEnabled" type="checkbox" ${h.enabled !== false ? 'checked' : ''}/> Enable controller pi.dev</label>
    <div class="two-column-grid">
      <label>Controller model<select id="setupHarnessModel"><option value="">profile default</option>${models.map(name => `<option value="${escapeHtml(name)}" ${name === (h.model || '') ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
      <label>Agent profile<select id="setupHarnessProfile"><option value="">none</option>${profiles.map(name => `<option value="${escapeHtml(name)}" ${name === (h.agent_profile || '') ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
    </div>
    <div class="two-column-grid">
      <label>Permission profile<select id="setupHarnessPermission">${perms.map(name => `<option value="${escapeHtml(name)}" ${name === (h.permission_profile || 'ask-first') ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select></label>
      <label>Workspace profile<input id="setupHarnessWorkspace" value="${escapeHtml(h.workspace_profile || 'agent-control')}" /></label>
    </div>
    <label>Runner ID<input id="setupHarnessRunner" value="${escapeHtml(h.runner_id || 'local-PAC')}" /></label>
    <div class="button-row">
      <button id="setupHarnessUpdateWrapper" type="button" class="ghost-button">Update wrapper</button>
      <button id="setupHarnessBootstrap" type="button" class="ghost-button">Bootstrap pi.dev</button>
    </div>
    ${setupWizardStatusMessage('')}
  </div>`;
}
function setupWizardReviewHtml() {
  const issues = setupStatus?.required_issues || [];
  const warnings = setupStatus?.warnings || [];
  const issueRows = issues.length
    ? issues.map(issue => `<div class="pack-summary warn-summary"><b>${escapeHtml(issue.title || 'Configuration required')}</b><div class="muted small-text">${escapeHtml(issue.detail || '')}</div></div>`).join('')
    : '<div class="pack-summary strong-summary">All required setup items are complete.</div>';
  const warningRows = warnings.length
    ? `<div class="muted small-text"><b>Warnings</b></div>${warnings.map(issue => `<div class="pack-summary"><b>${escapeHtml(issue.title || 'Warning')}</b><div class="muted small-text">${escapeHtml(issue.detail || '')}</div></div>`).join('')}`
    : '';
  return `<div class="stacked-output">
    ${issueRows}
    ${warningRows}
    ${setupWizardStatusMessage('Recheck setup after saving the previous steps.')}
  </div>`;
}
function buildSetupWizardSteps() {
  const allSteps = {
    overview: {id:'overview', label:'Remaining', title:'What still needs setup', render:setupWizardOverviewHtml, save:async()=>{}},
    connection: {id:'connection', label:'Connection', title:'Controller connection', render:setupWizardConnectionHtml, save:saveSetupWizardConnectionStep},
    provider: {id:'provider', label:'Provider', title:'Model provider', render:setupWizardProviderHtml, save:saveSetupWizardProviderStep},
    model: {id:'model', label:'Model', title:'Session model', render:setupWizardModelHtml, save:saveSetupWizardModelStep},
    controller: {id:'controller', label:'pi.dev', title:'Controller pi.dev', render:setupWizardControllerHtml, save:saveSetupWizardControllerStep},
    review: {id:'review', label:'Review', title:'Review and finish', render:setupWizardReviewHtml, save:async()=>{}},
  };
  return setupWizardNeededStepIds().map(id => allSteps[id]).filter(Boolean);
}
function setupWizardStepResult(message, tone='') {
  const el = document.getElementById('setupWizardStepResult');
  if (!el) return;
  el.textContent = message || '';
  el.className = `inline-result ${tone === 'warn' ? 'warn-text' : tone === 'ok' ? 'ok-text' : 'muted'}`;
}
function setupWizardLoadProviderIntoStep(name) {
  const p = (config?.providers || {})[name] || {};
  const preset = Object.entries(PROVIDER_PRESETS).find(([, item]) => item.type === p.type)?.[0] || 'custom-openai';
  const typeEl = document.getElementById('setupProviderType');
  const nameEl = document.getElementById('setupProviderName');
  const urlEl = document.getElementById('setupProviderBaseUrl');
  const envEl = document.getElementById('setupProviderApiKeyEnv');
  const keyEl = document.getElementById('setupProviderApiKey');
  const enabledEl = document.getElementById('setupProviderEnabled');
  if (nameEl) nameEl.value = name || '';
  if (typeEl) typeEl.value = p.type || (PROVIDER_PRESETS[preset]?.type || 'openai-compatible');
  if (urlEl) urlEl.value = p.base_url || '';
  if (envEl) envEl.value = p.api_key_env || '';
  if (keyEl) keyEl.value = p.api_key || '';
  if (enabledEl) enabledEl.checked = p.enabled !== false;
}
function setupWizardLoadModelIntoStep(name) {
  const m = (config?.models || {})[name] || {};
  const providerEl = document.getElementById('setupModelProvider');
  if (document.getElementById('setupModelName')) document.getElementById('setupModelName').value = name || '';
  if (document.getElementById('setupModelFunction')) document.getElementById('setupModelFunction').value = m.extra?.function || inferModelFunction(m.provider, m.model || name || '');
  if (providerEl) providerEl.value = m.provider || '';
  if (document.getElementById('setupModelId')) document.getElementById('setupModelId').value = m.model || '';
  if (document.getElementById('setupModelContext')) document.getElementById('setupModelContext').value = m.context_window || 32768;
  if (document.getElementById('setupModelOutput')) document.getElementById('setupModelOutput').value = m.max_output_tokens || 4096;
  if (document.getElementById('setupModelChat')) document.getElementById('setupModelChat').checked = m.capabilities?.supports_chat !== false;
  if (document.getElementById('setupModelTools')) document.getElementById('setupModelTools').checked = !!m.capabilities?.supports_tools;
  if (document.getElementById('setupModelJson')) document.getElementById('setupModelJson').checked = !!m.capabilities?.supports_json;
  if (document.getElementById('setupModelStreaming')) document.getElementById('setupModelStreaming').checked = m.capabilities?.supports_streaming !== false;
}
function wireSetupWizardStep(stepId) {
  if (stepId === 'provider') {
    const existing = document.getElementById('setupProviderExisting');
    if (existing?.value) setupWizardLoadProviderIntoStep(existing.value);
    document.getElementById('setupProviderExisting')?.addEventListener('change', (ev) => setupWizardLoadProviderIntoStep(ev.target.value || ''));
    document.getElementById('setupProviderType')?.addEventListener('change', (ev) => {
      const type = String(ev.target.value || '');
      const preset = Object.values(PROVIDER_PRESETS).find(item => item.type === type);
      if (preset) {
        const nameEl = document.getElementById('setupProviderName');
        const urlEl = document.getElementById('setupProviderBaseUrl');
        const envEl = document.getElementById('setupProviderApiKeyEnv');
        if (nameEl && !nameEl.value.trim()) nameEl.value = preset.name || '';
        if (urlEl && !urlEl.value.trim()) urlEl.value = preset.base_url || '';
        if (envEl && !envEl.value.trim()) envEl.value = preset.api_key_env || '';
      }
    });
    document.getElementById('setupProviderTest')?.addEventListener('click', async () => {
      try {
        await saveSetupWizardProviderStep();
        const name = document.getElementById('setupProviderName')?.value?.trim();
        const result = await api(`/v1/providers/${encodeURIComponent(name)}/test`, {method:'POST'});
        setupWizardStepResult(result?.ok ? 'Provider test succeeded.' : (result?.error || 'Provider test failed.'), result?.ok ? 'ok' : 'warn');
      } catch (e) {
        setupWizardStepResult(e.message || String(e), 'warn');
      }
    });
  }
  if (stepId === 'model') {
    const existing = document.getElementById('setupModelExisting');
    if (existing?.value) setupWizardLoadModelIntoStep(existing.value);
    document.getElementById('setupModelExisting')?.addEventListener('change', (ev) => setupWizardLoadModelIntoStep(ev.target.value || ''));
    document.getElementById('setupModelId')?.addEventListener('blur', () => {
      const modelId = document.getElementById('setupModelId')?.value?.trim() || '';
      const fn = document.getElementById('setupModelFunction')?.value?.trim() || 'general';
      const nameEl = document.getElementById('setupModelName');
      if (nameEl && !nameEl.value.trim() && modelId) nameEl.value = `${fn}/${modelId.split('/').pop()}`;
    });
  }
  if (stepId === 'controller') {
    document.getElementById('setupHarnessUpdateWrapper')?.addEventListener('click', async () => {
      try {
        await updateControllerHarnessWrapper();
        setupWizardStepResult('Wrapper updated and diagnostics refreshed.', 'ok');
      } catch (e) {
        setupWizardStepResult(e.message || String(e), 'warn');
      }
    });
    document.getElementById('setupHarnessBootstrap')?.addEventListener('click', async () => {
      try {
        await bootstrapControllerHarness();
        setupWizardStepResult('Controller pi.dev bootstrap started.', 'ok');
      } catch (e) {
        setupWizardStepResult(e.message || String(e), 'warn');
      }
    });
  }
}
async function saveSetupWizardConnectionStep() {
  let publicUrl = (document.getElementById('setupPublicUrl')?.value || '').trim();
  const mdnsEnabled = !!document.getElementById('setupMdnsEnabled')?.checked;
  let savedConnection = false;
  if (publicUrl) {
    if (!/^https?:\/\//i.test(publicUrl)) publicUrl = `https://${publicUrl}`;
    await api('/v1/server/connection', {method:'POST', body:JSON.stringify({public_url: publicUrl, mdns_enabled: mdnsEnabled})});
    savedConnection = true;
  }
  if (config?.auth?.enabled && config?.auth?.mode === 'dev-token') {
    const token = (document.getElementById('setupDevToken')?.value || '').trim();
    if (!token || token === 'change-me') throw new Error('Replace the default dev bearer token before continuing.');
    if (token !== config?.auth?.dev_token) {
      const nextConfig = JSON.parse(JSON.stringify(config));
      nextConfig.auth = nextConfig.auth || {};
      nextConfig.auth.dev_token = token;
      await api('/v1/config', {method:'PUT', body:JSON.stringify({config: nextConfig})});
      savedConnection = true;
    }
  }
  if (!savedConnection) setupWizardStepResult('No connection changes were needed.', 'ok');
  await loadConfig();
  setupWizardStepResult(savedConnection ? 'Connection settings saved.' : 'Connection settings already current.', 'ok');
}
async function saveSetupWizardProviderStep() {
  const name = (document.getElementById('setupProviderName')?.value || '').trim();
  if (!name) throw new Error('Provider name is required.');
  const existing = config?.providers?.[name] || {};
  let baseUrl = (document.getElementById('setupProviderBaseUrl')?.value || '').trim();
  const type = document.getElementById('setupProviderType')?.value || 'openai-compatible';
  if ((type === 'lmstudio' || type === 'vllm' || type === 'anthropic-compatible' || type === 'minimax') && baseUrl && !baseUrl.replace(/\/$/, '').endsWith('/v1')) {
    baseUrl = `${baseUrl.replace(/\/$/, '')}/v1`;
  }
  const payload = {
    ...existing,
    type,
    base_url: baseUrl || null,
    api_key_env: (document.getElementById('setupProviderApiKeyEnv')?.value || '').trim() || null,
    api_key: (document.getElementById('setupProviderApiKey')?.value || '').trim() || null,
    timeout_seconds: Number(existing.timeout_seconds || 30),
    default_headers: existing.default_headers || {},
    enabled: !!document.getElementById('setupProviderEnabled')?.checked,
    status: existing.status || 'unknown',
    runtime: existing.runtime || {},
  };
  await api(`/v1/providers/${encodeURIComponent(name)}`, {method:'PUT', body:JSON.stringify(payload)});
  await loadConfig();
  setupWizardStepResult(`Provider ${name} saved.`, 'ok');
}
async function saveSetupWizardModelStep() {
  const name = (document.getElementById('setupModelName')?.value || '').trim();
  const provider = document.getElementById('setupModelProvider')?.value || '';
  if (!name) throw new Error('PAC model key is required.');
  if (!provider) throw new Error('Choose a provider for the model.');
  const duplicate = findConfiguredModelByProviderModel(provider, (document.getElementById('setupModelId')?.value || '').trim() || name, name);
  if (duplicate) throw new Error(`This provider model is already configured as '${duplicate[0]}'.`);
  const nextConfig = JSON.parse(JSON.stringify(config));
  nextConfig.models = nextConfig.models || {};
  nextConfig.models[name] = {
    provider,
    model: (document.getElementById('setupModelId')?.value || '').trim() || null,
    runs_on: null,
    context_window: Number(document.getElementById('setupModelContext')?.value || 32768),
    max_output_tokens: Number(document.getElementById('setupModelOutput')?.value || 4096),
    capabilities: {
      supports_chat: !!document.getElementById('setupModelChat')?.checked,
      supports_tools: !!document.getElementById('setupModelTools')?.checked,
      supports_vision: false,
      supports_json: !!document.getElementById('setupModelJson')?.checked,
      supports_streaming: !!document.getElementById('setupModelStreaming')?.checked,
      reasoning: 'none',
    },
    extra: {function: (document.getElementById('setupModelFunction')?.value || 'general').trim() || 'general'},
  };
  await api('/v1/config', {method:'PUT', body:JSON.stringify({config: nextConfig})});
  await loadConfig();
  setupWizardStepResult(`Model ${name} saved.`, 'ok');
}
async function saveSetupWizardControllerStep() {
  const payload = {
    enabled: !!document.getElementById('setupHarnessEnabled')?.checked,
    agent_profile: document.getElementById('setupHarnessProfile')?.value || null,
    model: document.getElementById('setupHarnessModel')?.value || null,
    permission_profile: document.getElementById('setupHarnessPermission')?.value || 'ask-first',
    workspace_profile: (document.getElementById('setupHarnessWorkspace')?.value || '').trim() || 'agent-control',
    runner_id: (document.getElementById('setupHarnessRunner')?.value || '').trim() || 'local-PAC',
  };
  const status = await api('/v1/controller-harness/settings', {method:'POST', body:JSON.stringify(payload)});
  await loadConfig();
  setupWizardStepResult(status?.message || 'Controller pi.dev settings saved.', status?.ok ? 'ok' : 'warn');
}
async function advanceSetupWizard(direction) {
  const nextIndex = setupWizardStepIndex + direction;
  if (direction > 0 && setupWizardSteps[setupWizardStepIndex]?.save) {
    try {
      await setupWizardSteps[setupWizardStepIndex].save();
    } catch (e) {
      setupWizardStepResult(e.message || String(e), 'warn');
      return;
    }
  }
  setupWizardStepIndex = Math.max(0, Math.min(setupWizardSteps.length - 1, nextIndex));
  renderSetupWizard();
}
async function completeSetupWizard() {
  try {
    await loadConfig();
    setupWizardStepResult('Setup rechecked.', 'ok');
    if (!(config?.setup_status?.required_issues || []).length) {
      hideSetupWizard();
      return;
    }
    setupWizardStepIndex = setupWizardSteps.length - 1;
    renderSetupWizard();
  } catch (e) {
    setupWizardStepResult(e.message || String(e), 'warn');
  }
}
function renderSetupWizard() {
  setupStatus = config?.setup_status || null;
  const body = document.getElementById('setupWizardBody');
  const modal = document.getElementById('setupWizard');
  const title = document.getElementById('setupWizardTitle');
  const meta = document.getElementById('setupWizardMeta');
  const progress = document.getElementById('setupWizardProgress');
  const backBtn = document.getElementById('setupWizardBack');
  const nextBtn = document.getElementById('setupWizardNext');
  const doneBtn = document.getElementById('setupWizardDone');
  if (!body || !modal) return;
  const issues = setupStatus?.required_issues || [];
  const warnings = setupStatus?.warnings || [];
  if (!issues.length) {
    body.innerHTML = '';
    hideSetupWizard();
    return;
  }
  setupWizardSteps = buildSetupWizardSteps();
  setupWizardStepIndex = Math.max(0, Math.min(setupWizardStepIndex, setupWizardSteps.length - 1));
  const step = setupWizardSteps[setupWizardStepIndex];
  if (title) title.textContent = step?.title || 'Finish PAC setup';
  if (meta) meta.textContent = setupWizardOverviewMeta();
  if (progress) progress.innerHTML = setupWizardSteps.map((item, index) => {
    const active = index === setupWizardStepIndex;
    const issuesForStep = setupWizardIssuesForStep(item.id);
    const badge = issuesForStep.length ? ` <span class="setup-step-badge">${issuesForStep.length}</span>` : '';
    return `<button type="button" class="ghost-button ${active ? 'active' : ''}" data-setup-step="${index}" ${active ? 'aria-current="step"' : ''}>${escapeHtml(item.label)}${badge}</button>`;
  }).join('');
  body.innerHTML = step.render();
  progress?.querySelectorAll('[data-setup-step]').forEach(btn => btn.addEventListener('click', () => {
    setupWizardStepIndex = Number(btn.dataset.setupStep || 0);
    renderSetupWizard();
  }));
  if (backBtn) backBtn.disabled = setupWizardStepIndex === 0;
  if (nextBtn) nextBtn.hidden = setupWizardStepIndex >= setupWizardSteps.length - 1;
  if (doneBtn) doneBtn.hidden = setupWizardStepIndex < setupWizardSteps.length - 1;
  wireSetupWizardStep(step.id);
  if (step.id === 'overview') wireSetupWizardOverview();
  openSetupWizard();
}
