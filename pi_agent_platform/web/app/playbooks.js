(function () {
  let playbooksLoaded = false;
  let selectedRunId = '';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function statusPill(status) {
    const safe = escapeHtml(status || 'unknown');
    return `<span class="pill ${safe === 'failed' ? 'danger' : safe === 'waiting' ? 'attention' : safe === 'completed' ? 'ok' : ''}">${safe}</span>`;
  }

  function parameterDefaults(playbook) {
    const data = {};
    (playbook.parameters || []).forEach((param) => {
      if (param.default !== undefined && param.default !== null) data[param.name] = param.default;
    });
    return data;
  }

  function downloadText(filename, text) {
    const blob = new Blob([text], {type: 'text/yaml'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function renderPlaybookCard(playbook) {
    const params = (playbook.parameters || []).map((p) => `${p.name}${p.required ? '*' : ''}: ${p.type}`).join(', ') || 'no parameters';
    return `<article class="card playbook-card" data-playbook-id="${escapeHtml(playbook.id)}">
      <div class="section-heading compact-heading">
        <div><h3>${escapeHtml(playbook.title || playbook.id)}</h3><p class="muted small-text">${escapeHtml(playbook.description || '')}</p></div>
        <div class="button-row compact-row">
          <button class="ghost-button playbook-export" type="button" data-playbook-id="${escapeHtml(playbook.id)}">Export</button>
          <button class="ghost-button playbook-start" type="button" data-playbook-id="${escapeHtml(playbook.id)}">Start</button>
        </div>
      </div>
      <div class="muted small-text">${escapeHtml(params)}</div>
      <details><summary>Steps</summary><ol>${(playbook.steps || []).map((s) => `<li><strong>${escapeHtml(s.title || s.id)}</strong> <span class="muted">${escapeHtml(s.action || 'note')}</span>${s.gate ? ` <span class="pill attention">${escapeHtml(s.gate.type)}</span>` : ''}</li>`).join('')}</ol></details>
      <textarea class="playbook-params" data-playbook-id="${escapeHtml(playbook.id)}" spellcheck="false">${escapeHtml(JSON.stringify(parameterDefaults(playbook), null, 2))}</textarea>
    </article>`;
  }

  function renderRun(run) {
    const steps = (run.steps || []).map((step) => `<li class="playbook-step ${escapeHtml(step.status)}">
      <span>${statusPill(step.status)}</span>
      <strong>${escapeHtml(step.title || step.id)}</strong>
      <span class="muted small-text">${escapeHtml(step.message || '')}</span>
      ${step.output ? `<details class="small-text"><summary>Output</summary><pre>${escapeHtml(step.output)}</pre></details>` : ''}
    </li>`).join('');
    const gateButtons = run.status === 'waiting'
      ? `<button class="ghost-button playbook-approve" data-run-id="${escapeHtml(run.id)}">Approve gate</button>`
      : '';
    const canCancel = !['completed', 'failed', 'cancelled'].includes(run.status || '');
    const sessionLink = run.outputs?.session_id ? `<div class="notice subtle">Created session: <code>${escapeHtml(run.outputs.session_id)}</code></div>` : '';
    return `<article class="card playbook-run-card ${selectedRunId === run.id ? 'selected' : ''}" data-run-id="${escapeHtml(run.id)}">
      <div class="section-heading compact-heading">
        <div><h3>${escapeHtml(run.title || run.playbook_id)}</h3><p class="muted small-text">${escapeHtml(run.id)} · ${escapeHtml(run.playbook_id)}</p></div>
        ${statusPill(run.status)}
      </div>
      ${run.waiting_gate ? `<div class="notice subtle">${escapeHtml(run.waiting_gate.message || 'Waiting for approval')}</div>` : ''}
      ${sessionLink}
      <ol class="playbook-steps">${steps}</ol>
      <div class="button-row compact-row">
        ${gateButtons}
        <button class="ghost-button playbook-resume" data-run-id="${escapeHtml(run.id)}">Resume</button>
        ${canCancel ? `<button class="ghost-button danger playbook-cancel" data-run-id="${escapeHtml(run.id)}">Cancel</button>` : ''}
      </div>
    </article>`;
  }

  async function loadPlaybooksPanel() {
    const catalog = document.getElementById('playbooksCatalog');
    const runs = document.getElementById('playbookRuns');
    if (!catalog || !runs || typeof api !== 'function') return;
    catalog.textContent = 'Loading playbooks…';
    runs.textContent = 'Loading runs…';
    try {
      const [list, runList] = await Promise.all([api('/v1/playbooks'), api('/v1/playbooks/runs')]);
      catalog.innerHTML = (list.playbooks || []).map(renderPlaybookCard).join('') || '<div class="muted">No playbooks found.</div>';
      runs.innerHTML = (runList.runs || []).map(renderRun).join('') || '<div class="muted">No playbook runs yet.</div>';
      wirePlaybooksPanel();
      playbooksLoaded = true;
    } catch (err) {
      catalog.innerHTML = `<div class="notice danger">${escapeHtml(err.message || err)}</div>`;
      runs.textContent = '';
    }
  }

  function paramsFor(playbookId) {
    const ta = document.querySelector(`textarea.playbook-params[data-playbook-id="${CSS.escape(playbookId)}"]`);
    if (!ta) return {};
    const raw = ta.value.trim();
    return raw ? JSON.parse(raw) : {};
  }

  async function startPlaybook(playbookId) {
    const status = document.getElementById('playbooksStatus');
    try {
      const body = {parameters: paramsFor(playbookId)};
      if (typeof selectedSession === 'object' && selectedSession?.id) body.session_id = selectedSession.id;
      const run = await api(`/v1/playbooks/${encodeURIComponent(playbookId)}/runs`, {method: 'POST', body: JSON.stringify(body)});
      selectedRunId = run.id;
      if (status) status.textContent = `Started ${run.id}`;
      await loadPlaybooksPanel();
    } catch (err) {
      if (status) status.textContent = err.message || String(err);
    }
  }

  async function exportPlaybook(playbookId) {
    const response = await fetch(`/v1/playbooks/${encodeURIComponent(playbookId)}/export`, {headers: typeof tokenHeaders === 'function' ? tokenHeaders() : {}});
    if (!response.ok) throw new Error(await response.text());
    downloadText(`${playbookId}.yaml`, await response.text());
  }

  function openImportModal() {
    let modal = document.getElementById('playbookImportModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'playbookImportModal';
      modal.className = 'modal-backdrop hidden';
      modal.innerHTML = `<div class="modal card playbook-import-modal">
        <div class="section-heading compact-heading"><div><h2>Import playbook YAML</h2><p class="muted small-text">Paste a complete playbook definition. Existing custom playbooks are replaced only when overwrite is checked.</p></div><button class="ghost-button" data-close>Close</button></div>
        <label class="form-row"><span>YAML</span><textarea id="playbookImportYaml" spellcheck="false" placeholder="id: my-playbook\ntitle: My playbook\nsteps: []"></textarea></label>
        <label class="checkbox-row"><input id="playbookImportOverwrite" type="checkbox"> <span>Overwrite existing playbook with same id</span></label>
        <div class="button-row compact-row"><button id="playbookImportSubmit" class="primary-button" type="button">Import</button><span id="playbookImportStatus" class="muted small-text"></span></div>
      </div>`;
      document.body.appendChild(modal);
      modal.querySelector('[data-close]').onclick = () => modal.classList.add('hidden');
      modal.querySelector('#playbookImportSubmit').onclick = importPlaybook;
    }
    modal.classList.remove('hidden');
  }

  async function importPlaybook() {
    const text = document.getElementById('playbookImportYaml')?.value || '';
    const overwrite = !!document.getElementById('playbookImportOverwrite')?.checked;
    const status = document.getElementById('playbookImportStatus');
    try {
      const result = await api('/v1/playbooks/import', {method: 'POST', body: JSON.stringify({yaml: text, overwrite})});
      if (status) status.textContent = `Imported ${result.playbook?.id || 'playbook'}`;
      await loadPlaybooksPanel();
    } catch (err) {
      if (status) status.textContent = err.message || String(err);
    }
  }

  async function approveRun(runId) {
    await api(`/v1/playbooks/runs/${encodeURIComponent(runId)}/approve`, {method: 'POST', body: JSON.stringify({note: 'Approved from Playbooks UI'})});
    await loadPlaybooksPanel();
  }

  async function resumeRun(runId) {
    await api(`/v1/playbooks/runs/${encodeURIComponent(runId)}/resume`, {method: 'POST', body: JSON.stringify({})});
    await loadPlaybooksPanel();
  }

  async function cancelRun(runId) {
    await api(`/v1/playbooks/runs/${encodeURIComponent(runId)}/cancel`, {method: 'POST', body: JSON.stringify({note: 'Cancelled from Playbooks UI'})});
    await loadPlaybooksPanel();
  }

  function wirePlaybooksPanel() {
    document.querySelectorAll('.playbook-start').forEach((btn) => { btn.onclick = () => startPlaybook(btn.dataset.playbookId || ''); });
    document.querySelectorAll('.playbook-export').forEach((btn) => { btn.onclick = () => exportPlaybook(btn.dataset.playbookId || '').catch((err) => { const status = document.getElementById('playbooksStatus'); if (status) status.textContent = err.message || String(err); }); });
    document.querySelectorAll('.playbook-approve').forEach((btn) => { btn.onclick = () => approveRun(btn.dataset.runId || ''); });
    document.querySelectorAll('.playbook-resume').forEach((btn) => { btn.onclick = () => resumeRun(btn.dataset.runId || ''); });
    document.querySelectorAll('.playbook-cancel').forEach((btn) => { btn.onclick = () => cancelRun(btn.dataset.runId || ''); });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const refresh = document.getElementById('playbooksRefresh');
    if (refresh) refresh.onclick = () => loadPlaybooksPanel();
    const importer = document.getElementById('playbooksImport');
    if (importer) importer.onclick = openImportModal;
  });

  window.loadPlaybooksPanel = loadPlaybooksPanel;
  window.ensurePlaybooksLoaded = function () {
    if (!playbooksLoaded) return loadPlaybooksPanel();
    return Promise.resolve();
  };
})();
