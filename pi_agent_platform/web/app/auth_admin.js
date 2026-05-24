// Compatibility coordinator for authentication and legacy directory admin UI.
// Auth, personal-account, and directory rendering logic now lives in focused modules.

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
