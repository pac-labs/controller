// User workspace catalog rendering and workspace form actions.
function renderWorkspaces() {
  const el = document.getElementById('workspaces');
  const personalEl = document.getElementById('personalWorkspaces');
  const templateSelect = document.getElementById('userWorkspaceTemplate');
  const workspaceSelect = document.getElementById('userWorkspaceSelect');
  const storageSelect = document.getElementById('userWorkspaceSharedStorage');
  const endpointSelect = document.getElementById('userWorkspaceEndpoint');
  const profileSelect = document.getElementById('userWorkspaceAgentProfile');
  const modelSelect = document.getElementById('userWorkspaceModel');
  if (templateSelect) {
    templateSelect.innerHTML = '<option value="">None</option>' + workspaceTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (workspaceSelect) {
    workspaceSelect.innerHTML = '<option value="">New workspace</option>' + ideWorkspaces().map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    if (selectedIdeWorkspaceId && ideWorkspaces().some((item) => item.id === selectedIdeWorkspaceId)) workspaceSelect.value = selectedIdeWorkspaceId;
  }
  if (storageSelect) {
    storageSelect.innerHTML = '<option value="">none</option>' + (sharedStorages || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }
  if (endpointSelect) {
    endpointSelect.innerHTML = '<option value="">auto</option>';
    (window.__pacEndpoints || []).forEach((runner) => opt(endpointSelect, runner.id, `${runner.name || runner.id} (${runner.status || 'unknown'})`));
  }
  if (profileSelect) {
    profileSelect.innerHTML = '<option value="">default</option>';
    Object.entries(config.agent_profiles || {}).forEach(([name]) => opt(profileSelect, name));
  }
  if (modelSelect) {
    modelSelect.innerHTML = '<option value="">default</option>';
    Object.keys(config.models || {}).forEach((name) => { if (modelAvailability(name).ok) opt(modelSelect, name); });
  }
  if (personalEl) {
    personalEl.innerHTML = ideWorkspaces().map((item) => {
      const target = item.path || item.url || item.workspace_profile || '-';
      const templateName = item.template?.name || item.template_id || 'custom';
      const storage = item.shared_storage?.name || storageNameById(item.shared_storage_id);
      return `<div class="workspace-card clickable-row ${item.id === selectedIdeWorkspaceId ? 'selected' : ''}" data-user-workspace="${escapeHtml(item.id)}">
        <div class="workspace-card-title"><b>${escapeHtml(item.name)}</b><span>${item.pinned ? 'pinned' : templateName}</span></div>
        <div class="workspace-card-grid">
          <div><small>type</small><b>${escapeHtml(item.workspace_type || 'local')}</b></div>
          <div><small>storage</small><b>${escapeHtml(storage || '-')}</b></div>
          <div><small>endpoint</small><b>${escapeHtml(item.endpoint_id || 'auto')}</b></div>
          <div><small>profile</small><b>${escapeHtml(item.agent_profile || 'default')}</b></div>
          <div><small>session</small><b>${escapeHtml(item.last_session_id ? 'attached' : 'none')}</b></div>
        </div>
        <code>${escapeHtml(item.description || '')}${item.description ? '\n' : ''}target: ${escapeHtml(target)}\nstorage path: ${escapeHtml(item.storage_subpath || '-')}</code>
      </div>`;
    }).join('') || '<div class="muted">No personal workspaces yet. Create one from a template above.</div>';
    personalEl.querySelectorAll('[data-user-workspace]').forEach((row) => {
      row.onclick = () => fillUserWorkspaceForm(row.getAttribute('data-user-workspace') || '');
    });
  }
  if (!el) return;
  el.innerHTML = '';
  for (const [name,w] of Object.entries(config.workspaces || {})) {
    const lifecycle = w.ephemeral ? `ephemeral${w.ttl_hours ? `, ${w.ttl_hours}h TTL` : ''}` : 'persistent';
    const placement = w.endpoint_id || w.endpoint_selector || 'select at runtime';
    const data = w.data_bundle_url || w.data_bundle_path || 'none';
    const storage = storageNameById(w.shared_storage_id);
    const row = document.createElement('div');
    row.className = 'workspace-card clickable-row';
    row.innerHTML = `<div class="workspace-card-title"><b>${escapeHtml(name)}</b><span>${escapeHtml(lifecycle)}</span></div>
      <div class="workspace-card-grid">
        <div><small>type</small><b>${escapeHtml(w.type || 'local')}</b></div>
        <div><small>runtime</small><b>${escapeHtml(w.runtime || 'any')}</b></div>
        <div><small>placement</small><b>${escapeHtml(placement)}</b></div>
        <div><small>storage</small><b>${escapeHtml(storage || '-')}</b></div>
        <div><small>profile</small><b>${escapeHtml(w.default_agent_profile || '-')}</b></div>
      </div>
      <code>${escapeHtml(w.description || '')}${w.description ? '\n' : ''}path: ${escapeHtml(w.path || '-')}\nurl: ${escapeHtml(w.url || '-')}\nbranch: ${escapeHtml(w.branch || '-')}\ncontainer: ${escapeHtml(w.container_image || '-')}\nstorage subpath: ${escapeHtml(w.storage_subpath || '-')}\nmount: ${escapeHtml(w.storage_mount_path || '-')}\ndata zip: ${escapeHtml(data)}\ndata path: ${escapeHtml(w.data_mount_path || '-')}\ndefault: ${w.is_default ? 'yes' : 'no'}</code>`;
    row.onclick = () => fillWorkspaceForm(name);
    el.appendChild(row);
  }
  renderWorkspaceActivityPanel();
  if (selectedIdeWorkspaceId && !document.getElementById('userWorkspaceSelect')?.value) {
    fillUserWorkspaceForm(selectedIdeWorkspaceId);
  }
}

function fillUserWorkspaceForm(id='') {
  const item = ideWorkspaces().find((workspace) => workspace.id === id);
  selectedIdeWorkspaceId = item?.id || '';
  const set = (fieldId, value='') => { const el = document.getElementById(fieldId); if (el) el.value = value ?? ''; };
  set('userWorkspaceSelect', item?.id || '');
  set('userWorkspaceName', item?.name || '');
  set('userWorkspaceDescription', item?.description || '');
  set('userWorkspaceTemplate', item?.template_id || '');
  set('userWorkspaceType', item?.workspace_type || 'local');
  set('userWorkspaceProfile', item?.workspace_profile || '');
  set('userWorkspacePath', item?.path || '');
  set('userWorkspaceUrl', item?.url || '');
  set('userWorkspaceBranch', item?.branch || '');
  set('userWorkspaceSharedStorage', item?.shared_storage_id || '');
  set('userWorkspaceStorageSubpath', item?.storage_subpath || '');
  set('userWorkspaceStorageMountPath', item?.storage_mount_path || '');
  set('userWorkspaceEndpoint', item?.endpoint_id || '');
  set('userWorkspaceContainerImage', item?.container_image || '');
  set('userWorkspaceAgentProfile', item?.agent_profile || '');
  set('userWorkspaceModel', item?.model || '');
  const pinned = document.getElementById('userWorkspacePinned'); if (pinned) pinned.checked = !!item?.pinned;
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
}

function userWorkspaceFormPayload() {
  return {
    name: (document.getElementById('userWorkspaceName')?.value || '').trim(),
    description: (document.getElementById('userWorkspaceDescription')?.value || '').trim() || null,
    template_id: document.getElementById('userWorkspaceTemplate')?.value || null,
    workspace_type: document.getElementById('userWorkspaceType')?.value || 'local',
    workspace_profile: (document.getElementById('userWorkspaceProfile')?.value || '').trim() || null,
    path: (document.getElementById('userWorkspacePath')?.value || '').trim() || null,
    url: (document.getElementById('userWorkspaceUrl')?.value || '').trim() || null,
    branch: (document.getElementById('userWorkspaceBranch')?.value || '').trim() || null,
    shared_storage_id: document.getElementById('userWorkspaceSharedStorage')?.value || null,
    storage_subpath: (document.getElementById('userWorkspaceStorageSubpath')?.value || '').trim() || null,
    storage_mount_path: (document.getElementById('userWorkspaceStorageMountPath')?.value || '').trim() || null,
    endpoint_id: document.getElementById('userWorkspaceEndpoint')?.value || null,
    container_image: (document.getElementById('userWorkspaceContainerImage')?.value || '').trim() || null,
    agent_profile: document.getElementById('userWorkspaceAgentProfile')?.value || null,
    model: document.getElementById('userWorkspaceModel')?.value || null,
    pinned: !!document.getElementById('userWorkspacePinned')?.checked,
  };
}

async function saveUserWorkspaceFromForm() {
  const payload = userWorkspaceFormPayload();
  if (!payload.name) return alert('Workspace name is required');
  const existingId = document.getElementById('userWorkspaceSelect')?.value || '';
  const path = existingId ? `/v1/my-workspaces/${encodeURIComponent(existingId)}` : '/v1/my-workspaces';
  const method = existingId ? 'PUT' : 'POST';
  const result = await api(path, {method, body: JSON.stringify(payload)});
  await loadWorkspaceCatalogs();
  const workspace = result.workspace || null;
  selectedIdeWorkspaceId = workspace?.id || selectedIdeWorkspaceId;
  fillUserWorkspaceForm(selectedIdeWorkspaceId || '');
  renderWorkspaces();
  showInline('userWorkspaceFormResult', `Saved workspace ${payload.name}`);
}

async function deleteUserWorkspaceFromForm() {
  const id = document.getElementById('userWorkspaceSelect')?.value || '';
  if (!id) return alert('Select an existing personal workspace first');
  if (!confirm('Delete this personal workspace?')) return;
  await api(`/v1/my-workspaces/${encodeURIComponent(id)}`, {method:'DELETE'});
  await loadWorkspaceCatalogs();
  selectedIdeWorkspaceId = '';
  fillUserWorkspaceForm('');
  renderWorkspaces();
  showInline('userWorkspaceFormResult', 'Workspace deleted');
}

async function openUserWorkspaceInIde() {
  const id = document.getElementById('userWorkspaceSelect')?.value || selectedIdeWorkspaceId || '';
  if (!id) return alert('Select a personal workspace first');
  selectedIdeWorkspaceId = id;
  selectedIdeSessionId = '';
  sourceCodingSessionId = '';
  sourceTreeCache.clear();
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  switchToTab('sources-tab');
  await renderSources('');
}

function workspaceValue(id) { return document.getElementById(id)?.value?.trim() || ''; }

function workspaceChecked(id) { return !!document.getElementById(id)?.checked; }

function fillWorkspaceForm(name) {
  const w = config.workspaces?.[name]; if (!w) return;
  workspaceName.value = name;
  if (document.getElementById('workspaceDescription')) workspaceDescription.value = w.description || '';
  workspaceType.value = w.type || 'local';
  if (document.getElementById('workspaceRuntime')) workspaceRuntime.value = w.runtime || 'any';
  workspacePath.value = w.path || ''; workspaceUrl.value = w.url || ''; workspaceBranch.value = w.branch || '';
  if (document.getElementById('workspaceSharedStorage')) workspaceSharedStorage.value = w.shared_storage_id || '';
  if (document.getElementById('workspaceStorageSubpath')) workspaceStorageSubpath.value = w.storage_subpath || '';
  if (document.getElementById('workspaceStorageMountPath')) workspaceStorageMountPath.value = w.storage_mount_path || '';
  if (document.getElementById('workspaceContainerImage')) workspaceContainerImage.value = w.container_image || '';
  workspaceDefaultProfile.value = w.default_agent_profile || '';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.value = w.endpoint_id || '';
  if (document.getElementById('workspaceEndpointSelector')) workspaceEndpointSelector.value = w.endpoint_selector || '';
  if (document.getElementById('workspaceDataUrl')) workspaceDataUrl.value = w.data_bundle_url || '';
  if (document.getElementById('workspaceDataPath')) workspaceDataPath.value = w.data_bundle_path || '';
  if (document.getElementById('workspaceDataMount')) workspaceDataMount.value = w.data_mount_path || '';
  if (document.getElementById('workspaceTtlHours')) workspaceTtlHours.value = w.ttl_hours || '';
  if (document.getElementById('workspaceEphemeral')) workspaceEphemeral.checked = !!w.ephemeral;
  if (document.getElementById('workspaceDeleteOnExpire')) workspaceDeleteOnExpire.checked = w.delete_on_expire !== false;
  if (document.getElementById('workspaceIsDefault')) workspaceIsDefault.checked = !!w.is_default;
}

async function saveWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name) return alert('Workspace name is required');
  const body = {
    description: workspaceValue('workspaceDescription') || null,
    type: workspaceType.value || 'local',
    runtime: workspaceValue('workspaceRuntime') || 'any',
    path: workspacePath.value.trim() || null,
    url: workspaceUrl.value.trim() || null,
    branch: workspaceBranch.value.trim() || null,
    shared_storage_id: workspaceValue('workspaceSharedStorage') || null,
    storage_subpath: workspaceValue('workspaceStorageSubpath') || null,
    storage_mount_path: workspaceValue('workspaceStorageMountPath') || null,
    container_image: workspaceValue('workspaceContainerImage') || null,
    default_agent_profile: workspaceDefaultProfile.value || null,
    endpoint_id: document.getElementById('workspaceEndpoint')?.value || null,
    endpoint_selector: workspaceValue('workspaceEndpointSelector') || null,
    data_bundle_url: workspaceValue('workspaceDataUrl') || null,
    data_bundle_path: workspaceValue('workspaceDataPath') || null,
    data_mount_path: workspaceValue('workspaceDataMount') || null,
    ephemeral: workspaceChecked('workspaceEphemeral'),
    ttl_hours: workspaceValue('workspaceTtlHours') || null,
    delete_on_expire: workspaceChecked('workspaceDeleteOnExpire'),
    is_default: !!document.getElementById('workspaceIsDefault')?.checked,
  };
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'PUT', body:JSON.stringify(body)});
  await loadConfig();
  showInline('workspaceFormResult', `Saved workspace ${name}`);
}

async function deleteWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name || !config.workspaces?.[name]) return alert('Select an existing workspace first');
  if (!confirm(`Delete workspace ${name}?`)) return;
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadConfig();
  showInline('workspaceFormResult', `Deleted workspace ${name}`);
}


function openWorkspaceLiveTerminal(workspaceId) {
  if (!workspaceId) return;
  const modal = endpointModalShell ? endpointModalShell('workspaceLiveTerminalModal', `Workspace terminal: ${workspaceId}`, 'Commands are routed through PAC, streamed live, and retained in command history.') : null;
  if (!modal) return;
  modal.classList.add('workspace-terminal-modal');
  const body = modal.querySelector('.endpoint-progress-body');
  body.innerHTML = `<div class="workspace-terminal">
    <textarea class="workspace-terminal-command" placeholder="Enter a shell command, for example: pwd && ls -la"></textarea>
    <div class="workspace-terminal-toolbar">
      <button class="primary-button" data-terminal-run>Run and stream</button>
      <button class="ghost-button" data-terminal-interrupt disabled>Interrupt</button>
      <button class="ghost-button" data-terminal-refresh>Refresh history</button>
      <span class="muted small-text" data-terminal-status>Ready.</span>
    </div>
    <div class="workspace-terminal-layout">
      <div class="workspace-terminal-history" data-terminal-history><div class="muted small-text">Loading command history...</div></div>
      <pre class="workspace-terminal-output" data-terminal-output></pre>
    </div>
  </div>`;
  const commandEl = body.querySelector('[data-terminal-run]');
  const interruptEl = body.querySelector('[data-terminal-interrupt]');
  const refreshEl = body.querySelector('[data-terminal-refresh]');
  const textEl = body.querySelector('.workspace-terminal-command');
  const outEl = body.querySelector('[data-terminal-output]');
  const statusEl = body.querySelector('[data-terminal-status]');
  const historyEl = body.querySelector('[data-terminal-history]');
  let activeCommandId = '';
  let streamAbort = null;
  const appendOutput = (stream, data) => {
    if (!data || data === '<nil>') return;
    outEl.textContent += stream === 'stderr' ? `[stderr] ${data}` : data;
    outEl.scrollTop = outEl.scrollHeight;
  };
  const loadCommandEvents = async (commandId) => {
    if (!commandId) return;
    outEl.textContent = '';
    statusEl.textContent = `Loading history ${commandId}...`;
    const result = await api(`/v1/workspaces/${encodeURIComponent(workspaceId)}/commands/${encodeURIComponent(commandId)}/events?limit=5000`);
    (result.events || []).forEach((event) => appendOutput(event.stream || 'system', event.data || ''));
    statusEl.textContent = `Loaded ${result.count || 0} stored event(s) for ${commandId}.`;
  };
  const loadTerminalHistory = async () => {
    try {
      const result = await api(`/v1/workspaces/${encodeURIComponent(workspaceId)}`);
      const commands = result.commands || [];
      historyEl.innerHTML = commands.map((command) => {
        const when = command.created_at ? new Date(command.created_at).toLocaleString() : '';
        const label = `${command.status || 'unknown'}${command.exit_code !== undefined && command.exit_code !== null ? ` / ${command.exit_code}` : ''}`;
        return `<button class="workspace-terminal-history-item" data-terminal-command-id="${escapeHtml(command.id)}">
          <b>${escapeHtml(command.command || command.id)}</b>
          <span>${escapeHtml(label)} · ${escapeHtml(String(command.event_count || 0))} event(s)</span>
          <small>${escapeHtml(when)}</small>
        </button>`;
      }).join('') || '<div class="muted small-text">No commands have run in this workspace yet.</div>';
      historyEl.querySelectorAll('[data-terminal-command-id]').forEach((btn) => {
        btn.onclick = () => loadCommandEvents(btn.getAttribute('data-terminal-command-id') || '').catch((e) => { statusEl.textContent = `History error: ${e.message}`; });
      });
    } catch (e) {
      historyEl.innerHTML = `<div class="muted small-text">History unavailable: ${escapeHtml(e.message || String(e))}</div>`;
    }
  };
  const streamCommand = async (commandId) => {
    streamAbort = new AbortController();
    const response = await fetch(`/v1/workspaces/${encodeURIComponent(workspaceId)}/commands/${encodeURIComponent(commandId)}/stream`, {headers: tokenHeaders(), signal: streamAbort.signal});
    if (!response.ok || !response.body) throw new Error(`stream failed: HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'status') {
          statusEl.textContent = `Finished: ${event.status || 'complete'}${event.exit_code !== undefined && event.exit_code !== null ? `, exit ${event.exit_code}` : ''}`;
          continue;
        }
        appendOutput(event.stream || 'system', event.data || '');
      }
    }
  };
  commandEl.onclick = async () => {
    const command = textEl.value.trim();
    if (!command) return alert('Enter a command first');
    outEl.textContent = '';
    activeCommandId = '';
    interruptEl.disabled = true;
    statusEl.textContent = 'Queueing command...';
    try {
      const result = await api(`/v1/workspaces/${encodeURIComponent(workspaceId)}/commands`, {method:'POST', body:JSON.stringify({command, wait:true, metadata:{source:'ui-live-terminal'}})});
      activeCommandId = result?.command?.id || '';
      interruptEl.disabled = !activeCommandId;
      statusEl.textContent = activeCommandId ? `Streaming ${activeCommandId}...` : 'Command queued.';
      if (activeCommandId) await streamCommand(activeCommandId);
      await loadTerminalHistory();
    } catch (e) {
      if (String(e.name || '') !== 'AbortError') statusEl.textContent = `Terminal error: ${e.message}`;
    } finally {
      interruptEl.disabled = true;
      streamAbort = null;
    }
  };
  interruptEl.onclick = async () => {
    if (!activeCommandId) return;
    statusEl.textContent = 'Interrupt requested...';
    await api(`/v1/workspaces/${encodeURIComponent(workspaceId)}/commands/${encodeURIComponent(activeCommandId)}/cancel`, {method:'POST', body:JSON.stringify({reason:'Interrupted from PAC UI live terminal', force:false})});
    appendOutput('system', '\n[interrupt requested]\n');
  };
  refreshEl.onclick = () => loadTerminalHistory();
  loadTerminalHistory();
}
