// Legacy auth directory user detail renderer.

function renderUserDirectoryDetail(user) {
  const detail = document.getElementById('authDirectoryDetail');
  if (!detail) return;
  const username = user.username || user.name || user.id;
  const directGroups = user.direct_groups || [];
  const effectiveGroups = user.effective_groups || [];
  const inheritedGroups = effectiveGroups.filter((groupId) => !directGroups.includes(groupId));
  const current = user.id === currentUser?.id;
  detail.innerHTML = `
    <article class="directory-detail-card">
      <div class="directory-detail-head">
        <div>
          <h3>${escapeHtml(directoryUserName(user))}</h3>
          <p class="muted">${escapeHtml(username)} · ${escapeHtml(user.role || 'user')}</p>
        </div>
        <div class="admin-item-badges">
          <span class="admin-badge subtle">${escapeHtml(user.role || 'user')}</span>
          ${current ? '<span class="admin-badge">current</span>' : ''}
        </div>
      </div>
      <div class="form-grid compact-form">
        <label>Display name <input id="directoryUserDisplayName" value="${escapeHtml(user.display_name || username)}" /></label>
        <label>Role <select id="directoryUserRole">${roleOptions(user.role || 'user')}</select></label>
      </div>
      <div class="directory-members">
        <h4>Direct groups</h4>
        ${groupMembershipPills(directGroups, 'No direct group membership. Add this user from a group detail panel.')}
        <h4>Inherited groups</h4>
        ${groupMembershipPills(inheritedGroups, 'No inherited groups.')}
      </div>
      <div class="directory-detail-meta">
        <span>Created ${escapeHtml(formatDate(user.created_at) || '-')}</span>
        <span>User id <code>${escapeHtml(user.id)}</code></span>
      </div>
      <div class="button-row">
        <button id="saveDirectoryUserBtn" type="button">Save user</button>
        ${current ? '' : `<button id="deleteDirectoryUserBtn" class="ghost-button" type="button">Delete user</button>`}
      </div>
      <pre id="directoryUsersResult" class="inline-result compact-result"></pre>
    </article>`;
  document.getElementById('saveDirectoryUserBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryUsersResult');
    try {
      const display_name = document.getElementById('directoryUserDisplayName')?.value.trim() || username;
      const role = document.getElementById('directoryUserRole')?.value || 'user';
      await api(`/v1/users/${encodeURIComponent(user.id)}`, {method: 'PUT', body: JSON.stringify({display_name, role})});
      if (result) result.textContent = `Saved user ${username}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
  document.getElementById('deleteDirectoryUserBtn')?.addEventListener('click', async () => {
    const result = document.getElementById('directoryUsersResult');
    if (!confirm(`Delete user ${username}?`)) return;
    try {
      await api(`/v1/users/${encodeURIComponent(user.id)}`, {method: 'DELETE'});
      authDirectoryState.selectedId = '';
      if (result) result.textContent = `Deleted user ${username}`;
      await fetchAuthStatus();
      renderAuthInfo();
      await loadAuthDirectory();
    } catch (error) {
      if (result) result.textContent = `Failed: ${error.message || String(error)}`;
    }
  });
}
