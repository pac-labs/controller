// Directory & Access loader and top-level UI bindings.

function renderAuthDirectory() {
  renderAuthDirectoryTree();
  renderAuthDirectoryDetail();
  window.bindDirectoryDragDrop?.(document);
}

async function loadAuthDirectory(options = {}) {
  const tree = document.getElementById('authDirectoryTree');
  const detail = document.getElementById('authDirectoryDetail');
  if (!(tree && detail)) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    tree.innerHTML = '<div class="muted small-text">Directory & Access is available when auth mode is user-password.</div>';
    detail.innerHTML = '<div class="muted small-text">Enable user-password auth to manage directory identities and credentials.</div>';
    return;
  }
  try {
    const payload = await DirectoryApi.loadAll();
    Object.assign(directoryAccessState, {tree: payload.tree, users: payload.users || [], groups: payload.groups || [], service_accounts: payload.serviceAccounts || [], endpoints: payload.endpoints || [], providers: payload.providers || [], certificate_identities: payload.certificates || [], credentials: payload.credentials || []});
    ensureAuthDirectorySelection();
    renderAuthDirectory();
  } catch (error) {
    tree.innerHTML = `<div class="muted small-text">Could not load directory: ${escapeHtml(error.message || String(error))}</div>`;
    detail.innerHTML = '<div class="muted small-text">Directory details unavailable.</div>';
  }
}

async function loadUsersList() { return loadAuthDirectory(); }
async function loadGroupsList() { return loadAuthDirectory(); }

function replaceDirectoryButton(id) {
  const oldButton = document.getElementById(id);
  if (!oldButton || !oldButton.parentNode) return oldButton;
  const newButton = oldButton.cloneNode(true);
  oldButton.parentNode.replaceChild(newButton, oldButton);
  return newButton;
}

function bindDirectoryAccessUi() {
  const refreshButton = replaceDirectoryButton('refreshDirectoryBtn');
  const createUserButton = replaceDirectoryButton('createUserBtn');
  const createGroupButton = replaceDirectoryButton('createGroupBtn');
  const createServiceAccountButton = replaceDirectoryButton('createServiceAccountBtn');
  refreshButton?.addEventListener('click', () => loadAuthDirectory().catch((e) => paneError('Directory could not be refreshed', e.message || String(e))));
  document.querySelectorAll('[data-open-add]').forEach((button) => {
    button.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      openDirectoryCreateMenu(button.dataset.openAdd || 'addPersonMenu');
    });
  });
  document.querySelectorAll('[data-create-type]').forEach((button) => {
    button.addEventListener('click', () => setDirectoryCreateType(button.dataset.createType || 'person'));
  });
  document.getElementById('directoryCreateBack')?.addEventListener('click', directoryCreatePreviousStep);
  document.getElementById('directoryCreateNext')?.addEventListener('click', directoryCreateNextStep);
  document.getElementById('directoryCreateSubmit')?.addEventListener('click', submitDirectoryCreateWizard);
  document.getElementById('closeDirectoryCreateModal')?.addEventListener('click', closeDirectoryCreateModal);
  document.getElementById('directoryCreateModal')?.addEventListener('click', (ev) => {
    if (ev.target?.id === 'directoryCreateModal') closeDirectoryCreateModal();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !document.getElementById('directoryCreateModal')?.hidden) closeDirectoryCreateModal();
  });
  setDirectoryCreateType('person');
  setDirectoryCreateWizardStep('choose');
  const newGrantBuilder = document.getElementById('newDirectoryGroupGrantBuilder');
  if (newGrantBuilder) { newGrantBuilder.innerHTML = renderDirectoryGrantBuilder([]); bindDirectoryGrantBuilder(newGrantBuilder); }
  document.getElementById('directorySearch')?.addEventListener('input', (ev) => { directoryAccessState.search = ev.target.value || ''; renderAuthDirectoryTree(); });
  createUserButton?.addEventListener('click', async () => {
    const username = document.getElementById('newUsername')?.value.trim() || '';
    const display_name = document.getElementById('newDisplayName')?.value.trim() || username;
    const password = document.getElementById('newUserPassword')?.value || '';
    const role = document.getElementById('newUserRole')?.value || 'user';
    const result = document.getElementById('usersResult');
    try {
      if (!username || !password) throw new Error('Username and password are required.');
      await DirectoryApi.createUser({username, display_name, password, role});
      ['newUsername', 'newDisplayName', 'newUserPassword'].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
      if (result) result.textContent = `User created: ${username}`;
      closeDirectoryCreateModal();
      directoryAccessState.selectedKind = 'user'; directoryAccessState.selectedId = username;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  createGroupButton?.addEventListener('click', async () => {
    const id = document.getElementById('newGroupId')?.value.trim() || '';
    const name = document.getElementById('newGroupName')?.value.trim() || id;
    const description = document.getElementById('newGroupDescription')?.value.trim() || '';
    const groupPanel = document.querySelector('[data-create-panel="group"]');
    const grants = readDirectoryGrantRows(groupPanel || document);
    const result = document.getElementById('groupsResult');
    try {
      if (!id) throw new Error('Group id is required.');
      await DirectoryApi.createGroup({id, name, description, grants});
      ['newGroupId', 'newGroupName', 'newGroupDescription'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
      const newGrantBuilder = document.getElementById('newDirectoryGroupGrantBuilder');
      if (newGrantBuilder) { newGrantBuilder.innerHTML = renderDirectoryGrantBuilder([]); bindDirectoryGrantBuilder(newGrantBuilder); }
      if (result) result.textContent = `Group created: ${id}`;
      closeDirectoryCreateModal();
      directoryAccessState.selectedKind = 'group'; directoryAccessState.selectedId = id;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  createServiceAccountButton?.addEventListener('click', async () => {
    const result = document.getElementById('serviceAccountsResult');
    try {
      const id = document.getElementById('newServiceAccountId')?.value.trim() || '';
      const name = document.getElementById('newServiceAccountName')?.value.trim() || id;
      const description = document.getElementById('newServiceAccountDescription')?.value.trim() || '';
      if (!id) throw new Error('Service account id is required.');
      await DirectoryApi.createServiceAccount({id, name, description});
      ['newServiceAccountId','newServiceAccountName','newServiceAccountDescription'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
      if (result) result.textContent = `Service account created: ${id}`;
      closeDirectoryCreateModal();
      directoryAccessState.selectedKind = 'service_account'; directoryAccessState.selectedId = id;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

bindDirectoryAccessUi();
