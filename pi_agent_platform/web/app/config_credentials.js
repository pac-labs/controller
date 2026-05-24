(function () {
  const state = {variables: [], secrets: [], audit: [], loaded: false, loading: false, wizardStep: 'identify'};
  const STEPS = ['identify', 'value', 'review'];

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function showResult(message, kind = '') {
    const el = document.getElementById('configCredentialModalResult');
    if (!el) return;
    el.hidden = false;
    el.textContent = message;
    el.className = `inline-result compact-result ${kind ? `${kind}-text` : ''}`;
  }

  function parseJsonObject(raw, label) {
    const text = String(raw || '').trim();
    if (!text) return {};
    const parsed = JSON.parse(text);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(`${label} must be a JSON object`);
    return parsed;
  }

  function credentialValues() {
    const tags = String(document.getElementById('configCredentialTags')?.value || '').split(',').map((tag) => tag.trim()).filter(Boolean);
    return {
      kind: document.getElementById('configCredentialKind')?.value || 'secret',
      id: document.getElementById('configCredentialId')?.value?.trim() || '',
      value: document.getElementById('configCredentialValue')?.value ?? '',
      description: document.getElementById('configCredentialDescription')?.value?.trim() || '',
      tags,
      metaRaw: document.getElementById('configCredentialMeta')?.value || '{}',
    };
  }

  function validateStep(step = state.wizardStep) {
    const values = credentialValues();
    if (step === 'identify') {
      if (!values.id) return 'ID is required.';
      if (values.kind === 'secret') parseJsonObject(values.metaRaw, 'Secret meta');
    }
    if (step === 'value' && values.kind === 'secret' && !values.value) return 'Secret value is required when saving.';
    return '';
  }

  function renderCredentialReview() {
    const review = document.getElementById('configCredentialReview');
    if (!review) return;
    const values = credentialValues();
    const rows = values.kind === 'secret'
      ? [['Type', 'Write-only secret'], ['ID', values.id], ['Metadata', values.metaRaw.trim() || '{}'], ['Value', values.value ? 'will be rotated / saved' : 'missing']]
      : [['Type', 'Workspace variable'], ['ID', values.id], ['Description', values.description || '-'], ['Tags', values.tags.join(', ') || '-'], ['Value', values.value ? 'configured' : 'empty string']];
    review.innerHTML = `<div class="directory-create-review-card"><h3>Review credential</h3><div class="kv compact-kv">${rows.map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div><p class="muted small-text">This uses the existing credentials API. Secret values remain write-only after save.</p></div>`;
  }

  function setWizardStep(step) {
    state.wizardStep = STEPS.includes(step) ? step : 'identify';
    const isIdentify = state.wizardStep === 'identify';
    const isValue = state.wizardStep === 'value';
    const isReview = state.wizardStep === 'review';
    document.querySelectorAll('[data-credential-step]').forEach((button) => {
      const active = button.dataset.credentialStep === state.wizardStep;
      button.classList.toggle('active', active);
      button.setAttribute('aria-current', active ? 'step' : 'false');
    });
    const fields = document.getElementById('configCredentialFields');
    if (fields) fields.dataset.credentialStep = state.wizardStep;
    document.getElementById('configCredentialId')?.closest('label')?.toggleAttribute('hidden', !isIdentify);
    document.getElementById('configCredentialDescriptionWrap')?.toggleAttribute('hidden', !isIdentify || credentialValues().kind === 'secret');
    document.getElementById('configCredentialTagsWrap')?.toggleAttribute('hidden', !isIdentify || credentialValues().kind === 'secret');
    document.getElementById('configCredentialMetaWrap')?.toggleAttribute('hidden', !isIdentify || credentialValues().kind !== 'secret');
    document.querySelector('.config-credential-value-field')?.toggleAttribute('hidden', !isValue);
    const review = document.getElementById('configCredentialReview');
    if (review) review.hidden = !isReview;
    if (isReview) renderCredentialReview();
    const back = document.getElementById('backConfigCredential');
    const next = document.getElementById('nextConfigCredential');
    const save = document.getElementById('saveConfigCredential');
    if (back) back.hidden = isIdentify;
    if (next) next.hidden = isReview;
    if (save) save.hidden = !isReview;
    const result = document.getElementById('configCredentialModalResult');
    if (result) result.hidden = true;
  }

  function nextWizardStep() {
    try {
      const error = validateStep();
      if (error) return showResult(error, 'warn');
      const index = STEPS.indexOf(state.wizardStep);
      setWizardStep(STEPS[Math.min(STEPS.length - 1, index + 1)]);
    } catch (err) {
      showResult(err.message || String(err), 'warn');
    }
  }

  function previousWizardStep() {
    const index = STEPS.indexOf(state.wizardStep);
    setWizardStep(STEPS[Math.max(0, index - 1)]);
  }

  async function loadData() {
    state.loading = true;
    renderLoading();
    const [variableData, secretData, auditData] = await Promise.all([api('/v1/source-variables'), api('/v1/secrets'), api('/v1/secrets/audit?limit=16')]);
    state.variables = variableData.variables || [];
    state.secrets = secretData.secrets || [];
    state.audit = auditData.items || [];
    state.loaded = true;
    state.loading = false;
    window.__pacSourceVariables = state.variables;
    window.__pacSecrets = state.secrets;
    render();
  }

  function renderLoading() {
    setText('configCredentialsSummary', 'Loading credentials…');
    setText('configVariablesList', 'Loading variables…');
    setText('configSecretsList', 'Loading secrets…');
    setText('configCredentialAudit', 'Loading audit events…');
  }

  function tagPills(tags) {
    return (tags || []).map((tag) => `<span class="pill config-credential-pill">${esc(tag)}</span>`).join('');
  }

  function renderVariableList() {
    const el = document.getElementById('configVariablesList');
    if (!el) return;
    if (!state.variables.length) return void (el.innerHTML = '<div class="config-empty-state">No workspace variables are configured yet.</div>');
    el.innerHTML = state.variables.map((item) => `<article class="config-credential-item"><div><h4>${esc(item.id)}</h4><p class="muted small-text">${esc(item.description || 'No description provided.')}</p><div class="config-credential-pills">${tagPills(item.tags)}</div></div><div class="button-row compact-actions"><button class="ghost-button mini-button" type="button" data-config-edit-variable="${esc(item.id)}">Edit</button><button class="ghost-button mini-button danger-button" type="button" data-config-delete-variable="${esc(item.id)}">Delete</button></div></article>`).join('');
  }

  function renderSecretList() {
    const el = document.getElementById('configSecretsList');
    if (!el) return;
    if (!state.secrets.length) return void (el.innerHTML = '<div class="config-empty-state">No secret references are configured yet.</div>');
    el.innerHTML = state.secrets.map((item) => `<article class="config-credential-item"><div><h4>${esc(item.id)}</h4><p class="muted small-text">${esc(item.meta && Object.keys(item.meta).length ? JSON.stringify(item.meta) : 'No metadata')}</p></div><div class="button-row compact-actions"><button class="ghost-button mini-button" type="button" data-config-edit-secret="${esc(item.id)}">Rotate</button><button class="ghost-button mini-button danger-button" type="button" data-config-delete-secret="${esc(item.id)}">Delete</button></div></article>`).join('');
  }

  function renderSummary() {
    const el = document.getElementById('configCredentialsSummary');
    if (!el) return;
    el.innerHTML = `<div class="config-summary-tile"><strong>${state.variables.length}</strong><span>workspace variables</span></div><div class="config-summary-tile"><strong>${state.secrets.length}</strong><span>secret refs</span></div><div class="config-summary-tile"><strong>${state.audit.length}</strong><span>recent audit events</span></div>`;
  }

  function renderAudit() {
    setText('configCredentialAudit', state.audit.length ? state.audit.map((item) => `${item.created_at || '-'}  ${item.event || '-'}  ${item.secret_id || '-'}`).join('\n') : 'No secret audit events loaded yet.');
  }

  function render() {
    renderSummary(); renderVariableList(); renderSecretList(); renderAudit(); bindListActions();
  }

  function setModalMode(kind, existing = null) {
    const isSecret = kind === 'secret';
    const modal = document.getElementById('configCredentialModal');
    const kindInput = document.getElementById('configCredentialKind');
    if (!modal || !kindInput) return;
    kindInput.value = kind;
    setText('configCredentialModalTitle', isSecret ? (existing ? 'Rotate secret' : 'Add secret') : (existing ? 'Edit variable' : 'Add variable'));
    setText('configCredentialModalCopy', isSecret ? 'Secret values are stored write-only and only metadata is shown after saving.' : 'Variables are plain configuration values resolved into selected workspaces.');
    const id = document.getElementById('configCredentialId');
    const value = document.getElementById('configCredentialValue');
    const desc = document.getElementById('configCredentialDescription');
    const tags = document.getElementById('configCredentialTags');
    const meta = document.getElementById('configCredentialMeta');
    if (id) { id.value = existing?.id || ''; id.disabled = !!existing; }
    if (value) value.value = isSecret ? '' : (existing?.value || '');
    if (desc) desc.value = existing?.description || '';
    if (tags) tags.value = Array.isArray(existing?.tags) ? existing.tags.join(', ') : '';
    if (meta) meta.value = JSON.stringify(existing?.meta || {}, null, 2);
    modal.hidden = false;
    setWizardStep('identify');
    id?.focus();
  }

  function closeModal() {
    const modal = document.getElementById('configCredentialModal');
    if (modal) modal.hidden = true;
  }

  async function saveCredential() {
    try {
      const error = validateStep('value');
      if (error) throw new Error(error);
      const values = credentialValues();
      if (values.kind === 'secret') {
        await api(`/v1/secrets/${encodeURIComponent(values.id)}`, {method: 'PUT', body: JSON.stringify({value: values.value, meta: parseJsonObject(values.metaRaw, 'Secret meta')})});
      } else {
        await api(`/v1/source-variables/${encodeURIComponent(values.id)}`, {method: 'PUT', body: JSON.stringify({value: values.value, description: values.description, tags: values.tags})});
      }
      showResult('Credential saved.', 'ok');
      await loadData();
      closeModal();
    } catch (err) {
      showResult(err.message || String(err), 'warn');
    }
  }

  async function deleteVariable(id) { if (!id || !confirm(`Delete source variable ${id}?`)) return; await api(`/v1/source-variables/${encodeURIComponent(id)}`, {method: 'DELETE'}); await loadData(); }
  async function deleteSecret(id) { if (!id || !confirm(`Delete secret ${id}?`)) return; await api(`/v1/secrets/${encodeURIComponent(id)}`, {method: 'DELETE'}); await loadData(); }

  function bindListActions() {
    document.querySelectorAll('[data-config-edit-variable]').forEach((button) => { button.onclick = () => setModalMode('variable', state.variables.find((item) => item.id === button.dataset.configEditVariable)); });
    document.querySelectorAll('[data-config-delete-variable]').forEach((button) => { button.onclick = () => deleteVariable(button.dataset.configDeleteVariable).catch((err) => alert(err.message || String(err))); });
    document.querySelectorAll('[data-config-edit-secret]').forEach((button) => { button.onclick = () => setModalMode('secret', state.secrets.find((item) => item.id === button.dataset.configEditSecret)); });
    document.querySelectorAll('[data-config-delete-secret]').forEach((button) => { button.onclick = () => deleteSecret(button.dataset.configDeleteSecret).catch((err) => alert(err.message || String(err))); });
  }

  function bindControls() {
    document.getElementById('openConfigVariableWizard')?.addEventListener('click', () => setModalMode('variable'));
    document.getElementById('openConfigSecretWizard')?.addEventListener('click', () => setModalMode('secret'));
    document.getElementById('refreshConfigVariables')?.addEventListener('click', () => loadData().catch((err) => setText('configVariablesList', err.message || String(err))));
    document.getElementById('refreshConfigSecrets')?.addEventListener('click', () => loadData().catch((err) => setText('configSecretsList', err.message || String(err))));
    document.getElementById('backConfigCredential')?.addEventListener('click', previousWizardStep);
    document.getElementById('nextConfigCredential')?.addEventListener('click', nextWizardStep);
    document.getElementById('saveConfigCredential')?.addEventListener('click', saveCredential);
    document.getElementById('closeConfigCredentialModal')?.addEventListener('click', closeModal);
    document.getElementById('cancelConfigCredential')?.addEventListener('click', closeModal);
  }

  async function renderConfigCredentials() {
    if (!state.loaded && !state.loading) await loadData(); else render();
  }

  document.addEventListener('DOMContentLoaded', bindControls);
  window.renderConfigCredentials = renderConfigCredentials;
})();
