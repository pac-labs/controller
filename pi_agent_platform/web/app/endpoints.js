// Endpoint, dashboard, controller-runtime, and command modal UI helpers extracted from app.js.

function formatBytes(value) {
  const n = Number(value || 0);
  if (!n) return '-';
  const units = ['B','KB','MB','GB','TB','PB'];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}
function firstValue(...values) { return values.find(v => v !== undefined && v !== null && String(v) !== '') ?? '-'; }
function endpointHardware(r) {
  const c = r.capabilities || {};
  const hw = c.hardware || {};
  const cpu = firstValue(hw.cpu?.model, c.cpu?.model, hw.cpu_model);
  const cores = firstValue(hw.cpu?.logical_cores, c.cpu?.logical_cores, c.cpu?.cores);
  const ram = firstValue(hw.memory?.total_bytes ? formatBytes(hw.memory.total_bytes) : null, c.memory?.total_bytes ? formatBytes(c.memory.total_bytes) : null, hw.ram);
  const disk = firstValue(hw.disk?.total_bytes ? formatBytes(hw.disk.total_bytes) : null, c.disk?.total_bytes ? formatBytes(c.disk.total_bytes) : null, hw.disk);
  const gpuRaw = c.gpu?.devices?.length ? c.gpu.devices.map(g => g.name || g.raw || 'GPU').join(', ') : (c.gpu?.raw || (c.gpu?.available ? 'available' : '-'));
  return {cpu, cores, ram, disk, gpu: gpuRaw};
}

function endpointOsFamily(endpoint) {
  const values = [endpoint?.metadata?.os_family, endpoint?.metadata?.os, endpoint?.metadata?.onboarding_target, ...(endpoint?.labels || [])].map(v => String(v || '').toLowerCase());
  if (values.some(v => v.includes('windows') || v === 'win32' || v === 'win64')) return 'windows';
  if (values.some(v => v.includes('darwin') || v.includes('macos') || v === 'mac')) return 'darwin';
  if (values.some(v => v.includes('linux'))) return 'linux';
  return 'unknown';
}
function endpointDefaultCommand(endpoint) {
  return endpointOsFamily(endpoint) === 'windows' ? 'Get-Location; Get-ChildItem -Force | Select-Object -First 20' : 'pwd && ls -la';
}
function endpointDefaultWorkspaceForTarget(target) {
  return String(target || '').toLowerCase().includes('windows') ? 'C:\\PAC\\workspace' : '$HOME/pac-workspace';
}

function compactContainerLine(c) {
  const names = Array.isArray(c.Names) ? c.Names.join(', ') : (c.Names || c.names || c.Name || c.name || '-');
  const image = c.Image || c.image || '-';
  const state = c.State || c.state || c.Status || c.status || '';
  return `${names} · ${image}${state ? ` · ${state}` : ''}`;
}
async function loadRunners() {
  const endpoints = await api('/v1/endpoints');
  window.__pacEndpoints = endpoints;
  fillModelEndpointOptions(endpoints);
  if (document.getElementById('workspaceEndpoint')) { workspaceEndpoint.innerHTML = '<option value="">none</option>'; endpoints.forEach(r => opt(workspaceEndpoint, r.id, `${r.name || r.id} (${r.status || 'unknown'})`)); }
  if (document.getElementById('taskRunner')) { taskRunner.innerHTML = '<option value="">PAC/local</option>'; endpoints.forEach(r => opt(taskRunner, r.id, `${r.name} (${r.status})`)); }
  if (document.getElementById('sessionEndpoint')) { sessionEndpoint.innerHTML = '<option value="">select endpoint</option>'; endpoints.forEach(r => opt(sessionEndpoint, r.id, `${r.name} (${r.status})`)); }
  const summaries = [document.getElementById('runnerSummary'), document.getElementById('runnerSummaryEndpoints')].filter(Boolean);
  if (summaries.length) {
    const online = endpoints.filter(r => r.status === 'online').length;
    const gpu = endpoints.filter(r => r.capabilities?.gpu?.available || r.capabilities?.gpu?.devices?.length).length;
    const html = `<div class="metric"><b>${endpoints.length}</b><span>endpoints</span></div><div class="metric"><b>${online}</b><span>online</span></div><div class="metric"><b>${gpu}</b><span>GPU hosts</span></div>`;
    summaries.forEach(summary => summary.innerHTML = html);
  }
  const el = document.getElementById('runners'); if (!el) return;
  el.innerHTML = endpoints.length ? '' : '<div class="muted">No endpoints yet. Add the local host or register a remote endpoint.</div>';
  endpoints.forEach(r => {
    const hw = endpointHardware(r);
    const configuredTools = r.metadata?.agent_tools || [];
    const discoveredTools = r.capabilities?.tools ? Object.entries(r.capabilities.tools).filter(([_,v])=>v.available).map(([k])=>k) : [];
    const effectiveTools = configuredTools.length ? configuredTools : discoveredTools;
    const tools = effectiveTools.length ? effectiveTools.join(', ') : '-';
    const packages = (r.metadata?.tool_packages || packageNamesForTools(effectiveTools)).join(', ') || '-';
    const defaultWorkspace = r.metadata?.default_workspace || Object.entries(config.workspaces || {}).find(([_,w]) => w.endpoint_id === r.id && w.is_default)?.[0] || '-';
    const modelLinks = Object.entries(config.models || {}).filter(([_,m]) => m.runs_on === r.id).map(([k])=>k).join(', ');
    const containers = (r.containers || []).slice(0,4).map(compactContainerLine).join('\n');
    const card = renderEndpointInventoryCard(r, {
      helpers: {
        endpointHardware,
        endpointRuntimeLines,
        endpointPiContainer,
        packageNamesForTools,
        compactContainerLine,
        defaultWorkspace,
        modelLinks: modelLinks || '-',
      },
      actions: endpointInventoryCardActions(),
    });
    el.appendChild(card);
  });
  renderModelRecommendations();
  renderWorkspaceActivityPanel();
  renderProvidersLivePanel().catch(()=>{});
}


function renderStatCards(metrics) {
  const el = document.getElementById('dashboardStats');
  if (!el) return;
  const health = metrics.component_health || {};
  const providers = health.providers || {};
  const models = health.models || {};
  const endpoints = health.endpoints || {};
  const setup = health.setup || {};
  const updates = health.updates || {};
  const alerts = metrics.alert_counts || {};
  const stats = [
    ['Sessions', metrics.sessions_total, `${metrics.sessions_active || 0} active`],
    ['Tasks', metrics.tasks_total, `${metrics.tasks_running || 0} running/queued`],
    ['Failed', metrics.tasks_failed, 'tasks failed'],
    ['Approvals', metrics.approvals_pending, 'pending'],
    ['Alerts', alerts.total ?? 0, `${alerts.critical ?? 0} critical`],
    ['Endpoints', metrics.endpoints_total, `${metrics.endpoints_online || 0} online`],
    ['Providers', providers.connected ?? 0, `${providers.enabled ?? 0} enabled`],
    ['Models', models.available ?? 0, `${models.session_capable ?? 0} session-ready`],
    ['Setup', setup.required_issues ?? 0, `${setup.warnings ?? 0} warnings`],
    ['Updates', updates.archives ?? 0, `${updates.local_diffs ?? 0} local diffs`],
  ];
  el.innerHTML = stats.map(([label,value,hint]) => `<div class="metric"><b>${value ?? 0}</b><span>${label}</span><small>${hint}</small></div>`).join('');
}
function renderHealthGrid(id, sections, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!sections || !sections.length) {
    el.textContent = emptyText || 'No data yet.';
    return;
  }
  el.innerHTML = sections.map(section => {
    const rows = (section.rows || []).map(row => {
      const tone = row.tone ? ` tone-${row.tone}` : '';
      return `<div class="health-row${tone}"><span>${escapeHtml(row.label || '')}</span><b>${escapeHtml(String(row.value ?? '-'))}</b></div>`;
    }).join('');
    return `<section class="health-section"><h3>${escapeHtml(section.title || '')}</h3>${rows}</section>`;
  }).join('');
}
function renderCriticalComponentHealth(metrics) {
  const health = metrics.component_health || {};
  const providers = health.providers || {};
  const models = health.models || {};
  const endpoints = health.endpoints || {};
  const controller = health.controller || {};
  renderHealthGrid('componentHealth', [
    {
      title: 'Providers',
      rows: [
        {label:'Connected', value: `${providers.connected ?? 0}/${providers.total ?? 0}`, tone:(providers.failed || 0) ? 'warn' : 'ok'},
        {label:'Failed', value: providers.failed ?? 0, tone:(providers.failed || 0) ? 'danger' : 'ok'},
        {label:'Disabled', value: providers.disabled ?? 0},
      ],
    },
    {
      title: 'Models',
      rows: [
        {label:'Available', value: `${models.available ?? 0}/${models.total ?? 0}`, tone:(models.unavailable || 0) ? 'warn' : 'ok'},
        {label:'Unavailable', value: models.unavailable ?? 0, tone:(models.unavailable || 0) ? 'danger' : 'ok'},
        {label:'Unsupported provider', value: models.unsupported_provider ?? 0, tone:(models.unsupported_provider || 0) ? 'warn' : 'ok'},
      ],
    },
    {
      title: 'Endpoints',
      rows: [
        {label:'Online', value: `${endpoints.online ?? 0}/${endpoints.total ?? 0}`, tone:(endpoints.offline || 0) ? 'warn' : 'ok'},
        {label:'Agent ready', value: endpoints.agent_ready ?? 0, tone:(endpoints.agent_blocked || 0) ? 'warn' : 'ok'},
        {label:'GPU capable', value: endpoints.gpu_capable ?? 0},
      ],
    },
    {
      title: 'Controller',
      rows: [
        {label:'Runtime', value: controller.runtime_status || 'unknown', tone:(controller.runtime_status === 'ready') ? 'ok' : ((controller.runtime_status === 'disabled') ? '' : 'warn')},
        {label:'Wrapper', value: controller.wrapper_running ? 'running' : 'stopped', tone:controller.wrapper_running ? 'ok' : 'warn'},
        {label:'pi.dev', value: controller.pi_dev_running ? 'running' : 'stopped', tone:controller.pi_dev_running ? 'ok' : 'warn'},
        {label:'Wrapper version', value: controller.wrapper_version || '-', tone:(controller.wrapper_version && controller.wrapper_version !== metrics.version) ? 'danger' : 'ok'},
      ],
    },
  ], 'No component health is available yet.');
}
function renderOpsReadiness(metrics) {
  const health = metrics.component_health || {};
  const setup = health.setup || {};
  const secrets = health.secrets || {};
  const source = health.source || {};
  const updates = health.updates || {};
  const alerts = metrics.alert_counts || {};
  renderHealthGrid('opsReadiness', [
    {
      title: 'Alerts',
      rows: [
        {label:'Critical', value: alerts.critical ?? 0, tone:(alerts.critical || 0) ? 'danger' : 'ok'},
        {label:'Warnings', value: alerts.warning ?? 0, tone:(alerts.warning || 0) ? 'warn' : 'ok'},
        {label:'Total', value: alerts.total ?? 0, tone:(alerts.total || 0) ? 'warn' : 'ok'},
      ],
    },
    {
      title: 'Setup',
      rows: [
        {label:'Required blockers', value: setup.required_issues ?? 0, tone:(setup.required_issues || 0) ? 'danger' : 'ok'},
        {label:'Warnings', value: setup.warnings ?? 0, tone:(setup.warnings || 0) ? 'warn' : 'ok'},
        {label:'Ready', value: setup.ready ? 'yes' : 'no', tone:setup.ready ? 'ok' : 'danger'},
      ],
    },
    {
      title: 'Secrets',
      rows: [
        {label:'Backend', value: secrets.backend_ready ? 'ready' : 'degraded', tone:secrets.backend_ready ? 'ok' : 'warn'},
        {label:'Stored', value: secrets.count ?? 0},
        {label:'Path', value: secrets.store_path ? 'configured' : 'missing'},
      ],
    },
    {
      title: 'Source state',
      rows: [
        {label:'Contexts', value: source.contexts ?? 0},
        {label:'Variables', value: source.variables ?? 0},
        {label:'PAC RAM', value: (source.ram_profiles || 0) + (source.ram_users || 0) + (source.ram_workspaces || 0)},
      ],
    },
    {
      title: 'Updates',
      rows: [
        {label:'Archives', value: updates.archives ?? 0},
        {label:'Local diffs', value: updates.local_diffs ?? 0},
        {label:'UI build', value: metrics.ui_build || currentVersionInfo?.ui_build || '-'},
      ],
    },
  ], 'No setup or update data is available yet.');
}
function renderBarChart(id, rows, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  const entries = Object.entries(rows || {}).filter(([_,v]) => Number(v) > 0);
  if (!entries.length) { el.textContent = emptyText || 'No data yet.'; return; }
  const max = Math.max(...entries.map(([_,v]) => Number(v) || 0), 1);
  el.innerHTML = entries.map(([label,value]) => `<div class="bar-row"><span>${escapeHtml(label)}</span><div class="bar-track"><i style="width:${Math.max(6, Math.round((Number(value)/max)*100))}%"></i></div><b>${value}</b></div>`).join('');
}
function renderEventActivity(points) {
  const el = document.getElementById('eventActivityChart');
  if (!el) return;
  const rows = points || [];
  const max = Math.max(...rows.map(p => Number(p.count) || 0), 1);
  el.innerHTML = `<div class="spark-bars">${rows.map(p => `<div class="spark-col" title="${escapeHtml(p.date)}: ${p.count}"><i style="height:${Math.max(8, Math.round((Number(p.count || 0)/max)*100))}%"></i><span>${escapeHtml(String(p.date || '').slice(5))}</span></div>`).join('')}</div>`;
}
async function loadDashboardMetrics() {
  try {
    const metrics = await api('/v1/metrics/summary');
    renderStatCards(metrics);
    renderBarChart('taskStatusChart', metrics.task_status, 'No tasks have run yet.');
    renderEventActivity(metrics.events_by_day);
    renderCriticalComponentHealth(metrics);
    renderOpsReadiness(metrics);
    if (typeof loadNotificationSummary === 'function') loadNotificationSummary();
  } catch (e) {
    const el = document.getElementById('dashboardStats');
    if (el) el.innerHTML = `<div class="muted">Could not load metrics: ${escapeHtml(e.message)}</div>`;
    const component = document.getElementById('componentHealth');
    if (component) component.innerHTML = `<div class="muted">Could not load component health: ${escapeHtml(e.message)}</div>`;
    const readiness = document.getElementById('opsReadiness');
    if (readiness) readiness.innerHTML = `<div class="muted">Could not load setup state: ${escapeHtml(e.message)}</div>`;
  }
}

function openEndpointModal(id='') {
  editingEndpointId = id || null;
  const modal = document.getElementById('endpointModal');
  const status = document.getElementById('endpointModalStatus');
  const title = document.getElementById('endpointModalTitle');
  if (status) status.textContent = '';
  if (title) title.textContent = editingEndpointId ? 'Edit endpoint' : 'Add remote endpoint';
  const endpoint = editingEndpointId ? (window.__pacEndpoints || []).find(r => r.id === editingEndpointId) : null;
  if (endpoint) {
    runnerName.value = endpoint.name || '';
    runnerLabels.value = (endpoint.labels || []).join(',');
    runnerEndpoint.value = endpoint.endpoint || '';
    setSelectedRunnerToolNames(endpoint.metadata?.agent_tools || []);
    if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.value = endpoint.metadata?.default_workspace || '';
    if (document.getElementById('runnerAgentEnabled')) runnerAgentEnabled.checked = !!(endpoint.metadata?.agent_requested || endpoint.metadata?.agent_enabled);
  } else {
    runnerName.value = 'gpu-workstation-01';
    runnerLabels.value = 'linux,gpu,endpoint';
    runnerEndpoint.value = '';
    setSelectedRunnerToolNames([]);
    if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.value = '';
    if (document.getElementById('runnerAgentEnabled')) runnerAgentEnabled.checked = false;
  }
  if (modal) { modal.hidden = false; setTimeout(() => document.getElementById('runnerName')?.focus(), 0); }
}
function closeEndpointModal() {
  const modal = document.getElementById('endpointModal');
  if (modal) modal.hidden = true;
}
function switchToTab(tabId) {
  if (tabId) activateMainTab(tabId);
}

function renderZedConfigExamples() {
  const publicUrl = (config.server?.public_url || 'https://localhost').replace(/\/$/, '');
  const local = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'C:/tools/pac.exe',
        args: ['--base-url', publicUrl, '--insecure'],
        env: {}
      }
    }
  };
  const remote = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'npx',
        args: ['-y', 'mcp-remote', `${publicUrl}/mcp`, '--insecure'],
        env: {}
      }
    }
  };
  const localEl = document.getElementById('zedMcpConfigLocal');
  const remoteEl = document.getElementById('zedMcpConfigRemote');
  if (localEl) localEl.textContent = JSON.stringify(local, null, 2);
  if (remoteEl) remoteEl.textContent = JSON.stringify(remote, null, 2);
}


async function loadServiceModeStatus() {
  const info = document.getElementById('serviceModeInfo');
  if (!info) return;
  try {
    const svc = await api('/v1/admin/service/status');
    const rows = {
      'Configured mode': svc.configured_mode || '-',
      'System service': svc.system_unit_exists ? `present / ${svc.system_active || '-'}` : `missing / ${svc.system_active || '-'}`,
      'User service': svc.user_unit_exists ? `present / ${svc.user_active || '-'}` : `missing / ${svc.user_active || '-'}`,
      'Port': svc.port || '-',
      'Host switch allowed now': svc.can_manage_host_now ? 'yes' : 'needs sudo/manual command',
      'System unit': svc.system_unit || '-',
      'User unit': svc.user_unit || '-',
    };
    info.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('');
    const result = document.getElementById('serviceModeResult');
    if (result && svc.manual_host_command) result.textContent = `Host service manual command if sudo is needed:\n${svc.manual_host_command}`;
  } catch (e) {
    info.innerHTML = `<div><span>Status</span><code>Could not load service status: ${escapeHtml(e.message)}</code></div>`;
  }
}

async function setServiceMode(mode) {
  const result = document.getElementById('serviceModeResult');
  if (mode === 'host' && !confirm('Switch PAC to host/system service? This requires sudo/root or passwordless sudo, uses port 443, and will restart PAC.')) return;
  if (mode === 'user' && !confirm('Switch PAC to user service? This will move PAC back to the user systemd service, use 8443, and restart PAC.')) return;
  if (result) result.textContent = `Switching PAC to ${mode} service mode…`;
  const payload = await api('/v1/admin/service/mode', {method:'POST', body:JSON.stringify({mode})});
  if (result) result.textContent = payload?.message || payload?.status || `Service mode ${mode} requested. Details are in Events.`; emitUiEvent('service_mode_changed', result ? result.textContent : 'Service mode changed', payload);
  if (payload.restart_scheduled) scheduleHiddenReloadAfterRestart(18);
  await loadServiceModeStatus();
  await loadControllerHarnessStatus();
}

async function loadTlsStatus() {
  const el = document.getElementById('tlsInfo');
  if (!el) return;
  try {
    const tls = await api('/v1/tls/status');
    const rows = {
      'CA': tls.ca_exists ? 'present' : 'missing',
      'CA valid until': tls.ca_valid_until || '-',
      'Server cert': tls.server_cert_exists ? 'present' : 'missing',
      'Server valid until': tls.server_valid_until || '-',
      'mDNS name': tls.mdns_hostname || 'admin.pac.local',
      'mDNS URL': tls.mdns_url || '-',
      'mDNS enabled': tls.mdns?.enabled === false ? 'no' : 'yes',
      'mDNS state': tls.mdns_status?.state || '-',
      'mDNS message': tls.mdns_status?.message || '-',
      'Port 443': tls.port_443?.configured ? 'configured' : 'not configured',
      'CA file': tls.ca_cert_file || '-',
      'Server cert file': tls.server_cert_file || '-',
      'Details': tls.details_file || '-',
    };
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(v)}</code></div>`).join('');
  } catch (e) {
    el.innerHTML = `<div><span>Status</span><code>Could not load TLS status: ${escapeHtml(e.message)}</code></div>`;
  }
}

function renderSystemInfo() {
  const pacp = config.pacp || {};
  const rows = {
    'Backend version': currentVersionInfo?.version || config.version || '-',
    'UI build': currentVersionInfo?.ui_build || '-',
    'UI updated': currentVersionInfo?.ui_updated_at || '-',
    'PAC home': pacp.home || '-',
    'Config': pacp.config_path || '-',
    'Single-instance lock': pacp.single_instance_lock || '-',
    'Public URL': config.server?.public_url || '-',
    'Workspace root': config.server?.default_workspace_root || '-',
  };
  for (const id of ['systemInfo','pacpInfo']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${v}</code></div>`).join('');
  }
}


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

function renderEndpointConnectionSettings() {
  const urlInput = document.getElementById('endpointPublicUrl');
  const mdnsInput = document.getElementById('endpointMdnsEnabled');
  if (urlInput) urlInput.value = config.server?.public_url || '';
  if (mdnsInput) mdnsInput.checked = config.mdns?.enabled !== false;

  // Load letsencrypt status
  fetch('/v1/server/letsencrypt/status').then(r => r.json()).then(data => {
    const emailEl = document.getElementById('leEmail');
    if (emailEl) emailEl.value = data.email || '';
    const domainEl = document.getElementById('leDomain');
    if (domainEl && !domainEl.value) domainEl.value = data.domain || 'pac.thebigtree.life';
    const zoneEl = document.getElementById('leZoneId');
    if (zoneEl && !zoneEl.value) zoneEl.value = '';
    const statusEl = document.getElementById('leStatus');
    if (statusEl) {
      if (data.cert_exists) {
        const info = data.cert_info || {};
        statusEl.textContent = `Certificate present for ${data.domain || 'unknown'}. Valid until ${info.not_after || '?'}`;
      } else if (data.enabled) {
        statusEl.textContent = 'LE enabled but no cert file found.';
      } else {
        statusEl.textContent = 'No LE certificate installed. Enter your Cloudflare details and click Obtain.';
      }
    }
    const cfTestEl = document.getElementById('leCloudflareTest');
    if (cfTestEl) {
      cfTestEl.textContent = data.cloudflare_configured ? 'Cloudflare: configured' : 'Cloudflare: not configured yet';
    }
  }).catch(() => {});
}

async function saveEndpointConnectionSettings() {
  const result = document.getElementById('endpointConnectionResult');
  let publicUrl = (document.getElementById('endpointPublicUrl')?.value || '').trim();
  const mdnsEnabled = !!document.getElementById('endpointMdnsEnabled')?.checked;
  if (!publicUrl) return paneError('Enter the controller URL endpoints should use');
  if (!/^https?:\/\//i.test(publicUrl)) publicUrl = `https://${publicUrl}`;
  const payload = await api('/v1/server/connection', {method:'POST', body:JSON.stringify({public_url: publicUrl, mdns_enabled: mdnsEnabled})});
  if (result) result.textContent = `${payload.message || 'Endpoint connection settings saved.'}\nSaved URL: ${payload.public_url || publicUrl}`;
  await loadConfig();
  await loadGlobalEvents(true).catch(()=>{});
}

async function loadWorkspaceCatalogs() {
  const [templateData, workspaceData, contextData, groupsData, storageData] = await Promise.all([
    api('/v1/workspace-templates').catch(() => ({templates: []})),
    api('/v1/my-workspaces').catch(() => ({items: []})),
    api('/v1/agent-contexts').catch(() => ({items: []})),
    api('/v1/directory/groups').catch(() => []),
    api('/v1/shared-storages').catch(() => ({items: []})),
  ]);
  workspaceTemplates = Array.isArray(templateData?.templates) ? templateData.templates : [];
  personalWorkspaces = Array.isArray(workspaceData?.items) ? workspaceData.items : [];
  agentContexts = Array.isArray(contextData?.items) ? contextData.items : [];
  sharedStorages = Array.isArray(storageData?.items) ? storageData.items : [];
  window.__pacGroups = Array.isArray(groupsData) ? groupsData : [];
  if (selectedIdeWorkspaceId && !personalWorkspaces.some((item) => item.id === selectedIdeWorkspaceId)) selectedIdeWorkspaceId = '';
  if (!selectedIdeWorkspaceId && personalWorkspaces.length) {
    selectedIdeWorkspaceId = (personalWorkspaces.find((item) => item.pinned) || personalWorkspaces[0]).id;
  }
  if (selectedIdeContextId && !agentContexts.some((item) => item.id === selectedIdeContextId)) selectedIdeContextId = '';
  if (!selectedIdeContextId && agentContexts.length) {
    const defaultContexts = agentContexts.filter((item) => !isProtectedAgentContext(item));
    selectedIdeContextId = ((defaultContexts.find((item) => item.pinned) || defaultContexts[0]) || (agentContexts.find((item) => item.pinned) || agentContexts[0])).id;
  }
}


function switchEndpointPanel(panelId = 'endpointInventoryPanel') {
  document.querySelectorAll('#endpointSubnav .subtab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.endpointPanel === panelId);
  });
  document.querySelectorAll('#runners-tab .endpoint-subpanel').forEach(panel => {
    const active = panel.id === panelId;
    panel.hidden = !active;
    panel.classList.toggle('active', active);
  });
}
function wizardEndpointBody() {
  const chosenTools = selectedWizardToolNames();
  return {
    name: wizardRunnerName.value || 'remote-endpoint',
    labels: wizardRunnerLabels.value.split(',').map(x => x.trim()).filter(Boolean),
    endpoint: null,
    allow_host_execution: true,
    allow_container_execution: true,
    agent_enabled: false,
    metadata: {
      agent_tools: chosenTools,
      tool_packages: packageNamesForTools(chosenTools),
      default_workspace: document.getElementById('wizardRunnerDefaultWorkspace')?.value || null,
      desired_workspace_root: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
      onboarding_target: document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64',
      onboarding_mode: 'wizard',
    },
  };
}
async function saveWizardEndpointProfile() {
  const body = wizardEndpointBody();
  return api('/v1/endpoints', {method:'POST', body:JSON.stringify(body)});
}
function renderEndpointInstallKit(data) {
  const artifact = document.getElementById('endpointWizardArtifact');
  const linux = document.getElementById('endpointWizardLinux');
  const powershell = document.getElementById('endpointWizardPowerShell');
  const notes = document.getElementById('endpointWizardNotes');
  if (artifact) {
    artifact.textContent = data.artifact_missing
      ? `Build failed or no artifact was produced for ${data.target}.`
      : `Artifact: ${data.artifact?.name || '-'}\nVersion: ${data.build_result?.version || data.artifact?.version || '-'}\nCompiled URL: ${data.build_result?.compiled_server_url || data.public_url || '-'}\nCompiled endpoint: ${data.build_result?.compiled_endpoint_name || data.endpoint_name || '-'}\nRunner default: ${data.build_result?.compiled_runner_enabled === false ? 'disabled' : 'enabled'}\nWorkspace default: ${data.build_result?.compiled_workspace_root || '-'}\nDownload: ${data.download_url || '-'}\nToken: ${data.token_kind || '-'}${data.expires_at ? `\nExpires: ${data.expires_at}` : ''}`;
  }
  if (linux) linux.value = data.commands?.linux || '';
  if (powershell) powershell.value = data.commands?.powershell || '';
  if (notes) notes.textContent = Array.isArray(data.notes) ? data.notes.join('\n') : (data.message || '');
}

function ensureEndpointCommandModal() {
  let modal = document.getElementById('endpointCommandModal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'endpointCommandModal';
  modal.className = 'modal-backdrop';
  modal.hidden = true;
  modal.innerHTML = `<section class="modal-card endpoint-command-modal" role="dialog" aria-modal="true" aria-labelledby="endpointCommandTitle">
    <div class="section-heading"><div><h2 id="endpointCommandTitle">Queue endpoint command</h2><p class="muted">Run a scoped command through the endpoint job queue. Progress opens in a live modal after the job is queued.</p></div><button id="closeEndpointCommandModal" class="ghost-button">Close</button></div>
    <div class="form-grid">
      <label>Endpoint <input id="endpointCommandTarget" readonly /></label>
      <label>Mode <select id="endpointCommandMode"><option value="host">Host shell</option><option value="container">Container</option><option value="pi_container">pi.dev container</option></select></label>
      <label>Container image <input id="endpointCommandImage" placeholder="optional for container mode" /></label>
      <label>Workspace path <input id="endpointCommandWorkspace" placeholder="optional endpoint workspace" /></label>
      <label class="wide-label">Command <textarea id="endpointCommandText" rows="8" spellcheck="false"></textarea></label>
    </div>
    <div class="button-row"><button id="queueEndpointCommand">Queue command</button><span id="endpointCommandStatus" class="muted"></span></div>
  </section>`;
  document.body.appendChild(modal);
  document.getElementById('closeEndpointCommandModal').onclick = closeEndpointCommandModal;
  modal.onclick = (ev) => { if (ev.target === modal) closeEndpointCommandModal(); };
  document.getElementById('queueEndpointCommand').onclick = queueEndpointCommandFromModal;
  return modal;
}
function openEndpointCommandModal(id) {
  commandEndpointId = id;
  const r = (window.__pacEndpoints || []).find(x => x.id === id);
  const modal = ensureEndpointCommandModal();
  if (document.getElementById('endpointCommandTarget')) endpointCommandTarget.value = r ? `${r.name} (${r.id})` : id;
  if (document.getElementById('endpointCommandMode')) endpointCommandMode.value = 'host';
  if (document.getElementById('endpointCommandImage')) endpointCommandImage.value = '';
  if (document.getElementById('endpointCommandWorkspace')) endpointCommandWorkspace.value = r?.metadata?.default_workspace || '';
  if (document.getElementById('endpointCommandText')) endpointCommandText.value = endpointDefaultCommand(r);
  if (document.getElementById('endpointCommandStatus')) endpointCommandStatus.textContent = '';
  modal.hidden = false;
}
function closeEndpointCommandModal() {
  const modal = document.getElementById('endpointCommandModal');
  if (modal) modal.hidden = true;
}

const closeEndpointBtn = document.getElementById('closeEndpointModal');
if (closeEndpointBtn) closeEndpointBtn.onclick = closeEndpointModal;
const endpointModal = document.getElementById('endpointModal');
if (endpointModal) endpointModal.onclick = (ev) => { if (ev.target === endpointModal) closeEndpointModal(); };
async function queueEndpointCommandFromModal(){
  const button = document.getElementById('queueEndpointCommand');
  const status = document.getElementById('endpointCommandStatus');
  try {
    if (button) button.disabled = true;
    if (status) PACLoading.status(status, 'Queueing…');
    const mode = document.getElementById('endpointCommandMode')?.value || 'host';
    const selected = (window.__pacEndpoints || []).find(x => x.id === commandEndpointId);
    const shell = endpointOsFamily(selected) === 'windows' ? 'powershell' : 'sh';
    const body = {prompt:'Endpoint command', command:document.getElementById('endpointCommandText')?.value || endpointDefaultCommand(selected), execution_mode:mode, container_image:document.getElementById('endpointCommandImage')?.value || null, workspace_path:document.getElementById('endpointCommandWorkspace')?.value || null, metadata:{source_endpoint_id:'controller', shell}};
    const job = await api(`/v1/endpoints/${encodeURIComponent(commandEndpointId)}/commands`, {method:'POST', body:JSON.stringify(body)});
    if (status) PACLoading.status(status, 'Opening progress…');
    closeEndpointCommandModal();
    if (typeof watchEndpointJob === 'function') watchEndpointJob(job, {title:'Endpoint command progress', subtitle:selected?.name || commandEndpointId});
    await loadGlobalEvents(true).catch(()=>{});
  } catch(e) { if (status) status.textContent = `Failed: ${e.message}`; } finally { if (button) button.disabled = false; }
}
const closeEndpointCommandBtn = document.getElementById('closeEndpointCommandModal');
if (closeEndpointCommandBtn) closeEndpointCommandBtn.onclick = closeEndpointCommandModal;
const endpointCommandModal = document.getElementById('endpointCommandModal');
if (endpointCommandModal) endpointCommandModal.onclick = (ev) => { if (ev.target === endpointCommandModal) closeEndpointCommandModal(); };
const queueEndpointCommandBtn = document.getElementById('queueEndpointCommand');
if (queueEndpointCommandBtn) queueEndpointCommandBtn.onclick = queueEndpointCommandFromModal;
const addRunnerBtn = document.getElementById('addRunner');
if (addRunnerBtn) addRunnerBtn.onclick = async()=>{
  const status = document.getElementById('endpointModalStatus');
  try {
    addRunnerBtn.disabled = true;
    if (status) PACLoading.status(status, 'Adding endpoint…');
    const chosenTools = selectedRunnerToolNames(); const body={name:runnerName.value || 'remote-endpoint', labels:runnerLabels.value.split(',').map(x=>x.trim()).filter(Boolean), endpoint:runnerEndpoint.value || null, allow_host_execution:true, allow_container_execution:true, agent_enabled:!!document.getElementById('runnerAgentEnabled')?.checked, metadata:{agent_tools:chosenTools, tool_packages:packageNamesForTools(chosenTools), default_workspace:document.getElementById('runnerDefaultWorkspace')?.value || null}};
    const path = editingEndpointId ? `/v1/endpoints/${editingEndpointId}` : '/v1/endpoints';
    const method = editingEndpointId ? 'PUT' : 'POST';
    await api(path,{method, body:JSON.stringify(body)});
    if (status) status.textContent = editingEndpointId ? 'Saved.' : 'Added.';
    closeEndpointModal();
    await loadRunners(); await loadGlobalEvents(true).catch(()=>{});
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message}`;
  } finally {
    addRunnerBtn.disabled = false;
  }
};
document.querySelectorAll('#endpointSubnav .subtab').forEach(btn => {
  btn.onclick = () => switchEndpointPanel(btn.dataset.endpointPanel || 'endpointInventoryPanel');
});
const switchToEndpointOnboardingBtn = document.getElementById('switchToEndpointOnboarding');
if (switchToEndpointOnboardingBtn) switchToEndpointOnboardingBtn.onclick = () => switchEndpointPanel('endpointOnboardingPanel');
const wizardRunnerTargetSelect = document.getElementById('wizardRunnerTarget');
if (wizardRunnerTargetSelect) wizardRunnerTargetSelect.onchange = () => {
  const workspace = document.getElementById('wizardRunnerWorkspace');
  const labels = document.getElementById('wizardRunnerLabels');
  const target = wizardRunnerTargetSelect.value || 'linux/amd64';
  if (workspace && !workspace.value.trim()) workspace.value = endpointDefaultWorkspaceForTarget(target);
  if (labels) {
    const wanted = target.includes('windows') ? ['windows', 'remote-execution'] : [target.split('/')[0], 'remote-execution'];
    const existing = labels.value.split(',').map(x => x.trim()).filter(Boolean);
    labels.value = Array.from(new Set([...existing, ...wanted])).join(', ');
  }
};
const saveWizardEndpointBtn = document.getElementById('saveWizardEndpoint');
if (saveWizardEndpointBtn) saveWizardEndpointBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    saveWizardEndpointBtn.disabled = true;
    if (status) status.textContent = 'Saving endpoint profile…';
    const endpoint = await saveWizardEndpointProfile();
    if (status) status.textContent = `Saved endpoint profile: ${endpoint.name || endpoint.id}`;
    await loadRunners();
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    saveWizardEndpointBtn.disabled = false;
  }
};
const buildWizardEndpointBinaryBtn = document.getElementById('buildWizardEndpointBinary');
if (buildWizardEndpointBinaryBtn) buildWizardEndpointBinaryBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    buildWizardEndpointBinaryBtn.disabled = true;
    if (status) status.textContent = 'Building pac-endpoint…';
    const target = document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64';
    const endpointName = document.getElementById('wizardRunnerName')?.value || 'remote-endpoint';
    const endpointSlug = endpointName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'endpoint';
    const result = await api('/v1/sources/build-binary', {method:'POST', body:JSON.stringify({
      path:'binaries/pac-endpoint',
      targets:[target],
      server_url:(config.server?.public_url || '').replace(/\/$/, ''),
      binary_name:`pac-endpoint-${endpointSlug}`,
      endpoint_name:endpointName,
      runner_enabled: !!document.getElementById('wizardRunnerEnabled')?.checked,
      workspace_path: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
    })});
    if (status) status.textContent = result.ok ? `Built preconfigured pac-endpoint for ${endpointName} (${target})` : `Build failed for ${target}`;
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    buildWizardEndpointBinaryBtn.disabled = false;
  }
};
const generateWizardEndpointKitBtn = document.getElementById('generateWizardEndpointKit');
if (generateWizardEndpointKitBtn) generateWizardEndpointKitBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    generateWizardEndpointKitBtn.disabled = true;
    if (status) status.textContent = 'Generating install kit…';
    await saveWizardEndpointProfile().catch(()=>null);
    const payload = {
      endpoint_name: document.getElementById('wizardRunnerName')?.value || 'remote-endpoint',
      target: document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64',
      ttl_hours: Number(document.getElementById('wizardTokenTtl')?.value || 24) || 24,
      workspace_path: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
      runner_enabled: !!document.getElementById('wizardRunnerEnabled')?.checked,
    };
    const data = await api('/v1/endpoints/onboarding-kit', {method:'POST', body:JSON.stringify(payload)});
    renderEndpointInstallKit(data);
    if (status) status.textContent = data.artifact_missing ? 'Install kit generated. Build the binary first.' : 'Install kit generated.';
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    generateWizardEndpointKitBtn.disabled = false;
  }
};
const discoverBtn = document.getElementById('discoverLocal');
if (discoverBtn) discoverBtn.onclick = async()=>{ const r=await api('/v1/endpoints/local/discover'); if(localDiscovery) localDiscovery.textContent='Local host discovery completed. Details are in Events.'; emitUiEvent('local_endpoint_discovered', 'Local host discovery completed', r); };
if (document.getElementById('wizardRunnerTools')) wizardRunnerTools.addEventListener('change', updateWizardToolPackagePreview);
const addLocalBtn = document.getElementById('addLocalRunner');
if (addLocalBtn) addLocalBtn.onclick = async()=>{ const box=document.getElementById('localDiscovery'); try { if(box) box.textContent='Adding local endpoint…'; const r=await api('/v1/endpoints/local',{method:'POST'}); if(box) box.textContent='Local endpoint added. Details are in Events.'; emitUiEvent('local_endpoint_added', 'Local endpoint added', r); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); } catch(e){ if(box) box.textContent='Local endpoint could not be added. Details are in Events.'; paneError('Local endpoint could not be added', e.message); } };

const updateAllBtn = document.getElementById('updateAllEndpoints');
if (updateAllBtn) updateAllBtn.onclick = async()=>{
  if(!confirm('Queue software update for all online remote endpoints?')) return;
  const result = await api('/v1/endpoints/update-all',{method:'POST'});
  if(localDiscovery) localDiscovery.textContent = 'Endpoint update requested. Details are in Events.'; emitUiEvent('endpoint_update_all_requested', 'Endpoint update requested', result);
  await loadRunners();
};

const maintenanceAllBtn = document.getElementById('maintenanceAllEndpoints');
if (maintenanceAllBtn) maintenanceAllBtn.onclick = async()=>{
  if(!confirm('Run safe PAC maintenance cleanup on all online endpoints? This removes only PAC-created stopped containers, stale PAC workspaces, and temporary artifact bundles older than 24 hours.')) return;
  const result = await api('/v1/endpoints/maintenance-all',{method:'POST', body:JSON.stringify({max_age_hours:24,dry_run:false,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false})});
  if(localDiscovery) localDiscovery.textContent = 'Endpoint maintenance requested. Details are in Events.'; emitUiEvent('endpoint_maintenance_all_requested', 'Endpoint maintenance requested', result);
  await loadRunners();
  await loadGlobalEvents(true).catch(()=>{});
};

const buildMcpBtn = document.getElementById('buildMcpBridge');
if (buildMcpBtn) buildMcpBtn.onclick = () => buildMcpBridgeFromUi().catch(e=>paneError('Zed binary build failed', e.message));
const refreshMcpBtn = document.getElementById('refreshMcpBridge');
if (refreshMcpBtn) refreshMcpBtn.onclick = () => loadMcpBuildStatus();

const closeSessionEventBtn = document.getElementById('closeSessionEventModal');
if (closeSessionEventBtn) closeSessionEventBtn.onclick = closeSessionEventModal;
const sessionEventModal = document.getElementById('sessionEventModal');
if (sessionEventModal) sessionEventModal.onclick = (ev) => { if (ev.target === sessionEventModal) closeSessionEventModal(); };
const closeGitDiffBtn = document.getElementById('closeGitDiffModal');
if (closeGitDiffBtn) closeGitDiffBtn.onclick = closeGitDiffModal;
const gitDiffModal = document.getElementById('gitDiffModal');
if (gitDiffModal) gitDiffModal.onclick = (ev) => { if (ev.target === gitDiffModal) closeGitDiffModal(); };

// --- Let's Encrypt DNS-01 handlers ---
if (document.getElementById('leEnableBtn')) {
    document.getElementById('leEnableBtn').onclick = async () => {
        const email = document.getElementById('leEmail')?.value?.trim();
        const domain = document.getElementById('leDomain')?.value?.trim();
        const apiToken = document.getElementById('leApiToken')?.value?.trim();
        const zoneId = document.getElementById('leZoneId')?.value?.trim();
        const staging = !!document.getElementById('leStaging')?.checked;
        const statusEl = document.getElementById('leStatus');

        if (!email || !domain || !apiToken || !zoneId) {
            statusEl.textContent = 'All fields are required'; return;
        }

        statusEl.textContent = 'Requesting certificate via Cloudflare DNS-01... (this can take 2-3 minutes)';

        try {
            const result = await api('/v1/server/letsencrypt/enable', {
                method: 'POST',
                body: JSON.stringify({email, domain, cloudflare_api_token: apiToken, cloudflare_zone_id: zoneId, staging, auto_enable: true})
            });
            statusEl.textContent = result.ok ? `Success! Certificate installed for ${domain}` : `Failed: ${result.error}`;
            if (result.ok && result.cert_file) {
                await api('/v1/server/connection', {method:'POST', body: JSON.stringify({public_url: `https://${domain}`})}).catch(()=>{});
            }
        } catch(e) {
            statusEl.textContent = 'Error: ' + e.message;
        }
    };
}

if (document.getElementById('leDisableBtn')) {
    document.getElementById('leDisableBtn').onclick = async () => {
        const result = await api('/v1/server/letsencrypt/disable', {method:'POST'});
        document.getElementById('leStatus').textContent = result.message || 'Done';
    };
}

if (document.getElementById('leTestCfBtn')) {
    document.getElementById('leTestCfBtn').onclick = async () => {
        const apiToken = document.getElementById('leApiToken')?.value?.trim();
        const zoneId = document.getElementById('leZoneId')?.value?.trim();
        if (!apiToken || !zoneId) {
            document.getElementById('leCloudflareTest').textContent = 'Enter API token and Zone ID first'; return;
        }
        document.getElementById('leCloudflareTest').textContent = 'Testing...';
        try {
            const result = await api(`/v1/server/letsencrypt/test-cloudflare?api_token=${encodeURIComponent(apiToken)}&zone_id=${encodeURIComponent(zoneId)}`, {method:'POST'});
            document.getElementById('leCloudflareTest').textContent = result.ok ? `✓ Cloudflare OK — zone: ${result.zone}` : `✗ Cloudflare error: ${result.error}`;
        } catch(e) {
            document.getElementById('leCloudflareTest').textContent = 'Error: ' + e.message;
        }
    };
}

