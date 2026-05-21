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
        <div><h2 id="personalSettingsTitle">Personal settings</h2><p class="muted">Profile, personal tokens, and the memory PAC stores for your user.</p></div>
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
          <h3>Access tokens</h3>
          <div class="button-row">
            <button id="mintPersonalTokenBtn" type="button">Generate token</button>
            <label>TTL hours <input id="personalTokenTtl" type="number" value="720" min="1" max="8760" /></label>
          </div>
          <div id="personalTokensList" class="stacked-output compact-scroll-output"><div class="muted small-text">Loading tokens…</div></div>
        </section>
      </div>
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

