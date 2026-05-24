(function () {
  const directoryState = { loadedAt: null, counts: null };

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function settingMain() {
    return document.querySelector('#settings-users .settings-main');
  }

  function ensureDirectorySurface() {
    const main = settingMain();
    if (!main) return null;
    let surface = document.getElementById('configDirectorySurface');
    if (!surface) {
      surface = document.createElement('section');
      surface.id = 'configDirectorySurface';
      surface.className = 'config-route-surface config-directory-surface';
      main.insertBefore(surface, main.firstElementChild || null);
    }
    return surface;
  }

  function countItems(value) {
    return Array.isArray(value) ? value.length : 0;
  }

  async function loadDirectoryCounts() {
    const [users, groups, serviceAccounts, endpoints, providers, certificates] = await Promise.all([
      api('/v1/directory/principals?kind=user').catch(() => []),
      api('/v1/directory/groups').catch(() => []),
      api('/v1/directory/principals?kind=service_account').catch(() => []),
      api('/v1/directory/principals?kind=endpoint').catch(() => []),
      api('/v1/directory/principals?kind=provider').catch(() => []),
      api('/v1/directory/principals?kind=certificate_identity').catch(() => []),
    ]);
    directoryState.loadedAt = new Date();
    directoryState.counts = {
      users: countItems(users),
      groups: countItems(groups),
      serviceAccounts: countItems(serviceAccounts),
      endpoints: countItems(endpoints),
      providers: countItems(providers),
      certificates: countItems(certificates),
    };
    return directoryState.counts;
  }

  function tile(label, value, copy) {
    return `<article class="config-route-tile"><b>${esc(value)}</b><span>${esc(label)}</span><small>${esc(copy)}</small></article>`;
  }

  function shortcut(label, copy, menuId) {
    return `<button class="config-shortcut-card" type="button" data-directory-menu="${esc(menuId)}">
      <b>${esc(label)}</b><span>${esc(copy)}</span>
    </button>`;
  }

  function renderDirectorySurface(counts, loading = false) {
    const surface = ensureDirectorySurface();
    if (!surface) return;
    const c = counts || directoryState.counts || {};
    surface.innerHTML = `
      <section class="card wide config-route-card">
        <div class="section-heading compact-heading">
          <div>
            <p class="muted small-text">Directory & access</p>
            <h2>Users, groups, and service identities</h2>
            <p class="muted">Manage who can use PAC resources. Groups are the access boundary for people, service accounts, endpoints, providers, and certificate identities.</p>
          </div>
          <button id="refreshConfigDirectory" class="ghost-button" type="button">${loading ? 'Refreshing…' : 'Refresh'}</button>
        </div>
        <div class="config-route-grid directory-count-grid">
          ${tile('People', c.users ?? '—', 'Interactive users')}
          ${tile('Groups', c.groups ?? '—', 'Access boundaries')}
          ${tile('Service accounts', c.serviceAccounts ?? '—', 'Automation identities')}
          ${tile('Endpoint identities', c.endpoints ?? '—', 'Workload targets')}
          ${tile('Provider identities', c.providers ?? '—', 'Model/provider grants')}
          ${tile('Certificate identities', c.certificates ?? '—', 'mTLS principals')}
        </div>
      </section>
      <section class="config-shortcut-grid" aria-label="Directory guided actions">
        ${shortcut('Create a person', 'Add an interactive user and then place them in groups.', 'addPersonMenu')}
        ${shortcut('Create a group', 'Define access once and reuse it across PAC resources.', 'addGroupMenu')}
        ${shortcut('Create a service account', 'Add a non-interactive automation identity.', 'addServiceAccountMenu')}
      </section>`;
  }

  function openDirectoryMenu(menuId) {
    const trigger = document.querySelector(`[data-open-add="${String(menuId).replace(/"/g, '')}"]`);
    if (trigger) trigger.click();
  }

  function bindDirectorySurface() {
    document.addEventListener('click', (event) => {
      const refresh = event.target.closest('#refreshConfigDirectory');
      if (refresh) {
        window.renderConfigDirectoryPage?.({ refresh: true });
        return;
      }
      const shortcutButton = event.target.closest('[data-directory-menu]');
      if (shortcutButton) openDirectoryMenu(shortcutButton.dataset.directoryMenu || '');
    });
  }

  async function renderConfigDirectoryPage(options = {}) {
    renderDirectorySurface(directoryState.counts, true);
    try {
      const counts = options.refresh || !directoryState.counts ? await loadDirectoryCounts() : directoryState.counts;
      renderDirectorySurface(counts, false);
      await window.loadAuthDirectory?.({ refresh: !!options.refresh });
    } catch (error) {
      const surface = ensureDirectorySurface();
      if (surface) {
        surface.innerHTML = `<section class="card wide config-route-card"><h2>Users, groups, and service identities</h2><p class="muted">Could not load directory summary: ${esc(error.message || String(error))}</p><button id="refreshConfigDirectory" class="ghost-button" type="button">Retry</button></section>`;
      }
    }
  }

  bindDirectorySurface();
  window.renderConfigDirectoryPage = renderConfigDirectoryPage;
})();
