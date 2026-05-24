// Directory & Access tree rendering.

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
