// Card-based agent profile management.

const profileEditorState = {
  groups: [],
  bound: false,
};

function profileManagementAllowed() {
  if (!authStatus?.enabled || authStatus?.mode !== 'user-password') return true;
  return currentUser?.role === 'admin';
}

async function ensureProfileGroupsLoaded() {
  if (!profileManagementAllowed()) {
    profileEditorState.groups = [];
    return [];
  }
  profileEditorState.groups = await api('/v1/directory/groups');
  return profileEditorState.groups;
}

function profileInstructionPreview(text) {
  const source = String(text || '').replace(/\s+/g, ' ').trim();
  return source.length > 180 ? `${source.slice(0, 177)}...` : source;
}

function profilePills(profile) {
  const pills = [
    `<span class="pill">Context: ${escapeHtml(profile.context_profile || 'medium')}</span>`,
  ];
  if (profile.planner_context_profile) pills.push(`<span class="pill">Planner: ${escapeHtml(profile.planner_context_profile)}</span>`);
  if (profile.permission_profile) pills.push(`<span class="pill">Policy: ${escapeHtml(profile.permission_profile)}</span>`);
  const groups = profile.allowed_groups || [];
  if (groups.length) pills.push(`<span class="pill">Groups: ${escapeHtml(groups.join(', '))}</span>`);
  else pills.push('<span class="pill">Groups: global</span>');
  return pills.join('');
}

function renderProfiles() {
  const el = document.getElementById('profiles');
  const result = document.getElementById('profileFormResult');
  const openBtn = document.getElementById('openProfileModalBtn');
  if (!el) return;
  if (result) result.textContent = '';
  if (openBtn) openBtn.hidden = !profileManagementAllowed();
  const profiles = Object.entries(config.agent_profiles || {}).sort((a, b) => {
    const left = String(a[1]?.display_name || a[0]).toLowerCase();
    const right = String(b[1]?.display_name || b[0]).toLowerCase();
    return left.localeCompare(right);
  });
  if (!profiles.length) {
    el.innerHTML = '<div class="muted small-text">No profiles are available for your account.</div>';
    return;
  }
  el.innerHTML = profiles.map(([name, profile]) => {
    const editable = profileManagementAllowed();
    const description = escapeHtml(profile.description || 'No description yet.');
    const instructions = escapeHtml(profileInstructionPreview(profile.instructions));
    return `<article class="model-card profile-card">
      <div class="model-card-header">
        <div>
          <h3>${escapeHtml(profile.display_name || name)}</h3>
          <div class="small-text muted"><code>${escapeHtml(name)}</code></div>
        </div>
        <span class="pill">${escapeHtml(profile.visibility || (profile.allowed_groups?.length ? 'group' : 'global'))}</span>
      </div>
      <p class="profile-card-description">${description}</p>
      <div class="workspace-card-pills">${profilePills(profile)}</div>
      <p class="profile-card-instructions">${instructions || 'No instructions yet.'}</p>
      <div class="button-row">
        <button type="button" onclick="openProfileModal('${escapeHtml(name)}')" ${editable ? '' : 'disabled'}>Edit</button>
        <button type="button" class="ghost-button" onclick="duplicateProfile('${escapeHtml(name)}')" ${editable ? '' : 'disabled'}>Duplicate</button>
        <button type="button" class="ghost-button danger-button" onclick="deleteProfileCard('${escapeHtml(name)}')" ${editable ? '' : 'disabled'}>Delete</button>
      </div>
    </article>`;
  }).join('');
}

function closeProfileModal() {
  document.getElementById('profileModal')?.setAttribute('hidden', '');
}

function selectedProfileGroupIds() {
  return Array.from(document.querySelectorAll('#profileAllowedGroups input[type="checkbox"]:checked')).map((node) => node.value).filter(Boolean);
}

function renderProfileGroupSelector(selected = []) {
  const container = document.getElementById('profileAllowedGroups');
  if (!container) return;
  const selectedSet = new Set(selected || []);
  if (!profileEditorState.groups.length) {
    container.innerHTML = '<div class="muted small-text">No groups available. Leave empty for global access.</div>';
    return;
  }
  container.innerHTML = profileEditorState.groups.map((group) => `
    <label class="profile-group-option">
      <input type="checkbox" value="${escapeHtml(group.id)}" ${selectedSet.has(group.id) ? 'checked' : ''} />
      <span>${escapeHtml(group.name || group.id)}</span>
      <span class="muted small-text">${escapeHtml(group.id)}</span>
    </label>
  `).join('');
}

function fillProfileEditor(name = '') {
  const profile = config.agent_profiles?.[name] || {};
  const original = document.getElementById('profileEditOriginalName');
  const nameInput = document.getElementById('profileEditorName');
  const title = document.getElementById('profileModalTitle');
  if (original) original.value = name;
  if (title) title.textContent = name ? 'Edit profile' : 'New profile';
  if (nameInput) {
    nameInput.value = name || '';
    nameInput.disabled = !!name;
  }
  document.getElementById('profileEditorDisplayName').value = profile.display_name || '';
  document.getElementById('profileEditorDescription').value = profile.description || '';
  document.getElementById('profileEditorInstructions').value = profile.instructions || profile.system_prompt || 'You are a careful remote coding and infrastructure agent.';
  document.getElementById('profileEditorContextProfile').value = profile.context_profile || 'medium';
  document.getElementById('profileEditorPlannerContextProfile').value = profile.planner_context_profile || '';
  document.getElementById('profileEditorPermissionProfile').value = profile.permission_profile || 'ask-first';
  document.getElementById('profileEditorVisibility').value = profile.visibility || (profile.allowed_groups?.length ? 'group' : 'global');
  const preferences = profile.output_preferences || {};
  document.getElementById('profilePreferDiffs').checked = !!preferences.prefer_diffs;
  document.getElementById('profileSummarizeFirst').checked = !!preferences.summarize_before_changes;
  document.getElementById('profileAvoidMutation').checked = !!preferences.avoid_file_mutation_unless_requested;
  renderProfileGroupSelector(profile.allowed_groups || []);
  const duplicateBtn = document.getElementById('duplicateProfileModalBtn');
  const deleteBtn = document.getElementById('deleteProfileModalBtn');
  if (duplicateBtn) duplicateBtn.hidden = !name;
  if (deleteBtn) deleteBtn.hidden = !name;
}

function openProfileModal(name = '') {
  if (!profileManagementAllowed()) return;
  ensureProfileGroupsLoaded().then(() => {
    fillProfileEditor(name);
    document.getElementById('profileModalStatus').textContent = '';
    document.getElementById('profileModal')?.removeAttribute('hidden');
    document.getElementById('profileEditorName')?.focus();
  }).catch((error) => {
    paneError('Loading groups failed', error.message);
  });
}

function profileEditorPayload() {
  return {
    display_name: document.getElementById('profileEditorDisplayName').value.trim() || null,
    description: document.getElementById('profileEditorDescription').value.trim() || null,
    instructions: document.getElementById('profileEditorInstructions').value.trim() || 'You are a careful remote coding and infrastructure agent.',
    context_profile: document.getElementById('profileEditorContextProfile').value || null,
    planner_context_profile: document.getElementById('profileEditorPlannerContextProfile').value || null,
    permission_profile: document.getElementById('profileEditorPermissionProfile').value || 'ask-first',
    visibility: document.getElementById('profileEditorVisibility').value || 'global',
    allowed_groups: selectedProfileGroupIds(),
    output_preferences: {
      prefer_diffs: !!document.getElementById('profilePreferDiffs').checked,
      summarize_before_changes: !!document.getElementById('profileSummarizeFirst').checked,
      avoid_file_mutation_unless_requested: !!document.getElementById('profileAvoidMutation').checked,
    },
  };
}

async function saveProfileFromForm() {
  const originalName = document.getElementById('profileEditOriginalName').value.trim();
  const name = originalName || document.getElementById('profileEditorName').value.trim();
  if (!name) return alert('Profile name is required');
  const payload = profileEditorPayload();
  const result = await api(`/v1/agent-profiles/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(payload) });
  config.agent_profiles = config.agent_profiles || {};
  config.agent_profiles[name] = result;
  await loadConfig();
  document.getElementById('profileModalStatus').textContent = `Saved profile ${name}`;
  closeProfileModal();
}

async function deleteProfileFromForm() {
  const originalName = document.getElementById('profileEditOriginalName').value.trim();
  if (!originalName) return;
  if (!confirm(`Delete profile ${originalName}?`)) return;
  await api(`/v1/agent-profiles/${encodeURIComponent(originalName)}`, { method: 'DELETE' });
  await loadConfig();
  closeProfileModal();
}

async function deleteProfileCard(name) {
  if (!profileManagementAllowed()) return;
  if (!confirm(`Delete profile ${name}?`)) return;
  await api(`/v1/agent-profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
  await loadConfig();
}

async function duplicateProfile(name) {
  if (!profileManagementAllowed()) return;
  const displayName = config.agent_profiles?.[name]?.display_name || name;
  const suggested = `${name}-copy`;
  const newName = prompt(`Duplicate "${displayName}" as`, suggested);
  if (!newName) return;
  await api(`/v1/agent-profiles/${encodeURIComponent(name)}/duplicate`, { method: 'POST', body: JSON.stringify({ name: newName }) });
  await loadConfig();
}

function bindProfilesPage() {
  if (profileEditorState.bound) return;
  profileEditorState.bound = true;
  document.getElementById('openProfileModalBtn')?.addEventListener('click', () => openProfileModal());
  document.getElementById('closeProfileModal')?.addEventListener('click', closeProfileModal);
  document.getElementById('saveProfileModalBtn')?.addEventListener('click', () => saveProfileFromForm().catch((error) => paneError('Profile save failed', error.message)));
  document.getElementById('duplicateProfileModalBtn')?.addEventListener('click', () => {
    const name = document.getElementById('profileEditOriginalName').value.trim();
    if (!name) return;
    duplicateProfile(name).catch((error) => paneError('Profile duplicate failed', error.message));
  });
  document.getElementById('deleteProfileModalBtn')?.addEventListener('click', () => deleteProfileFromForm().catch((error) => paneError('Profile delete failed', error.message)));
  document.getElementById('profileModal')?.addEventListener('click', (event) => {
    if (event.target?.id === 'profileModal') closeProfileModal();
  });
}
