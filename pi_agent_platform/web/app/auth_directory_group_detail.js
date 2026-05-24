// Legacy auth directory group detail renderer.

function renderGroupDirectoryDetail(group) {
  const detail = document.getElementById('authDirectoryDetail');
  if (!detail) return;
  const members = group.members || [];
  const userOptions = authDirectoryState.users.map((user) => `<option value="user:${escapeHtml(user.id)}">User · ${escapeHtml(directoryUserName(user))}</option>`).join('');
  const groupOptions = authDirectoryState.groups.filter((item) => item.id !== group.id).map((item) => `<option value="group:${escapeHtml(item.id)}">Group · ${escapeHtml(directoryGroupName(item))}</option>`).join('');
  detail.innerHTML = `
    <article class="directory-detail-card">
      <div class="directory-detail-head">
        <div>
          <h3>${escapeHtml(directoryGroupName(group))}</h3>
          <p class="muted">${escapeHtml(group.id)} · ${escapeHtml(String((group.grants || []).length))} grants</p>
        </div>
        <div class="admin-item-badges">
          <span class="admin-badge subtle">${escapeHtml(String(members.length))} members</span>
          ${group.system_managed ? '<span class="admin-badge">system</span>' : ''}
        </div>
      </div>
      <div class="form-grid compact-form">
        <label>Name <input id="directoryGroupName" value="${escapeHtml(group.name || group.id)}" /></label>
        <label>Description <input id="directoryGroupDescription" value="${escapeHtml(group.description || '')}" /></label>
        <label class="admin-form-wide">Grants <input id="directoryGroupGrants" value="${escapeHtml(serializeGroupGrants(group.grants || []))}" placeholder="workspace:*:write, source_context:*:write" /></label>
      </div>
      <div class="directory-members">
        <h4>Direct members</h4>
        ${members.length ? members.map((member) => `<span class="directory-member-pill">${escapeHtml(directoryMemberLabel(member))}<button class="link-button remove-directory-member" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">×</button></span>`).join('') : '<span class="muted small-text">No direct members.</span>'}
      </div>
      <div class="form-grid compact-form">
        <label class="admin-form-wide">Add member <select id="directoryMemberPicker"><option value="">Select a user or group…</option>${userOptions}${groupOptions}</select></label>
      </div>
      <div class="button-row">
        <button id="addDirectoryMemberBtn" class="ghost-button" type="button">Add member</button>
        <button id="saveDirectoryGroupBtn" type="button">Save group</button>
        <button id="deleteDirectoryGroupBtn" class="ghost-button" type="button">Delete group</button>
      </div>
      <pre id="directoryGroupsResult" class="inline-result compact-result"></pre>
    </article>`;
  document.getElementById('addDirectoryMemberBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    const value = document.getElementById('directoryMemberPicker')?.value || '';
    const sep = value.indexOf(':');
    const kind = sep >= 0 ? value.slice(0, sep) : '';
    const id = sep >= 0 ? value.slice(sep + 1) : '';
    if (!kind || !id) {
      if (result) result.textContent = 'Select a user or group to add.';
      return;
    }
    try {
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members`, {method: 'POST', body: JSON.stringify({kind, id})});
      if (result) result.textContent = `Added ${kind}:${id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  detail.querySelectorAll('.remove-directory-member').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const result = document.getElementById('directoryGroupsResult');
      const kind = btn.dataset.kind || '';
      const id = btn.dataset.id || '';
      try {
        await api(`/v1/directory/groups/${encodeURIComponent(group.id)}/members/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {method: 'DELETE'});
        if (result) result.textContent = `Removed ${kind}:${id}`;
        await fetchAuthStatus();
        renderAuthInfo();
        await loadAuthDirectory();
      } catch (error) {
        if (result) result.textContent = `Failed: ${error.message || String(error)}`;
      }
    });
  });
  document.getElementById('saveDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    try {
      const name = document.getElementById('directoryGroupName')?.value.trim() || group.id;
      const description = document.getElementById('directoryGroupDescription')?.value.trim() || '';
      const grants = parseGroupGrants(document.getElementById('directoryGroupGrants')?.value || '');
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'PUT', body: JSON.stringify({name, description, grants})});
      if (result) result.textContent = `Saved group ${group.id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  document.getElementById('deleteDirectoryGroupBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryGroupsResult');
    if (!confirm(`Delete group ${group.id}?`)) return;
    try {
      await api(`/v1/directory/groups/${encodeURIComponent(group.id)}`, {method: 'DELETE'});
      authDirectoryState.selectedId = '';
      if (result) result.textContent = `Deleted group ${group.id}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
}
