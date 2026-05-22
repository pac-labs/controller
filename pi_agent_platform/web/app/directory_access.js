// Directory & Access UI pass 6. Overrides the legacy user/group admin renderer with a directory-first surface.

const directoryAccessState = {
  tree: null,
  users: [],
  groups: [],
  service_accounts: [],
  endpoints: [],
  providers: [],
  certificate_identities: [],
  credentials: [],
  selectedKind: 'folder',
  selectedId: 'people',
  search: '',
};

const DIRECTORY_GRANT_PRESETS = [
  ['profile:*:use', 'Can use all profiles'],
  ['workspace:*:read', 'Can view all workspaces'],
  ['workspace:*:write', 'Can edit all workspaces'],
  ['agent_context:*:use', 'Can use all agent contexts'],
  ['agent_context:*:write', 'Can edit all agent contexts'],
  ['endpoint:*:execute', 'Can execute endpoint jobs'],
  ['provider:*:use', 'Can use model providers'],
  ['diagnostics:*:read', 'Can view diagnostics'],
  ['system:*:manage', 'Full PAC administration'],
];

const DIRECTORY_FOLDERS = [
  ['people', 'People', 'user', 'users'],
  ['groups', 'Groups', 'group', 'groups'],
  ['service_accounts', 'Service Accounts', 'service_account', 'service_accounts'],
  ['endpoints', 'Endpoints', 'endpoint', 'endpoints'],
  ['providers', 'Providers', 'provider', 'providers'],
  ['certificate_identities', 'Certificate Identities', 'certificate_identity', 'certificate_identities'],
  ['credentials', 'Credentials', 'credential', 'credentials'],
];

function directoryItemsForKind(kind) {
  if (kind === 'user') return directoryAccessState.users;
  if (kind === 'group') return directoryAccessState.groups;
  if (kind === 'service_account') return directoryAccessState.service_accounts;
  if (kind === 'endpoint') return directoryAccessState.endpoints;
  if (kind === 'provider') return directoryAccessState.providers;
  if (kind === 'certificate_identity') return directoryAccessState.certificate_identities;
  if (kind === 'credential') return directoryAccessState.credentials;
  return [];
}

function directoryPrincipalLabel(item) {
  return item?.display_name || item?.name || item?.username || item?.id || 'Directory object';
}

function directoryPrincipalSubtitle(item) {
  const parts = [item?.kind || 'object'];
  if (item?.source) parts.push(item.source);
  if (item?.status) parts.push(item.status);
  return parts.filter(Boolean).join(' · ');
}

function directoryFind(kind, id) {
  return directoryItemsForKind(kind).find((item) => item.id === id) || null;
}

function directoryMemberTitle(member) {
  const item = directoryFind(member.kind, member.id);
  return directoryPrincipalLabel(item) || `${member.kind}:${member.id}`;
}

function directoryMatches(item, folderLabel = '') {
  const q = String(directoryAccessState.search || '').trim().toLowerCase();
  if (!q) return true;
  return [folderLabel, item?.id, item?.name, item?.display_name, item?.username, item?.description, item?.kind]
    .some((value) => String(value || '').toLowerCase().includes(q));
}

function selectAuthDirectoryNode(kind, id) {
  directoryAccessState.selectedKind = kind;
  directoryAccessState.selectedId = id;
  renderAuthDirectory();
}

function ensureAuthDirectorySelection() {
  if (directoryAccessState.selectedKind === 'folder') return;
  const found = directoryFind(directoryAccessState.selectedKind, directoryAccessState.selectedId);
  if (found) return;
  const firstUser = directoryAccessState.users[0];
  directoryAccessState.selectedKind = firstUser ? 'user' : 'folder';
  directoryAccessState.selectedId = firstUser?.id || 'people';
}

function renderAuthDirectoryTree() {
  const tree = document.getElementById('authDirectoryTree');
  if (!tree) return;
  tree.innerHTML = DIRECTORY_FOLDERS.map(([folderId, label, itemKind, stateKey]) => {
    const items = (directoryAccessState[stateKey] || []).filter((item) => directoryMatches(item, label));
    return `<details class="directory-root" open>
      <summary class="directory-folder${directoryAccessState.selectedKind === 'folder' && directoryAccessState.selectedId === folderId ? ' active' : ''}" data-kind="folder" data-id="${escapeHtml(folderId)}">
        <span>${escapeHtml(label)}</span><span class="directory-count">${items.length}</span>
      </summary>
      <div class="directory-children">
        ${items.map((item) => renderDirectoryTreeItem(itemKind, item)).join('') || '<div class="directory-empty">No entries.</div>'}
      </div>
    </details>`;
  }).join('');
  tree.querySelectorAll('.directory-node,.directory-folder').forEach((node) => {
    node.addEventListener('click', (ev) => {
      if (node.classList.contains('directory-folder')) ev.preventDefault();
      selectAuthDirectoryNode(node.dataset.kind || 'folder', node.dataset.id || 'people');
    });
  });
}

function renderDirectoryTreeItem(kind, item) {
  const active = directoryAccessState.selectedKind === kind && directoryAccessState.selectedId === item.id;
  const label = kind === 'credential' ? item.name || item.id : directoryPrincipalLabel(item);
  const meta = kind === 'group' ? `${(item.members || []).length} members` : (kind === 'credential' ? item.kind : (item.status || item.source || kind));
  const nested = kind === 'group' && (item.members || []).length
    ? `<div class="directory-children nested">${(item.members || []).slice(0, 8).map((member) => `<button class="directory-node directory-leaf${directoryAccessState.selectedKind === member.kind && directoryAccessState.selectedId === member.id ? ' active' : ''}" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button"><span class="directory-node-label">${escapeHtml(directoryMemberTitle(member))}</span><span class="directory-node-meta">${escapeHtml(member.kind)}</span></button>`).join('')}</div>`
    : '';
  return `<div class="directory-group-shell"><button class="directory-node${active ? ' active' : ''}" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}" type="button"><span class="directory-node-label">${escapeHtml(label)}</span><span class="directory-node-meta">${escapeHtml(meta || '')}</span></button>${nested}</div>`;
}

function selectedAuthDirectoryItem() {
  if (directoryAccessState.selectedKind === 'folder') return {id: directoryAccessState.selectedId, kind: 'folder'};
  return directoryFind(directoryAccessState.selectedKind, directoryAccessState.selectedId);
}

function formatGrantPills(grants) {
  const items = Array.isArray(grants) ? grants : [];
  if (!items.length) return '<span class="muted small-text">No explicit grants. Access may still be inherited from containing groups.</span>';
  return items.map((grant) => `<span class="directory-member-pill">${escapeHtml(grant.resource_type || 'resource')}:${escapeHtml(grant.pattern || '*')}:${escapeHtml(grant.access || 'read')}</span>`).join('');
}

function formatGroupPills(groups, emptyText) {
  const entries = Array.isArray(groups) ? groups : [];
  if (!entries.length) return `<span class="muted small-text">${escapeHtml(emptyText)}</span>`;
  return entries.map((entry) => {
    const id = typeof entry === 'string' ? entry : entry.id;
    const path = Array.isArray(entry.path) && entry.path.length > 1 ? ` title="${escapeHtml(entry.path.join(' → '))}"` : '';
    return `<span class="directory-member-pill"${path}>${escapeHtml(directoryPrincipalLabel(directoryFind('group', id)) || id)}</span>`;
  }).join('');
}

function renderAuthDirectoryDetail() {
  const detail = document.getElementById('authDirectoryDetail');
  const title = document.getElementById('directoryDetailTitle');
  const subtitle = document.getElementById('directoryDetailSubtitle');
  if (!detail) return;
  const item = selectedAuthDirectoryItem();
  if (!item) {
    detail.innerHTML = '<div class="muted small-text">Select an item from the directory tree.</div>';
    return;
  }
  if (item.kind === 'folder') {
    renderDirectoryFolderDetail(item.id, detail, title, subtitle);
    return;
  }
  if (item.kind === 'group') renderDirectoryGroupDetail(item, detail, title, subtitle);
  else if (item.kind === 'credential') renderCredentialDetail(item, detail, title, subtitle);
  else renderDirectoryPrincipalDetail(item, detail, title, subtitle);
}

function renderDirectoryFolderDetail(folderId, detail, title, subtitle) {
  const folder = DIRECTORY_FOLDERS.find(([id]) => id === folderId) || DIRECTORY_FOLDERS[0];
  const items = directoryItemsForKind(folder[2]);
  if (title) title.textContent = folder[1];
  if (subtitle) subtitle.textContent = 'Directory container';
  detail.innerHTML = `<article class="directory-detail-card"><h3>${escapeHtml(folder[1])}</h3><p class="muted">${items.length} entries in this directory section.</p><div class="directory-folder-summary">${items.slice(0, 20).map((item) => `<button class="directory-summary-card" data-kind="${escapeHtml(folder[2])}" data-id="${escapeHtml(item.id)}" type="button"><b>${escapeHtml(directoryPrincipalLabel(item))}</b><span>${escapeHtml(directoryPrincipalSubtitle(item))}</span></button>`).join('') || '<span class="muted small-text">No entries.</span>'}</div></article>`;
  detail.querySelectorAll('.directory-summary-card').forEach((btn) => btn.addEventListener('click', () => selectAuthDirectoryNode(btn.dataset.kind || 'user', btn.dataset.id || '')));
}

async function renderDirectoryPrincipalDetail(item, detail, title, subtitle) {
  if (title) title.textContent = directoryPrincipalLabel(item);
  if (subtitle) subtitle.textContent = directoryPrincipalSubtitle(item);
  detail.innerHTML = `<article class="directory-detail-card"><div class="muted small-text">Loading effective access…</div></article>`;
  const [access, credentials] = await Promise.all([
    api(`/v1/directory/principals/${encodeURIComponent(item.id)}/effective-access`).catch(() => null),
    api(`/v1/directory/principals/${encodeURIComponent(item.id)}/credentials`).catch(() => []),
  ]);
  const membership = access?.membership || {direct_groups: item.direct_groups || [], effective_groups: item.effective_groups || []};
  const direct = membership.direct_groups || [];
  const effective = (membership.effective_groups || []).filter((entry) => !(typeof entry === 'string' ? direct.includes(entry) : entry.direct));
  detail.innerHTML = `<article class="directory-detail-card">
    <div class="directory-detail-head"><div><h3>${escapeHtml(directoryPrincipalLabel(item))}</h3><p class="muted">${escapeHtml(item.id)} · ${escapeHtml(item.kind)}</p></div><div class="admin-item-badges"><span class="admin-badge subtle">${escapeHtml(item.source || 'local')}</span>${item.system_managed ? '<span class="admin-badge">system</span>' : ''}</div></div>
    <div class="directory-tabs-grid">
      <section><h4>Overview</h4><div class="directory-detail-meta"><span>Status ${escapeHtml(item.status || 'active')}</span><span>Created ${escapeHtml(formatDate(item.created_at) || '-')}</span></div><p class="muted small-text">${escapeHtml(item.description || 'No description provided.')}</p></section>
      <section><h4>Groups</h4><p class="muted small-text">Direct membership</p>${formatGroupPills(direct, 'No direct groups.')}<p class="muted small-text">Inherited membership</p>${formatGroupPills(effective, 'No inherited groups.')}</section>
      <section><h4>Credentials</h4><p class="muted small-text">Credentials identify this principal. Permissions come from directory groups.</p>${renderCredentialRows(credentials, false)}${renderCredentialCreateControls(item)}</section>
      <section><h4>Effective access</h4>${formatGrantPills(access?.grants || [])}</section>
    </div>
    <pre id="directoryPrincipalResult" class="inline-result compact-result"></pre>
  </article>`;
  bindCredentialActions(detail, item);
}

function renderDirectoryGroupDetail(group, detail, title, subtitle) {
  if (title) title.textContent = directoryPrincipalLabel(group);
  if (subtitle) subtitle.textContent = `Group · ${(group.members || []).length} direct members`;
  const members = group.members || [];
  const options = ['user','group','service_account','endpoint','provider','certificate_identity'].map((kind) => directoryItemsForKind(kind).filter((entry) => !(kind === 'group' && entry.id === group.id)).map((entry) => `<option value="${escapeHtml(kind)}:${escapeHtml(entry.id)}">${escapeHtml(kind)} · ${escapeHtml(directoryPrincipalLabel(entry))}</option>`).join('')).join('');
  detail.innerHTML = `<article class="directory-detail-card">
    <div class="directory-detail-head"><div><h3>${escapeHtml(directoryPrincipalLabel(group))}</h3><p class="muted">${escapeHtml(group.id)} · group</p></div><div class="admin-item-badges"><span class="admin-badge subtle">${members.length} members</span>${group.system_managed ? '<span class="admin-badge">system</span>' : ''}</div></div>
    <div class="form-grid compact-form"><label>Name <input id="directoryGroupName" value="${escapeHtml(group.name || group.id)}" /></label><label>Description <input id="directoryGroupDescription" value="${escapeHtml(group.description || '')}" /></label><label class="admin-form-wide">Access grants <input id="directoryGroupGrants" value="${escapeHtml(serializeGroupGrants(group.grants || []))}" placeholder="profile:*:use, workspace:*:read" /></label><label>Common grant <select id="directoryGrantPreset"><option value="">Add a permission…</option>${DIRECTORY_GRANT_PRESETS.map(([value,label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join('')}</select></label><p class="muted small-text admin-form-wide">Tokens only identify the principal. These directory grants decide what members can use.</p></div>
    <div class="directory-tabs-grid"><section><h4>Members</h4>${members.length ? members.map((member) => `<span class="directory-member-pill">${escapeHtml(directoryMemberTitle(member))}<button class="link-button remove-directory-member" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">×</button></span>`).join('') : '<span class="muted small-text">No direct members.</span>'}<label class="admin-form-wide directory-add-member">Add member <select id="directoryMemberPicker"><option value="">Select a directory object…</option>${options}</select></label><button id="addDirectoryMemberBtn" class="ghost-button" type="button">Add member</button></section><section><h4>Access grants</h4>${formatGrantPills(group.grants || [])}</section></div>
    <div class="button-row"><button id="saveDirectoryGroupBtn" type="button">Save group</button><button id="deleteDirectoryGroupBtn" class="ghost-button" type="button">Delete group</button></div><pre id="directoryGroupsResult" class="inline-result compact-result"></pre>
  </article>`;
  bindGroupDetailActions(detail, group);
}

function bindGroupDetailActions(detail, group) {
  detail.querySelector('#addDirectoryMemberBtn')?.addEventListener('click', async () => {
    const result = detail.querySelector('#directoryGroupsResult');
    const value = detail.querySelector('#directoryMemberPicker')?.value || '';
    const sep = value.indexOf(':');
    const kind = sep >= 0 ? value.slice(0, sep) : '';
    const id = sep >= 0 ? value.slice(sep + 1) : '';
    if (!kind || !id) { if (result) result.textContent = 'Select a directory object to add.'; return; }
    try { await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members`, {method: 'POST', body: JSON.stringify({kind, id})}); if (result) result.textContent = `Added ${kind}:${id}`; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  detail.querySelectorAll('.remove-directory-member').forEach((btn) => btn.addEventListener('click', async () => {
    const result = detail.querySelector('#directoryGroupsResult');
    try { await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members/${encodeURIComponent(btn.dataset.kind || '')}/${encodeURIComponent(btn.dataset.id || '')}`, {method: 'DELETE'}); if (result) result.textContent = 'Removed member.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  }));
  detail.querySelector('#saveDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = detail.querySelector('#directoryGroupsResult');
    try { await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'PUT', body: JSON.stringify({name: detail.querySelector('#directoryGroupName')?.value.trim() || group.id, description: detail.querySelector('#directoryGroupDescription')?.value.trim() || '', grants: parseGroupGrants(detail.querySelector('#directoryGroupGrants')?.value || '')})}); if (result) result.textContent = 'Saved group.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  detail.querySelector('#deleteDirectoryGroupBtn')?.addEventListener('click', async () => {
    if (!confirm(`Delete group ${group.id}?`)) return;
    const result = detail.querySelector('#directoryGroupsResult');
    try { await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'DELETE'}); directoryAccessState.selectedKind = 'folder'; directoryAccessState.selectedId = 'groups'; if (result) result.textContent = 'Deleted group.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

function renderCredentialRows(credentials, includePrincipal = true) {
  const items = Array.isArray(credentials) ? credentials : [];
  if (!items.length) return '<div class="muted small-text">No credentials.</div>';
  return `<div class="credential-list">${items.map((cred) => `<div class="credential-row"><div><b>${escapeHtml(cred.name || cred.id)}</b><br><span class="muted small-text">${includePrincipal ? `${escapeHtml(cred.principal_id || '')} · ` : ''}${escapeHtml(cred.kind || '')} · ${escapeHtml(cred.status || '')} · expires ${escapeHtml(cred.expires_at || 'never')}</span></div><button class="ghost-button revoke-directory-credential" data-id="${escapeHtml(cred.id)}" type="button">Revoke</button></div>`).join('')}</div>`;
}

function renderCredentialCreateControls(item) {
  if (item.kind === 'group' || item.kind === 'credential') return '';
  return `<div class="directory-credential-create"><label>Token name <input id="directoryTokenName" placeholder="Automation token" /></label><label>TTL hours <input id="directoryTokenTtl" type="number" min="1" max="8760" value="720" /></label><button id="createDirectoryTokenBtn" class="ghost-button" type="button">Generate token</button><label class="admin-form-wide">Certificate fingerprint or PEM <textarea id="directoryCertificateInput" rows="3" placeholder="sha256:... or PEM text"></textarea></label><button id="createDirectoryCertificateBtn" class="ghost-button" type="button">Register certificate</button></div>`;
}

function bindCredentialActions(root, item) {
  root.querySelectorAll('.revoke-directory-credential').forEach((btn) => btn.addEventListener('click', async () => {
    if (!confirm('Revoke this credential?')) return;
    await api(`/v1/directory/credentials/${encodeURIComponent(btn.dataset.id || '')}`, {method: 'DELETE'});
    await loadAuthDirectory();
  }));
  root.querySelector('#createDirectoryTokenBtn')?.addEventListener('click', async () => {
    const result = root.querySelector('#directoryPrincipalResult');
    try {
      const payload = {name: root.querySelector('#directoryTokenName')?.value.trim() || 'Directory token', ttl_hours: Number(root.querySelector('#directoryTokenTtl')?.value || 720)};
      const response = await api(`/v1/directory/principals/${encodeURIComponent(item.id)}/tokens`, {method: 'POST', body: JSON.stringify(payload)});
      if (result) result.textContent = `Token shown once:\n${response.token || ''}\n\nCredentials identify the principal only. Directory groups decide access.`;
      await loadAuthDirectory({preserveDetail: true});
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  root.querySelector('#createDirectoryCertificateBtn')?.addEventListener('click', async () => {
    const result = root.querySelector('#directoryPrincipalResult');
    try {
      const value = root.querySelector('#directoryCertificateInput')?.value.trim() || '';
      const payload = value.startsWith('sha256:') ? {fingerprint: value, name: 'Certificate'} : {certificate_pem: value, name: 'Certificate'};
      await api(`/v1/directory/principals/${encodeURIComponent(item.id)}/certificates`, {method: 'POST', body: JSON.stringify(payload)});
      if (result) result.textContent = 'Certificate registered. Access still comes from directory membership.';
      await loadAuthDirectory({preserveDetail: true});
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

function renderCredentialDetail(credential, detail, title, subtitle) {
  if (title) title.textContent = credential.name || credential.id;
  if (subtitle) subtitle.textContent = `Credential · ${credential.kind || ''}`;
  detail.innerHTML = `<article class="directory-detail-card"><h3>${escapeHtml(credential.name || credential.id)}</h3><p class="muted">Credentials answer who the caller is. They do not contain permissions.</p><div class="directory-detail-meta"><span>Principal <code>${escapeHtml(credential.principal_id || '-')}</code></span><span>Status ${escapeHtml(credential.status || '-')}</span><span>Expires ${escapeHtml(credential.expires_at || 'never')}</span></div><div class="button-row"><button class="ghost-button revoke-directory-credential" data-id="${escapeHtml(credential.id)}" type="button">Revoke credential</button></div></article>`;
  bindCredentialActions(detail, credential);
}

function renderAuthDirectory() {
  renderAuthDirectoryTree();
  renderAuthDirectoryDetail();
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
    const [treePayload, users, groups, serviceAccounts, endpoints, providers, certificates, credentials] = await Promise.all([
      api('/v1/directory/tree'),
      api('/v1/directory/principals?kind=user'),
      api('/v1/directory/groups'),
      api('/v1/directory/principals?kind=service_account').catch(() => []),
      api('/v1/directory/principals?kind=endpoint').catch(() => []),
      api('/v1/directory/principals?kind=provider').catch(() => []),
      api('/v1/directory/principals?kind=certificate_identity').catch(() => []),
      api('/v1/auth/tokens').catch(() => []),
    ]);
    Object.assign(directoryAccessState, {tree: treePayload, users: users || [], groups: groups || [], service_accounts: serviceAccounts || [], endpoints: endpoints || [], providers: providers || [], certificate_identities: certificates || [], credentials: credentials || []});
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
  document.getElementById('directorySearch')?.addEventListener('input', (ev) => { directoryAccessState.search = ev.target.value || ''; renderAuthDirectoryTree(); });
  createUserButton?.addEventListener('click', async () => {
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
      directoryAccessState.selectedKind = 'user'; directoryAccessState.selectedId = username;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  createGroupButton?.addEventListener('click', async () => {
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
      await api('/v1/directory/service-accounts', {method: 'POST', body: JSON.stringify({id, name, description})});
      ['newServiceAccountId','newServiceAccountName','newServiceAccountDescription'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
      if (result) result.textContent = `Service account created: ${id}`;
      directoryAccessState.selectedKind = 'service_account'; directoryAccessState.selectedId = id;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

bindDirectoryAccessUi();
