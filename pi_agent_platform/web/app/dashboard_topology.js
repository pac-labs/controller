// Dashboard widget selection, PAC Component Atlas rendering, and notification summary helpers.

const DASHBOARD_WIDGET_KEY = 'pac-dashboard-widgets-v1';
const DASHBOARD_ATLAS_ZOOM_KEY = 'pac-dashboard-atlas-zoom-v1';
const DASHBOARD_ATLAS_DETAIL_KEY = 'pac-dashboard-atlas-detail-v1';
const DASHBOARD_DEFAULT_WIDGETS = ['topology', 'overview', 'execution', 'components', 'readiness', 'events', 'sessions'];
const DASHBOARD_WIDGETS = [
  {id: 'overview', label: 'Operations overview'},
  {id: 'topology', label: 'PAC Component Atlas'},
  {id: 'execution', label: 'Execution health'},
  {id: 'components', label: 'Critical components'},
  {id: 'readiness', label: 'Setup and updates'},
  {id: 'events', label: 'Event activity'},
  {id: 'sessions', label: 'Recent sessions'},
  {id: 'system', label: 'System', mandatory: true},
];

const ATLAS_WIDTH = 2240;
const ATLAS_HEIGHT = 1560;
const ATLAS_GROUPS = {
  controller: {label: 'PAC Controller', icon: '⌂', x: 840, y: 560, w: 520, h: 360},
  agents: {label: 'Agents', icon: '✣', x: 780, y: 80, w: 620, h: 360},
  providers: {label: 'Providers & models', icon: '◍', x: 1460, y: 90, w: 620, h: 520},
  endpoints: {label: 'Endpoints', icon: '▰', x: 120, y: 230, w: 600, h: 500},
  workspaces: {label: 'Workspaces & context', icon: '▤', x: 1460, y: 680, w: 620, h: 430},
  sessions: {label: 'Sessions', icon: '▶', x: 800, y: 1010, w: 660, h: 430},
  tools: {label: 'Tools & packages', icon: '⚙', x: 120, y: 800, w: 600, h: 520},
  plugins: {label: 'Plugins', icon: '◇', x: 80, y: 1340, w: 640, h: 170},
  profiles: {label: 'Profiles & access', icon: '◈', x: 1540, y: 1160, w: 520, h: 310},
  observability: {label: 'Observability', icon: '◌', x: 120, y: 40, w: 560, h: 150},
  artifacts: {label: 'Artifacts', icon: '▧', x: 1500, y: 1490, w: 540, h: 160},
};

const ATLAS_KIND_META = {
  controller: {icon: '⌂', label: 'Controller'}, subsystem: {icon: '·', label: 'Controller part'},
  agent: {icon: '✣', label: 'Agent'}, agent_part: {icon: '•', label: 'Agent part'},
  provider: {icon: '◍', label: 'Provider'}, model: {icon: '✦', label: 'Model'}, capability: {icon: '+', label: 'Capability'},
  endpoint: {icon: '▰', label: 'Endpoint'}, runtime: {icon: '↯', label: 'Runtime'},
  workspace: {icon: '▤', label: 'Workspace'}, context: {icon: '▣', label: 'Context'},
  session: {icon: '▶', label: 'Session'}, profile: {icon: '◈', label: 'Profile'},
  tool_package: {icon: '▦', label: 'Tool package'}, tool: {icon: '⚙', label: 'Tool'}, plugin: {icon: '◇', label: 'Plugin'},
  observability: {icon: '◌', label: 'Signals'}, signal: {icon: '◦', label: 'Signal'}, artifact: {icon: '▧', label: 'Artifact'},
};

function dashboardSelectedWidgets() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DASHBOARD_WIDGET_KEY) || 'null');
    if (Array.isArray(parsed)) return new Set([...parsed, 'system']);
  } catch (_) {}
  return new Set([...DASHBOARD_DEFAULT_WIDGETS, 'system']);
}

function saveDashboardSelectedWidgets(selected) {
  try { localStorage.setItem(DASHBOARD_WIDGET_KEY, JSON.stringify([...selected].filter((id) => id !== 'system'))); } catch (_) {}
}

function applyDashboardWidgetVisibility() {
  const selected = dashboardSelectedWidgets();
  document.querySelectorAll('.dashboard-widget[data-dashboard-widget]').forEach((card) => {
    const widget = card.dataset.dashboardWidget || '';
    card.hidden = widget !== 'system' && !selected.has(widget);
  });
  renderDashboardWidgetMenu(selected);
}

function renderDashboardWidgetMenu(selected = dashboardSelectedWidgets()) {
  const menu = document.getElementById('dashboardWidgetMenu');
  if (!menu) return;
  menu.innerHTML = DASHBOARD_WIDGETS.map((widget) => {
    const checked = widget.mandatory || selected.has(widget.id);
    return `<label class="dashboard-widget-choice"><input type="checkbox" value="${escapeHtml(widget.id)}"${checked ? ' checked' : ''}${widget.mandatory ? ' disabled' : ''} /> <span>${escapeHtml(widget.label)}</span>${widget.mandatory ? '<small>mandatory</small>' : ''}</label>`;
  }).join('');
  menu.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.onchange = () => {
      const next = dashboardSelectedWidgets();
      if (input.checked) next.add(input.value); else next.delete(input.value);
      next.add('system');
      saveDashboardSelectedWidgets(next);
      applyDashboardWidgetVisibility();
    };
  });
}

function setupDashboardWidgetPicker() {
  const button = document.getElementById('dashboardWidgetPicker');
  const menu = document.getElementById('dashboardWidgetMenu');
  if (!button || !menu) return;
  applyDashboardWidgetVisibility();
  button.onclick = (ev) => {
    ev.stopPropagation();
    menu.hidden = !menu.hidden;
    button.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
  };
  document.addEventListener('click', (ev) => {
    if (menu.hidden) return;
    const wrap = button.closest('.dashboard-widget-picker-wrap');
    if (wrap && wrap.contains(ev.target)) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
  });
}

function atlasZoom() {
  const value = Number(localStorage.getItem(DASHBOARD_ATLAS_ZOOM_KEY) || '0.82');
  return Number.isFinite(value) ? Math.max(0.55, Math.min(1.35, value)) : 0.82;
}

function atlasDetail() {
  const value = localStorage.getItem(DASHBOARD_ATLAS_DETAIL_KEY) || 'auto';
  return ['auto', 'overview', 'infrastructure', 'full'].includes(value) ? value : 'auto';
}

function atlasEffectiveDetail() {
  const configured = atlasDetail();
  if (configured !== 'auto') return configured;
  const z = atlasZoom();
  if (z < 0.72) return 'overview';
  if (z < 1.0) return 'infrastructure';
  return 'full';
}

function atlasKindMeta(kind) {
  return ATLAS_KIND_META[kind] || {icon: '•', label: kind || 'Object'};
}

function atlasStatusClass(status) {
  const s = String(status || '').toLowerCase();
  if (['online', 'connected', 'available', 'configured', 'enabled', 'active', 'running'].includes(s)) return 'ok';
  if (['failed', 'unresolved', 'offline', 'disabled', 'stopped'].includes(s)) return 'warn';
  return 'neutral';
}

function atlasNodeVisible(node) {
  const detail = atlasEffectiveDetail();
  if (detail === 'full') return true;
  if (detail === 'infrastructure') return node.depth !== 'subcomponent' || ['model', 'tool', 'context'].includes(node.kind);
  return ['core', 'instance'].includes(node.depth) && !['capability', 'artifact'].includes(node.kind);
}

function atlasVisibleGraph(rawGraph) {
  const nodes = (rawGraph?.nodes || []).filter(atlasNodeVisible);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = (rawGraph?.edges || []).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  return {nodes, edges, summary: rawGraph?.summary || {}};
}

function atlasLayout(nodes) {
  const byGroup = new Map();
  nodes.forEach((node) => {
    const group = ATLAS_GROUPS[node.group] ? node.group : 'controller';
    if (!byGroup.has(group)) byGroup.set(group, []);
    byGroup.get(group).push(node);
  });
  const positions = {};
  byGroup.forEach((items, groupKey) => {
    const group = ATLAS_GROUPS[groupKey];
    const sorted = [...items].sort((a, b) => {
      const rank = {core: 0, instance: 1, subcomponent: 2};
      return (rank[a.depth] ?? 3) - (rank[b.depth] ?? 3) || String(a.parent || '').localeCompare(String(b.parent || '')) || String(a.label || a.id).localeCompare(String(b.label || b.id));
    });
    const compact = group.h < 220;
    const cols = compact ? 3 : Math.max(1, Math.floor((group.w - 44) / 220));
    sorted.forEach((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      positions[node.id] = {x: group.x + 22 + col * 220, y: group.y + 58 + row * 92};
    });
  });
  return positions;
}

function atlasNodeHtml(node, pos) {
  const meta = atlasKindMeta(node.kind);
  const status = atlasStatusClass(node.status);
  const active = ['running', 'active', 'queued', 'approval_required'].includes(String(node.status || '').toLowerCase());
  const loader = active ? '<span class="pac-loader atlas-node-loader" aria-label="active"></span>' : `<span class="atlas-node-icon">${escapeHtml(meta.icon)}</span>`;
  return `<button type="button" class="atlas-node atlas-node-depth-${escapeHtml(node.depth || 'instance')} atlas-kind-${escapeHtml(node.kind)} status-${status}" data-node-id="${escapeHtml(node.id)}" style="left:${pos.x}px;top:${pos.y}px">${loader}<span class="atlas-node-main"><b>${escapeHtml(node.label || node.id)}</b><small>${escapeHtml(meta.label)}${node.detail ? ` · ${escapeHtml(node.detail)}` : ''}</small></span><i>${escapeHtml(node.status || '')}</i></button>`;
}

function renderAtlasGroups(nodes) {
  const counts = new Map();
  nodes.forEach((node) => counts.set(node.group, (counts.get(node.group) || 0) + 1));
  return Object.entries(ATLAS_GROUPS).map(([key, group]) => `
    <section class="atlas-group atlas-group-${escapeHtml(key)}" data-atlas-group="${escapeHtml(key)}" style="left:${group.x}px;top:${group.y}px;width:${group.w}px;height:${group.h}px">
      <header><span>${escapeHtml(group.icon)}</span><b>${escapeHtml(group.label)}</b><small>${counts.get(key) || 0}</small></header>
    </section>`).join('');
}

function selectAtlasNode(node, graph) {
  document.querySelectorAll('.atlas-node').forEach((el) => el.classList.toggle('selected', el.dataset.nodeId === node.id));
  const details = document.getElementById('dashboardTopologyDetails');
  if (!details) return;
  const incoming = (graph.edges || []).filter((edge) => edge.target === node.id);
  const outgoing = (graph.edges || []).filter((edge) => edge.source === node.id);
  const data = node.data && typeof node.data === 'object' ? node.data : {};
  const compactData = Object.entries(data).filter(([, value]) => value != null && typeof value !== 'object').slice(0, 10);
  const relatedLine = (edge, reverse = false) => {
    const otherId = reverse ? edge.source : edge.target;
    const other = (graph.nodes || []).find((item) => item.id === otherId);
    return `<li><b>${escapeHtml(edge.label || 'connected')}</b> ${escapeHtml(reverse ? 'from' : 'to')} ${escapeHtml(other?.label || otherId)}</li>`;
  };
  const meta = atlasKindMeta(node.kind);
  details.innerHTML = `
    <div class="topology-detail-head"><span class="topology-icon">${escapeHtml(meta.icon)}</span><div><h3>${escapeHtml(node.label || node.id)}</h3><p>${escapeHtml(meta.label)} · ${escapeHtml(node.status || 'unknown')}</p></div></div>
    ${node.detail ? `<p class="muted small-text">${escapeHtml(node.detail)}</p>` : ''}
    <div class="topology-detail-section"><h4>Atlas position</h4><dl><dt>Group</dt><dd>${escapeHtml(ATLAS_GROUPS[node.group]?.label || node.group || 'PAC')}</dd><dt>Depth</dt><dd>${escapeHtml(node.depth || 'instance')}</dd>${node.parent ? `<dt>Parent</dt><dd>${escapeHtml((graph.nodes || []).find((item) => item.id === node.parent)?.label || node.parent)}</dd>` : ''}</dl></div>
    <div class="topology-detail-section"><h4>Connections</h4>${incoming.length || outgoing.length ? `<ul>${incoming.map((edge) => relatedLine(edge, true)).join('')}${outgoing.map((edge) => relatedLine(edge, false)).join('')}</ul>` : '<p class="muted small-text">No visible links at this detail level.</p>'}</div>
    ${compactData.length ? `<div class="topology-detail-section"><h4>Details</h4><dl>${compactData.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('')}</dl></div>` : ''}
    <div class="muted small-text">Object id: <code>${escapeHtml(node.id)}</code></div>`;
}

function drawAtlasEdges(container, graph, positions) {
  const svg = container.querySelector('svg');
  if (!svg) return;
  svg.setAttribute('viewBox', `0 0 ${ATLAS_WIDTH} ${ATLAS_HEIGHT}`);
  svg.innerHTML = '';
  (graph.edges || []).forEach((edge) => {
    const a = positions[edge.source];
    const b = positions[edge.target];
    if (!a || !b) return;
    const x1 = a.x + 108;
    const y1 = a.y + 36;
    const x2 = b.x + 108;
    const y2 = b.y + 36;
    const dx = Math.max(80, Math.abs(x2 - x1) / 2);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + (x2 >= x1 ? dx : -dx)} ${y1}, ${x2 - (x2 >= x1 ? dx : -dx)} ${y2}, ${x2} ${y2}`);
    path.setAttribute('class', `atlas-edge atlas-edge-${String(edge.kind || 'connected').replace(/[^a-z0-9_-]/gi, '-')}`);
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = edge.label || 'connected';
    path.appendChild(title);
    svg.appendChild(path);
  });
}

function renderAtlasControls(graph) {
  const zoom = atlasZoom();
  const detail = atlasDetail();
  const summary = graph.summary || {};
  return `<div class="atlas-toolbar">
    <div class="atlas-summary"><b>${summary.groups || Object.keys(ATLAS_GROUPS).length}</b><span>groups</span><b>${graph.nodes.length}</b><span>nodes</span><b>${graph.edges.length}</b><span>links</span></div>
    <label>Zoom <input id="atlasZoomRange" type="range" min="0.55" max="1.35" step="0.05" value="${zoom}" /></label>
    <label>Detail <select id="atlasDetailSelect"><option value="auto"${detail === 'auto' ? ' selected' : ''}>Auto</option><option value="overview"${detail === 'overview' ? ' selected' : ''}>Overview</option><option value="infrastructure"${detail === 'infrastructure' ? ' selected' : ''}>Infrastructure</option><option value="full"${detail === 'full' ? ' selected' : ''}>Full</option></select></label>
  </div>`;
}

function renderDashboardTopology(rawGraph) {
  const el = document.getElementById('dashboardTopologyMap');
  if (!el) return;
  const graph = atlasVisibleGraph(rawGraph || {nodes: [], edges: []});
  if (!graph.nodes.length) {
    el.textContent = 'No topology objects are configured yet.';
    return;
  }
  const zoom = atlasZoom();
  const positions = atlasLayout(graph.nodes);
  el.classList.remove('muted');
  el.innerHTML = `${renderAtlasControls(graph)}<div class="atlas-scroll-plane" style="width:${ATLAS_WIDTH * zoom}px;height:${ATLAS_HEIGHT * zoom}px"><div class="atlas-canvas" style="width:${ATLAS_WIDTH}px;height:${ATLAS_HEIGHT}px;transform:scale(${zoom})"><svg class="atlas-lines" aria-hidden="true"></svg>${renderAtlasGroups(graph.nodes)}<div class="atlas-node-layer">${graph.nodes.map((node) => atlasNodeHtml(node, positions[node.id] || {x: 40, y: 40})).join('')}</div></div></div>`;
  document.getElementById('atlasZoomRange')?.addEventListener('input', (ev) => {
    localStorage.setItem(DASHBOARD_ATLAS_ZOOM_KEY, String(ev.target.value));
    renderDashboardTopology(window.__pacDashboardTopology || rawGraph);
  });
  document.getElementById('atlasDetailSelect')?.addEventListener('change', (ev) => {
    localStorage.setItem(DASHBOARD_ATLAS_DETAIL_KEY, String(ev.target.value));
    renderDashboardTopology(window.__pacDashboardTopology || rawGraph);
  });
  el.querySelectorAll('.atlas-node').forEach((btn) => {
    const node = graph.nodes.find((item) => item.id === btn.dataset.nodeId);
    if (node) btn.onclick = () => selectAtlasNode(node, graph);
  });
  requestAnimationFrame(() => drawAtlasEdges(el, graph, positions));
  const firstNode = graph.nodes.find((node) => node.id === 'controller:pac') || graph.nodes[0];
  if (firstNode) selectAtlasNode(firstNode, graph);
}

async function loadDashboardTopology() {
  const el = document.getElementById('dashboardTopologyMap');
  try {
    const graph = await api('/v1/dashboard/topology');
    window.__pacDashboardTopology = graph;
    renderDashboardTopology(graph || {nodes: [], edges: []});
  } catch (e) {
    if (el) el.innerHTML = `<div class="muted">Could not load PAC Component Atlas: ${escapeHtml(e.message || e)}</div>`;
  }
}

function resetDashboardTopologyLayout() {
  try {
    localStorage.removeItem(DASHBOARD_ATLAS_ZOOM_KEY);
    localStorage.removeItem(DASHBOARD_ATLAS_DETAIL_KEY);
  } catch (_) {}
  const graph = window.__pacDashboardTopology;
  if (graph) renderDashboardTopology(graph);
}

function renderNotificationSummary(summary) {
  const badge = document.getElementById('notificationBadge');
  const panel = document.getElementById('notificationSummary');
  const count = Number(summary?.counts?.total || 0);
  if (badge) {
    badge.hidden = count <= 0;
    badge.textContent = String(Math.min(count, 99));
    badge.classList.toggle('has-critical', Number(summary?.counts?.critical || 0) > 0);
  }
  if (!panel) return;
  const items = summary?.items || [];
  panel.hidden = false;
  const toolbar = `<div class="notification-summary-head"><b>${items.length ? 'Needs attention' : 'Notifications'}</b><span>${count} item${count === 1 ? '' : 's'}</span><button id="notificationCheckNow" class="ghost-button mini-button" type="button">Check now</button></div>`;
  panel.innerHTML = items.length
    ? `${toolbar}${items.slice(0, 8).map((item) => `<button class="notification-item severity-${escapeHtml(item.severity || 'info')}" type="button" data-target="${escapeHtml(item.target || '')}"><span>${escapeHtml(item.kind || 'notice')}</span><b>${escapeHtml(item.title || 'Notification')}</b><small>${escapeHtml(item.detail || '')}</small></button>`).join('')}`
    : `${toolbar}<div class="notification-empty">No updates, approvals, alerts, or optimization notices need attention.</div>`;
  const checkNow = document.getElementById('notificationCheckNow');
  if (checkNow) checkNow.onclick = () => checkDashboardNotificationsNow(checkNow);
  panel.querySelectorAll('.notification-item').forEach((btn) => {
    btn.onclick = () => {
      const target = btn.dataset.target || '';
      if (target.startsWith('settings:')) {
        activateMainTab('settings-tab');
        switchSettingsPanel(target.split(':')[1] || 'updates');
      } else if (target) {
        activateMainTab(target);
      }
    };
  });
}

async function loadNotificationSummary() {
  try {
    const summary = await api('/v1/notifications/summary');
    window.__pacNotificationSummary = summary;
    renderNotificationSummary(summary);
  } catch (_) {}
}

async function checkDashboardNotificationsNow(button) {
  const original = button?.textContent || 'Check now';
  if (button) {
    button.disabled = true;
    button.textContent = 'Checking…';
  }
  await Promise.allSettled([api('/v1/updates/check'), api('/v1/sources/online-updates')]);
  await loadNotificationSummary();
  if (button) {
    button.disabled = false;
    button.textContent = original;
  }
}

function setupDashboardTopologyUi() {
  setupDashboardWidgetPicker();
  const refresh = document.getElementById('dashboardRefreshTopology');
  if (refresh) refresh.onclick = () => loadDashboardTopology();
  const reset = document.getElementById('dashboardResetTopologyLayout');
  if (reset) reset.onclick = () => resetDashboardTopologyLayout();
}
