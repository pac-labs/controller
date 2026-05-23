// Endpoint inventory action callbacks.
// Kept separate so endpoint rendering and loading do not grow with command handlers.

function endpointLocalStatusBox() {
  return document.getElementById('localDiscovery');
}

async function endpointActionRefreshEvents() {
  await loadGlobalEvents(true).catch(()=>{});
}

function endpointModalShell(id, title, subtitle = '') {
  document.getElementById(id)?.remove();
  const modal = document.createElement('div');
  modal.id = id;
  modal.className = 'modal-backdrop endpoint-progress-backdrop';
  modal.innerHTML = `<section class="modal-card endpoint-progress-modal" role="dialog" aria-modal="true">
    <div class="section-heading">
      <div><h2>${escapeHtml(title)}</h2>${subtitle ? `<p class="muted">${escapeHtml(subtitle)}</p>` : ''}</div>
      <button class="ghost-button" data-close>Close</button>
    </div>
    <div class="endpoint-progress-body"></div>
  </section>`;
  modal.querySelector('[data-close]').onclick = () => modal.remove();
  modal.onclick = (ev) => { if (ev.target === modal) modal.remove(); };
  document.body.appendChild(modal);
  return modal;
}

function endpointJobStatusTone(status) {
  const value = String(status || '').toLowerCase();
  if (['completed', 'success'].includes(value)) return 'ok';
  if (['failed', 'cancelled'].includes(value)) return 'danger';
  if (['running', 'claimed', 'queued'].includes(value)) return 'warn';
  return 'info';
}

function endpointJobProgressHtml(detail) {
  const job = detail?.job || detail || {};
  const endpoint = detail?.endpoint || {};
  const events = detail?.events || [];
  const tone = endpointJobStatusTone(job.status);
  const eventRows = events.length ? events.map(event => `<li><span>${escapeHtml(formatDate(event.created_at))}</span><b>${escapeHtml(event.type || 'event')}</b><p>${escapeHtml(event.message || '')}</p></li>`).join('') : '<li class="muted">No endpoint events have been reported for this job yet.</li>';
  const activeLoader = ['running', 'claimed', 'queued'].includes(String(job.status || '').toLowerCase()) ? pacLoaderIconHtml('small', 'Endpoint job running') : '';
  const command = job.command ? `<pre>${escapeHtml(job.command)}</pre>` : '<p class="muted small-text">No direct command payload. The endpoint interprets this as a managed operation.</p>';
  return `<div class="endpoint-progress-state endpoint-progress-${tone}">
      ${activeLoader}
      <span>${escapeHtml(job.status || 'queued')}</span>
      <b>${escapeHtml(job.prompt || 'Endpoint job')}</b>
      <small>${escapeHtml(endpoint.name || job.runner_id || '')}</small>
    </div>
    <div class="endpoint-progress-grid">
      <div><span>Job</span><code>${escapeHtml(job.id || '-')}</code></div>
      <div><span>Endpoint</span><code>${escapeHtml(job.runner_id || '-')}</code></div>
      <div><span>Mode</span><code>${escapeHtml(job.execution_mode || '-')}</code></div>
      <div><span>Shell</span><code>${escapeHtml(job.metadata?.shell || job.metadata?.command_channel || '-')}</code></div>
      <div><span>Created</span><code>${escapeHtml(formatDate(job.created_at))}</code></div>
      <div><span>Updated</span><code>${escapeHtml(formatDate(job.updated_at))}</code></div>
      <div><span>Exit code</span><code>${escapeHtml(job.exit_code ?? '-')}</code></div>
      <div><span>Operation</span><code>${escapeHtml(job.metadata?.operation || '-')}</code></div>
    </div>
    <details open><summary>Command / operation</summary>${command}</details>
    ${job.output ? `<details open><summary>Output</summary><pre>${escapeHtml(job.output)}</pre></details>` : ''}
    ${job.error ? `<details open><summary>Error</summary><pre>${escapeHtml(job.error)}</pre></details>` : ''}
    <details open><summary>Progress events</summary><ul class="endpoint-progress-events">${eventRows}</ul></details>`;
}

function watchEndpointJob(job, options = {}) {
  if (!job?.id) return;
  const modal = endpointModalShell('endpointJobProgressModal', options.title || 'Endpoint job progress', options.subtitle || job.prompt || job.id);
  const body = modal.querySelector('.endpoint-progress-body');
  let stopped = false;
  modal.addEventListener('DOMNodeRemoved', () => { stopped = true; }, {once:true});
  const render = async () => {
    try {
      const detail = await api(`/v1/runner-jobs/${encodeURIComponent(job.id)}`);
      if (body) body.innerHTML = endpointJobProgressHtml(detail);
      const status = String(detail?.job?.status || '').toLowerCase();
      if (!['completed', 'failed', 'cancelled'].includes(status) && !stopped) setTimeout(render, 2000);
      if (['completed', 'failed', 'cancelled'].includes(status)) {
        await endpointActionRefreshEvents();
        await loadRunners().catch(()=>{});
      }
    } catch (e) {
      if (body) body.innerHTML = `<div class="inline-result">Failed to load job progress: ${escapeHtml(e.message)}</div>`;
    }
  };
  if (body) body.innerHTML = endpointJobProgressHtml({job, events: []});
  setTimeout(render, 600);
}

async function openEndpointDetailsModal(endpoint) {
  const modal = endpointModalShell('endpointDetailsModal', endpoint.name || endpoint.id || 'Endpoint details', 'Current inventory, queued jobs, and operational diagnostics.');
  const body = modal.querySelector('.endpoint-progress-body');
  const jobs = await api(`/v1/runner-jobs?runner_id=${encodeURIComponent(endpoint.id)}`).catch(() => []);
  const obs = await api('/v1/system/observability').catch(() => null);
  const metadata = endpoint.metadata || {};
  const caps = endpoint.capabilities || {};
  const jobRows = (jobs || []).slice(0, 8).map(job => `<tr><td>${escapeHtml(job.status)}</td><td>${escapeHtml(job.prompt || '-')}</td><td><code>${escapeHtml(job.id)}</code></td><td>${escapeHtml(formatDate(job.updated_at))}</td><td><button class="ghost-button mini-button" data-watch-job="${escapeHtml(job.id)}">Open</button></td></tr>`).join('') || '<tr><td colspan="5" class="muted">No jobs recorded for this endpoint.</td></tr>';
  body.innerHTML = `<div class="endpoint-detail-console">
    <section><h3>Identity</h3><div class="endpoint-progress-grid">
      <div><span>ID</span><code>${escapeHtml(endpoint.id || '-')}</code></div>
      <div><span>Status</span><code>${escapeHtml(endpoint.status || '-')}</code></div>
      <div><span>OS family</span><code>${escapeHtml(metadata.os_family || metadata.onboarding_target || '-')}</code></div>
      <div><span>Directory principal</span><code>${escapeHtml(metadata.directory_principal_id || `endpoint:${endpoint.id}`)}</code></div>
      <div><span>Last seen</span><code>${escapeHtml(formatDate(endpoint.last_seen_at))}</code></div>
      <div><span>Default workspace</span><code>${escapeHtml(metadata.default_workspace || '-')}</code></div>
    </div></section>
    <section><h3>pi.dev / command channel</h3><div class="endpoint-progress-grid">
      <div><span>Agent status</span><code>${escapeHtml(metadata.agent_enablement?.status || metadata.agent_runtime?.status || '-')}</code></div>
      <div><span>Detail</span><code>${escapeHtml(metadata.agent_enablement?.detail || '-')}</code></div>
      <div><span>Host execution</span><code>${endpoint.allow_host_execution ? 'allowed' : 'disabled'}</code></div>
      <div><span>Container execution</span><code>${endpoint.allow_container_execution ? 'allowed' : 'disabled'}</code></div>
    </div></section>
    <section><h3>Recent endpoint jobs</h3><table class="endpoint-job-table"><thead><tr><th>Status</th><th>Operation</th><th>Job</th><th>Updated</th><th></th></tr></thead><tbody>${jobRows}</tbody></table></section>
    <section><h3>Raw inventory</h3><details><summary>Metadata</summary><pre>${escapeHtml(JSON.stringify(metadata, null, 2))}</pre></details><details><summary>Capabilities</summary><pre>${escapeHtml(JSON.stringify(caps, null, 2))}</pre></details></section>
    <section><h3>Controller observability</h3><p class="muted small-text">${escapeHtml(obs?.recommendation || 'Rotating controller logs are available from the System observability endpoint.')}</p><code>${escapeHtml(obs?.logging?.log_dir || '')}</code></section>
  </div>`;
  body.querySelectorAll('[data-watch-job]').forEach(btn => {
    btn.onclick = async () => {
      const detail = await api(`/v1/runner-jobs/${encodeURIComponent(btn.dataset.watchJob)}`);
      watchEndpointJob(detail.job, {title:'Endpoint job progress', subtitle: detail.job.prompt || detail.job.id});
    };
  });
}

async function queueEndpointAction(endpoint, path, payload, options = {}) {
  const result = await api(path, {method:'POST', body:JSON.stringify(payload || {})});
  if (result?.id && result?.runner_id) {
    watchEndpointJob(result, {title: options.title || 'Endpoint operation progress', subtitle: `${endpoint.name || endpoint.id} · ${result.prompt || result.id}`});
  } else {
    const modal = endpointModalShell('endpointJobProgressModal', options.title || 'Endpoint operation result', endpoint.name || endpoint.id);
    modal.querySelector('.endpoint-progress-body').innerHTML = `<pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  }
  await loadRunners().catch(()=>{});
  await endpointActionRefreshEvents();
  return result;
}

function endpointInventoryCardActions() {
  return {
    details: endpoint => openEndpointDetailsModal(endpoint),
    edit: endpoint => openEndpointModal(endpoint.id),
    command: endpoint => openEndpointCommandModal(endpoint.id),
    installNode: async endpoint => {
      if (!confirm(`Install Node.js on ${endpoint.name}?`)) return;
      const status = endpointLocalStatusBox();
      if (status) status.textContent = 'Node.js install requested. A progress modal is open.';
      const res = await queueEndpointAction(endpoint, `/v1/endpoints/${endpoint.id}/install-node`, {method:'auto'}, {title:'Install Node.js'});
      emitUiEvent('endpoint_node_install_requested', `Node.js install requested: ${endpoint.name}`, res);
    },
    bootstrapController: async () => {
      const res = await api('/v1/controller-harness/bootstrap', {method:'POST'});
      emitUiEvent('controller_pi_dev_bootstrap_requested', 'Controller pi.dev bootstrap started', res);
      await endpointActionRefreshEvents();
      await loadRunners();
    },
    installPi: async endpoint => {
      const piContainer = endpointPiContainer(endpoint);
      const image = piContainer.image || 'localhost/pi-agent-harness:stage11';
      const status = endpointLocalStatusBox();
      if (status) status.textContent = 'pi.dev install started. A progress modal is open.';
      const res = await queueEndpointAction(endpoint, `/v1/endpoints/${endpoint.id}/install-pi-harness`, {image, runtime:'auto'}, {title:'Install pi.dev'});
      emitUiEvent('endpoint_pi_harness_install_requested', `pi.dev install started: ${endpoint.name}`, res);
    },
    update: async endpoint => {
      if (!confirm(`Queue software update for ${endpoint.name}?`)) return;
      await queueEndpointAction(endpoint, `/v1/endpoints/${endpoint.id}/update`, {restart:true}, {title:'Endpoint software update'});
    },
    maintenance: async endpoint => {
      if (!confirm(`Run safe PAC maintenance cleanup on ${endpoint.name}?`)) return;
      await queueEndpointAction(endpoint, `/v1/endpoints/${endpoint.id}/maintenance`, {max_age_hours:24,dry_run:false,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false}, {title:'Endpoint maintenance'});
    },
    dryRun: async endpoint => {
      await queueEndpointAction(endpoint, `/v1/endpoints/${endpoint.id}/maintenance`, {max_age_hours:24,dry_run:true,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false}, {title:'Endpoint maintenance dry run'});
    },
    delete: async endpoint => {
      if (!confirm(`Delete endpoint ${endpoint.name}?`)) return;
      await api(`/v1/endpoints/${endpoint.id}`, {method:'DELETE'});
      await loadRunners();
    },
  };
}
