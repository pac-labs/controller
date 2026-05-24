// Directory & Access guided create-modal helpers.

const DIRECTORY_CREATE_STEPS = ['choose', 'details', 'review'];
let directoryCreateWizardStep = 'choose';

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

function currentDirectoryCreateType() {
  return document.getElementById('directoryCreateModal')?.dataset.createType || 'person';
}

function setDirectoryCreateType(type) {
  const selectedType = type || 'person';
  const modal = document.getElementById('directoryCreateModal');
  if (!modal) return;
  modal.dataset.createType = selectedType;
  document.getElementById('directoryCreateModalTitle').textContent = directoryCreateTypeTitle(selectedType);
  document.getElementById('directoryCreateModalSubtitle').textContent = directoryCreateTypeSubtitle(selectedType);
  modal.querySelectorAll('[data-create-type]').forEach((button) => {
    button.classList.toggle('active', button.dataset.createType === selectedType);
  });
  modal.querySelectorAll('[data-create-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.createPanel !== selectedType;
  });
}

function directoryCreateValues(type = currentDirectoryCreateType()) {
  if (type === 'group') {
    const panel = document.querySelector('[data-create-panel="group"]');
    return {
      type,
      id: document.getElementById('newGroupId')?.value.trim() || '',
      name: document.getElementById('newGroupName')?.value.trim() || '',
      description: document.getElementById('newGroupDescription')?.value.trim() || '',
      grants: readDirectoryGrantRows(panel || document),
    };
  }
  if (type === 'service_account') {
    return {
      type,
      id: document.getElementById('newServiceAccountId')?.value.trim() || '',
      name: document.getElementById('newServiceAccountName')?.value.trim() || '',
      description: document.getElementById('newServiceAccountDescription')?.value.trim() || '',
    };
  }
  return {
    type,
    username: document.getElementById('newUsername')?.value.trim() || '',
    display_name: document.getElementById('newDisplayName')?.value.trim() || '',
    password: document.getElementById('newUserPassword')?.value || '',
    role: document.getElementById('newUserRole')?.value || 'user',
  };
}

function validateDirectoryCreateDetails(values = directoryCreateValues()) {
  if (values.type === 'group' && !values.id) return 'Group id is required.';
  if (values.type === 'service_account' && !values.id) return 'Principal id is required.';
  if (values.type === 'person') {
    if (!values.username) return 'Username is required.';
    if (!values.password) return 'Password is required.';
  }
  return '';
}

function renderDirectoryCreateReview() {
  const review = document.getElementById('directoryCreateReview');
  if (!review) return;
  const values = directoryCreateValues();
  const rows = values.type === 'person'
    ? [['Type', 'Person'], ['Username', values.username], ['Display name', values.display_name || values.username], ['Role', values.role], ['Password', values.password ? 'set on create' : 'missing']]
    : values.type === 'group'
      ? [['Type', 'Group'], ['Group id', values.id], ['Name', values.name || values.id], ['Description', values.description || '-'], ['Initial grants', String(values.grants?.length || 0)]]
      : [['Type', 'Service account'], ['Principal id', values.id], ['Name', values.name || values.id], ['Description', values.description || '-']];
  review.innerHTML = `<div class="directory-create-review-card"><h3>Review before creating</h3><div class="kv compact-kv">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><b>${escapeHtml(String(value || '-'))}</b></div>`).join('')}</div><p class="muted small-text">Creation uses the existing Directory API. No backend contract changes are needed for this wizard.</p></div>`;
}

function setDirectoryCreateWizardStep(step) {
  directoryCreateWizardStep = DIRECTORY_CREATE_STEPS.includes(step) ? step : 'choose';
  document.querySelectorAll('[data-directory-step]').forEach((item) => {
    item.classList.toggle('active', item.dataset.directoryStep === directoryCreateWizardStep);
    item.setAttribute('aria-current', item.dataset.directoryStep === directoryCreateWizardStep ? 'step' : 'false');
  });
  const choice = document.getElementById('directoryCreateChoice');
  const form = document.getElementById('directoryCreateFormShell');
  const review = document.getElementById('directoryCreateReview');
  if (choice) choice.hidden = directoryCreateWizardStep !== 'choose';
  if (form) form.hidden = directoryCreateWizardStep !== 'details';
  if (review) review.hidden = directoryCreateWizardStep !== 'review';
  if (directoryCreateWizardStep === 'review') renderDirectoryCreateReview();
  const back = document.getElementById('directoryCreateBack');
  const next = document.getElementById('directoryCreateNext');
  const submit = document.getElementById('directoryCreateSubmit');
  if (back) back.hidden = directoryCreateWizardStep === 'choose';
  if (next) next.hidden = directoryCreateWizardStep === 'review';
  if (submit) submit.hidden = directoryCreateWizardStep !== 'review';
  const status = document.getElementById('directoryCreateWizardStatus');
  if (status) status.textContent = '';
}

function directoryCreateNextStep() {
  if (directoryCreateWizardStep === 'choose') return setDirectoryCreateWizardStep('details');
  if (directoryCreateWizardStep === 'details') {
    const error = validateDirectoryCreateDetails();
    const status = document.getElementById('directoryCreateWizardStatus');
    if (error) { if (status) status.textContent = error; return; }
    return setDirectoryCreateWizardStep('review');
  }
}

function directoryCreatePreviousStep() {
  if (directoryCreateWizardStep === 'details') return setDirectoryCreateWizardStep('choose');
  if (directoryCreateWizardStep === 'review') return setDirectoryCreateWizardStep('details');
}

function submitDirectoryCreateWizard() {
  const type = currentDirectoryCreateType();
  const targetId = type === 'group' ? 'createGroupBtn' : type === 'service_account' ? 'createServiceAccountBtn' : 'createUserBtn';
  document.getElementById(targetId)?.click();
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
  setDirectoryCreateWizardStep('choose');
  modal.hidden = false;
  modal.querySelector('button[data-create-type].active')?.focus?.();
}
