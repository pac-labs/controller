(function () {
  const PANEL_META = {
    credentials: {
      title: 'Credentials',
      eyebrow: 'Configuration / Credentials',
      copy: 'Workspace variables and write-only secrets are managed separately from personal user settings.',
      steps: ['Identify material', 'Store safely', 'Review audit'],
      actions: [{label: 'Add variable', target: 'addConfigVariable'}, {label: 'Add secret', target: 'addConfigSecret'}],
    },
    users: {
      title: 'Users & groups',
      eyebrow: 'Configuration / Directory',
      copy: 'People, groups, service accounts, and resource grants are managed as one directory surface.',
      steps: ['Create identity', 'Assign groups', 'Verify access'],
      actions: [{label: 'Person', menu: 'addPersonMenu'}, {label: 'Group', menu: 'addGroupMenu'}, {label: 'Service account', menu: 'addServiceAccountMenu'}],
    },
    approvals: {
      title: 'Approvals',
      eyebrow: 'Configuration / Governance',
      copy: 'Review pending task approvals and access requests without mixing them into the user profile menu.',
      steps: ['Inspect request', 'Approve or deny', 'Audit result'],
      actions: [{label: 'Refresh', target: 'refreshApprovalsBtn'}],
    },
    updates: {
      title: 'Updates',
      eyebrow: 'Configuration / Platform',
      copy: 'PAC releases, feature packs, source updates, backups, and local diff checks live in one admin route.',
      steps: ['Check version', 'Preview changes', 'Apply or restore'],
      actions: [{label: 'Check release', target: 'checkPacRelease'}, {label: 'Backups', target: 'openBackupsModal'}],
    },
    'pi-dev': {
      title: 'Runtime',
      eyebrow: 'Configuration / Runtime',
      copy: 'Controller pi.dev settings determine the built-in PAC agent session and local execution wrapper.',
      steps: ['Check wrapper', 'Select model/profile', 'Keep session ready'],
      actions: [{label: 'Refresh status', target: 'refreshControllerHarness'}, {label: 'Open session', target: 'openControllerHarnessSession'}],
    },
    endpoint: {
      title: 'Endpoints',
      eyebrow: 'Configuration / Endpoint join',
      copy: 'Controller URL and discovery settings decide how endpoint binaries find and register with PAC.',
      steps: ['Choose URL', 'Set discovery', 'Save join path'],
      actions: [{label: 'Save endpoint URL', target: 'saveEndpointConnection'}],
    },
    service: {
      title: 'Service',
      eyebrow: 'Configuration / Service mode',
      copy: 'Choose whether PAC runs as a user service or host/system service, and inspect the current unit state.',
      steps: ['Inspect units', 'Choose mode', 'Restart safely'],
      actions: [{label: 'User service', target: 'setUserService'}, {label: 'Host service', target: 'setHostService'}],
    },
    tls: {
      title: 'TLS / CA',
      eyebrow: 'Configuration / Trust',
      copy: 'Local CA status and DNS-01 certificate setup are grouped as security configuration, not personal settings.',
      steps: ['Check local CA', 'Configure DNS-01', 'Download trust'],
      actions: [{label: 'Refresh TLS', target: 'refreshTlsStatus'}, {label: 'Download CA', href: '/v1/tls/ca.pem'}],
    },
    'proxy-routes': {
      title: 'Proxy routes',
      eyebrow: 'Configuration / Routes',
      copy: 'Expose internal services through PAC with explicit target URLs and optional profile access limits.',
      steps: ['Define backend', 'Set access', 'Test route'],
      actions: [{label: 'Create route', target: 'openProxyRouteModal'}],
    },
    config: {
      title: 'Raw config',
      eyebrow: 'Configuration / Raw editor',
      copy: 'Inspect and edit the controller configuration directly when a dedicated page does not cover a setting yet.',
      steps: ['Validate JSON', 'Save YAML', 'Reload state'],
      actions: [{label: 'Validate JSON', event: 'pac:validate-config'}, {label: 'Save config', target: 'saveConfig'}],
    },
  };

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function ensureShell() {
    const settings = document.getElementById('settings-tab');
    if (!settings) return null;
    let shell = document.getElementById('configurationPageShell');
    if (!shell) {
      shell = document.createElement('section');
      shell.id = 'configurationPageShell';
      shell.className = 'configuration-page-shell';
      const subnav = settings.querySelector('.settings-subnav');
      settings.insertBefore(shell, subnav ? subnav.nextSibling : settings.firstChild);
    }
    return shell;
  }

  function actionMarkup(action) {
    if (action.href) {
      return `<a class="button-link config-shell-action" href="${esc(action.href)}" download>${esc(action.label)}</a>`;
    }
    const attr = action.event
      ? `data-config-shell-event="${esc(action.event)}"`
      : action.menu
        ? `data-config-shell-menu="${esc(action.menu)}"`
        : `data-config-shell-target="${esc(action.target || '')}"`;
    return `<button class="ghost-button config-shell-action" type="button" ${attr}>${esc(action.label)}</button>`;
  }

  function setPanelClass(name) {
    document.body?.classList.forEach((className) => {
      if (className.startsWith('config-panel-')) document.body.classList.remove(className);
    });
    document.body?.classList.add(`config-panel-${String(name || 'updates').replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()}`);
  }

  function renderConfigPageShell(name = 'updates') {
    const meta = PANEL_META[name] || PANEL_META.updates;
    const shell = ensureShell();
    if (!shell) return;
    setPanelClass(name);
    shell.innerHTML = `<div class="config-shell-copy">
      <p class="config-shell-eyebrow">${esc(meta.eyebrow)}</p>
      <h1>${esc(meta.title)}</h1>
      <p class="muted">${esc(meta.copy)}</p>
    </div>
    <div class="config-shell-flow" aria-label="Configuration flow">
      ${(meta.steps || []).map((step, index) => `<span><b>${index + 1}</b>${esc(step)}</span>`).join('')}
    </div>
    <div class="config-shell-actions">${(meta.actions || []).map(actionMarkup).join('')}</div>`;
  }

  function clickShellAction(event) {
    const button = event.target.closest('.config-shell-action');
    if (!button) return;
    const targetId = button.dataset.configShellTarget;
    const customEvent = button.dataset.configShellEvent;
    const menu = button.dataset.configShellMenu;
    if (customEvent) {
      document.dispatchEvent(new CustomEvent(customEvent));
      return;
    }
    if (menu) {
      const menuButton = document.querySelector(`[data-open-add="${menu.replace(/\"/g, '')}"]`);
      if (menuButton) menuButton.click();
      return;
    }
    if (!targetId) return;
    const target = document.getElementById(targetId);
    if (target) target.click();
  }

  document.addEventListener('click', clickShellAction);
  window.renderConfigPageShell = renderConfigPageShell;
})();
