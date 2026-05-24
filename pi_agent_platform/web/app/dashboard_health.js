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
