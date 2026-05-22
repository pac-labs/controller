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


const DIRECTORY_GRANT_RESOURCE_TYPES = [
  ['profile', 'Profile'],
  ['workspace', 'Workspace'],
  ['agent_context', 'Agent context'],
  ['source_context', 'Source context'],
  ['secret', 'Secret'],
  ['session', 'Session'],
  ['diagnostics', 'Diagnostics'],
  ['model_usage', 'Model usage'],
  ['endpoint', 'Endpoint'],
  ['provider', 'Provider'],
  ['system', 'System'],
];

const DIRECTORY_GRANT_ACTIONS = ['use', 'read', 'write', 'execute', 'create', 'manage'];

const DIRECTORY_FOLDERS = [
  ['people', 'People', 'user', 'users'],
  ['groups', 'Groups', 'group', 'groups'],
  ['service_accounts', 'Service Accounts', 'service_account', 'service_accounts'],
  ['endpoints', 'Endpoints', 'endpoint', 'endpoints'],
  ['providers', 'Providers', 'provider', 'providers'],
  ['certificate_identities', 'Certificate Identities', 'certificate_identity', 'certificate_identities'],
  ['credentials', 'Credentials', 'credential', 'credentials'],
];

const DIRECTORY_KIND_LABELS = {
  user: 'User',
  group: 'Group',
  service_account: 'Service account',
  endpoint: 'Endpoint identity',
  provider: 'Provider identity',
  certificate_identity: 'Certificate identity',
  credential: 'Credential',
};


function directoryFormatDate(value) {
  if (!value) return '';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  } catch (_) {
    return String(value);
  }
}


function parseDirectoryGrantSpec(value) {
  const parts = String(value || '').split(':');
  if (parts.length < 3) return null;
  const resource_type = (parts.shift() || '').trim();
  const access = (parts.pop() || '').trim();
  const pattern = parts.join(':').trim() || '*';
  if (!resource_type || !access) return null;
  return {resource_type, pattern, access};
}

function directoryGrantSpec(grant) {
  return `${grant?.resource_type || 'workspace'}:${grant?.pattern || '*'}:${grant?.access || 'read'}`;
}

function directoryGrantResourceOptions(selected = '') {
  return DIRECTORY_GRANT_RESOURCE_TYPES.map(([value, label]) => `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
}

function directoryGrantActionOptions(selected = '') {
  return DIRECTORY_GRANT_ACTIONS.map((value) => `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(value)}</option>`).join('');
}

function renderDirectoryGrantBuilder(grants = []) {
  const rows = (grants || []).length ? grants : [];
  return `<div class="directory-grant-builder">
    <div class="directory-grant-builder-head">
      <div><b>Access grants</b><p class="muted small-text">Pick what this group can use. Tokens only identify principals; these grants decide access.</p></div>
      <div class="button-row compact-actions"><select class="directory-grant-preset"><option value="">Common grant…</option>${DIRECTORY_GRANT_PRESETS.map(([value,label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join('')}</select><button class="ghost-button add-directory-grant" type="button">+ grant</button></div>
    </div>
    <div class="directory-grant-rows">
      ${rows.map((grant) => renderDirectoryGrantRow(grant)).join('') || '<div class="muted small-text directory-no-grants">No grants yet.</div>'}
    </div>
  </div>`;
}

function renderDirectoryGrantRow(grant = {}) {
  const resourceType = grant.resource_type || 'workspace';
  const pattern = grant.pattern || '*';
  const access = grant.access || 'read';
  return `<div class="directory-grant-row" data-grant-row>
    <select class="directory-grant-resource">${directoryGrantResourceOptions(resourceType)}</select>
    <input class="directory-grant-pattern" value="${escapeHtml(pattern)}" placeholder="resource id or *" />
    <select class="directory-grant-action">${directoryGrantActionOptions(access)}</select>
    <button class="ghost-button remove-directory-grant" type="button" title="Remove grant">×</button>
  </div>`;
}

function addDirectoryGrantRow(root, grant = {}) {
  const rows = root.querySelector('.directory-grant-rows');
  if (!rows) return;
  rows.querySelector('.directory-no-grants')?.remove();
  rows.insertAdjacentHTML('beforeend', renderDirectoryGrantRow(grant));
  bindDirectoryGrantBuilder(root);
}

function readDirectoryGrantRows(root) {
  return Array.from(root.querySelectorAll('[data-grant-row]')).map((row) => ({
    resource_type: row.querySelector('.directory-grant-resource')?.value || 'workspace',
    pattern: row.querySelector('.directory-grant-pattern')?.value.trim() || '*',
    access: row.querySelector('.directory-grant-action')?.value || 'read',
  })).filter((grant) => grant.resource_type && grant.pattern && grant.access);
}

function bindDirectoryGrantBuilder(root) {
  root.querySelectorAll('.add-directory-grant').forEach((button) => {
    if (button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', () => addDirectoryGrantRow(button.closest('.directory-grant-builder') || root, {resource_type: 'workspace', pattern: '*', access: 'read'}));
  });
  root.querySelectorAll('.directory-grant-preset').forEach((select) => {
    if (select.dataset.bound === '1') return;
    select.dataset.bound = '1';
    select.addEventListener('change', () => {
      const grant = parseDirectoryGrantSpec(select.value || '');
      if (grant) addDirectoryGrantRow(select.closest('.directory-grant-builder') || root, grant);
      select.value = '';
    });
  });
  root.querySelectorAll('.remove-directory-grant').forEach((button) => {
    if (button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', () => {
      const builder = button.closest('.directory-grant-builder');
      button.closest('[data-grant-row]')?.remove();
      const rows = builder?.querySelector('.directory-grant-rows');
      if (rows && !rows.querySelector('[data-grant-row]')) rows.innerHTML = '<div class="muted small-text directory-no-grants">No grants yet.</div>';
    });
  });
}

function directoryCreateMenuForFolder(folderId) {
  if (folderId === 'people') return 'addPersonMenu';
  if (folderId === 'groups') return 'addGroupMenu';
  if (folderId === 'service_accounts') return 'addServiceAccountMenu';
  return '';
}

function directoryCreateTypeFromMenuId(menuId) {
  if (menuId === 'addPersonMenu') return 'person';
  if (menuId === 'addGroupMenu') return 'group';
  if (menuId === 'addServiceAccountMenu') return 'service_account';
  return 'person';
}

function directoryCreateTypeTitle(type) {
  if (type === 'group') return 'Create group';
  if (type === 'service_account') return 'Create service account';
  return 'Create person';
}

function directoryCreateTypeSubtitle(type) {
  if (type === 'group') return 'Create a group that can hold people, service accounts, endpoint identities, provider identities, certificate identities, and other groups.';
  if (type === 'service_account') return 'Create a non-interactive identity for automation, endpoints, providers, or integration work.';
  return 'Create an interactive user. Add group membership after creation from the group detail panel or by drag/drop.';
}

function setDirectoryCreateType(type) {
  const selectedType = type || 'person';
  const modal = document.getElementById('directoryCreateModal');
  if (!modal) return;
  modal.dataset.createType = selectedType;
  const title = document.getElementById('directoryCreateModalTitle');
  const subtitle = document.getElementById('directoryCreateModalSubtitle');
  if (title) title.textContent = directoryCreateTypeTitle(selectedType);
  if (subtitle) subtitle.textContent = directoryCreateTypeSubtitle(selectedType);
  modal.querySelectorAll('[data-create-type]').forEach((button) => {
    button.classList.toggle('active', button.dataset.createType === selectedType);
  });
  modal.querySelectorAll('[data-create-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.createPanel !== selectedType;
  });
}

function closeDirectoryCreateModal() {
  const modal = document.getElementById('directoryCreateModal');
  if (!modal) return;
  modal.hidden = true;
}

function openDirectoryCreateMenu(menuId) {
  const modal = document.getElementById('directoryCreateModal');
  if (!modal) return;
  setDirectoryCreateType(directoryCreateTypeFromMenuId(menuId));
  modal.hidden = false;
  modal.querySelector('input, select, textarea, button')?.focus?.();
}

function directoryKindLabel(kind) {
  return DIRECTORY_KIND_LABELS[kind] || kind || 'Object';
}

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
        <span class="directory-label-with-icon"><span class="directory-kind-icon folder" aria-hidden="true"></span>${escapeHtml(label)}</span><span class="directory-folder-actions">${directoryCreateMenuForFolder(folderId) ? `<button class="directory-inline-add" data-open-add="${escapeHtml(directoryCreateMenuForFolder(folderId))}" type="button" title="Add ${escapeHtml(label.slice(0, -1) || label)}" aria-label="Add ${escapeHtml(label.slice(0, -1) || label)}">+</button>` : ''}<span class="directory-count">${items.length}</span></span>
      </summary>
      <div class="directory-children">
        ${items.map((item) => renderDirectoryTreeItem(itemKind, item)).join('') || '<div class="directory-empty">No entries.</div>'}
      </div>
    </details>`;
  }).join('');
  tree.querySelectorAll('[data-open-add]').forEach((button) => {
    button.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      openDirectoryCreateMenu(button.dataset.openAdd || '');
    });
  });
  tree.querySelectorAll('.directory-node,.directory-folder').forEach((node) => {
    node.addEventListener('click', (ev) => {
      if (ev.target.closest?.('[data-open-add]')) return;
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
  const dropAttrs = kind === 'group' ? ` data-drop-group-id="${escapeHtml(item.id)}" aria-label="Drop directory objects here to add them to ${escapeHtml(label)}"` : '';
  return `<div class="directory-group-shell"><button class="directory-node${active ? ' active' : ''}" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}"${dropAttrs} type="button"><span class="directory-node-label directory-label-with-icon"><span class="directory-kind-icon ${escapeHtml(kind)}" aria-hidden="true"></span>${escapeHtml(label)}</span><span class="directory-node-meta">${escapeHtml(meta || '')}</span></button>${nested}</div>`;
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
  const itemKind = folder[2];
  const items = directoryItemsForKind(itemKind).filter((item) => directoryMatches(item, folder[1]));
  if (title) title.textContent = folder[1];
  if (subtitle) subtitle.textContent = `PAC Directory / ${folder[1]}`;
  const rows = items.slice(0, 100).map((item) => {
    const dropAttrs = itemKind === 'group' ? ` data-drop-group-id="${escapeHtml(item.id)}"` : '';
    return `<tr class="directory-object-row" data-kind="${escapeHtml(itemKind)}" data-id="${escapeHtml(item.id)}"${dropAttrs}><td><span class="directory-label-with-icon"><span class="directory-kind-icon ${escapeHtml(itemKind)}" aria-hidden="true"></span><b>${escapeHtml(directoryPrincipalLabel(item))}</b></span></td><td>${escapeHtml(directoryKindLabel(itemKind))}</td><td>${escapeHtml(item.source || item.kind || '')}</td><td><span class="directory-status-pill">${escapeHtml(item.status || 'active')}</span></td><td>${escapeHtml(item.description || item.id || '')}</td></tr>`;
  }).join('');
  detail.innerHTML = `<article class="directory-detail-card directory-console"><div class="directory-console-toolbar"><div><h3>${escapeHtml(folder[1])}</h3><p class="muted small-text">${items.length} objects. Select a row to inspect it. Drag people, groups, service accounts, endpoints, or providers onto a group to add membership.</p></div><span class="directory-path-pill">PAC Directory › ${escapeHtml(folder[1])}</span></div><div class="directory-table-wrap"><table class="directory-object-table"><thead><tr><th>Name</th><th>Type</th><th>Source</th><th>Status</th><th>Description / ID</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="directory-empty-cell">No objects in this container.</td></tr>`}</tbody></table></div></article>`;
  detail.querySelectorAll('.directory-object-row').forEach((row) => row.addEventListener('click', () => selectAuthDirectoryNode(row.dataset.kind || itemKind, row.dataset.id || '')));
  window.bindDirectoryDragDrop?.(detail);
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
      <section><h4>Overview</h4><dl class="directory-property-list"><div><dt>Type</dt><dd>${escapeHtml(directoryKindLabel(item.kind))}</dd></div><div><dt>Status</dt><dd>${escapeHtml(item.status || 'active')}</dd></div><div><dt>Source</dt><dd>${escapeHtml(item.source || 'local')}</dd></div><div><dt>Created</dt><dd>${escapeHtml(directoryFormatDate(item.created_at) || '-')}</dd></div></dl><p class="muted small-text">${escapeHtml(item.description || 'No description provided.')}</p></section>
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
    <div class="form-grid compact-form"><label>Name <input id="directoryGroupName" value="${escapeHtml(group.name || group.id)}" /></label><label>Description <input id="directoryGroupDescription" value="${escapeHtml(group.description || '')}" /></label></div>
    <div class="directory-tabs-grid"><section class="directory-group-drop-zone" data-drop-group-id="${escapeHtml(group.id)}"><h4>Members</h4><p class="muted small-text">Drop directory objects here, or onto this group in the tree, to add direct membership. Drag a member to the removal zone to remove direct membership.</p><div class="directory-member-list">${members.length ? members.map((member) => `<span class="directory-member-pill" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}"><span class="directory-kind-icon ${escapeHtml(member.kind)}" aria-hidden="true"></span>${escapeHtml(directoryMemberTitle(member))}<button class="link-button remove-directory-member" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">×</button></span>`).join('') : '<span class="muted small-text">No direct members.</span>'}</div><label class="admin-form-wide directory-add-member">Add member <select id="directoryMemberPicker"><option value="">Select a directory object…</option>${options}</select></label><button id="addDirectoryMemberBtn" class="ghost-button" type="button">Add member</button><div class="directory-remove-drop-zone" data-remove-group-id="${escapeHtml(group.id)}">Drop a direct member here to remove it from this group.</div></section><section>${renderDirectoryGrantBuilder(group.grants || [])}</section></div>
    <div class="button-row"><button id="saveDirectoryGroupBtn" type="button">Save group</button><button id="deleteDirectoryGroupBtn" class="ghost-button" type="button">Delete group</button></div><pre id="directoryGroupsResult" class="inline-result compact-result"></pre>
  </article>`;
  bindDirectoryGrantBuilder(detail);
  bindGroupDetailActions(detail, group);
  window.bindDirectoryDragDrop?.(detail);
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
    try { await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'PUT', body: JSON.stringify({name: detail.querySelector('#directoryGroupName')?.value.trim() || group.id, description: detail.querySelector('#directoryGroupDescription')?.value.trim() || '', grants: readDirectoryGrantRows(detail)})}); if (result) result.textContent = 'Saved group.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
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
  return `<div class="directory-credential-create"><button class="ghost-button" data-open-credential-modal="token" type="button">+ Generate token</button><button class="ghost-button" data-open-credential-modal="certificate" type="button">+ Register certificate</button></div>`;
}


function closeDirectoryCredentialModal() {
  document.getElementById('directoryCredentialModal')?.remove();
}

function openDirectoryCredentialModal(item, credentialType = 'token') {
  closeDirectoryCredentialModal();
  const isCertificate = credentialType === 'certificate';
  const modal = document.createElement('div');
  modal.id = 'directoryCredentialModal';
  modal.className = 'modal-backdrop directory-modal-backdrop';
  modal.innerHTML = `<section class="modal-card directory-create-modal" role="dialog" aria-modal="true" aria-labelledby="directoryCredentialModalTitle">
    <div class="modal-head directory-modal-head"><div><p class="muted small-text directory-modal-kicker">Guided credential creation</p><h2 id="directoryCredentialModalTitle">${isCertificate ? 'Register certificate' : 'Generate token'}</h2><p class="muted">Credentials answer who this caller is. Directory membership decides what it can do.</p></div><button id="closeDirectoryCredentialModal" class="ghost-button" type="button">Close</button></div>
    <div class="directory-wizard-steps" aria-label="Credential steps"><span class="active">1. Principal</span><span class="active">2. Credential</span><span>3. Review</span></div>
    <div class="directory-detail-card subtle-card"><b>${escapeHtml(directoryPrincipalLabel(item))}</b><br><span class="muted small-text">${escapeHtml(item.kind)} · ${escapeHtml(item.id)}</span></div>
    <div class="form-grid compact-form">
      <label>Name <input id="directoryModalCredentialName" placeholder="${isCertificate ? 'Workstation certificate' : 'Automation token'}" /></label>
      ${isCertificate ? '<label class="admin-form-wide">Certificate fingerprint or PEM <textarea id="directoryModalCertificateInput" rows="5" placeholder="sha256:... or PEM text"></textarea></label>' : '<label>TTL hours <input id="directoryModalTokenTtl" type="number" min="1" max="8760" value="720" /></label>'}
    </div>
    <p class="muted small-text">No permissions are stored on this credential. Add the principal to groups to change access.</p>
    <div id="directoryCredentialModalResult" class="inline-result compact-result" hidden></div>
    <div class="button-row"><button id="submitDirectoryCredentialModal" type="button">${isCertificate ? 'Register certificate' : 'Generate token'}</button><button id="cancelDirectoryCredentialModal" class="ghost-button" type="button">Cancel</button></div>
  </section>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', (ev) => { if (ev.target === modal) closeDirectoryCredentialModal(); });
  modal.querySelector('#closeDirectoryCredentialModal')?.addEventListener('click', closeDirectoryCredentialModal);
  modal.querySelector('#cancelDirectoryCredentialModal')?.addEventListener('click', closeDirectoryCredentialModal);
  modal.querySelector('#submitDirectoryCredentialModal')?.addEventListener('click', async () => {
    const result = modal.querySelector('#directoryCredentialModalResult');
    try {
      if (isCertificate) {
        const value = modal.querySelector('#directoryModalCertificateInput')?.value.trim() || '';
        if (!value) throw new Error('Certificate fingerprint or PEM is required.');
        const name = modal.querySelector('#directoryModalCredentialName')?.value.trim() || 'Certificate';
        const payload = value.startsWith('sha256:') ? {fingerprint: value, name} : {certificate_pem: value, name};
        await api(`/v1/directory/principals/${encodeURIComponent(item.id)}/certificates`, {method: 'POST', body: JSON.stringify(payload)});
        if (result) { result.hidden = false; result.textContent = 'Certificate registered. Access still comes from directory membership.'; }
        await loadAuthDirectory({preserveDetail: true});
        closeDirectoryCredentialModal();
      } else {
        const payload = {name: modal.querySelector('#directoryModalCredentialName')?.value.trim() || 'Directory token', ttl_hours: Number(modal.querySelector('#directoryModalTokenTtl')?.value || 720)};
        const response = await api(`/v1/directory/principals/${encodeURIComponent(item.id)}/tokens`, {method: 'POST', body: JSON.stringify(payload)});
        if (result) { result.hidden = false; result.textContent = `Token shown once:\n${response.token || ''}\n\nSave it now. PAC stores only the hash.`; }
        await loadAuthDirectory({preserveDetail: true});
      }
    } catch (error) {
      if (result) { result.hidden = false; result.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
  modal.querySelector('input, textarea, button')?.focus?.();
}

function bindCredentialActions(root, item) {
  root.querySelectorAll('[data-open-credential-modal]').forEach((button) => {
    if (button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', () => openDirectoryCredentialModal(item, button.dataset.openCredentialModal || 'token'));
  });
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
  document.getElementById('closeDirectoryCreateModal')?.addEventListener('click', closeDirectoryCreateModal);
  document.getElementById('directoryCreateModal')?.addEventListener('click', (ev) => {
    if (ev.target?.id === 'directoryCreateModal') closeDirectoryCreateModal();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !document.getElementById('directoryCreateModal')?.hidden) closeDirectoryCreateModal();
  });
  setDirectoryCreateType('person');
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
      await api('/v1/directory/users', {method: 'POST', body: JSON.stringify({username, display_name, password, role})});
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
      await api('/v1/directory/groups', {method: 'POST', body: JSON.stringify({id, name, description, grants})});
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
      await api('/v1/directory/service-accounts', {method: 'POST', body: JSON.stringify({id, name, description})});
      ['newServiceAccountId','newServiceAccountName','newServiceAccountDescription'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
      if (result) result.textContent = `Service account created: ${id}`;
      closeDirectoryCreateModal();
      directoryAccessState.selectedKind = 'service_account'; directoryAccessState.selectedId = id;
      await fetchAuthStatus(); renderAuthInfo(); await loadAuthDirectory();
    } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}

bindDirectoryAccessUi();
