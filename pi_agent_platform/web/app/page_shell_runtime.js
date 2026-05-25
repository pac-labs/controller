(function () {
  const ROUTE_EXTRAS = {
    dashboard: {
      actions: [{label: 'Widgets', target: 'dashboardWidgetPicker'}, {label: 'Refresh atlas', target: 'dashboardRefreshTopology', subtle: true}],
      toolbar: {hidden: true},
    },
    atlas: {
      title: 'PAC Component Atlas',
      description: 'Zoomable component map of controller, agents, endpoints, workspaces, providers, models, tools, and active relationships.',
      actions: [{label: 'Reset atlas', target: 'dashboardResetTopologyLayout'}, {label: 'Refresh atlas', target: 'dashboardRefreshTopology', subtle: true}],
      toolbar: {hidden: true},
    },
    sessions: {
      actions: [{label: 'New session', target: 'openSessionModal'}],
      toolbar: {search: {placeholder: 'Filter sessions and timeline…', target: '#sessions-tab'}},
    },
    endpoints: {
      actions: [{label: 'Endpoint wizard', target: 'switchToEndpointOnboarding'}, {label: 'Add local endpoint', target: 'addLocalRunner', subtle: true}],
      tabs: [
        {label: 'Inventory', target: 'endpointInventoryPanel'},
        {label: 'Add endpoint', target: 'endpointOnboardingPanel'},
      ],
      toolbar: {search: {placeholder: 'Search endpoints…', target: '#runners'}, actions: [{label: 'Discover local host', target: 'discoverLocal'}, {label: 'Update online endpoints', target: 'updateAllEndpoints'}]},
    },
    providers: {
      actions: [{label: 'Add provider', target: 'openProviderModal'}],
      toolbar: {search: {placeholder: 'Search providers…', target: '#providers'}},
    },
    models: {
      actions: [{label: 'Add model', target: 'openModelModal'}],
      toolbar: {search: {placeholder: 'Search models…', target: '#models'}, actions: [{label: 'Browse providers', target: 'showUnconfigModels'}, {label: 'Marketplace', target: 'openMarketplaceModal'}, {label: 'Sync from provider', target: 'syncModelProviderBtn'}]},
    },
    profiles: {
      actions: [{label: 'Add profile', target: 'openProfileModalBtn'}],
      toolbar: {search: {placeholder: 'Search profiles…', target: '#profiles'}},
    },
    contexts: {
      actions: [{label: 'Add context', target: 'openAgentContextWizard'}],
      toolbar: {search: {placeholder: 'Search contexts…', target: '#agentContexts'}},
    },
    workspaces: {
      actions: [{label: 'Add workspace', target: 'openWorkspaceModal'}],
      toolbar: {search: {placeholder: 'Search workspaces…', target: '#workspaces-tab'}},
    },
    tools: {
      toolbar: {search: {placeholder: 'Search tools and packages…', target: '#tools-tab'}},
    },
    credentials: {
      actions: [{label: 'Add secret', target: 'openConfigSecretWizard'}, {label: 'Add variable', target: 'openConfigVariableWizard', subtle: true}],
      toolbar: {search: {placeholder: 'Search credentials…', target: '#settings-credentials'}, actions: [{label: 'Refresh variables', target: 'refreshConfigVariables'}, {label: 'Refresh secrets', target: 'refreshConfigSecrets'}]},
    },
    'users-groups': {
      actions: [{label: 'Add user/group', menu: 'addPersonMenu'}],
      toolbar: {search: {placeholder: 'Search users, groups, resources…', target: '#settings-users'}, actions: [{label: 'Refresh directory', target: 'refreshDirectoryBtn'}]},
    },
    'approvals-policy': {
      actions: [{label: 'Refresh approvals', target: 'refreshApprovalsBtn'}],
      toolbar: {search: {placeholder: 'Search approvals…', target: '#settings-approvals'}},
    },
    updates: {
      actions: [{label: 'Check release', target: 'checkPacRelease'}, {label: 'Backups', target: 'openBackupsModal', subtle: true}],
      toolbar: {actions: [{label: 'Apply latest release', target: 'applyPacRelease'}, {label: 'Preview update', target: 'inspectFeaturePack'}, {label: 'Check source modules', target: 'checkSourceUpdates'}]},
    },
    runtime: {actions: [{label: 'Refresh status', target: 'refreshControllerHarness'}]},
    'service-mode': {actions: [{label: 'User service', target: 'setUserService'}, {label: 'Host service', target: 'setHostService', subtle: true}]},
    'network-security': {actions: [{label: 'Refresh TLS', target: 'refreshTlsStatus'}]},
    'proxy-routes': {actions: [{label: 'Create route', target: 'openProxyRouteModal'}], toolbar: {search: {placeholder: 'Search proxy routes…', target: '#proxyRoutesList'}}},
    'raw-config': {actions: [{label: 'Save config', target: 'saveConfig'}, {label: 'Validate JSON', event: 'pac:validate-config', subtle: true}]},
    observability: {toolbar: {search: {placeholder: 'Search observability panels…', target: '#observe-tab'}}},
    events: {
      title: 'Events',
      description: 'Alerting and event hub for controller, agent, endpoint, release, approval, and UI activity.',
      actions: [{label: 'Reload events', target: 'eventsHubReload'}, {label: 'Critical only', target: 'eventsHubCriticalOnly', subtle: true}],
      toolbar: {search: {placeholder: 'Search events…', target: '#events-tab'}, actions: [{label: 'Export visible', target: 'eventsHubExport'}]},
    },
  };

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function routeFor(item) {
    return item?.id || item?.tab || 'dashboard';
  }

  function clickTarget(action) {
    if (!action) return;
    if (action.event) {
      document.dispatchEvent(new CustomEvent(action.event));
      return;
    }
    if (action.menu && typeof window.openDirectoryCreateMenu === 'function') {
      window.openDirectoryCreateMenu(action.menu);
      return;
    }
    const target = document.getElementById(action.target || '');
    if (target) target.click();
  }

  function actionButton(action, index, scope) {
    const kind = action.subtle ? 'ghost-button' : 'primary-button';
    return `<button class="${kind} page-shell-action" type="button" data-page-action-scope="${esc(scope)}" data-page-action-index="${index}">${esc(action.label)}</button>`;
  }

  function renderActions(actions, scope, container) {
    if (!container) return;
    container.innerHTML = (actions || []).map((action, index) => actionButton(action, index, scope)).join('');
    container.querySelectorAll('[data-page-action-index]').forEach((button) => {
      button.addEventListener('click', () => clickTarget((actions || [])[Number(button.dataset.pageActionIndex || 0)]));
    });
  }

  function syncMasthead(mode) {
    const masthead = document.getElementById('pacPageMasthead');
    if (!masthead) return;
    const next = mode || 'sticky';
    masthead.dataset.mastheadMode = next;
    masthead.classList.remove('page-masthead-normal', 'page-masthead-sticky', 'page-masthead-compact', 'page-masthead-hidden');
    masthead.classList.add(`page-masthead-${next}`);
    document.body?.setAttribute('data-page-masthead-mode', next);
    window.setTimeout(() => {
      const height = masthead.classList.contains('page-masthead-hidden') ? 0 : masthead.getBoundingClientRect().height;
      document.documentElement.style.setProperty('--page-masthead-height', `${Math.max(0, Math.round(height))}px`);
    }, 0);
  }

  function setCopy(item, extras) {
    const groupLabel = item?.group?.label || 'Operate';
    const itemLabel = extras?.title || item?.label || 'Dashboard';
    const title = document.getElementById('pacPageTitle');
    const context = document.getElementById('pacShellContext');
    const breadcrumb = document.getElementById('pacShellBreadcrumb');
    if (breadcrumb) breadcrumb.textContent = `${groupLabel} / ${item?.label || itemLabel}`;
    if (title) title.textContent = itemLabel === 'Dashboard' ? 'Operations dashboard' : itemLabel;
    if (context) context.textContent = extras?.description || item?.description || item?.group?.description || 'PAC controller workspace';
  }

  function renderTabs(tabs) {
    const container = document.getElementById('pacPageTabs');
    if (!container) return;
    if (!Array.isArray(tabs) || !tabs.length) {
      container.hidden = true;
      container.innerHTML = '';
      return;
    }
    container.hidden = false;
    container.innerHTML = tabs.map((tab, index) => `<button type="button" data-page-tab-index="${index}">${esc(tab.label)}</button>`).join('');
    const updateActive = () => {
      container.querySelectorAll('button').forEach((button) => {
        const tab = tabs[Number(button.dataset.pageTabIndex || 0)];
        const target = document.getElementById(tab.target || '');
        button.classList.toggle('active', !!target && !target.hidden && target.classList.contains('active'));
      });
    };
    container.querySelectorAll('button').forEach((button) => {
      button.addEventListener('click', () => {
        const tab = tabs[Number(button.dataset.pageTabIndex || 0)];
        if (tab?.target && typeof window.switchEndpointPanel === 'function' && tab.target.startsWith('endpoint')) window.switchEndpointPanel(tab.target);
        else document.getElementById(tab?.target || '')?.click();
        window.setTimeout(updateActive, 0);
      });
    });
    window.setTimeout(updateActive, 0);
  }

  function filterTarget(selector, query) {
    const root = selector ? document.querySelector(selector) : null;
    if (!root) return;
    const cards = root.querySelectorAll('.card, article, tr, .provider-card, .endpoint-card, .workspace-card, .directory-object-row');
    const needle = String(query || '').trim().toLowerCase();
    cards.forEach((node) => {
      const visible = !needle || node.textContent.toLowerCase().includes(needle);
      node.classList.toggle('page-filter-hidden', !visible);
    });
  }

  function renderToolbar(toolbar) {
    const container = document.getElementById('pacPageToolbar');
    if (!container) return;
    if (!toolbar || toolbar.hidden) {
      container.hidden = true;
      container.innerHTML = '';
      return;
    }
    const search = toolbar.search ? `<label class="page-toolbar-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="${esc(toolbar.search.placeholder || 'Search…')}" data-page-toolbar-search="1" /></label>` : '';
    const actions = (toolbar.actions || []).map((action, index) => actionButton(action, index, 'toolbar')).join('');
    container.hidden = false;
    container.innerHTML = `<div class="page-toolbar-main">${search}</div><div class="page-toolbar-actions">${actions}</div>`;
    const input = container.querySelector('[data-page-toolbar-search]');
    if (input) input.addEventListener('input', () => filterTarget(toolbar.search?.target, input.value));
    container.querySelectorAll('[data-page-action-index]').forEach((button) => {
      button.addEventListener('click', () => clickTarget((toolbar.actions || [])[Number(button.dataset.pageActionIndex || 0)]));
    });
  }

  function applyRoute(item) {
    const route = routeFor(item);
    const extras = ROUTE_EXTRAS[route] || {};
    setCopy(item, extras);
    syncMasthead(extras.mastheadMode || item?.mastheadMode || 'sticky');
    renderTabs(extras.tabs);
    renderActions(extras.actions || [], 'masthead', document.getElementById('pacPageMastheadActions'));
    renderToolbar(extras.toolbar);
    return true;
  }

  function applyConfigPanel(panelMeta, panelName) {
    const routeMap = {users: 'users-groups', approvals: 'approvals-policy', 'pi-dev': 'runtime', endpoint: 'endpoints', service: 'service-mode', tls: 'network-security', config: 'raw-config'};
    const route = routeMap[panelName] || panelName || '';
    const item = window.PacShellNav?.findItemByRoute?.(route) || null;
    if (item) {
      applyRoute({...item, label: panelMeta.title, description: panelMeta.copy});
      return;
    }
    setCopy({group: {label: 'Configuration'}, label: panelMeta.title, description: panelMeta.copy}, {description: panelMeta.copy});
    renderActions(panelMeta.actions || [], 'masthead', document.getElementById('pacPageMastheadActions'));
  }

  window.PacPageShell = {applyRoute, applyConfigPanel, clickTarget, filterTarget};
})();
