// Controller pi.dev runtime settings and actions.

function fillHarnessSelects() {
  const profileSel = document.getElementById('harnessAgentProfile');
  const modelSel = document.getElementById('harnessModel');
  const permSel = document.getElementById('harnessPermission');
  if (profileSel) { profileSel.innerHTML = '<option value="">none</option>'; Object.keys(config.agent_profiles || {}).forEach(name => opt(profileSel, name, name)); }
  if (modelSel) { modelSel.innerHTML = '<option value="">profile default</option>'; Object.keys(config.models || {}).forEach(name => opt(modelSel, name, name)); }
  if (permSel) { permSel.innerHTML = ''; Object.keys(config.permission_profiles || {'ask-first':{}}).forEach(name => opt(permSel, name, name)); }
}

function renderControllerHarnessSettings(status=null) {
  const baseStatus = status || controllerHarnessStatusCache;
  const liveStatus = baseStatus?.diagnostics?.status && typeof baseStatus.diagnostics.status === 'object'
    ? {...baseStatus, ...baseStatus.diagnostics.status, diagnostics: baseStatus.diagnostics}
    : baseStatus;
  const effectiveStatus = liveStatus;
  fillHarnessSelects();
  const h = config.controller_harness || {};
  const setVal = (id, value) => { const el = document.getElementById(id); if (el) el.value = value ?? ''; };
  const setChecked = (id, value) => { const el = document.getElementById(id); if (el) el.checked = !!value; };
  setChecked('harnessEnabled', h.enabled !== false);
  setChecked('harnessAutoBootstrap', h.auto_bootstrap !== false);
  setChecked('harnessAutoBuildWrapper', h.auto_build_wrapper !== false);
  setChecked('harnessAutoInstallPiDev', h.auto_install_pi_dev !== false);
  setChecked('harnessAutoSession', h.auto_create_session !== false);
  setChecked('harnessExposeTools', h.expose_platform_tools !== false);
  setVal('harnessSessionName', h.session_name || 'PAC controller pi.dev');
  setVal('harnessWorkspaceProfile', h.workspace_profile || 'agent-control');
  setVal('harnessAgentProfile', h.agent_profile || 'main-pi-dev');
  setVal('harnessModel', h.model || '');
  setVal('harnessPermission', h.permission_profile || 'ask-first');
  setVal('harnessContextMode', h.context_mode || 'medium');
  setVal('harnessRunnerId', h.runner_id || 'local-PAC');
  const box = document.getElementById('controllerHarnessStatus');
  const runtimeBox = document.getElementById('controllerHarnessRuntime');
  const logsBox = document.getElementById('controllerHarnessLogs');
  const actionsBox = document.getElementById('controllerHarnessActions');
  if (box) {
    const session = effectiveStatus?.session;
    const runner = effectiveStatus?.runner;
    const diag = effectiveStatus?.diagnostics || {};
    const wrapperCap = runner?.capabilities?.pac_wrapper || {};
    const wrapperProc = diag.wrapper_process || {};
    const pi = runner?.capabilities?.pi_container || {};
    const runnerMeta = runner?.metadata || {};
    const wrapperVersion = runnerMeta.runner_version || runnerMeta.endpoint_version || '';
    const serverVersion = currentVersionInfo?.version || config?.version || config?.setup_status?.version || '';
    const versionMismatch = !!(wrapperVersion && serverVersion && wrapperVersion !== serverVersion);
    const wrapperText = wrapperCap.available
      ? (wrapperCap.path || wrapperProc.path || 'available')
      : (wrapperProc.available ? (wrapperProc.path || 'installed') : (wrapperCap.reason || 'missing'));
    const piText = (pi.image_available || pi.available)
      ? `${pi.image || 'available'}${pi.available ? '' : ' (image present, runtime not ready)'}`
      : (pi.reason || 'missing');
    const state = effectiveStatus ? (effectiveStatus.ok ? 'ready' : 'needs setup') : 'not checked';
    box.innerHTML = `
      <div class="pi-dev-status-banner ${escapeHtml(effectiveStatus?.ok ? 'ok' : 'warn')}">
        <div>
          <div class="pi-dev-status-kicker">Status</div>
          <div class="pi-dev-status-title">${escapeHtml(state)}</div>
          <div class="pi-dev-status-copy">${escapeHtml(effectiveStatus?.message || 'Saved settings are shown below.')}</div>
        </div>
      </div>
      ${versionMismatch ? `<div class="pi-dev-notice critical"><b>Wrapper version mismatch</b><span>PAC server is v${escapeHtml(serverVersion)}, but the local wrapper reports v${escapeHtml(wrapperVersion)}. Rebuild/install the local wrapper before trusting controller pi.dev readiness.</span></div>` : ''}
      <div class="pi-dev-kv-grid">
        <div><span>Runner</span><code>${escapeHtml(String(runner?.name || h.runner_id || '-'))}</code></div>
        <div><span>Session</span><code>${escapeHtml(String(session?.name || '-'))}</code></div>
        <div><span>Model</span><code>${escapeHtml(String(session?.model || h.model || 'profile default'))}</code></div>
        <div><span>Workspace</span><code>${escapeHtml(String(session?.workspace_path || '-'))}</code></div>
        <div><span>PAC wrapper</span><code>${escapeHtml(String(wrapperText))}</code></div>
        <div><span>Wrapper version</span><code>${escapeHtml(String(wrapperVersion || '-'))}</code></div>
        <div><span>pi.dev image</span><code>${escapeHtml(String(piText))}</code></div>
      </div>`;
    if (actionsBox) {
      actionsBox.dataset.needsAttention = effectiveStatus?.ok ? 'false' : 'true';
    }
  }
  if (runtimeBox) {
    const diag = effectiveStatus?.diagnostics || {};
    const wrapper = diag.wrapper_process || {};
    const daemon = diag.pi_daemon || {};
    const runnerMeta = effectiveStatus?.runner?.metadata || {};
    const agentRuntime = runnerMeta.agent_runtime || {};
    const rows = {
      'Wrapper state': wrapper.running ? 'running' : 'stopped',
      'Wrapper pid': wrapper.pid || '-',
      'Wrapper exit': wrapper.return_code ?? '-',
      'Wrapper binary': wrapper.path || '-',
      'pi.dev daemon': daemon.running ? 'running' : 'stopped',
      'pi.dev daemon pid': daemon.pid || '-',
      'Agent runtime': agentRuntime.status || '-',
      'Agent detail': agentRuntime.detail || '-',
      'Wrapper log': diag.wrapper_log || '-',
    };
    runtimeBox.innerHTML = `<div class="pi-dev-kv-grid">${Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('')}</div>`;
  }
  if (logsBox) logsBox.textContent = effectiveStatus?.diagnostics?.wrapper_log_tail || '';
}

async function loadControllerHarnessStatus() {
  try {
    const [status, diagnostics] = await Promise.all([
      api('/v1/controller-harness'),
      api('/v1/controller-harness/diagnostics').catch(()=>null),
    ]);
    if (diagnostics) status.diagnostics = diagnostics;
    controllerHarnessStatusCache = status;
    renderControllerHarnessSettings(status);
    return status;
  } catch (e) {
    const fallback = controllerHarnessStatusCache ? {...controllerHarnessStatusCache, ok:false, message:e.message || controllerHarnessStatusCache.message} : {ok:false, message:e.message};
    controllerHarnessStatusCache = fallback;
    renderControllerHarnessSettings(fallback);
    return null;
  }
}

async function saveControllerHarnessSettings() {
  const result = document.getElementById('controllerHarnessResult');
  const payload = {
    enabled: !!document.getElementById('harnessEnabled')?.checked,
    auto_bootstrap: !!document.getElementById('harnessAutoBootstrap')?.checked,
    auto_build_wrapper: !!document.getElementById('harnessAutoBuildWrapper')?.checked,
    auto_install_pi_dev: !!document.getElementById('harnessAutoInstallPiDev')?.checked,
    auto_create_session: !!document.getElementById('harnessAutoSession')?.checked,
    expose_platform_tools: !!document.getElementById('harnessExposeTools')?.checked,
    session_name: document.getElementById('harnessSessionName')?.value?.trim() || 'PAC controller pi.dev',
    workspace_profile: document.getElementById('harnessWorkspaceProfile')?.value?.trim() || 'agent-control',
    agent_profile: document.getElementById('harnessAgentProfile')?.value || 'main-pi-dev',
    model: document.getElementById('harnessModel')?.value || null,
    permission_profile: document.getElementById('harnessPermission')?.value || 'ask-first',
    context_mode: document.getElementById('harnessContextMode')?.value || 'medium',
    runner_id: document.getElementById('harnessRunnerId')?.value?.trim() || 'local-PAC',
  };
  const status = await api('/v1/controller-harness/settings', {method:'POST', body:JSON.stringify(payload)});
  if (result) result.textContent = status.message || 'Controller pi.dev settings saved.';
  await loadConfig();
  switchSettingsPanel('updates');
  await loadSessions();
  if (status?.session?.id) { selectedSession = status.session; }
  await loadGlobalEvents(true).catch(()=>{});
}


async function bootstrapControllerHarness() {
  const result = document.getElementById('controllerHarnessResult');
  if (result) result.textContent = 'Starting controller pi.dev bootstrap…';
  const status = await api('/v1/controller-harness/bootstrap', {method:'POST'});
  if (result) result.textContent = status.message || 'Controller pi.dev bootstrap started.';
  await loadGlobalEvents(true).catch(()=>{});
  await loadRunners().catch(()=>{});
}

async function updateControllerHarnessWrapper() {
  const result = document.getElementById('controllerHarnessResult');
  if (result) result.textContent = 'Updating local PAC wrapper…';
  const status = await api('/v1/controller-harness/update-wrapper', {method:'POST'});
  if (result) result.textContent = status.message || 'Controller wrapper update completed.';
  await loadControllerHarnessStatus().catch(()=>{});
  await loadRunners().catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}

async function openControllerHarnessSession() {
  const status = await loadControllerHarnessStatus();
  if (status?.session?.id) { switchToTab('sessions-tab'); await selectSession(status.session.id); }
  else showInline('controllerHarnessResult', status?.message || 'pi.dev session is not available yet. Select a model/profile first.');
}

