// Authentication status summary and header auth controls.

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
  if (!enabled && tokenInput && !hasToken) tokenInput.placeholder = 'Optional';
}
