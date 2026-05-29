// Endpoint inventory card renderer.
// Keeps the endpoint page presentation separate from endpoint loading/actions.

function endpointCardText(value, fallback = '-') {
  if (value === undefined || value === null || String(value).trim() === '') return fallback;
  return String(value);
}

function endpointCardList(values, fallback = '-') {
  const list = Array.isArray(values) ? values.filter(Boolean).map(v => String(v)) : [];
  return list.length ? list.join(', ') : fallback;
}

function endpointCardOs(endpoint) {
  const metadata = endpoint?.metadata || {};
  const labels = Array.isArray(endpoint?.labels) ? endpoint.labels : [];
  const raw = [metadata.os_family, metadata.os, metadata.workload_platform, metadata.onboarding_target, ...labels]
    .map(v => String(v || '').toLowerCase());
  if (raw.some(v => v.includes('windows') || v === 'win32' || v === 'win64')) return {id: 'windows', label: 'Windows', icon: '⊞'};
  if (raw.some(v => v.includes('darwin') || v.includes('macos') || v === 'mac')) return {id: 'darwin', label: 'macOS', icon: '⌘'};
  if (raw.some(v => v.includes('linux'))) return {id: 'linux', label: 'Linux', icon: '◧'};
  return {id: 'unknown', label: 'Unknown OS', icon: '◇'};
}

function endpointCardStatus(endpoint) {
  const online = endpoint?.status === 'online' || !!endpoint?.metadata?.local_control_plane;
  if (online) return {label: endpoint.status || 'online', tone: 'ok', detail: 'Reachable for controller-queued work'};
  if (endpoint?.status === 'maintenance') return {label: 'maintenance', tone: 'warn', detail: 'Maintenance mode'};
  return {label: endpoint?.status || 'offline', tone: 'danger', detail: 'Not reachable for new work'};
}

function endpointCardTime(value) {
  if (!value) return 'never';
  try { return new Date(value).toLocaleString(); } catch (_) { return String(value); }
}

function endpointCardCapability(label, state, detail, icon = '•') {
  const tone = state === 'ready' ? 'ok' : (state === 'attention' ? 'warn' : (state === 'blocked' ? 'danger' : 'neutral'));
  return `<div class="endpoint-capability endpoint-capability-${tone}" title="${escapeHtml(detail || label)}">
    <span class="endpoint-capability-icon">${escapeHtml(icon)}</span>
    <span><b>${escapeHtml(label)}</b><small>${escapeHtml(detail || '')}</small></span>
  </div>`;
}

function endpointCardCapabilities(endpoint, effectiveTools = [], helpers = {}) {
  const caps = endpoint?.capabilities || {};
  const metadata = endpoint?.metadata || {};
  const enablement = metadata.agent_enablement || {};
  const pi = helpers.endpointPiContainer ? helpers.endpointPiContainer(endpoint) : (metadata.agent_runtime?.pi_container || caps.pi_container || {});
  const online = endpoint.status === 'online' || metadata.local_control_plane;
  const hasWorkspace = !!metadata.default_workspace;
  const containers = Array.isArray(caps.container_runtimes) && caps.container_runtimes.length;
  const rce = metadata.remote_code_execution || caps.remote_code_execution || {};
  const os = endpointCardOs(endpoint);
  const shell = rce.default_shell || metadata.default_shell || (os.id === 'windows' ? 'PowerShell' : 'shell');
  const toolCount = (effectiveTools || []).length;
  const gpuCount = caps.gpu?.devices?.length || (caps.gpu?.available ? 1 : 0);
  const items = [];
  items.push(endpointCardCapability('Command channel', online ? 'ready' : 'blocked', online ? `${shell} jobs can be queued` : 'Endpoint must reconnect before commands can run', '↯'));
  items.push(endpointCardCapability('Default workspace', hasWorkspace ? 'ready' : 'attention', hasWorkspace ? metadata.default_workspace : 'Choose where workloads should land', '⌂'));
  items.push(endpointCardCapability('pi.dev runtime', pi?.available ? 'ready' : ((pi?.image_available || pi?.available) ? 'attention' : 'blocked'), pi?.available ? 'Ready for agent workloads' : (pi?.reason || 'Runtime not ready yet'), 'π'));
  items.push(endpointCardCapability('Container runtime', containers ? 'ready' : 'attention', containers ? caps.container_runtimes.join(', ') : 'No Docker/Podman runtime reported', '▣'));
  items.push(endpointCardCapability('Tool inventory', toolCount ? 'ready' : 'attention', toolCount ? `${toolCount} configured/discovered tools` : 'No endpoint tools reported yet', '⚙'));
  items.push(endpointCardCapability('Hardware acceleration', gpuCount ? 'ready' : 'neutral', gpuCount ? `${gpuCount} GPU device(s)` : 'CPU-only workload target', '✦'));
  return items.join('');
}

function endpointCardIdentityRows(endpoint, helpers = {}) {
  const metadata = endpoint?.metadata || {};
  const configuredTools = metadata.agent_tools || [];
  const discoveredTools = endpoint?.capabilities?.tools ? Object.entries(endpoint.capabilities.tools).filter(([_, v]) => v.available).map(([k]) => k) : [];
  const effectiveTools = configuredTools.length ? configuredTools : discoveredTools;
  const packages = (metadata.tool_packages || (helpers.packageNamesForTools ? helpers.packageNamesForTools(effectiveTools) : [])).join(', ') || '-';
  const defaultWorkspace = metadata.default_workspace || helpers.defaultWorkspace || '-';
  return [
    ['Directory principal', metadata.directory_principal_id || `endpoint:${endpoint.id}`],
    ['Default workspace', defaultWorkspace],
    ['Tool packages', packages],
    ['Labels', endpointCardList(endpoint.labels || [])],
    ['Models pinned here', helpers.modelLinks || '-'],
    ['Last heartbeat', endpointCardTime(endpoint.last_seen_at)],
  ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><code>${escapeHtml(endpointCardText(value))}</code></div>`).join('');
}

function endpointCardTechnicalDetails(endpoint, helpers = {}) {
  const metadata = endpoint?.metadata || {};
  const runtimeLines = helpers.endpointRuntimeLines ? helpers.endpointRuntimeLines(endpoint) : '';
  const tools = helpers.tools || '-';
  const containers = helpers.containers || 'No running containers reported.';
  return `<details class="endpoint-technical">
    <summary>Technical inventory</summary>
    <div class="endpoint-detail-grid">${endpointCardIdentityRows(endpoint, helpers)}</div>
    <pre>${escapeHtml(runtimeLines)}</pre>
    <div class="muted small-text">pi.dev: ${escapeHtml(metadata.agent_enablement?.detail || '-')}</div>
    <div class="muted small-text">tools: ${escapeHtml(tools)}</div>
    <pre>${escapeHtml(containers)}</pre>
  </details>`;
}

function endpointCardAction(label, className, disabled, onClick) {
  const button = document.createElement('button');
  button.textContent = label;
  button.className = className || 'ghost-button';
  button.disabled = !!disabled;
  button.onclick = onClick;
  return button;
}

function renderEndpointInventoryCard(endpoint, options = {}) {
  const helpers = options.helpers || {};
  const actions = options.actions || {};
  const metadata = endpoint?.metadata || {};
  const os = endpointCardOs(endpoint);
  const status = endpointCardStatus(endpoint);
  const hardware = helpers.endpointHardware ? helpers.endpointHardware(endpoint) : {cpu: '-', cores: '-', ram: '-', disk: '-', gpu: '-'};
  const configuredTools = metadata.agent_tools || [];
  const discoveredTools = endpoint?.capabilities?.tools ? Object.entries(endpoint.capabilities.tools).filter(([_, v]) => v.available).map(([k]) => k) : [];
  const effectiveTools = configuredTools.length ? configuredTools : discoveredTools;
  const version = metadata.runner_version || metadata.endpoint_version || metadata.agent_runtime?.version || '-';
  const containers = (endpoint.containers || []).slice(0, 4).map(helpers.compactContainerLine || (c => String(c))).join('\n');
  const defaultWorkspace = metadata.default_workspace || helpers.defaultWorkspace || '-';
  const modelLinks = helpers.modelLinks || '-';
  const pi = helpers.endpointPiContainer ? helpers.endpointPiContainer(endpoint) : (metadata.agent_runtime?.pi_container || endpoint?.capabilities?.pi_container || {});
  const piMissing = pi && !(pi.image_available || pi.available);
  const online = endpoint.status === 'online' || metadata.local_control_plane;
  const agentState = metadata.agent_enablement?.status || metadata.agent_runtime?.status || 'unknown';

  const card = document.createElement('article');
  card.className = `endpoint-inventory-card endpoint-os-${os.id} endpoint-status-${status.tone}`;
  card.dataset.endpointId = endpoint.id || '';
  card.innerHTML = `
    <header class="endpoint-card-header">
      <div class="endpoint-card-main">
        <div class="endpoint-os-icon" aria-hidden="true">${escapeHtml(os.icon)}</div>
        <div>
          <h3>${escapeHtml(endpoint.name || endpoint.id || 'Endpoint')}</h3>
          <p>${escapeHtml(os.label)} workload endpoint · ${escapeHtml(endpoint.id || '-')}</p>
        </div>
      </div>
      <div class="endpoint-status-block">
        <span class="endpoint-status-badge endpoint-status-badge-${status.tone}"><i></i>${escapeHtml(status.label)}</span>
        <small>${escapeHtml(status.detail)}</small>
      </div>
    </header>
    <section class="endpoint-card-summary">
      <div><span>Version</span><b>${escapeHtml(version)}</b></div>
      <div><span>Workspace</span><b>${escapeHtml(defaultWorkspace)}</b></div>
      <div><span>Models</span><b>${escapeHtml(modelLinks || '-')}</b></div>
      <div><span>Agent runtime</span><b>${escapeHtml(agentState)}</b></div>
    </section>
    <section class="endpoint-capability-grid">
      ${endpointCardCapabilities(endpoint, effectiveTools, helpers)}
    </section>
    <section class="endpoint-hardware-strip">
      <div><span>CPU</span><b>${escapeHtml(hardware.cpu)}</b><small>${escapeHtml(hardware.cores)} threads</small></div>
      <div><span>GPU</span><b>${escapeHtml(hardware.gpu)}</b></div>
      <div><span>Memory</span><b>${escapeHtml(hardware.ram)}</b></div>
      <div><span>Disk</span><b>${escapeHtml(hardware.disk)}</b></div>
    </section>
    ${endpointCardTechnicalDetails(endpoint, {...helpers, tools: effectiveTools.length ? effectiveTools.join(', ') : '-', containers: containers || 'No running containers reported.', defaultWorkspace, modelLinks})}
    <div class="endpoint-card-alerts">
      ${metadata.update_status ? `<span class="endpoint-alert-chip">Update: ${escapeHtml(metadata.update_status)}</span>` : ''}
      ${metadata.maintenance_status ? `<span class="endpoint-alert-chip">Maintenance: ${escapeHtml(metadata.maintenance_status)}</span>` : ''}
      ${piMissing ? '<span class="endpoint-alert-chip endpoint-alert-warning">pi.dev image missing</span>' : ''}
    </div>`;

  const actionRow = document.createElement('div');
  actionRow.className = 'endpoint-card-actions';
  actionRow.appendChild(endpointCardAction('Details', 'ghost-button', false, () => actions.details?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Edit', 'ghost-button', false, () => actions.edit?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Command', 'ghost-button', !online, () => actions.command?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Install Node.js', 'ghost-button', metadata.agent_enablement?.node_available || !online, () => actions.installNode?.(endpoint)));
  if (metadata.local_control_plane) {
    actionRow.appendChild(endpointCardAction('Build/install controller pi.dev', 'ghost-button', false, () => actions.bootstrapController?.(endpoint)));
  }
  actionRow.appendChild(endpointCardAction('Install pi.dev', 'ghost-button', !piMissing || !online, () => actions.installPi?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Update', 'ghost-button', !online || !!metadata.local_control_plane, () => actions.update?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Maintenance', 'ghost-button', !online, () => actions.maintenance?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Dry run', 'ghost-button', !online, () => actions.dryRun?.(endpoint)));
  actionRow.appendChild(endpointCardAction('Delete', 'danger-button', false, () => actions.delete?.(endpoint)));
  card.appendChild(actionRow);
  return card;
}
