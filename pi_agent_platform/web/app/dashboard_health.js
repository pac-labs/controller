// Dashboard metric, component health, readiness, and small chart rendering.

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

function formatDashboardBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}
function utilizationTone(value) {
  const number = Number(value || 0);
  if (number >= 90) return 'danger';
  if (number >= 75) return 'warn';
  return 'ok';
}
function pushUsageSample(usage) {
  window.__pacDashboardUsageSamples = window.__pacDashboardUsageSamples || [];
  const sample = {
    at: new Date(),
    cpu: Number(usage?.cpu_percent || 0),
    memory: Number(usage?.memory?.percent || 0),
    disk: Number(usage?.disk?.percent || 0),
  };
  window.__pacDashboardUsageSamples.push(sample);
  window.__pacDashboardUsageSamples = window.__pacDashboardUsageSamples.slice(-18);
  return window.__pacDashboardUsageSamples;
}
function normalizeUsageHistory(history) {
  return (Array.isArray(history) ? history : [])
    .map((item) => ({
      at: item.ts ? new Date(item.ts) : new Date(),
      cpu: Number(item.cpu ?? 0),
      memory: Number(item.memory ?? 0),
      disk: Number(item.disk ?? 0),
    }))
    .filter((item) => Number.isFinite(item.cpu) || Number.isFinite(item.memory) || Number.isFinite(item.disk))
    .slice(-48);
}
function renderUsageSeries(samples) {
  const rows = samples && samples.length ? samples : [];
  if (!rows.length) return '<div class="muted small-text">Integrated time-series history will appear after samples are collected.</div>';
  const width = 640;
  const height = 132;
  const padX = 18;
  const padY = 14;
  const plotW = width - (padX * 2);
  const plotH = height - (padY * 2);
  const point = (item, index, key) => {
    const x = padX + ((rows.length <= 1 ? 0 : index / (rows.length - 1)) * plotW);
    const y = padY + (plotH - ((Math.max(0, Math.min(100, Number(item[key] || 0))) / 100) * plotH));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };
  const line = (key) => rows.map((item, index) => point(item, index, key)).join(' ');
  const latest = rows[rows.length - 1] || {};
  const startLabel = rows[0]?.at instanceof Date ? rows[0].at.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
  const endLabel = latest.at instanceof Date ? latest.at.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
  const latestValue = (key) => `${Math.round(Number(latest[key] || 0))}%`;
  return `<div class="utilization-timeseries utilization-line-chart" aria-label="Controller usage time series">
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="CPU, memory, and filesystem usage trend">
      <line class="chart-grid" x1="${padX}" y1="${padY}" x2="${width - padX}" y2="${padY}" />
      <line class="chart-grid" x1="${padX}" y1="${padY + plotH / 2}" x2="${width - padX}" y2="${padY + plotH / 2}" />
      <line class="chart-grid" x1="${padX}" y1="${height - padY}" x2="${width - padX}" y2="${height - padY}" />
      <polyline class="usage-line usage-line-cpu" points="${line('cpu')}" />
      <polyline class="usage-line usage-line-memory" points="${line('memory')}" />
      <polyline class="usage-line usage-line-disk" points="${line('disk')}" />
    </svg>
    <div class="usage-chart-footer"><span>${escapeHtml(startLabel)}</span><span>${escapeHtml(endLabel)}</span></div>
    <div class="usage-chart-legend"><span class="legend-cpu">CPU ${escapeHtml(latestValue('cpu'))}</span><span class="legend-memory">Memory ${escapeHtml(latestValue('memory'))}</span><span class="legend-disk">Filesystem ${escapeHtml(latestValue('disk'))}</span></div>
  </div>`;
}
function renderUtilizationMeter(label, value, detail) {
  const pct = Number(value || 0);
  const tone = utilizationTone(pct);
  return `<div class="utilization-meter" data-state="${tone}"><div><b>${escapeHtml(label)}</b><span>${escapeHtml(detail || '')}</span></div><strong>${Number.isFinite(pct) ? `${pct.toFixed(1)}%` : '—'}</strong><div class="utilization-track"><i style="width:${Math.max(2, Math.min(100, pct))}%"></i></div></div>`;
}
function renderControllerUtilization(metrics) {
  const el = document.getElementById('controllerUtilization');
  if (!el) return;
  const usage = metrics?.controller_usage || {};
  const memory = usage.memory || {};
  const disk = usage.disk || {};
  const persistedSamples = normalizeUsageHistory(metrics?.controller_usage_history);
  const samples = persistedSamples.length ? persistedSamples : pushUsageSample(usage);
  const sampleHint = persistedSamples.length ? `${persistedSamples.length} persisted sample${persistedSamples.length === 1 ? '' : 's'} from integrated time-series` : 'Waiting for integrated time-series samples';
  el.innerHTML = `<div class="utilization-meters">
    ${renderUtilizationMeter('CPU load', usage.cpu_percent, '1 minute load / logical cores')}
    ${renderUtilizationMeter('Memory', memory.percent, `${formatDashboardBytes(memory.used_bytes)} of ${formatDashboardBytes(memory.total_bytes)}`)}
    ${renderUtilizationMeter('Filesystem', disk.percent, `${formatDashboardBytes(disk.used_bytes)} of ${formatDashboardBytes(disk.total_bytes)}`)}
  </div>${renderUsageSeries(samples)}<div class="muted small-text">${escapeHtml(sampleHint)}</div>`;
}
function bindDashboardRouteActions() {
  document.querySelectorAll('[data-route-target="observe-events"]').forEach((button) => {
    if (button.dataset.boundRouteTarget === '1') return;
    button.dataset.boundRouteTarget = '1';
    button.addEventListener('click', () => {
      if (typeof activateMainTab === 'function') activateMainTab('events-tab');
    });
  });
}

async function loadDashboardMetrics() {
  try {
    const metrics = await api('/v1/metrics/summary');
    renderStatCards(metrics);
    renderBarChart('taskStatusChart', metrics.task_status, 'No tasks have run yet.');
    renderEventActivity(metrics.events_by_day);
    renderCriticalComponentHealth(metrics);
    renderOpsReadiness(metrics);
    renderControllerUtilization(metrics);
    bindDashboardRouteActions();
    if (typeof loadNotificationSummary === 'function') loadNotificationSummary();
  } catch (e) {
    const el = document.getElementById('dashboardStats');
    if (el) el.innerHTML = `<div class="muted">Could not load metrics: ${escapeHtml(e.message)}</div>`;
    const component = document.getElementById('componentHealth');
    if (component) component.innerHTML = `<div class="muted">Could not load component health: ${escapeHtml(e.message)}</div>`;
    const usage = document.getElementById('controllerUtilization');
    if (usage) usage.innerHTML = `<div class="muted">Could not load controller utilization: ${escapeHtml(e.message)}</div>`;
    const readiness = document.getElementById('opsReadiness');
    if (readiness) readiness.innerHTML = `<div class="muted">Could not load setup state: ${escapeHtml(e.message)}</div>`;
  }
}
