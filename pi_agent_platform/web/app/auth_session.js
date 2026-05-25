// Authentication session and login modal helpers.

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
  const logoutBtn = document.getElementById('userChipLogout');
  const authEnabled = !!(authStatus || config?.auth || {}).enabled;
  const localMode = !authEnabled;
  if (chip && name) {
    if (user || localMode) {
      name.textContent = user ? (user.display_name || user.username || user.id || 'User') : 'Local PAC';
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
  if (loginBtn) loginBtn.hidden = !!user || localMode;
  if (logoutBtn) logoutBtn.hidden = !user && !getStoredToken();
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
