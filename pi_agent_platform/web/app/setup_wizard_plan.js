// Setup wizard planning, summary copy, and issue-to-step mapping.

const SETUP_WIZARD_STEP_COPY = {
  connection: {
    label: 'Connection',
    title: 'Controller connection',
    summary: 'Fix controller connection or authentication settings that block safe use.',
  },
  provider: {
    label: 'Provider',
    title: 'Model provider',
    summary: 'Connect one enabled model provider PAC can call for sessions.',
  },
  model: {
    label: 'Model',
    title: 'Session model',
    summary: 'Register one model that can be used by agent-backed sessions.',
  },
  controller: {
    label: 'pi.dev',
    title: 'Controller pi.dev',
    summary: 'Select or update the local controller runtime wrapper.',
  },
  review: {
    label: 'Review',
    title: 'Review and finish',
    summary: 'Recheck setup after saving the required changes.',
  },
};

const SETUP_WIZARD_ISSUE_STEPS = {
  controller_model_missing: 'controller',
  controller_wrapper_version_mismatch: 'controller',
  dev_token_default: 'connection',
  no_enabled_providers: 'provider',
  no_models: 'model',
  no_session_capable_models: 'model',
};

function setupWizardStepForIssue(issue) {
  return SETUP_WIZARD_ISSUE_STEPS[issue?.id] || 'review';
}

function setupWizardCurrentIssues() {
  return setupStatus?.required_issues || [];
}

function setupWizardCurrentWarnings() {
  return setupStatus?.warnings || [];
}

function setupWizardNeedsProviderForModel() {
  const issues = setupWizardCurrentIssues();
  const needsModel = issues.some(issue => setupWizardStepForIssue(issue) === 'model');
  return needsModel && !setupWizardProviderNames().length;
}

function setupWizardNeededStepIds() {
  const issueStepIds = setupWizardCurrentIssues().map(setupWizardStepForIssue);
  const ids = new Set(issueStepIds.filter(id => id !== 'review'));
  if (setupWizardNeedsProviderForModel()) ids.add('provider');
  if (!ids.size) ids.add('review');
  const ordered = ['provider', 'model', 'connection', 'controller'].filter(id => ids.has(id));
  return ['overview', ...ordered, 'review'];
}

function setupWizardIssuesForStep(stepId) {
  return setupWizardCurrentIssues().filter(issue => setupWizardStepForIssue(issue) === stepId);
}

function setupWizardStepCard(stepId, index) {
  const copy = SETUP_WIZARD_STEP_COPY[stepId] || SETUP_WIZARD_STEP_COPY.review;
  const issues = setupWizardIssuesForStep(stepId);
  const issueCopy = issues.length
    ? issues.map(issue => escapeHtml(issue.title || 'Required setup')).join(', ')
    : stepId === 'provider' && setupWizardNeedsProviderForModel()
      ? 'Needed before a session model can be registered.'
      : copy.summary;
  return `<button type="button" class="setup-needed-card" data-setup-jump="${escapeHtml(stepId)}">
    <span class="setup-needed-index">${index + 1}</span>
    <span><b>${escapeHtml(copy.label)}</b><small>${issueCopy}</small></span>
  </button>`;
}

function setupWizardOverviewHtml() {
  const issues = setupWizardCurrentIssues();
  const warnings = setupWizardCurrentWarnings();
  const stepIds = setupWizardNeededStepIds().filter(id => id !== 'overview' && id !== 'review');
  const steps = stepIds.length
    ? stepIds.map((stepId, index) => setupWizardStepCard(stepId, index)).join('')
    : '<div class="pack-summary strong-summary">No required setup blockers remain.</div>';
  const issueList = issues.length
    ? `<div class="setup-blocker-list">${issues.map(issue => `<div class="pack-summary warn-summary"><b>${escapeHtml(issue.title || 'Required setup')}</b><div class="muted small-text">${escapeHtml(issue.detail || '')}</div></div>`).join('')}</div>`
    : '';
  const warningCopy = warnings.length
    ? `<div class="muted small-text">${warnings.length} non-blocking warning(s) will remain visible after the required setup is complete.</div>`
    : '';
  return `<div class="stacked-output setup-wizard-overview">
    <div class="pack-summary strong-summary">
      <b>Finish only the setup that is still blocking PAC sessions.</b>
      <div class="muted small-text">This wizard is filtered to the current required blockers. Optional fields stay on their normal configuration pages.</div>
    </div>
    <div class="setup-needed-grid">${steps}</div>
    ${issueList}
    ${warningCopy}
    ${setupWizardStatusMessage('Choose the first needed step, or continue through the filtered flow.')}
  </div>`;
}

function setupWizardOverviewMeta() {
  const requiredCount = setupWizardCurrentIssues().length;
  const warningCount = setupWizardCurrentWarnings().length;
  const stepCount = Math.max(0, setupWizardNeededStepIds().length - 2);
  const requiredLabel = requiredCount === 1 ? 'required blocker' : 'required blockers';
  const stepLabel = stepCount === 1 ? 'step' : 'steps';
  return `${requiredCount} ${requiredLabel}. ${stepCount} focused ${stepLabel}. ${warningCount} warning(s).`;
}

function wireSetupWizardOverview() {
  document.querySelectorAll('[data-setup-jump]').forEach((button) => {
    button.addEventListener('click', () => {
      const targetId = button.dataset.setupJump || 'overview';
      const nextIndex = setupWizardSteps.findIndex(step => step.id === targetId);
      if (nextIndex >= 0) {
        setupWizardStepIndex = nextIndex;
        renderSetupWizard();
      }
    });
  });
}
