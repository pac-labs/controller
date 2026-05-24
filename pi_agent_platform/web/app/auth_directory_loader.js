// Legacy auth directory loading and coordinator helpers.

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
