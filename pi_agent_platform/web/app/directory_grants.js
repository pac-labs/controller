// Directory & Access grant-builder rendering and bindings.

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
