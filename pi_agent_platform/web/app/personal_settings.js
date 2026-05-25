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
    <section class="modal-card personal-profile-modal" role="dialog" aria-modal="true" aria-labelledby="personalSettingsTitle">
      <header class="personal-profile-header">
        <div class="personal-profile-identity">
          <div class="personal-profile-avatar" aria-hidden="true">${escapeHtml((currentUser?.display_name || currentUser?.username || 'U').slice(0, 1).toUpperCase())}</div>
          <div>
            <p class="modal-eyebrow">Directory profile</p>
            <h2 id="personalSettingsTitle">My profile settings</h2>
            <p class="muted">Manage your PAC identity, access, tokens, and personal memory from one profile.</p>
          </div>
        </div>
        <button id="closePersonalSettingsBtn" class="ghost-button" type="button">Close</button>
      </header>
      <div class="personal-profile-body">
        <aside class="personal-profile-nav" aria-label="Profile settings sections">
          <div class="personal-profile-card identity-card">
            <span class="identity-label">Signed in as</span>
            <strong id="personalNavDisplayName">${escapeHtml(currentUser?.display_name || currentUser?.username || 'Current user')}</strong>
            <code id="personalNavUsername">${escapeHtml(currentUser?.username || '')}</code>
          </div>
          <button class="personal-profile-tab is-active" type="button" data-personal-tab="overview">Overview</button>
          <button class="personal-profile-tab" type="button" data-personal-tab="access">Access</button>
          <button class="personal-profile-tab" type="button" data-personal-tab="credentials">Credentials</button>
          <button class="personal-profile-tab" type="button" data-personal-tab="memory">PAC RAM</button>
          <button class="personal-profile-tab" type="button" data-personal-tab="preferences">Preferences</button>
          <div class="personal-profile-rule">
            <b>Credential rule</b>
            <span>Tokens identify who you are. Directory groups decide what you can do.</span>
          </div>
        </aside>
        <main class="personal-profile-content">
          <section class="personal-profile-panel is-active" data-personal-panel="overview">
            <div class="profile-panel-heading">
              <div><h3>Profile overview</h3><p class="muted">The identity shown to PAC and used by directory-backed access checks.</p></div>
              <button id="savePersonalProfileBtn" type="button">Save profile</button>
            </div>
            <div class="profile-form-card">
              <div class="form-grid compact-form">
                <label>Username <input id="personalUsername" disabled /></label>
                <label>Display name <input id="personalDisplayName" /></label>
                <label>Email <input id="personalEmail" placeholder="name@example.com" /></label>
              </div>
              <div id="personalProfileStatus" class="inline-result" hidden></div>
            </div>
          </section>
          <section class="personal-profile-panel" data-personal-panel="access">
            <div class="profile-panel-heading">
              <div><h3>My platform access</h3><p class="muted">Groups, profiles, workspaces, contexts, and requests resolved from your directory principal.</p></div>
              <button id="refreshMyAccessBtn" class="ghost-button" type="button">Refresh access</button>
            </div>
            <div id="myAccessSummary" class="my-access-summary unified-access-summary"><div class="muted small-text" data-pac-loading="Loading access…">Loading access…</div></div>
          </section>
          <section class="personal-profile-panel" data-personal-panel="credentials">
            <div class="profile-panel-heading">
              <div><h3>Credentials</h3><p class="muted">Generate or revoke tokens for this identity. Tokens do not carry their own permissions.</p></div>
              <div class="button-row compact-token-controls">
                <label>TTL hours <input id="personalTokenTtl" type="number" value="720" min="1" max="8760" /></label>
                <button id="mintPersonalTokenBtn" type="button">Generate token</button>
              </div>
            </div>
            <div id="personalTokensList" class="stacked-output compact-scroll-output credential-list"><div class="muted small-text" data-pac-loading="Loading tokens…">Loading tokens…</div></div>
          </section>
          <section class="personal-profile-panel" data-personal-panel="memory">
            <div class="profile-panel-heading">
              <div><h3>Personal PAC RAM</h3><p class="muted">Memory used by PAC when working as your user.</p></div>
              <button id="savePersonalRamBtn" type="button">Save memory</button>
            </div>
            <label class="profile-textarea-label"><textarea id="personalRamContent" rows="14"></textarea></label>
            <div id="personalRamStatus" class="inline-result" hidden></div>
          </section>
          <section class="personal-profile-panel" data-personal-panel="preferences">
            <div class="profile-panel-heading">
              <div><h3>Preferences</h3><p class="muted">Theme and structured user preferences live in your profile menu instead of the global utility bar.</p></div>
              <button id="savePersonalPreferencesBtn" type="button">Save preferences</button>
            </div>
            <div class="profile-form-card profile-preferences-card">
              <label>Theme
                <select id="personalThemeMode">
                  <option value="system">System</option>
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                  <option value="terminal">Terminal</option>
                  <option value="dusk">Dusk</option>
                </select>
              </label>
              <p class="muted small-text">Themes change surfaces and content styling while preserving PAC shell layout, navigation behavior, and icon meanings.</p>
            </div>
            <label class="profile-textarea-label"><textarea id="personalPreferences" rows="10"></textarea></label>
            <p class="muted small-text">Profile details and preferences are saved together.</p>
          </section>
        </main>
      </div>
    </section>`;
  document.body.appendChild(modal);
  bindPersonalProfileTabs(modal);
  document.getElementById('closePersonalSettingsBtn')?.addEventListener('click', closePersonalSettingsModal);
  modal.addEventListener('click', (ev) => { if (ev.target === modal) closePersonalSettingsModal(); });
  const data = await loadPersonalSettingsData();
  document.getElementById('personalUsername').value = data.me?.username || '';
  document.getElementById('personalNavUsername').textContent = data.me?.username || '';
  document.getElementById('personalDisplayName').value = data.me?.display_name || data.me?.username || '';
  document.getElementById('personalNavDisplayName').textContent = data.me?.display_name || data.me?.username || 'Current user';
  document.getElementById('personalEmail').value = data.me?.metadata?.email || '';
  document.getElementById('personalPreferences').value = JSON.stringify(data.me?.metadata?.preferences || {}, null, 2);
  const personalThemeSelect = document.getElementById('personalThemeMode');
  if (personalThemeSelect) {
    personalThemeSelect.value = pacThemeMode || 'system';
    personalThemeSelect.addEventListener('change', () => applyThemeMode(personalThemeSelect.value || 'system'));
  }
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
  document.getElementById('savePersonalPreferencesBtn')?.addEventListener('click', () => document.getElementById('savePersonalProfileBtn')?.click());
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

function bindPersonalProfileTabs(modal) {
  const tabs = Array.from(modal.querySelectorAll('[data-personal-tab]'));
  const panels = Array.from(modal.querySelectorAll('[data-personal-panel]'));
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const selected = tab.dataset.personalTab;
      tabs.forEach((item) => item.classList.toggle('is-active', item === tab));
      panels.forEach((panel) => panel.classList.toggle('is-active', panel.dataset.personalPanel === selected));
    });
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
