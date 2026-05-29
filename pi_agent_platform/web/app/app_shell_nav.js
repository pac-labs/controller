(function () {
  const DEFAULT_ROUTE = 'dashboard';
  const STORAGE_KEY = 'pac-shell-active-route';
  const URL_BASE = '/ui';

  function navGroups() {
    return Array.isArray(window.PAC_NAV_GROUPS) ? window.PAC_NAV_GROUPS : [];
  }

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>\"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function flattenItems() {
    return navGroups().flatMap((group) => (group.items || []).map((item) => ({...item, group})));
  }

  function routeFor(item) {
    return item?.id || item?.tab || DEFAULT_ROUTE;
  }

  function selectorEscape(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(String(value || ''));
    return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  function buildTabToGroup() {
    const map = {};
    for (const group of navGroups()) {
      for (const item of group.items || []) {
        if (item.tab && !map[item.tab]) map[item.tab] = group.id;
      }
    }
    map['settings-tab'] = 'admin';
    return map;
  }

  function findItemByRoute(route) {
    return flattenItems().find((entry) => routeFor(entry) === route) || null;
  }

  function findItemByTab(tabId) {
    return flattenItems().find((entry) => entry.tab === tabId) || null;
  }

  function routeFromLocation() {
    const path = String(window.location?.pathname || '');
    if (!path.startsWith(URL_BASE)) return '';
    const rest = path.slice(URL_BASE.length).replace(/^\/+|\/+$/g, '');
    if (!rest || rest === 'index.html') return '';
    const first = rest.split('/')[0] || '';
    return findItemByRoute(first) ? first : '';
  }

  function pathForRoute(route) {
    const safe = route || DEFAULT_ROUTE;
    return `${URL_BASE}/${encodeURIComponent(safe)}`;
  }

  function savedRoute() {
    const urlRoute = routeFromLocation();
    if (urlRoute) return urlRoute;
    try { return localStorage.getItem(STORAGE_KEY) || DEFAULT_ROUTE; } catch (_) { return DEFAULT_ROUTE; }
  }

  function saveRoute(route) {
    try { localStorage.setItem(STORAGE_KEY, route || DEFAULT_ROUTE); } catch (_) {}
  }

  function updateBrowserRoute(route, options = {}) {
    const activeRoute = route || DEFAULT_ROUTE;
    saveRoute(activeRoute);
    if (window.__pacShellApplyingPopstate) return;
    if (!window.history?.pushState || !window.location) return;
    const target = pathForRoute(activeRoute);
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (current === target) return;
    const state = {pacRoute: activeRoute};
    if (options.replace) window.history.replaceState(state, '', target);
    else window.history.pushState(state, '', target);
  }

  function renderNav(container) {
    if (!container) return;
    const sections = navGroups().map((group) => {
      const collapsed = window.PacShellNavState?.isSectionCollapsed(group.id) || false;
      const rows = (group.items || []).map((item) => {
        const description = item.description ? `<span class="shell-nav-item-description">${esc(item.description)}</span>` : '';
        const settingsPanel = item.settingsPanel ? ` data-settings-panel="${esc(item.settingsPanel)}"` : '';
        const aliases = Array.isArray(item.aliases) ? ` data-shell-aliases="${esc(item.aliases.join(' '))}"` : '';
        return `<button class="shell-nav-item" type="button" data-shell-route="${esc(routeFor(item))}" data-tab="${esc(item.tab || '')}"${settingsPanel}${aliases} title="${esc(item.description || item.label)}">
          <span class="shell-nav-icon" aria-hidden="true">${esc(item.icon || '•')}</span>
          <span class="shell-nav-labels"><span class="shell-nav-label">${esc(item.label)}</span>${description}</span>
        </button>`;
      }).join('');
      return `<section class="shell-nav-section${collapsed ? ' collapsed' : ''}" data-shell-group="${esc(group.id)}">
        <button class="shell-nav-section-toggle" type="button" data-shell-toggle-group="${esc(group.id)}" aria-expanded="${collapsed ? 'false' : 'true'}" title="${esc(group.description || group.label)}">
          <span class="shell-nav-section-title">${esc(group.label)}</span>
          <span class="shell-nav-section-chevron" aria-hidden="true">⌄</span>
        </button>
        <div class="shell-nav-section-description">${esc(group.description || '')}</div>
        <div class="shell-nav-items">${rows}</div>
      </section>`;
    }).join('');
    container.innerHTML = `<div class="shell-nav-tools"><label class="shell-nav-search-wrap"><span class="shell-nav-search-icon" aria-hidden="true">⌕</span><input id="pacShellNavSearch" class="shell-nav-search" type="search" placeholder="Filter menu" autocomplete="off" /></label><div class="shell-nav-tool-actions"><button id="pacShellNavExpandAll" type="button" class="shell-nav-tool-button">Expand all</button><button id="pacShellNavCollapseAll" type="button" class="shell-nav-tool-button">Collapse all</button></div></div><div class="shell-nav-scroll">${sections}</div><button id="pacShellNavCollapse" class="shell-nav-collapse" type="button" aria-pressed="false">Collapse</button>`;
  }

  function applySectionState(groupId, collapsed) {
    const section = document.querySelector(`.shell-nav-section[data-shell-group="${selectorEscape(groupId)}"]`);
    const toggle = section?.querySelector('.shell-nav-section-toggle');
    section?.classList.toggle('collapsed', collapsed);
    if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  function expandActiveSection(groupId) {
    if (!groupId || !window.PacShellNavState?.isSectionCollapsed(groupId)) return;
    window.PacShellNavState.setSectionCollapsed(groupId, false);
    applySectionState(groupId, false);
  }

  function setCollapsed(collapsed) {
    const shell = document.querySelector('.app-shell');
    const nav = document.getElementById('pacShellNav');
    const button = document.getElementById('pacShellNavCollapse');
    shell?.classList.toggle('shell-nav-collapsed', collapsed);
    nav?.classList.toggle('collapsed', collapsed);
    if (button) {
      button.textContent = collapsed ? 'Expand' : 'Collapse';
      button.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
    }
    window.PacShellNavState?.setRailCollapsed(collapsed);
  }

  function isCollapsed() {
    return window.PacShellNavState?.isRailCollapsed() || false;
  }

  function mastheadModeFor(item) {
    const panelModes = {
      updates: 'sticky', credentials: 'sticky', users: 'sticky', approvals: 'sticky',
      'pi-dev': 'sticky', endpoint: 'sticky', service: 'sticky', tls: 'sticky',
      'proxy-routes': 'sticky', config: 'sticky',
    };
    return item?.mastheadMode || panelModes[item?.settingsPanel || ''] || 'sticky';
  }

  function updateMastheadMode(item) {
    const masthead = document.getElementById('pacPageMasthead');
    if (!masthead) return;
    const mode = mastheadModeFor(item);
    masthead.dataset.mastheadMode = mode;
    masthead.classList.remove('page-masthead-normal', 'page-masthead-sticky', 'page-masthead-compact', 'page-masthead-hidden');
    masthead.classList.add(`page-masthead-${mode}`);
    document.body?.setAttribute('data-page-masthead-mode', mode);
  }

  function updateBreadcrumb(item) {
    if (window.PacPageShell?.applyRoute?.(item)) return;
    const breadcrumb = document.getElementById('pacShellBreadcrumb');
    const context = document.getElementById('pacShellContext');
    const title = document.getElementById('pacPageTitle');
    const groupLabel = item?.group?.label || 'Operate';
    const itemLabel = item?.label || 'Dashboard';
    const subLabel = item?.settingsPanel ? ` / ${itemLabel}` : ` / ${itemLabel}`;
    if (breadcrumb) breadcrumb.textContent = `${groupLabel}${subLabel}`;
    if (title) title.textContent = itemLabel === 'Dashboard' ? 'Operations dashboard' : itemLabel;
    if (context) context.textContent = item?.description || item?.group?.description || 'PAC controller workspace';
    updateMastheadMode(item);
  }

  function focusTarget(item) {
    if (!item?.focus) return;
    const target = document.getElementById(item.focus);
    if (!target) return;
    target.scrollIntoView({block: 'center', inline: 'center', behavior: 'smooth'});
    target.classList.add('shell-nav-focus-pulse');
    window.setTimeout(() => target.classList.remove('shell-nav-focus-pulse'), 1000);
  }

  function activeItemFor(groupName, activeTab) {
    const storedItem = findItemByRoute(window.__pacActiveShellRoute || savedRoute());
    if (storedItem?.tab === activeTab) return storedItem;
    return findItemByTab(activeTab) || flattenItems().find((entry) => entry.group.id === groupName) || findItemByRoute(DEFAULT_ROUTE);
  }

  function routeClass(route) {
    return `shell-route-${String(route || DEFAULT_ROUTE).replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()}`;
  }

  function applyRouteClass(route) {
    const body = document.body;
    if (!body) return;
    Array.from(body.classList).forEach((name) => {
      if (name.startsWith('shell-route-')) body.classList.remove(name);
    });
    body.classList.add(routeClass(route));
    body.dataset.shellRoute = route || DEFAULT_ROUTE;
  }

  function renderGroup(groupName, activeTab) {
    const item = activeItemFor(groupName, activeTab);
    const activeRoute = routeFor(item);
    window.__pacActiveShellRoute = activeRoute;
    applyRouteClass(activeRoute);
    expandActiveSection(item?.group?.id || groupName);
    document.querySelectorAll('.shell-nav-section').forEach((section) => {
      section.classList.toggle('active', section.dataset.shellGroup === (item?.group?.id || groupName));
    });
    document.querySelectorAll('.shell-nav-item').forEach((button) => {
      button.classList.toggle('active', (button.dataset.shellRoute || '') === activeRoute);
    });
    const select = document.getElementById('pacShellMobileSelect');
    if (select && select.value !== activeRoute) select.value = activeRoute;
    updateBreadcrumb(item);
  }

  function switchSettingsPanel(panel) {
    if (!panel) return;
    window.setTimeout(() => {
      if (typeof window.switchSettingsPanel === 'function') window.switchSettingsPanel(panel);
    }, 0);
  }

  function activateItem(item, activateMainTab, showRail, options = {}) {
    if (!item) return;
    const route = routeFor(item);
    window.__pacActiveShellRoute = route;
    updateBrowserRoute(route, options);
    window.__pacActiveSettingsPanel = item.settingsPanel || '';
    if (typeof activateMainTab === 'function') activateMainTab(item.tab || DEFAULT_ROUTE);
    renderGroup(item.group.id, item.tab || DEFAULT_ROUTE);
    switchSettingsPanel(item.settingsPanel);
    focusTarget(item);
  }

  function bindNav(container, activateMainTab, showRail) {
    container?.querySelectorAll('.shell-nav-item').forEach((button) => {
      button.addEventListener('click', () => activateItem(findItemByRoute(button.dataset.shellRoute || ''), activateMainTab, showRail));
    });
    container?.querySelectorAll('.shell-nav-section-toggle').forEach((button) => {
      button.addEventListener('click', () => {
        const groupId = button.dataset.shellToggleGroup || '';
        const collapsed = window.PacShellNavState?.toggleSection(groupId) || false;
        applySectionState(groupId, collapsed);
      });
    });
    document.getElementById('pacShellNavCollapse')?.addEventListener('click', () => {
      const nav = document.getElementById('pacShellNav');
      setCollapsed(!nav?.classList.contains('collapsed'));
    });
  }

  function installCompactMenuFallback(activateMainTab, showRail) {
    const select = document.getElementById('pacShellMobileSelect');
    if (!select) return;
    select.innerHTML = flattenItems().map((item) => `<option value="${esc(routeFor(item))}">${esc(item.group.label)} / ${esc(item.label)}</option>`).join('');
    select.addEventListener('change', () => activateItem(findItemByRoute(select.value), activateMainTab, showRail));
  }

  function setupTabs(activateMainTab, showRail) {
    const container = document.getElementById('pacShellNav');
    renderNav(container);
    bindNav(container, activateMainTab, showRail);
    window.PacShellNavTools?.bind(container, {applySectionState, navGroups, selectorEscape});
    installCompactMenuFallback(activateMainTab, showRail);
    window.__pacTabGroups = {NAV_GROUPS: Object.fromEntries(navGroups().map((group) => [group.id, group.items || []])), TAB_TO_GROUP: buildTabToGroup(), renderGroup};
    setCollapsed(isCollapsed());
    const initialItem = findItemByRoute(savedRoute()) || findItemByRoute(DEFAULT_ROUTE);
    activateItem(initialItem, activateMainTab, showRail, {replace: true});
    if (!window.__pacShellPopstateBound) {
      window.__pacShellPopstateBound = true;
      window.addEventListener('popstate', () => {
        const route = routeFromLocation() || savedRoute() || DEFAULT_ROUTE;
        const item = findItemByRoute(route) || findItemByRoute(DEFAULT_ROUTE);
        if (!item) return;
        window.__pacShellApplyingPopstate = true;
        try { activateItem(item, activateMainTab, showRail); }
        finally { window.__pacShellApplyingPopstate = false; }
      });
    }
  }

  window.PacShellNav = {setupTabs, renderGroup, findItemByRoute, findItemByTab, activateItem, applyRouteClass, routeFromLocation, pathForRoute};
})();
