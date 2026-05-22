// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

async function openPersonalSettingsModal() {
  if (!currentUser && authStatus?.enabled) {
    openLoginModal(authStatus?.needs_setup ? 'setup' : 'login');
    return;
  }
  closePersonalSettingsModal();
  const modal = document.createElement('div');
  modal.id = 'personalSettingsModal';
  modal.className = 'modal-backdrop';
  modal.innerHTML = `
    <section class="modal-card auth-modal-card personal-settings-modal" role="dialog" aria-modal="true" aria-labelledby="personalSettingsTitle">
      <div class="section-heading">
        <div><h2 id="personalSettingsTitle">My Access</h2><p class="muted">Your profile, groups, usable PAC resources, tokens, access requests, and personal memory.</p></div>
        <button id="closePersonalSettingsBtn" class="ghost-button" type="button">Close</button>
      </div>
      <div class="split personal-settings-grid">
        <section class="card setting-cube compact-setting-card">
          <h3>Profile</h3>
          <div class="form-grid compact-form">
            <label>Username <input id="personalUsername" disabled /></label>
            <label>Display name <input id="personalDisplayName" /></label>
            <label>Email <input id="personalEmail" placeholder="name@example.com" /></label>
          </div>
          <label>Preferences JSON <textarea id="personalPreferences" rows="8"></textarea></label>
          <div class="button-row"><button id="savePersonalProfileBtn" type="button">Save profile</button></div>
          <div id="personalProfileStatus" class="inline-result" hidden></div>
        </section>
        <section class="card setting-cube compact-setting-card">
          <h3>My tokens</h3>
          <p class="muted small-text">Tokens answer who you are. Directory groups decide what you are allowed to do.</p>
          <div class="button-row">
            <button id="mintPersonalTokenBtn" type="button">Generate token</button>
            <label>TTL hours <input id="personalTokenTtl" type="number" value="720" min="1" max="8760" /></label>
          </div>
          <div id="personalTokensList" class="stacked-output compact-scroll-output"><div class="muted small-text">Loading tokens…</div></div>
        </section>
      </div>
      <section class="card setting-cube compact-setting-card my-access-card" style="margin-top:1rem">
        <div class="section-heading"><div><h3>My platform access</h3><p class="muted">Groups, profiles, workspaces, contexts, and access requests available to your directory principal.</p></div><button id="refreshMyAccessBtn" class="ghost-button" type="button">Refresh access</button></div>
        <div id="myAccessSummary" class="my-access-summary"><div class="muted small-text">Loading access…</div></div>
      </section>
      <section class="card setting-cube compact-setting-card" style="margin-top:1rem">
        <h3>Personal PAC RAM</h3>
        <p class="muted">This is the remote memory bundle PAC can use for your user.</p>
        <label><textarea id="personalRamContent" rows="10"></textarea></label>
        <div class="button-row"><button id="savePersonalRamBtn" type="button">Save memory</button></div>
        <div id="personalRamStatus" class="inline-result" hidden></div>
      </section>
    </section>`;
  document.body.appendChild(modal);
  document.getElementById('closePersonalSettingsBtn')?.addEventListener('click', closePersonalSettingsModal);
  modal.addEventListener('click', (ev) => { if (ev.target === modal) closePersonalSettingsModal(); });
  const data = await loadPersonalSettingsData();
  document.getElementById('personalUsername').value = data.me?.username || '';
  document.getElementById('personalDisplayName').value = data.me?.display_name || data.me?.username || '';
  document.getElementById('personalEmail').value = data.me?.metadata?.email || '';
  document.getElementById('personalPreferences').value = JSON.stringify(data.me?.metadata?.preferences || {}, null, 2);
  document.getElementById('personalRamContent').value = data.ram?.content || '';
  renderPersonalTokens(document.getElementById('personalTokensList'), data.tokens || []);
  await renderMyAccessSummary();
  document.getElementById('savePersonalProfileBtn')?.addEventListener('click', async () => {
    const status = document.getElementById('personalProfileStatus');
    try {
      const preferences = JSON.parse(document.getElementById('personalPreferences').value || '{}');
      const response = await api('/v1/users/me', {method:'PUT', body: JSON.stringify({display_name: document.getElementById('personalDisplayName').value.trim(), email: document.getElementById('personalEmail').value.trim(), preferences})});
      currentUser = response.user || currentUser;
      showUserChip(currentUser);
      if (status) { status.hidden = false; status.textContent = 'Profile saved.'; }
    } catch (error) {
      if (status) { status.hidden = false; status.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
  document.getElementById('mintPersonalTokenBtn')?.addEventListener('click', async () => {
    const ttl = Number(document.getElementById('personalTokenTtl').value || 720);
    const response = await api('/v1/users/me/tokens', {method:'POST', body: JSON.stringify({ttl_hours: ttl})});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(document.getElementById('personalTokensList'), refreshed, response.token || '');
  });
  document.getElementById('refreshMyAccessBtn')?.addEventListener('click', () => renderMyAccessSummary().catch((e) => paneError('My Access could not be refreshed', e.message || String(e))));
  document.getElementById('savePersonalRamBtn')?.addEventListener('click', async () => {
    const status = document.getElementById('personalRamStatus');
    try {
      await api('/v1/users/me/ram', {method:'PUT', body: JSON.stringify({content: document.getElementById('personalRamContent').value})});
      if (status) { status.hidden = false; status.textContent = 'Personal memory saved.'; }
    } catch (error) {
      if (status) { status.hidden = false; status.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
}



function myAccessList(items, labelField = 'display_name') {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return '<span class="muted small-text">None available.</span>';
  return list.slice(0, 12).map((item) => `<span class="directory-member-pill">${escapeHtml(item[labelField] || item.name || item.id || item.resource_id || '-')}</span>`).join('');
}

async function renderMyAccessSummary() {
  const target = document.getElementById('myAccessSummary');
  if (!target) return;
  try {
    const data = await api('/v1/users/me/access');
    const groups = data.membership?.effective_groups || [];
    const groupPills = groups.length ? groups.map((entry) => `<span class="directory-member-pill" title="${escapeHtml((entry.path || []).join(' → '))}">${escapeHtml(entry.id || entry)}</span>`).join('') : '<span class="muted small-text">No groups.</span>';
    target.innerHTML = `<div class="my-access-grid">
      <section><h4>My profile</h4><p><b>${escapeHtml(data.principal?.display_name || data.principal?.name || data.principal?.id || 'Current user')}</b></p><p class="muted small-text">${escapeHtml(data.principal?.id || '')} · ${escapeHtml(data.principal?.kind || 'user')}</p></section>
      <section><h4>My groups</h4>${groupPills}</section>
      <section><h4>My available profiles</h4>${myAccessList(data.available?.profiles || [])}</section>
      <section><h4>My workspaces</h4>${myAccessList(data.available?.workspaces || [], 'name')}</section>
      <section><h4>My contexts</h4>${myAccessList(data.available?.contexts || [], 'name')}</section>
      <section><h4>My tokens</h4>${myAccessList(data.credentials || [], 'name')}</section>
      <section><h4>My access requests</h4>${myAccessList(data.access_requests || [], 'resource_id')}</section>
    </div><p class="muted small-text">${escapeHtml(data.rule?.token_question || 'Who are you?')} / ${escapeHtml(data.rule?.directory_question || 'What are you allowed to do?')}</p>`;
  } catch (error) {
    target.innerHTML = `<div class="muted small-text">Could not load access: ${escapeHtml(error.message || String(error))}</div>`;
  }
}
