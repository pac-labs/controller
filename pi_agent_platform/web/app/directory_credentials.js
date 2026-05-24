// Directory & Access credential rendering and modal actions.

function renderCredentialRows(credentials, includePrincipal = true) {
  const items = Array.isArray(credentials) ? credentials : [];
  if (!items.length) return '<div class="muted small-text">No credentials.</div>';
  return `<div class="credential-list">${items.map((cred) => `<div class="credential-row"><div><b>${escapeHtml(cred.name || cred.id)}</b><br><span class="muted small-text">${includePrincipal ? `${escapeHtml(cred.principal_id || '')} · ` : ''}${escapeHtml(cred.kind || '')} · ${escapeHtml(cred.status || '')} · expires ${escapeHtml(cred.expires_at || 'never')}</span></div><button class="ghost-button revoke-directory-credential" data-id="${escapeHtml(cred.id)}" type="button">Revoke</button></div>`).join('')}</div>`;
}

function renderCredentialCreateControls(item) {
  if (item.kind === 'group' || item.kind === 'credential') return '';
  return `<div class="directory-credential-create"><button class="ghost-button" data-open-credential-modal="token" type="button">+ Generate token</button><button class="ghost-button" data-open-credential-modal="certificate" type="button">+ Register certificate</button></div>`;
}


function closeDirectoryCredentialModal() {
  document.getElementById('directoryCredentialModal')?.remove();
}

function openDirectoryCredentialModal(item, credentialType = 'token') {
  closeDirectoryCredentialModal();
  const isCertificate = credentialType === 'certificate';
  const modal = document.createElement('div');
  modal.id = 'directoryCredentialModal';
  modal.className = 'modal-backdrop directory-modal-backdrop';
  modal.innerHTML = `<section class="modal-card directory-create-modal" role="dialog" aria-modal="true" aria-labelledby="directoryCredentialModalTitle">
    <div class="modal-head directory-modal-head"><div><p class="muted small-text directory-modal-kicker">Guided credential creation</p><h2 id="directoryCredentialModalTitle">${isCertificate ? 'Register certificate' : 'Generate token'}</h2><p class="muted">Credentials answer who this caller is. Directory membership decides what it can do.</p></div><button id="closeDirectoryCredentialModal" class="ghost-button" type="button">Close</button></div>
    <div class="directory-wizard-steps" aria-label="Credential steps"><span class="active">1. Principal</span><span class="active">2. Credential</span><span>3. Review</span></div>
    <div class="directory-detail-card subtle-card"><b>${escapeHtml(directoryPrincipalLabel(item))}</b><br><span class="muted small-text">${escapeHtml(item.kind)} · ${escapeHtml(item.id)}</span></div>
    <div class="form-grid compact-form">
      <label>Name <input id="directoryModalCredentialName" placeholder="${isCertificate ? 'Workstation certificate' : 'Automation token'}" /></label>
      ${isCertificate ? '<label class="admin-form-wide">Certificate fingerprint or PEM <textarea id="directoryModalCertificateInput" rows="5" placeholder="sha256:... or PEM text"></textarea></label>' : '<label>TTL hours <input id="directoryModalTokenTtl" type="number" min="1" max="8760" value="720" /></label>'}
    </div>
    <p class="muted small-text">No permissions are stored on this credential. Add the principal to groups to change access.</p>
    <div id="directoryCredentialModalResult" class="inline-result compact-result" hidden></div>
    <div class="button-row"><button id="submitDirectoryCredentialModal" type="button">${isCertificate ? 'Register certificate' : 'Generate token'}</button><button id="cancelDirectoryCredentialModal" class="ghost-button" type="button">Cancel</button></div>
  </section>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', (ev) => { if (ev.target === modal) closeDirectoryCredentialModal(); });
  modal.querySelector('#closeDirectoryCredentialModal')?.addEventListener('click', closeDirectoryCredentialModal);
  modal.querySelector('#cancelDirectoryCredentialModal')?.addEventListener('click', closeDirectoryCredentialModal);
  modal.querySelector('#submitDirectoryCredentialModal')?.addEventListener('click', async () => {
    const result = modal.querySelector('#directoryCredentialModalResult');
    try {
      if (isCertificate) {
        const value = modal.querySelector('#directoryModalCertificateInput')?.value.trim() || '';
        if (!value) throw new Error('Certificate fingerprint or PEM is required.');
        const name = modal.querySelector('#directoryModalCredentialName')?.value.trim() || 'Certificate';
        const payload = value.startsWith('sha256:') ? {fingerprint: value, name} : {certificate_pem: value, name};
        await DirectoryApi.createCertificate(item.id, payload);
        if (result) { result.hidden = false; result.textContent = 'Certificate registered. Access still comes from directory membership.'; }
        await loadAuthDirectory({preserveDetail: true});
        closeDirectoryCredentialModal();
      } else {
        const payload = {name: modal.querySelector('#directoryModalCredentialName')?.value.trim() || 'Directory token', ttl_hours: Number(modal.querySelector('#directoryModalTokenTtl')?.value || 720)};
        const response = await DirectoryApi.createToken(item.id, payload);
        if (result) { result.hidden = false; result.textContent = `Token shown once:\n${response.token || ''}\n\nSave it now. PAC stores only the hash.`; }
        await loadAuthDirectory({preserveDetail: true});
      }
    } catch (error) {
      if (result) { result.hidden = false; result.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
  modal.querySelector('input, textarea, button')?.focus?.();
}

function bindCredentialActions(root, item) {
  root.querySelectorAll('[data-open-credential-modal]').forEach((button) => {
    if (button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', () => openDirectoryCredentialModal(item, button.dataset.openCredentialModal || 'token'));
  });
  root.querySelectorAll('.revoke-directory-credential').forEach((btn) => btn.addEventListener('click', async () => {
    if (!confirm('Revoke this credential?')) return;
    await DirectoryApi.revokeCredential(btn.dataset.id || '');
    await loadAuthDirectory();
  }));
  root.querySelector('#createDirectoryTokenBtn')?.addEventListener('click', async () => {
    const result = root.querySelector('#directoryPrincipalResult');
    try {
      const payload = {name: root.querySelector('#directoryTokenName')?.value.trim() || 'Directory token', ttl_hours: Number(root.querySelector('#directoryTokenTtl')?.value || 720)};
      const response = await DirectoryApi.createToken(item.id, payload);
      if (result) result.textContent = `Token shown once:\n${response.token || ''}\n\nCredentials identify the principal only. Directory groups decide access.`;
      await loadAuthDirectory({preserveDetail: true});
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  root.querySelector('#createDirectoryCertificateBtn')?.addEventListener('click', async () => {
    const result = root.querySelector('#directoryPrincipalResult');
    try {
      const value = root.querySelector('#directoryCertificateInput')?.value.trim() || '';
      const payload = value.startsWith('sha256:') ? {fingerprint: value, name: 'Certificate'} : {certificate_pem: value, name: 'Certificate'};
      await DirectoryApi.createCertificate(item.id, payload);
      if (result) result.textContent = 'Certificate registered. Access still comes from directory membership.';
      await loadAuthDirectory({preserveDetail: true});
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

function renderCredentialDetail(credential, detail, title, subtitle) {
  if (title) title.textContent = credential.name || credential.id;
  if (subtitle) subtitle.textContent = `Credential · ${credential.kind || ''}`;
  detail.innerHTML = `<article class="directory-detail-card"><h3>${escapeHtml(credential.name || credential.id)}</h3><p class="muted">Credentials answer who the caller is. They do not contain permissions.</p><div class="directory-detail-meta"><span>Principal <code>${escapeHtml(credential.principal_id || '-')}</code></span><span>Status ${escapeHtml(credential.status || '-')}</span><span>Expires ${escapeHtml(credential.expires_at || 'never')}</span></div><div class="button-row"><button class="ghost-button revoke-directory-credential" data-id="${escapeHtml(credential.id)}" type="button">Revoke credential</button></div></article>`;
  bindCredentialActions(detail, credential);
}
