// Directory & Access object lookup, labels, and selection helpers.

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
