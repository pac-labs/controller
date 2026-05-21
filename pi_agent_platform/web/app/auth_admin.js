// Authentication, user, group, and personal-settings UI helpers extracted from app.js.

function getStoredToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || '';
}
function setStoredToken(token) {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}
function showUserChip(user) {
  const chip = document.getElementById('userChip');
  const name = document.getElementById('userChipName');
  const loginBtn = document.getElementById('loginBtn');
  if (chip && name) {
    if (user) {
      name.textContent = user.display_name || user.username || user.id || 'User';
      chip.hidden = false;
      chip.style.display = 'inline-flex';
    } else {
      chip.hidden = true;
      chip.style.display = 'none';
      chip.setAttribute('aria-expanded', 'false');
      chip.closest('.user-menu-wrap')?.classList.remove('open');
      document.getElementById('userMenu')?.setAttribute('hidden', '');
    }
  }
  if (loginBtn) loginBtn.hidden = !!user;
}
async function fetchAuthStatus() {
  try {
    authStatus = await fetch('/v1/auth/status').then(r => r.ok ? r.json() : {enabled:false, mode:'dev-token', needs_setup:false, user_count:0});
  } catch (_) {
    authStatus = {enabled:false, mode:'dev-token', needs_setup:false, user_count:0};
  }
  return authStatus;
}
async function fetchCurrentUser() {
  if (!getStoredToken()) {
    currentUser = null;
    showUserChip(null);
    return null;
  }
  try {
    currentUser = await api('/v1/auth/me');
    showUserChip(currentUser);
    return currentUser;
  } catch (_) {
    setStoredToken('');
    currentUser = null;
    showUserChip(null);
    return null;
  }
}
function closeLoginModal() {
  const modal = document.getElementById('loginModal');
  if (modal) modal.remove();
}
function openLoginModal(mode = 'login') {
  closeLoginModal();
  const modal = document.createElement('div');
  modal.id = 'loginModal';
  modal.className = 'modal-backdrop';
  const isSetup = mode === 'setup';
  modal.innerHTML = `
    <section class="modal-card auth-modal-card" role="dialog" aria-modal="true" aria-labelledby="loginModalTitle">
      <div class="section-heading">
        <div>
          <h2 id="loginModalTitle">${isSetup ? 'Create PAC admin account' : 'Log in to PAC'}</h2>
          <p class="muted">${isSetup ? 'Initial setup is required before PAC can be used with named users.' : 'Use your PAC account to unlock the controller UI.'}</p>
        </div>
        ${isSetup ? '' : '<button id="closeLoginModalBtn" class="ghost-button" type="button">Close</button>'}
      </div>
      <div class="form-grid compact-form">
        <label>Username <input id="loginUsername" autocomplete="username" /></label>
        ${isSetup ? '<label>Display name <input id="loginDisplayName" autocomplete="name" /></label>' : ''}
        <label>Password <input id="loginPassword" type="password" autocomplete="current-password" /></label>
      </div>
      <div id="loginError" class="inline-result" hidden></div>
      <div class="button-row">
        <button id="doLoginBtn" type="button">${isSetup ? 'Create admin account' : 'Log in'}</button>
        ${isSetup ? '' : '<button id="cancelLoginBtn" class="ghost-button" type="button">Cancel</button>'}
      </div>
    </section>`;
  document.body.appendChild(modal);
  if (!isSetup) {
    document.getElementById('closeLoginModalBtn')?.addEventListener('click', closeLoginModal);
    document.getElementById('cancelLoginBtn')?.addEventListener('click', closeLoginModal);
    modal.addEventListener('click', (ev) => { if (ev.target === modal) closeLoginModal(); });
  }
  document.getElementById('doLoginBtn')?.addEventListener('click', () => submitLoginModal(mode));
  document.getElementById('loginPassword')?.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') submitLoginModal(mode); });
  document.getElementById('loginUsername')?.focus();
}
async function submitLoginModal(mode = 'login') {
  const username = document.getElementById('loginUsername')?.value.trim() || '';
  const password = document.getElementById('loginPassword')?.value || '';
  const displayName = document.getElementById('loginDisplayName')?.value.trim() || username;
  const errorEl = document.getElementById('loginError');
  if (!username || !password) {
    if (errorEl) { errorEl.hidden = false; errorEl.textContent = 'Username and password are required.'; }
    return;
  }
  const path = mode === 'setup' ? '/v1/auth/setup' : '/v1/auth/login';
  const payload = mode === 'setup' ? {username, password, display_name: displayName} : {username, password};
  try {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || 'Authentication failed');
    setStoredToken(data.token || '');
    currentUser = data.user || null;
    showUserChip(currentUser);
    renderHeaderAuthBox();
    closeLoginModal();
    await init();
  } catch (error) {
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = error.message || 'Authentication failed';
    }
  }
}
function logoutUser() {
  setStoredToken('');
  currentUser = null;
  showUserChip(null);
  renderHeaderAuthBox();
  if (authStatus?.enabled && authStatus?.mode === 'user-password') openLoginModal('login');
}
async function ensureAuthReady() {
  await fetchAuthStatus();
  if (!authStatus?.enabled) {
    currentUser = null;
    showUserChip(null);
    return true;
  }
  if (authStatus.mode === 'user-password') {
    if (authStatus.needs_setup) {
      openLoginModal('setup');
      return false;
    }
    const user = await fetchCurrentUser();
    if (!user) {
      openLoginModal('login');
      return false;
    }
    return true;
  }
  return true;
}
function renderAuthInfo() {
  const el = document.getElementById('authInfo');
  if (!el) return;
  const info = authStatus || config?.auth || {};
  el.innerHTML = '';
  const rows = [
    ['Mode', String(info.mode || 'open')],
    ['Enabled', info.enabled ? 'yes' : 'no'],
    ['Users', String(info.user_count ?? '-')],
    ['TTL', `${info.token_ttl_hours || config?.auth?.token_ttl_hours || 720}h`],
  ];
  rows.forEach(([label, value]) => {
    const row = document.createElement('div');
    row.innerHTML = `<span>${escapeHtml(label)}</span><code>${escapeHtml(value)}</code>`;
    el.appendChild(row);
  });
}

function serializeGroupGrants(grants = []) {
  return (grants || []).map((grant) => `${grant.resource_type}:${grant.pattern}:${grant.access}`).join(', ');
}

function parseGroupGrants(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean).map((item) => {
    const parts = item.split(':');
    const access = (parts.pop() || 'read').trim();
    const resource_type = (parts.shift() || 'workspace').trim();
    const pattern = parts.join(':').trim();
    return {resource_type, pattern, access};
  }).filter((item) => item.pattern);
}

function roleOptions(selected) {
  const current = String(selected || 'user');
  return ['user', 'admin', 'readonly'].map((role) => `<option value="${role}" ${current === role ? 'selected' : ''}>${role}</option>`).join('');
}
async function loadUsersList() {
  const el = document.getElementById('usersList');
  if (!el) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    el.innerHTML = '<div class="muted small-text">User management is available when auth mode is set to user-password.</div>';
    return;
  }
  try {
    const users = await api('/v1/users');
    if (!users.length) {
      el.innerHTML = '<div class="muted small-text">No users found.</div>';
      return;
    }
    el.innerHTML = users.map((user) => `
      <div class="row">
        <div><b>${escapeHtml(user.display_name || user.username)}</b><br><span class="muted small-text">${escapeHtml(user.username)} · ${escapeHtml(user.role || 'user')}</span></div>
        <div class="button-row">
          ${user.id === currentUser?.id ? '<span class="muted small-text">current</span>' : `<button class="ghost-button delete-user-btn" data-user-id="${escapeHtml(user.id)}" type="button">Delete</button>`}
        </div>
      </div>`).join('');
    el.querySelectorAll('.delete-user-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        if (!userId || !confirm(`Delete user ${userId}?`)) return;
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load users: ${escapeHtml(error.message || String(error))}</div>`;
  }
}
function renderHeaderAuthBox() {
  const tokenInput = document.getElementById('token');
  const loginBtn = document.getElementById('loginBtn');
  const auth = authStatus || config?.auth || {};
  const enabled = !!auth.enabled;
  const storedToken = getStoredToken();
  const hasToken = !!(storedToken || String(tokenInput?.value || '').trim());
  if (tokenInput) tokenInput.hidden = !!(enabled && auth.mode === 'user-password');
  if (loginBtn) loginBtn.textContent = auth.needs_setup ? 'Set up account' : 'Log in';
  showUserChip(currentUser);
}
function closePersonalSettingsModal() {
  document.getElementById('personalSettingsModal')?.remove();
}
async function loadPersonalSettingsData() {
  const [me, tokens, ram] = await Promise.all([
    api('/v1/users/me'),
    api('/v1/users/me/tokens').catch(() => []),
    api('/v1/users/me/ram').catch(() => ({content:''})),
  ]);
  return {me, tokens, ram};
}
function renderPersonalTokens(target, tokens, latestToken='') {
  if (!target) return;
  const items = Array.isArray(tokens) ? tokens : [];
  target.innerHTML = `
    ${latestToken ? `<div class="inline-result">${escapeHtml(latestToken)}</div>` : ''}
    ${items.length ? items.map((item) => `<div class="row"><div><b>${escapeHtml(item.username || currentUser?.username || 'token')}</b><br><span class="muted small-text">expires ${escapeHtml(item.expires_at || '-')}</span></div><div class="button-row"><button class="ghost-button revoke-self-token-btn" data-token="${escapeHtml(item.token)}" type="button">Revoke</button></div></div>`).join('') : '<div class="muted small-text">No personal tokens yet.</div>'}`;
  target.querySelectorAll('.revoke-self-token-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const token = btn.dataset.token || '';
    if (!token || !confirm('Revoke this token?')) return;
    await api(`/v1/users/me/tokens/${encodeURIComponent(token)}`, {method:'DELETE'});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(target, refreshed);
  }));
}

function renderAuthInfo() {
  const el = document.getElementById('authInfo');
  if (!el) return;
  const info = authStatus || config?.auth || {};
  el.innerHTML = '';
  [
    ['Mode', String(info.mode || 'open')],
    ['Enabled', info.enabled ? 'yes' : 'no'],
    ['Users', String(info.user_count ?? '-')],
    ['Groups', String(info.group_count ?? '-')],
    ['Access requests', String(info.pending_access_requests ?? 0)],
    ['TTL', `${info.token_ttl_hours || config?.auth?.token_ttl_hours || 720}h`],
  ].forEach(([label, value]) => {
    const row = document.createElement('div');
    row.innerHTML = `<span>${escapeHtml(label)}</span><code>${escapeHtml(value)}</code>`;
    el.appendChild(row);
  });
}

async function loadUsersList() {
  const el = document.getElementById('usersList');
  if (!el) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    el.innerHTML = '<div class="muted small-text">User management is available when auth mode is set to user-password.</div>';
    return;
  }
  try {
    const users = await api('/v1/users');
    if (!users.length) {
      el.innerHTML = '<div class="muted small-text">No users found.</div>';
      return;
    }
    el.innerHTML = users.map((user) => {
      const current = user.id === currentUser?.id;
      return `
        <article class="admin-item-card">
          <div class="admin-item-head">
            <div>
              <b>${escapeHtml(user.display_name || user.username)}</b>
              <span class="muted small-text">${escapeHtml(user.username)} · ${escapeHtml(user.role || 'user')}</span>
            </div>
            <div class="admin-item-badges">
              <span class="admin-badge subtle">${escapeHtml(user.role || 'user')}</span>
              ${current ? '<span class="admin-badge">current</span>' : ''}
            </div>
          </div>
          <div class="admin-item-summary">Users inherit platform administration separately from resource usage. Use groups to control which contexts, workspaces, and tools they may actually use.</div>
          <div class="admin-inline-grid">
            <label>Display name <input class="user-display-input" data-user-id="${escapeHtml(user.id)}" value="${escapeHtml(user.display_name || user.username)}" placeholder="Display name" /></label>
            <label>Role <select class="user-role-input" data-user-id="${escapeHtml(user.id)}">${roleOptions(user.role || 'user')}</select></label>
            <label class="admin-form-wide">Groups <input class="user-groups-input" data-user-id="${escapeHtml(user.id)}" value="${escapeHtml((user.groups || []).join(', '))}" placeholder="admin,docs,coders" /></label>
          </div>
          <div class="admin-item-actions">
            <span class="muted">Created ${escapeHtml(formatDate(user.created_at) || '-')}</span>
            <div class="button-row">
              <button class="ghost-button save-user-btn" data-user-id="${escapeHtml(user.id)}" type="button">Save</button>
              ${current ? '' : `<button class="ghost-button delete-user-btn" data-user-id="${escapeHtml(user.id)}" type="button">Delete</button>`}
            </div>
          </div>
        </article>`;
    }).join('');
    el.querySelectorAll('.save-user-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        const card = btn.closest('.admin-item-card');
        const display_name = card?.querySelector('.user-display-input')?.value?.trim() || userId;
        const role = card?.querySelector('.user-role-input')?.value || 'user';
        const groups = String(card?.querySelector('.user-groups-input')?.value || '').split(',').map((item) => item.trim()).filter(Boolean);
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'PUT', body: JSON.stringify({display_name, role, groups})});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
    el.querySelectorAll('.delete-user-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        if (!userId || !confirm(`Delete user ${userId}?`)) return;
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load users: ${escapeHtml(error.message || String(error))}</div>`;
  }
}

async function loadGroupsList() {
  const el = document.getElementById('groupsList');
  if (!el) return;
  try {
    const groups = await api('/v1/groups');
    if (!groups.length) {
      el.innerHTML = '<div class="muted small-text">No groups found.</div>';
      return;
    }
    el.innerHTML = groups.map((group) => `
      <article class="admin-item-card">
        <div class="admin-item-head">
          <div>
            <b>${escapeHtml(group.name || group.id)}</b>
            <span class="muted small-text">${escapeHtml(group.id)}</span>
          </div>
          <div class="admin-item-badges">
            <span class="admin-badge subtle">${escapeHtml(String((group.grants || []).length))} grants</span>
          </div>
        </div>
        <div class="admin-inline-grid">
          <label>Name <input class="group-name-input" data-group-id="${escapeHtml(group.id)}" value="${escapeHtml(group.name || group.id)}" /></label>
          <label>Description <input class="group-description-input" data-group-id="${escapeHtml(group.id)}" value="${escapeHtml(group.description || '')}" /></label>
          <label class="admin-form-wide">Grants <input class="group-grants-input" data-group-id="${escapeHtml(group.id)}" value="${escapeHtml(serializeGroupGrants(group.grants || []))}" placeholder="workspace:*:write, source_context:*:write" /></label>
        </div>
        <div class="admin-item-actions">
          <span class="muted">Use groups on agent contexts for who may use or edit them. Grants cover broad resource access.</span>
          <div class="button-row">
            <button class="ghost-button save-group-btn" data-group-id="${escapeHtml(group.id)}" type="button">Save</button>
            <button class="ghost-button delete-group-btn" data-group-id="${escapeHtml(group.id)}" type="button">Delete</button>
          </div>
        </div>
      </article>`).join('');
    el.querySelectorAll('.save-group-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const groupId = btn.dataset.groupId || '';
        const card = btn.closest('.admin-item-card');
        const name = card?.querySelector('.group-name-input')?.value?.trim() || groupId;
        const description = card?.querySelector('.group-description-input')?.value?.trim() || '';
        const grants = parseGroupGrants(card?.querySelector('.group-grants-input')?.value || '');
        await api(`/v1/groups/${encodeURIComponent(groupId)}`, {method:'PUT', body: JSON.stringify({name, description, grants})});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadGroupsList();
        await loadUsersList();
      });
    });
    el.querySelectorAll('.delete-group-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const groupId = btn.dataset.groupId || '';
        if (!groupId || !confirm(`Delete group ${groupId}?`)) return;
        await api(`/v1/groups/${encodeURIComponent(groupId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadGroupsList();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load groups: ${escapeHtml(error.message || String(error))}</div>`;
  }
}


