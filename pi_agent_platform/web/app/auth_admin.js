// Authentication, user, group, and directory-style admin UI helpers.

const authDirectoryState = {
  users: [],
  groups: [],
  selectedKind: 'group',
  selectedId: 'admin',
};

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
    authStatus = await fetch('/v1/auth/status').then((r) => (r.ok ? r.json() : {enabled: false, mode: 'dev-token', needs_setup: false, user_count: 0}));
  } catch (_) {
    authStatus = {enabled: false, mode: 'dev-token', needs_setup: false, user_count: 0};
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
  document.getElementById('loginModal')?.remove();
}

function openLoginModal(mode = 'login') {
  closeLoginModal();
  const modal = document.createElement('div');
  const isSetup = mode === 'setup';
  modal.id = 'loginModal';
  modal.className = 'modal-backdrop';
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
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = 'Username and password are required.';
    }
    return;
  }
  const path = mode === 'setup' ? '/v1/auth/setup' : '/v1/auth/login';
  const payload = mode === 'setup' ? {username, password, display_name: displayName} : {username, password};
  try {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
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
  }
  return true;
}

function serializeGroupGrants(grants = []) {
  return (grants || []).map((grant) => `${grant.resource_type}:${grant.pattern}:${grant.access}`).join(', ');
}

function parseGroupGrants(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const parts = item.split(':');
      const access = (parts.pop() || 'read').trim();
      const resource_type = (parts.shift() || 'workspace').trim();
      const pattern = parts.join(':').trim();
      return {resource_type, pattern, access};
    })
    .filter((item) => item.pattern);
}

function roleOptions(selected) {
  const current = String(selected || 'user');
  return ['user', 'admin', 'readonly'].map((role) => `<option value="${role}" ${current === role ? 'selected' : ''}>${role}</option>`).join('');
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
  if (!enabled && tokenInput && !hasToken) tokenInput.placeholder = 'Bearer token, optional';
}

function closePersonalSettingsModal() {
  document.getElementById('personalSettingsModal')?.remove();
}

async function loadPersonalSettingsData() {
  const [me, tokens, ram] = await Promise.all([
    api('/v1/users/me'),
    api('/v1/users/me/tokens').catch(() => []),
    api('/v1/users/me/ram').catch(() => ({content: ''})),
  ]);
  return {me, tokens, ram};
}

function renderPersonalTokens(target, tokens, latestToken = '') {
  if (!target) return;
  const items = Array.isArray(tokens) ? tokens : [];
  target.innerHTML = `
    ${latestToken ? `<div class="inline-result">${escapeHtml(latestToken)}</div>` : ''}
    ${items.length ? items.map((item) => `<div class="row"><div><b>${escapeHtml(item.username || currentUser?.username || 'token')}</b><br><span class="muted small-text">expires ${escapeHtml(item.expires_at || '-')}</span></div><div class="button-row"><button class="ghost-button revoke-self-token-btn" data-token="${escapeHtml(item.id || item.token || '')}" type="button">Revoke</button></div></div>`).join('') : '<div class="muted small-text">No personal tokens yet.</div>'}`;
  target.querySelectorAll('.revoke-self-token-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const token = btn.dataset.token || '';
    if (!token || !confirm('Revoke this token?')) return;
    await api(`/v1/users/me/tokens/${encodeURIComponent(token)}`, {method: 'DELETE'});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(target, refreshed);
  }));
}

function selectAuthDirectoryNode(kind, id) {
  authDirectoryState.selectedKind = kind;
  authDirectoryState.selectedId = id;
  renderAuthDirectory();
}

function ensureAuthDirectorySelection() {
  const currentItems = authDirectoryState[`${authDirectoryState.selectedKind}s`] || [];
  const found = currentItems.find((item) => item.id === authDirectoryState.selectedId);
  if (found) return;
  const firstGroup = authDirectoryState.groups[0];
  const firstUser = authDirectoryState.users[0];
  if (firstGroup) {
    authDirectoryState.selectedKind = 'group';
    authDirectoryState.selectedId = firstGroup.id;
  } else if (firstUser) {
    authDirectoryState.selectedKind = 'user';
    authDirectoryState.selectedId = firstUser.id;
  } else {
    authDirectoryState.selectedKind = 'group';
    authDirectoryState.selectedId = '';
  }
}

function directoryUserName(user) {
  return user?.display_name || user?.username || user?.name || user?.id || 'User';
}

function directoryGroupName(group) {
  return group?.name || group?.display_name || group?.id || 'Group';
}

function directoryUserById(id) {
  return authDirectoryState.users.find((user) => user.id === id) || null;
}

function directoryGroupById(id) {
  return authDirectoryState.groups.find((group) => group.id === id) || null;
}

function directoryMemberLabel(member) {
  if (member.kind === 'user') return directoryUserName(directoryUserById(member.id)) || member.id;
  if (member.kind === 'group') return directoryGroupName(directoryGroupById(member.id)) || member.id;
  return `${member.kind}:${member.id}`;
}

function renderAuthDirectoryTree() {
  const tree = document.getElementById('authDirectoryTree');
  if (!tree) return;
  tree.innerHTML = `
    <details class="directory-root" open>
      <summary>Groups <span class="directory-count">${authDirectoryState.groups.length}</span></summary>
      <div class="directory-children">
        ${authDirectoryState.groups.map((group) => {
          const members = group.members || [];
          return `<div class="directory-group-shell">
            <button class="directory-node${authDirectoryState.selectedKind === 'group' && authDirectoryState.selectedId === group.id ? ' active' : ''}" data-kind="group" data-id="${escapeHtml(group.id)}" type="button">
              <span class="directory-node-label">${escapeHtml(directoryGroupName(group))}</span>
              <span class="directory-node-meta">${escapeHtml(String(members.length))} members</span>
            </button>
            <div class="directory-children nested">
              ${members.map((member) => `
                <button class="directory-node directory-leaf${authDirectoryState.selectedKind === member.kind && authDirectoryState.selectedId === member.id ? ' active' : ''}" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">
                  <span class="directory-node-label">${escapeHtml(directoryMemberLabel(member))}</span>
                  <span class="directory-node-meta">${escapeHtml(member.kind)}</span>
                </button>`).join('') || '<div class="directory-empty">No direct members.</div>'}
            </div>
          </div>`;
        }).join('') || '<div class="directory-empty">No groups found.</div>'}
      </div>
    </details>
    <details class="directory-root" open>
      <summary>People <span class="directory-count">${authDirectoryState.users.length}</span></summary>
      <div class="directory-children">
        ${authDirectoryState.users.map((user) => `
          <button class="directory-node${authDirectoryState.selectedKind === 'user' && authDirectoryState.selectedId === user.id ? ' active' : ''}" data-kind="user" data-id="${escapeHtml(user.id)}" type="button">
            <span class="directory-node-label">${escapeHtml(directoryUserName(user))}</span>
            <span class="directory-node-meta">${escapeHtml(user.role || 'user')}</span>
          </button>`).join('') || '<div class="directory-empty">No users found.</div>'}
      </div>
    </details>`;
  tree.querySelectorAll('.directory-node').forEach((btn) => {
    btn.addEventListener('click', () => selectAuthDirectoryNode(btn.dataset.kind || 'user', btn.dataset.id || ''));
  });
}

function selectedAuthDirectoryItem() {
  const items = authDirectoryState[`${authDirectoryState.selectedKind}s`] || [];
  return items.find((item) => item.id === authDirectoryState.selectedId) || null;
}

function groupMembershipPills(groupIds, emptyText) {
  return groupIds.length
    ? groupIds.map((groupId) => `<span class="directory-member-pill">${escapeHtml(directoryGroupName(directoryGroupById(groupId)) || groupId)}</span>`).join('')
    : `<span class="muted small-text">${escapeHtml(emptyText)}</span>`;
}

function renderUserDirectoryDetail(user) {
  const detail = document.getElementById('authDirectoryDetail');
  if (!detail) return;
  const username = user.username || user.name || user.id;
  const directGroups = user.direct_groups || [];
  const effectiveGroups = user.effective_groups || [];
  const inheritedGroups = effectiveGroups.filter((groupId) => !directGroups.includes(groupId));
  const current = user.id === currentUser?.id;
  detail.innerHTML = `
    <article class="directory-detail-card">
      <div class="directory-detail-head">
        <div>
          <h3>${escapeHtml(directoryUserName(user))}</h3>
          <p class="muted">${escapeHtml(username)} · ${escapeHtml(user.role || 'user')}</p>
        </div>
        <div class="admin-item-badges">
          <span class="admin-badge subtle">${escapeHtml(user.role || 'user')}</span>
          ${current ? '<span class="admin-badge">current</span>' : ''}
        </div>
      </div>
      <div class="form-grid compact-form">
        <label>Display name <input id="directoryUserDisplayName" value="${escapeHtml(user.display_name || username)}" /></label>
        <label>Role <select id="directoryUserRole">${roleOptions(user.role || 'user')}</select></label>
      </div>
      <div class="directory-members">
        <h4>Direct groups</h4>
        ${groupMembershipPills(directGroups, 'No direct group membership. Add this user from a group detail panel.')}
        <h4>Inherited groups</h4>
        ${groupMembershipPills(inheritedGroups, 'No inherited groups.')}
      </div>
      <div class="directory-detail-meta">
        <span>Created ${escapeHtml(formatDate(user.created_at) || '-')}</span>
        <span>User id <code>${escapeHtml(user.id)}</code></span>
      </div>
      <div class="button-row">
        <button id="saveDirectoryUserBtn" type="button">Save user</button>
        ${current ? '' : `<button id="deleteDirectoryUserBtn" class="ghost-button" type="button">Delete user</button>`}
      </div>
      <pre id="directoryUsersResult" class="inline-result compact-result"></pre>
    </article>`;
  document.getElementById('saveDirectoryUserBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryUsersResult');
    try {
      const display_name = document.getElementById('directoryUserDisplayName')?.value.trim() || username;
      const role = document.getElementById('directoryUserRole')?.value || 'user';
      await api(`/v1/users/${encodeURIComponent(user.id)}`, {method: 'PUT', body: JSON.stringify({display_name, role})});
      if (result) result.textContent = `Saved user ${username}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  document.getElementById('deleteDirectoryUserBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryUsersResult');
    if (!confirm(`Delete user ${username}?`)) return;
    try {
      await api(`/v1/users/${encodeURIComponent(user.id)}`, {method: 'DELETE'});
      authDirectoryState.selectedId = '';
      if (result) result.textContent = `Deleted user ${username}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
}

function renderGroupDirectoryDetail(group) {
  const detail = document.getElementById('authDirectoryDetail');
  if (!detail) return;
  const members = group.members || [];
  const userOptions = authDirectoryState.users.map((user) => `<option value="user:${escapeHtml(user.id)}">User · ${escapeHtml(directoryUserName(user))}</option>`).join('');
  const groupOptions = authDirectoryState.groups.filter((item) => item.id !== group.id).map((item) => `<option value="group:${escapeHtml(item.id)}">Group · ${escapeHtml(directoryGroupName(item))}</option>`).join('');
  detail.innerHTML = `
    <article class="directory-detail-card">
      <div class="directory-detail-head">
        <div>
          <h3>${escapeHtml(directoryGroupName(group))}</h3>
          <p class="muted">${escapeHtml(group.id)} · ${escapeHtml(String((group.grants || []).length))} grants</p>
        </div>
        <div class="admin-item-badges">
          <span class="admin-badge subtle">${escapeHtml(String(members.length))} members</span>
          ${group.system_managed ? '<span class="admin-badge">system</span>' : ''}
        </div>
      </div>
      <div class="form-grid compact-form">
        <label>Name <input id="directoryGroupName" value="${escapeHtml(group.name || group.id)}" /></label>
        <label>Description <input id="directoryGroupDescription" value="${escapeHtml(group.description || '')}" /></label>
        <label class="admin-form-wide">Grants <input id="directoryGroupGrants" value="${escapeHtml(serializeGroupGrants(group.grants || []))}" placeholder="workspace:*:write, source_context:*:write" /></label>
      </div>
      <div class="directory-members">
        <h4>Direct members</h4>
        ${members.length ? members.map((member) => `<span class="directory-member-pill">${escapeHtml(directoryMemberLabel(member))}<button class="link-button remove-directory-member" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">×</button></span>`).join('') : '<span class="muted small-text">No direct members.</span>'}
      </div>
      <div class="form-grid compact-form">
        <label class="admin-form-wide">Add member <select id="directoryMemberPicker"><option value="">Select a user or group…</option>${userOptions}${groupOptions}</select></label>
      </div>
      <div class="button-row">
        <button id="addDirectoryMemberBtn" class="ghost-button" type="button">Add member</button>
        <button id="saveDirectoryGroupBtn" type="button">Save group</button>
        <button id="deleteDirectoryGroupBtn" class="ghost-button" type="button">Delete group</button>
      </div>
      <pre id="directoryGroupsResult" class="inline-result compact-result"></pre>
    </article>`;
  document.getElementById('addDirectoryMemberBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    const value = document.getElementById('directoryMemberPicker')?.value || '';
    const sep = value.indexOf(':');
    const kind = sep >= 0 ? value.slice(0, sep) : '';
    const id = sep >= 0 ? value.slice(sep + 1) : '';
    if (!kind || !id) {
      if (result) result.textContent = 'Select a user or group to add.';
      return;
    }
    try {
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members`, {method: 'POST', body: JSON.stringify({kind, id})});
      if (result) result.textContent = `Added ${kind}:${id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  detail.querySelectorAll('.remove-directory-member').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const result = document.getElementById('directoryGroupsResult');
      const kind = btn.dataset.kind || '';
      const id = btn.dataset.id || '';
      try {
        await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {method: 'DELETE'});
        if (result) result.textContent = `Removed ${kind}:${id}`;
        await fetchAuthStatus();
        renderAuthInfo();
        await loadAuthDirectory();
      } catch (error) {
        if (result) result.textContent = `Failed: ${error.message || String(error)}`;
      }
    });
  });
  document.getElementById('saveDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    try {
      const name = document.getElementById('directoryGroupName')?.value.trim() || group.id;
      const description = document.getElementById('directoryGroupDescription')?.value.trim() || '';
      const grants = parseGroupGrants(document.getElementById('directoryGroupGrants')?.value || '');
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'PUT', body: JSON.stringify({name, description, grants})});
      if (result) result.textContent = `Saved group ${group.id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  document.getElementById('deleteDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    if (!confirm(`Delete group ${group.id}?`)) return;
    try {
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'DELETE'});
      authDirectoryState.selectedId = '';
      if (result) result.textContent = `Deleted group ${group.id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
}

function renderAuthDirectoryDetail() {
  const detail = document.getElementById('authDirectoryDetail');
  if (!detail) return;
  const item = selectedAuthDirectoryItem();
  if (!item) {
    detail.innerHTML = '<div class="muted small-text">Select a user or group from the directory tree.</div>';
    return;
  }
  if (authDirectoryState.selectedKind === 'user') renderUserDirectoryDetail(item);
  else renderGroupDirectoryDetail(item);
}

function renderAuthDirectory() {
  renderAuthDirectoryTree();
  renderAuthDirectoryDetail();
}

async function loadAuthDirectory() {
  const tree = document.getElementById('authDirectoryTree');
  const detail = document.getElementById('authDirectoryDetail');
  if (!(tree && detail)) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    tree.innerHTML = '<div class="muted small-text">User management is available when auth mode is set to user-password.</div>';
    detail.innerHTML = '<div class="muted small-text">Enable user-password auth to manage users, groups, and context access.</div>';
    return;
  }
  try {
    const [users, groups] = await Promise.all([api('/v1/directory/principals?kind=user'), api('/v1/directory/groups')]);
    authDirectoryState.users = users || [];
    authDirectoryState.groups = groups || [];
    ensureAuthDirectorySelection();
    renderAuthDirectory();
  } catch (error) {
    tree.innerHTML = `<div class="muted small-text">Could not load directory: ${escapeHtml(error.message || String(error))}</div>`;
    detail.innerHTML = '<div class="muted small-text">Directory details unavailable.</div>';
  }
}

async function loadUsersList() {
  return loadAuthDirectory();
}

async function loadGroupsList() {
  return loadAuthDirectory();
}

function bindAuthAdminButtons() {
  document.getElementById('refreshDirectoryBtn')?.addEventListener('click', () => loadAuthDirectory().catch((e) => paneError('Directory could not be refreshed', e.message || String(e))));
  document.getElementById('createUserBtn')?.addEventListener('click', async () => {
    const username = document.getElementById('newUsername')?.value.trim() || '';
    const display_name = document.getElementById('newDisplayName')?.value.trim() || username;
    const password = document.getElementById('newUserPassword')?.value || '';
    const role = document.getElementById('newUserRole')?.value || 'user';
    const result = document.getElementById('usersResult');
    try {
      if (!username || !password) throw new Error('Username and password are required.');
      await api('/v1/directory/users', {method: 'POST', body: JSON.stringify({username, display_name, password, role})});
      ['newUsername', 'newDisplayName', 'newUserPassword'].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
      if (result) result.textContent = `User created: ${username}`;
      await fetchAuthStatus();
      renderAuthInfo();
      authDirectoryState.selectedKind = 'user';
      authDirectoryState.selectedId = username;
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  document.getElementById('createGroupBtn')?.addEventListener('click', async () => {
    const id = document.getElementById('newGroupId')?.value.trim() || '';
    const name = document.getElementById('newGroupName')?.value.trim() || id;
    const description = document.getElementById('newGroupDescription')?.value.trim() || '';
    const grants = parseGroupGrants(document.getElementById('newGroupGrants')?.value || '');
    const result = document.getElementById('groupsResult');
    try {
      if (!id) throw new Error('Group id is required.');
      await api('/v1/directory/groups', {method: 'POST', body: JSON.stringify({id, name, description, grants})});
      ['newGroupId', 'newGroupName', 'newGroupDescription', 'newGroupGrants'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
      if (result) result.textContent = `Group created: ${id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      authDirectoryState.selectedKind = 'group';
      authDirectoryState.selectedId = id;
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
}

bindAuthAdminButtons();
