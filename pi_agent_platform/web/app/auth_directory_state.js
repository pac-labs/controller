// Legacy auth directory state, grant parsing, and label helpers.

const authDirectoryState = {
  users: [],
  groups: [],
  selectedKind: 'group',
  selectedId: 'admin',
};

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

function selectedAuthDirectoryItem() {
  const items = authDirectoryState[`${authDirectoryState.selectedKind}s`] || [];
  return items.find((item) => item.id === authDirectoryState.selectedId) || null;
}

function groupMembershipPills(groupIds, emptyText) {
  return groupIds.length
    ? groupIds.map((groupId) => `<span class="directory-member-pill">${escapeHtml(directoryGroupName(directoryGroupById(groupId)) || groupId)}</span>`).join('')
    : `<span class="muted small-text">${escapeHtml(emptyText)}</span>`;
}
