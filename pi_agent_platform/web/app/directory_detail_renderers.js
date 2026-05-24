// Directory & Access detail-panel rendering and group actions.

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
  detail.innerHTML = `<article class="directory-detail-card"><div class="muted small-text pac-loading-placeholder">${pacLoadingLineHtml('Loading effective access…')}</div></article>`;
  const [access, credentials] = await Promise.all([
    DirectoryApi.effectiveAccess(item.id).catch(() => null),
    DirectoryApi.principalCredentials(item.id).catch(() => []),
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
    try { await DirectoryApi.addGroupMember(group.id, {kind, id}); if (result) result.textContent = `Added ${kind}:${id}`; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  detail.querySelectorAll('.remove-directory-member').forEach((btn) => btn.addEventListener('click', async () => {
    const result = detail.querySelector('#directoryGroupsResult');
    try { await DirectoryApi.removeGroupMember(group.id, btn.dataset.kind || '', btn.dataset.id || ''); if (result) result.textContent = 'Removed member.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  }));
  detail.querySelector('#saveDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = detail.querySelector('#directoryGroupsResult');
    try { await DirectoryApi.updateGroup(group.id, {name: detail.querySelector('#directoryGroupName')?.value.trim() || group.id, description: detail.querySelector('#directoryGroupDescription')?.value.trim() || '', grants: readDirectoryGrantRows(detail)}); if (result) result.textContent = 'Saved group.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
  detail.querySelector('#deleteDirectoryGroupBtn')?.addEventListener('click', async () => {
    if (!confirm(`Delete group ${group.id}?`)) return;
    const result = detail.querySelector('#directoryGroupsResult');
    try { await DirectoryApi.deleteGroup(group.id); directoryAccessState.selectedKind = 'folder'; directoryAccessState.selectedId = 'groups'; if (result) result.textContent = 'Deleted group.'; await loadAuthDirectory(); } catch (error) { if (result) result.textContent = `Failed: ${error.message || String(error)}`; }
  });
}
