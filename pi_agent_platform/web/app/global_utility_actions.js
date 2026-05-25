(function () {
  const CREATE_TARGETS = [
    { label: 'Session', description: 'Start a new PAC task conversation.', route: 'sessions', target: 'openSessionModal' },
    { label: 'Endpoint', description: 'Add a machine that can run workloads.', route: 'endpoints', target: 'openEndpointModal' },
    { label: 'Provider', description: 'Register a model or service provider.', route: 'providers', target: 'openProviderModal' },
    { label: 'Model', description: 'Add a model exposed by a provider.', route: 'models', target: 'openModelModal' },
    { label: 'Profile', description: 'Create instructions and context policy.', route: 'profiles', target: 'openProfileModalBtn' },
    { label: 'Workspace', description: 'Create a bounded execution context.', route: 'workspaces', target: 'openWorkspaceModal' },
    { label: 'Credential', description: 'Store a variable or write-only secret.', route: 'credentials', target: 'openConfigVariableWizard' },
    { label: 'User / group', description: 'Open the guided identity wizard.', route: 'users-groups', menu: 'addPersonMenu' },
    { label: 'Proxy route', description: 'Expose an internal service through PAC.', route: 'proxy-routes', target: 'openProxyRouteModal' },
  ];

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function activeRoute() {
    return document.body?.dataset.shellRoute || window.__pacActiveShellRoute || 'dashboard';
  }

  function rankTargets() {
    const route = activeRoute();
    return [...CREATE_TARGETS].sort((a, b) => {
      const aScore = a.route === route ? 0 : 1;
      const bScore = b.route === route ? 0 : 1;
      return aScore - bScore || a.label.localeCompare(b.label);
    });
  }

  function renderCreateMenu() {
    const menu = document.getElementById('globalCreateMenu');
    if (!menu) return;
    menu.innerHTML = rankTargets().map((target) => `<button type="button" role="menuitem" data-create-target="${esc(target.target || '')}" data-create-menu="${esc(target.menu || '')}"><b>${esc(target.label)}</b><span>${esc(target.description)}</span></button>`).join('');
  }

  function closeCreateMenu() {
    const menu = document.getElementById('globalCreateMenu');
    const button = document.getElementById('globalCreateButton');
    if (menu) menu.hidden = true;
    button?.setAttribute('aria-expanded', 'false');
  }

  function toggleCreateMenu() {
    const menu = document.getElementById('globalCreateMenu');
    const button = document.getElementById('globalCreateButton');
    if (!menu) return;
    renderCreateMenu();
    const nextHidden = !menu.hidden ? true : false;
    menu.hidden = nextHidden;
    button?.setAttribute('aria-expanded', nextHidden ? 'false' : 'true');
  }

  function openCreateTarget(targetId, menuId) {
    closeCreateMenu();
    if (menuId && typeof window.openDirectoryCreateMenu === 'function') {
      window.openDirectoryCreateMenu(menuId);
      return;
    }
    if (targetId === 'openWorkspaceModal') {
      document.querySelector('[data-open-workspace-modal]')?.click();
      document.getElementById('openWorkspaceModal')?.click();
      return;
    }
    const target = document.getElementById(targetId || '');
    if (target) {
      target.click();
      return;
    }
    const fallback = {
      openSessionModal: window.openSessionModal,
      openProviderModal: window.openProviderModal,
      openModelModal: window.openModelModal,
      openEndpointModal: window.openEndpointModal,
    }[targetId || ''];
    if (typeof fallback === 'function') fallback();
  }

  function openHelp() {
    const help = window.PacPageHelp?.get?.() || {};
    const title = help.title || document.getElementById('pacPageTitle')?.textContent || 'PAC';
    const context = help.purpose || document.getElementById('pacShellContext')?.textContent || 'PAC controller workspace.';
    const tips = Array.isArray(help.tips) && help.tips.length ? help.tips : [
      'Use the Page Masthead for page actions.',
      'Use the Page Toolbar for search, filters, and list-level actions.',
      'Use the notification bell for events and the Update Center for version details.',
    ];
    const modal = document.createElement('div');
    modal.className = 'modal-backdrop global-help-modal-backdrop';
    modal.innerHTML = `<section class="modal-card global-help-modal" role="dialog" aria-modal="true" aria-labelledby="globalHelpTitle">
      <div class="section-heading"><div><p class="muted small-text">Context help</p><h2 id="globalHelpTitle">${esc(title)}</h2><p class="muted">${esc(context)}</p></div><button class="ghost-button" data-close-global-help type="button">Close</button></div>
      <div class="global-help-grid">
        <section><h3>How to use this page</h3><ul class="global-help-tips">${tips.map((tip) => `<li>${esc(tip)}</li>`).join('')}</ul></section>
        <section><h3>PAC shell pattern</h3><p class="muted small-text">The shared layout is Brand Banner, Utility Bar, Navigation Rail, Page Masthead, Page Toolbar, and Content Workspace.</p></section>
      </div>
    </section>`;
    document.body.appendChild(modal);
    modal.querySelector('[data-close-global-help]')?.addEventListener('click', () => modal.remove());
    modal.addEventListener('click', (event) => { if (event.target === modal) modal.remove(); });
  }

  function bind() {
    document.getElementById('globalCreateButton')?.addEventListener('click', toggleCreateMenu);
    document.getElementById('globalHelpButton')?.addEventListener('click', openHelp);
    document.getElementById('globalCreateMenu')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-create-target], [data-create-menu]');
      if (button) openCreateTarget(button.dataset.createTarget || '', button.dataset.createMenu || '');
    });
    document.addEventListener('click', (event) => {
      if (!event.target.closest('.global-create-wrap')) closeCreateMenu();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
