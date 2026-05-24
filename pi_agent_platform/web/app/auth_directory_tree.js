// Legacy auth directory tree renderer.

function renderAuthDirectoryTree() {
  const tree = document.getElementById('authDirectoryTree');
  if (!tree) return;
  tree.innerHTML = `
    <details class="directory-root" open>
      <summary>Groups <span class="directory-count">${authDirectoryState.groups.length}</span></summary>
      <div class="directory-children">
        ${authDirectoryState.groups.map((group) => {
          const members = group.members || [];
          return `<div class="directory-group-shell">
            <button class="directory-node${authDirectoryState.selectedKind === 'group' && authDirectoryState.selectedId === group.id ? ' active' : ''}" data-kind="group" data-id="${escapeHtml(group.id)}" type="button">
              <span class="directory-node-label">${escapeHtml(directoryGroupName(group))}</span>
              <span class="directory-node-meta">${escapeHtml(String(members.length))} members</span>
            </button>
            <div class="directory-children nested">
              ${members.map((member) => `
                <button class="directory-node directory-leaf${authDirectoryState.selectedKind === member.kind && authDirectoryState.selectedId === member.id ? ' active' : ''}" data-kind="${escapeHtml(member.kind)}" data-id="${escapeHtml(member.id)}" type="button">
                  <span class="directory-node-label">${escapeHtml(directoryMemberLabel(member))}</span>
                  <span class="directory-node-meta">${escapeHtml(member.kind)}</span>
                </button>`).join('') || '<div class="directory-empty">No direct members.</div>'}
            </div>
          </div>`;
        }).join('') || '<div class="directory-empty">No groups found.</div>'}
      </div>
    </details>
    <details class="directory-root" open>
      <summary>People <span class="directory-count">${authDirectoryState.users.length}</span></summary>
      <div class="directory-children">
        ${authDirectoryState.users.map((user) => `
          <button class="directory-node${authDirectoryState.selectedKind === 'user' && authDirectoryState.selectedId === user.id ? ' active' : ''}" data-kind="user" data-id="${escapeHtml(user.id)}" type="button">
            <span class="directory-node-label">${escapeHtml(directoryUserName(user))}</span>
            <span class="directory-node-meta">${escapeHtml(user.role || 'user')}</span>
          </button>`).join('') || '<div class="directory-empty">No users found.</div>'}
      </div>
    </details>`;
  tree.querySelectorAll('.directory-node').forEach((btn) => {
    btn.addEventListener('click', () => selectAuthDirectoryNode(btn.dataset.kind || 'user', btn.dataset.id || ''));
  });
}
