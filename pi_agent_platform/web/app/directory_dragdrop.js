// Drag/drop helpers for Directory & Access.
// Dropping a principal onto a group adds that principal as a direct member of the group.

const DIRECTORY_DRAGGABLE_KINDS = new Set([
  'user',
  'group',
  'service_account',
  'endpoint',
  'provider',
  'certificate_identity',
]);

function directoryDragPayloadFromElement(el) {
  const kind = el?.dataset?.kind || '';
  const id = el?.dataset?.id || '';
  if (!DIRECTORY_DRAGGABLE_KINDS.has(kind) || !id) return null;
  return {kind, id};
}

function directoryEncodeDragPayload(payload) {
  return JSON.stringify({kind: payload.kind, id: payload.id});
}

function directoryReadDragPayload(event) {
  const raw = event.dataTransfer?.getData('application/x-pac-directory-member')
    || event.dataTransfer?.getData('application/json')
    || event.dataTransfer?.getData('text/plain')
    || '';
  try {
    const payload = JSON.parse(raw);
    if (DIRECTORY_DRAGGABLE_KINDS.has(payload.kind) && payload.id) return payload;
  } catch (_) {}
  return null;
}

function directoryDropTargetGroupId(el) {
  return el?.closest?.('[data-drop-group-id]')?.dataset?.dropGroupId || '';
}

function directorySetDragMessage(message, isError = false) {
  const target = document.getElementById('directoryDragDropStatus')
    || document.getElementById('directoryGroupsResult')
    || document.getElementById('usersResult');
  if (!target) return;
  target.textContent = message || '';
  target.classList.toggle('error-text', Boolean(isError));
}

function directoryBindDraggable(el) {
  if (el.dataset.dragBound === '1') return;
  const payload = directoryDragPayloadFromElement(el);
  if (!payload) return;
  el.dataset.dragBound = '1';
  el.setAttribute('draggable', 'true');
  el.setAttribute('title', `${el.getAttribute('title') || ''} Drag onto a group to add membership.`.trim());
  el.addEventListener('dragstart', (event) => {
    const currentPayload = directoryDragPayloadFromElement(el);
    if (!currentPayload) return;
    const encoded = directoryEncodeDragPayload(currentPayload);
    event.dataTransfer.effectAllowed = 'copyMove';
    event.dataTransfer.setData('application/x-pac-directory-member', encoded);
    event.dataTransfer.setData('application/json', encoded);
    event.dataTransfer.setData('text/plain', encoded);
    document.body.classList.add('directory-dragging');
    el.classList.add('directory-drag-source');
    directorySetDragMessage(`Dragging ${currentPayload.kind}:${currentPayload.id}. Drop onto a group to add it as a member.`);
  });
  el.addEventListener('dragend', () => {
    document.body.classList.remove('directory-dragging');
    el.classList.remove('directory-drag-source');
    document.querySelectorAll('.directory-drop-over').forEach((node) => node.classList.remove('directory-drop-over'));
  });
}

function directoryBindDropTarget(el) {
  if (el.dataset.dropBound === '1') return;
  const groupId = directoryDropTargetGroupId(el);
  if (!groupId) return;
  el.dataset.dropBound = '1';
  el.addEventListener('dragover', (event) => {
    const payload = directoryReadDragPayload(event);
    if (!payload || (payload.kind === 'group' && payload.id === groupId)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    el.classList.add('directory-drop-over');
  });
  el.addEventListener('dragleave', (event) => {
    if (!el.contains(event.relatedTarget)) el.classList.remove('directory-drop-over');
  });
  el.addEventListener('drop', async (event) => {
    const payload = directoryReadDragPayload(event);
    el.classList.remove('directory-drop-over');
    if (!payload) return;
    event.preventDefault();
    if (payload.kind === 'group' && payload.id === groupId) {
      directorySetDragMessage('A group cannot be added to itself.', true);
      return;
    }
    try {
      await api(`/v1/directory/groups/${encodeURIComponent(groupId)}/members`, {
        method: 'POST',
        body: JSON.stringify({kind: payload.kind, id: payload.id}),
      });
      directorySetDragMessage(`Added ${payload.kind}:${payload.id} to ${groupId}.`);
      if (typeof selectAuthDirectoryNode === 'function') selectAuthDirectoryNode('group', groupId);
      if (typeof loadAuthDirectory === 'function') await loadAuthDirectory({preserveDetail: true});
    } catch (error) {
      directorySetDragMessage(`Could not add member: ${error.message || String(error)}`, true);
    }
  });
}

function bindDirectoryDragDrop(root = document) {
  root.querySelectorAll('.directory-node[data-kind], .directory-object-row[data-kind], .directory-member-pill[data-kind]')
    .forEach(directoryBindDraggable);
  root.querySelectorAll('[data-drop-group-id]').forEach(directoryBindDropTarget);
}

window.bindDirectoryDragDrop = bindDirectoryDragDrop;
