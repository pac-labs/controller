// Guided agent context wizard state and navigation.
function renderAgentContextWizardProgress() {
  const progressEl = document.getElementById('agentContextWizardProgress');
  if (!progressEl) return;
  progressEl.innerHTML = AGENT_CONTEXT_WIZARD_STEPS.map((step, index) => `<button type="button" class="ghost-button ${index === agentContextWizardStepIndex ? 'active' : ''}" data-agent-context-step="${index}">${escapeHtml(step.label)}</button>`).join('');
  progressEl.querySelectorAll('[data-agent-context-step]').forEach((button) => {
    button.onclick = () => {
      agentContextWizardStepIndex = Number(button.getAttribute('data-agent-context-step') || 0);
      renderAgentContextWizard();
    };
  });
}

function renderAgentContextWizard() {
  renderAgentContextWizardProgress();
  AGENT_CONTEXT_WIZARD_STEPS.forEach((step, index) => {
    const el = document.getElementById(step.id);
    if (el) el.hidden = index !== agentContextWizardStepIndex;
  });
  const existingId = document.getElementById('agentContextSelect')?.value || '';
  const saveBtn = document.getElementById('saveAgentContext');
  const nextBtn = document.getElementById('agentContextWizardNext');
  const backBtn = document.getElementById('agentContextWizardBack');
  if (saveBtn) saveBtn.textContent = existingId ? 'Save changes' : 'Create context';
  if (nextBtn) nextBtn.hidden = agentContextWizardStepIndex >= AGENT_CONTEXT_WIZARD_STEPS.length - 1;
  if (backBtn) backBtn.disabled = agentContextWizardStepIndex <= 0;
}

function openAgentContextWizard(id = '') {
  fillAgentContextForm(id);
  agentContextWizardStepIndex = 0;
  renderAgentContextWizard();
  const modal = document.getElementById('agentContextWizardModal');
  if (modal) modal.hidden = false;
}

function closeAgentContextWizard() {
  const modal = document.getElementById('agentContextWizardModal');
  if (modal) modal.hidden = true;
}
