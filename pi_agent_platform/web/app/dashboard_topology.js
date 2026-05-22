// Dashboard topology, private widgets, and notification-summary helpers.

const DASHBOARD_WIDGET_KEY = 'pac-dashboard-widgets-v1';
const DASHBOARD_TOPOLOGY_LAYOUT_KEY = 'pac-dashboard-topology-layout-v1';
const DASHBOARD_DEFAULT_WIDGETS = ['overview', 'topology', 'execution', 'components', 'readiness', 'events', 'sessions'];
const DASHBOARD_WIDGETS = [
  {id: 'overview', label: 'Operations overview'},
  {id: 'topology', label: 'Connection map'},
  {id: 'execution', label: 'Execution health'},
  {id: 'components', label: 'Critical components'},
  {id: 'readiness', label: 'Setup and updates'},
  {id: 'events', label: 'Event activity'},
  {id: 'sessions', label: 'Recent sessions'},
  {id: 'system', label: 'System', mandatory: true},
];

const TOPOLOGY_KIND_META = {
  controller: {icon: '⌂', label: 'Controller', column: 0},
  profile: {icon: '◈', label: 'Profile', column: 1},
  model: {icon: '✦', label: 'Model', column: 2},
  provider: {icon: '◍', label: 'Provider', column: 3},
  context: {icon: '▣', label: 'Context', column: 1},
  workspace: {icon: '▤', label: 'Workspace', column: 2},
  endpoint: {icon: '▰', label: 'Endpoint', column: 3},
};

function dashboardSelectedWidgets() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DASHBOARD_WIDGET_KEY) || 'null');
    if (Array.isArray(parsed)) return new Set([...parsed, 'system']);
  } catch (_) {}
  return new Set([...DASHBOARD_DEFAULT_WIDGETS, 'system']);
}

function saveDashboardSelectedWidgets(selected) {
  const values = [...selected].filter((id) => id !== 'system');
  try { localStorage.setItem(DASHBOARD_WIDGET_KEY, JSON.stringify(values)); } catch (_) {}
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
    const disabled = widget.mandatory ? ' disabled' : '';
    return `<label class="dashboard-widget-choice"><input type="checkbox" value="${escapeHtml(widget.id)}"${checked ? ' checked' : ''}${disabled} /> <span>${escapeHtml(widget.label)}</span>${widget.mandatory ? '<small>mandatory</small>' : ''}</label>`;
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
    const open = menu.hidden;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  document.addEventListener('click', (ev) => {
    if (menu.hidden) return;
    const wrap = button.closest('.dashboard-widget-picker-wrap');
    if (wrap && wrap.contains(ev.target)) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
  });
}

function topologyKindMeta(kind) {
  return TOPOLOGY_KIND_META[kind] || {icon: '•', label: kind || 'Object', column: 2};
}

function topologyStatusClass(status) {
  const s = String(status || '').toLowerCase();
  if (['online', 'connected', 'available', 'configured', 'enabled'].includes(s)) return 'ok';
  if (['failed', 'unresolved', 'offline', 'disabled'].includes(s)) return 'warn';
  return 'neutral';
}

function loadTopologyLayout() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DASHBOARD_TOPOLOGY_LAYOUT_KEY) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

function saveTopologyLayout(layout) {
  try { localStorage.setItem(DASHBOARD_TOPOLOGY_LAYOUT_KEY, JSON.stringify(layout || {})); } catch (_) {}
}

function defaultTopologyPositions(nodes, containerWidth = 920) {
  const lanes = [0, 1, 2, 3];
  const laneWidth = Math.max(210, Math.floor(Math.max(containerWidth, 880) / lanes.length));
  const counts = new Map();
  const positions = {};
  nodes.forEach((node) => {
    const col = topologyKindMeta(node.kind).column ?? 2;
    const idx = counts.get(col) || 0;
    counts.set(col, idx + 1);
    positions[node.id] = {
      x: 18 + col * laneWidth,
      y: 54 + idx * 96,
    };
  });
  return positions;
}

function effectiveTopologyPositions(nodes, container) {
  const saved = loadTopologyLayout();
  const defaults = defaultTopologyPositions(nodes, container?.clientWidth || 920);
  const positions = {};
  nodes.forEach((node) => {
    const item = saved[node.id];
    const fallback = defaults[node.id] || {x: 24, y: 64};
    const x = Number.isFinite(Number(item?.x)) ? Number(item.x) : fallback.x;
    const y = Number.isFinite(Number(item?.y)) ? Number(item.y) : fallback.y;
    positions[node.id] = {x: Math.max(0, x), y: Math.max(0, y)};
  });
  return positions;
}

function selectTopologyNode(node, graph) {
  document.querySelectorAll('.topology-node').forEach((el) => el.classList.toggle('selected', el.dataset.nodeId === node.id));
  const details = document.getElementById('dashboardTopologyDetails');
  if (!details) return;
  const incoming = (graph.edges || []).filter((edge) => edge.target === node.id);
  const outgoing = (graph.edges || []).filter((edge) => edge.source === node.id);
  const relatedLine = (edge, reverse = false) => {
    const otherId = reverse ? edge.source : edge.target;
    const other = (graph.nodes || []).find((item) => item.id === otherId);
    return `<li><b>${escapeHtml(edge.label || 'connected')}</b> ${escapeHtml(reverse ? 'from' : 'to')} ${escapeHtml(other?.label || otherId)}</li>`;
  };
  const meta = topologyKindMeta(node.kind);
  const data = node.data && typeof node.data === 'object' ? node.data : {};
  const compactData = Object.entries(data).filter(([_, value]) => value != null && typeof value !== 'object').slice(0, 8);
  details.innerHTML = `
    <div class="topology-detail-head"><span class="topology-icon">${escapeHtml(meta.icon)}</span><div><h3>${escapeHtml(node.label || node.id)}</h3><p>${escapeHtml(meta.label)} · ${escapeHtml(node.status || 'unknown')}</p></div></div>
    ${node.detail ? `<p class="muted small-text">${escapeHtml(node.detail)}</p>` : ''}
    <div class="topology-detail-section"><h4>Connections</h4>${incoming.length || outgoing.length ? `<ul>${incoming.map((edge) => relatedLine(edge, true)).join('')}${outgoing.map((edge) => relatedLine(edge, false)).join('')}</ul>` : '<p class="muted small-text">No links reported.</p>'}</div>
    ${compactData.length ? `<div class="topology-detail-section"><h4>Details</h4><dl>${compactData.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('')}</dl></div>` : ''}
    <div class="muted small-text">Object id: <code>${escapeHtml(node.id)}</code></div>`;
}

function drawTopologyEdges(container, graph) {
  const svg = container.querySelector('svg');
  if (!svg) return;
  const wrap = container.getBoundingClientRect();
  const nodes = new Map([...container.querySelectorAll('.topology-node')].map((el) => [el.dataset.nodeId, el]));
  const width = Math.max(1, container.scrollWidth, wrap.width);
  const height = Math.max(1, container.scrollHeight, wrap.height);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.innerHTML = '';
  (graph.edges || []).forEach((edge) => {
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    if (!source || !target) return;
    const a = source.getBoundingClientRect();
    const b = target.getBoundingClientRect();
    const x1 = a.left + a.width / 2 - wrap.left + container.scrollLeft;
    const y1 = a.top + a.height / 2 - wrap.top + container.scrollTop;
    const x2 = b.left + b.width / 2 - wrap.left + container.scrollLeft;
    const y2 = b.top + b.height / 2 - wrap.top + container.scrollTop;
    const dx = Math.max(48, Math.abs(x2 - x1) / 2);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + (x2 >= x1 ? dx : -dx)} ${y1}, ${x2 - (x2 >= x1 ? dx : -dx)} ${y2}, ${x2} ${y2}`);
    path.setAttribute('class', `topology-edge topology-edge-${String(edge.kind || 'connected').replace(/[^a-z0-9_-]/gi, '-')}`);
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = edge.label || 'connected';
    path.appendChild(title);
    svg.appendChild(path);
  });
}

function saveDraggedTopologyNode(nodeId, x, y) {
  const layout = loadTopologyLayout();
  layout[nodeId] = {x: Math.round(x), y: Math.round(y)};
  saveTopologyLayout(layout);
}

function setupTopologyNodeDrag(button, node, graph, container) {
  let start = null;
  button.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    start = {
      pointerId: ev.pointerId,
      x: ev.clientX,
      y: ev.clientY,
      left: parseFloat(button.style.left || '0'),
      top: parseFloat(button.style.top || '0'),
      dragging: false,
    };
    button.setPointerCapture?.(ev.pointerId);
  });
  button.addEventListener('pointermove', (ev) => {
    if (!start || start.pointerId !== ev.pointerId) return;
    const dx = ev.clientX - start.x;
    const dy = ev.clientY - start.y;
    if (!start.dragging && Math.hypot(dx, dy) < 4) return;
    start.dragging = true;
    button.classList.add('dragging');
    ev.preventDefault();
    const maxLeft = Math.max(0, container.scrollWidth - button.offsetWidth - 12);
    const maxTop = Math.max(0, container.scrollHeight - button.offsetHeight - 12);
    const left = Math.min(maxLeft, Math.max(8, start.left + dx));
    const top = Math.min(maxTop, Math.max(42, start.top + dy));
    button.style.left = `${left}px`;
    button.style.top = `${top}px`;
    drawTopologyEdges(container, graph);
  });
  button.addEventListener('pointerup', (ev) => {
    if (!start || start.pointerId !== ev.pointerId) return;
    const wasDragging = start.dragging;
    const left = parseFloat(button.style.left || '0');
    const top = parseFloat(button.style.top || '0');
    button.releasePointerCapture?.(ev.pointerId);
    button.classList.remove('dragging');
    start = null;
    if (wasDragging) {
      saveDraggedTopologyNode(node.id, left, top);
      drawTopologyEdges(container, graph);
    } else {
      selectTopologyNode(node, graph);
    }
  });
  button.addEventListener('pointercancel', () => {
    button.classList.remove('dragging');
    start = null;
  });
}

function renderDashboardTopology(graph) {
  const el = document.getElementById('dashboardTopologyMap');
  if (!el) return;
  const nodes = graph.nodes || [];
  if (!nodes.length) {
    el.textContent = 'No topology objects are configured yet.';
    return;
  }
  const positions = effectiveTopologyPositions(nodes, el);
  const maxY = Math.max(...Object.values(positions).map((pos) => pos.y), 260) + 110;
  const maxX = Math.max(...Object.values(positions).map((pos) => pos.x), 720) + 260;
  const lanes = ['Control', 'Use', 'Runtime', 'Infrastructure'];
  const laneWidth = Math.max(210, Math.floor(Math.max(maxX, 880) / lanes.length));
  el.classList.remove('muted');
  el.innerHTML = `
    <svg class="topology-lines" aria-hidden="true"></svg>
    <div class="topology-lane-labels" style="width:${Math.max(maxX, 880)}px">${lanes.map((title, index) => `<span style="left:${18 + index * laneWidth}px">${escapeHtml(title)}</span>`).join('')}</div>
    <div class="topology-freeform-layer" style="width:${Math.max(maxX, 880)}px; min-height:${Math.max(maxY, 420)}px">${nodes.map((node) => {
      const meta = topologyKindMeta(node.kind);
      const pos = positions[node.id] || {x: 24, y: 64};
      return `<button type="button" class="topology-node status-${topologyStatusClass(node.status)}" data-node-id="${escapeHtml(node.id)}" style="left:${pos.x}px;top:${pos.y}px"><span class="topology-icon">${escapeHtml(meta.icon)}</span><span class="topology-node-main"><b>${escapeHtml(node.label || node.id)}</b><small>${escapeHtml(meta.label)}${node.detail ? ` · ${escapeHtml(node.detail)}` : ''}</small></span><i>${escapeHtml(node.status || '')}</i></button>`;
    }).join('')}</div>`;
  el.querySelectorAll('.topology-node').forEach((btn) => {
    const node = nodes.find((item) => item.id === btn.dataset.nodeId);
    if (node) setupTopologyNodeDrag(btn, node, graph, el);
  });
  requestAnimationFrame(() => drawTopologyEdges(el, graph));
  window.setTimeout(() => drawTopologyEdges(el, graph), 200);
  if (nodes[0]) selectTopologyNode(nodes[0], graph);
}

async function loadDashboardTopology() {
  const el = document.getElementById('dashboardTopologyMap');
  try {
    const graph = await api('/v1/dashboard/topology');
    window.__pacDashboardTopology = graph;
    renderDashboardTopology(graph || {nodes: [], edges: []});
  } catch (e) {
    if (el) el.innerHTML = `<div class="muted">Could not load connection map: ${escapeHtml(e.message || e)}</div>`;
  }
}

function resetDashboardTopologyLayout() {
  try { localStorage.removeItem(DASHBOARD_TOPOLOGY_LAYOUT_KEY); } catch (_) {}
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
  if (!items.length) {
    panel.innerHTML = `${toolbar}<div class="notification-empty">No updates, approvals, alerts, or optimization notices need attention.</div>`;
  } else {
    panel.innerHTML = `${toolbar}${items.slice(0, 8).map((item) => `<button class="notification-item severity-${escapeHtml(item.severity || 'info')}" type="button" data-target="${escapeHtml(item.target || '')}"><span>${escapeHtml(item.kind || 'notice')}</span><b>${escapeHtml(item.title || 'Notification')}</b><small>${escapeHtml(item.detail || '')}</small></button>`).join('')}`;
  }
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
  await Promise.allSettled([
    api('/v1/updates/check'),
    api('/v1/sources/online-updates'),
  ]);
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
  window.addEventListener('resize', () => {
    const graph = window.__pacDashboardTopology;
    const el = document.getElementById('dashboardTopologyMap');
    if (graph && el && !el.hidden) drawTopologyEdges(el, graph);
  });
}
