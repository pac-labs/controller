// Session create modal, wizard review, and permission quick controls

function syncSessionPermissionQuick() {
  const select = document.getElementById('sessionPermissionQuick');
  const button = document.getElementById('applySessionPermission');
  const usageButton = document.getElementById('downloadSessionUsage');
  const diagButton = document.getElementById('downloadSessionDiagnostics');
  if (usageButton) usageButton.disabled = !selectedSession?.id;
  if (diagButton) diagButton.disabled = !selectedSession?.id;
  if (!select || !button) return;
  const profiles = Object.keys(config?.permission_profiles || {});
  select.innerHTML = '';
  if (!selectedSession) {
    opt(select, '', 'No session');
    select.disabled = true;
    button.disabled = true;
    return;
  }
  profiles.forEach((name) => opt(select, name, name));
  select.value = selectedSession.permission_profile || profiles[0] || '';
  const locked = !!selectedSession?.metadata?.system_context;
  select.disabled = !profiles.length || locked;
  button.disabled = !profiles.length || locked || select.value === (selectedSession.permission_profile || '');
  if (locked) select.title = 'PAC/core uses a locked permission profile.';
  else select.title = 'Permissions';
}

async function applySessionPermissionProfile() {
  if (!selectedSession?.id || selectedSession?.metadata?.system_context) return;
  const select = document.getElementById('sessionPermissionQuick');
  const next = select?.value || '';
  if (!next || next === selectedSession.permission_profile) return;
  const updated = await api(`/v1/sessions/${selectedSession.id}`, {method:'PUT', body:JSON.stringify({permission_profile: next})});
  selectedSession = updated;
  renderSelectedSessionSummary(selectedSession);
  syncSessionPermissionQuick();
  updateComposerChrome();
  renderSessionSidebar(window.__pacSessions || []);
  emitUiEvent('session_permission_profile_changed', `Session permissions changed to ${next}`, {session_id: selectedSession.id, permission_profile: next});
}

function openSessionModal() {
  const modal = document.getElementById('sessionModal');
  applySessionBootstrapMode();
  sessionWizardStepIndex = 0;
  renderSessionWizard();
  if (modal) { modal.hidden = false; setTimeout(() => document.getElementById('sessionName')?.focus(), 0); }
}

function closeSessionModal() {
  const modal = document.getElementById('sessionModal');
  if (modal) modal.hidden = true;
}
const SESSION_WIZARD_STEPS = ['Basics', 'Source', 'Runtime', 'Review'];

function renderSessionWizard() {
  const panes = Array.from(document.querySelectorAll('.session-wizard-pane'));
  panes.forEach((pane, index) => { pane.hidden = index !== sessionWizardStepIndex; pane.classList.toggle('active', index === sessionWizardStepIndex); });
  const steps = Array.from(document.querySelectorAll('#sessionWizardStepper .wizard-step'));
  steps.forEach((step, index) => step.classList.toggle('active', index === sessionWizardStepIndex));
  const back = document.getElementById('sessionWizardBack');
  const next = document.getElementById('sessionWizardNext');
  const create = document.getElementById('createSession');
  if (back) back.hidden = sessionWizardStepIndex === 0;
  if (next) next.hidden = sessionWizardStepIndex >= SESSION_WIZARD_STEPS.length - 1;
  if (create) create.hidden = sessionWizardStepIndex !== SESSION_WIZARD_STEPS.length - 1;
  updateSessionWizardReview();
}

function updateSessionWizardReview() {
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value || '-'; };
  const contextLabel = document.getElementById('sessionAgentContext')?.selectedOptions?.[0]?.textContent || '';
  const profileLabel = document.getElementById('agentProfile')?.selectedOptions?.[0]?.textContent || '';
  const workspaceMode = document.getElementById('sessionWorkspaceType')?.value || 'profile';
  const workspaceLabel = workspaceMode === 'git'
    ? (document.getElementById('sessionWorkspaceUrl')?.value || '').trim() || 'git repository'
    : workspaceMode === 'local'
      ? (document.getElementById('sessionWorkspacePath')?.value || '').trim() || 'local workspace'
      : (document.getElementById('workspaceProfile')?.selectedOptions?.[0]?.textContent || '');
  const endpointLabel = document.getElementById('sessionEndpoint')?.selectedOptions?.[0]?.textContent || '';
  const permissionLabel = document.getElementById('permissionOverride')?.selectedOptions?.[0]?.textContent || 'profile default';
  const modeLabel = document.getElementById('contextMode')?.value || 'profile default';
  const modelLabel = document.getElementById('modelOverride')?.selectedOptions?.[0]?.textContent || 'profile default';
  set('sessionWizardReviewName', (document.getElementById('sessionName')?.value || '').trim() || 'web-session');
  set('sessionWizardReviewContext', contextLabel || 'none');
  set('sessionWizardReviewProfile', profileLabel || 'none');
  set('sessionWizardReviewWorkspace', workspaceLabel || 'none');
  set('sessionWizardReviewEndpoint', endpointLabel || 'not selected');
  set('sessionWizardReviewPermission', permissionLabel || 'profile default');
  set('sessionWizardReviewMode', modeLabel || 'profile default');
  set('sessionWizardReviewModel', modelLabel || 'profile default');
}

function advanceSessionWizard(delta = 1) {
  sessionWizardStepIndex = Math.max(0, Math.min(SESSION_WIZARD_STEPS.length - 1, sessionWizardStepIndex + delta));
  renderSessionWizard();
}

