(function () {
  let proxyRoutesCache = [];

  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>\"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'}[char]));
  }

  function resultId(name) {
    return `proxyRouteTestResult_${String(name || '').replace(/[^a-z0-9_-]+/gi, '_')}`;
  }

  function normalizeAllowed(value) {
    return String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function routeCard(route) {
    const allowed = Array.isArray(route.allowed) && route.allowed.length ? route.allowed.join(', ') : 'All profiles';
    const description = route.description || 'Authenticated reverse proxy route.';
    const safeName = esc(route.name);
    return `<article class="provider-card model-overview-card config-proxy-card" data-proxy-route="${safeName}">
      <div class="provider-card-head">
        <div class="provider-title-block">
          <p class="muted small-text">Proxy route</p>
          <h3>${safeName}</h3>
        </div>
        <span class="status-pill ok">Configured</span>
      </div>
      <div class="provider-health-strip small-text"><span>Target <code>${esc(route.target)}</code></span></div>
      <p class="model-card-subline">${esc(description)}</p>
      <div class="config-proxy-access small-text muted">Allowed profiles: ${esc(allowed)}</div>
      <div class="button-row compact-actions">
        <button class="ghost-button mini-button" type="button" data-proxy-action="test" data-route-name="${safeName}">Test</button>
        <button class="ghost-button mini-button" type="button" data-proxy-action="edit" data-route-name="${safeName}">Edit</button>
        <button class="ghost-button mini-button danger-button" type="button" data-proxy-action="delete" data-route-name="${safeName}">Delete</button>
      </div>
      <div id="${resultId(route.name)}" class="inline-result compact-result" hidden></div>
    </article>`;
  }

  function renderProxyRouteSummary() {
    const summary = document.getElementById('proxyRoutesSummary');
    if (!summary) return;
    const openRoutes = proxyRoutesCache.filter((route) => !(route.allowed || []).length).length;
    summary.innerHTML = `<span><b>${proxyRoutesCache.length}</b> routes</span><span><b>${openRoutes}</b> open to all profiles</span>`;
  }

  function renderProxyRoutes() {
    const el = document.getElementById('proxyRoutesList');
    if (!el) return;
    renderProxyRouteSummary();
    if (!proxyRoutesCache.length) {
      el.innerHTML = '<div class="empty-state muted small-text">No proxy routes configured yet. Use the + button to expose a backend through PAC.</div>';
      return;
    }
    el.innerHTML = proxyRoutesCache.map(routeCard).join('');
  }

  async function loadProxyRoutes() {
    try {
      const routes = await window.api('/v1/proxy-routes');
      proxyRoutesCache = Array.isArray(routes) ? routes : [];
      renderProxyRoutes();
    } catch (error) {
      console.error('Failed to load proxy routes:', error);
      const el = document.getElementById('proxyRoutesList');
      if (el) el.innerHTML = `<div class="inline-result warn-text">Could not load proxy routes: ${esc(error.message || error)}</div>`;
    }
  }

  function fillProxyRouteForm(route) {
    const nameIn = document.getElementById('proxyRouteName');
    const targetIn = document.getElementById('proxyRouteTarget');
    const descIn = document.getElementById('proxyRouteDescription');
    const allowedIn = document.getElementById('proxyRouteAllowed');
    if (!nameIn || !targetIn || !descIn || !allowedIn) return false;
    nameIn.value = route?.name || '';
    nameIn.disabled = Boolean(route);
    targetIn.value = route?.target || '';
    descIn.value = route?.description || '';
    allowedIn.value = Array.isArray(route?.allowed) ? route.allowed.join(', ') : '';
    return true;
  }

  function openProxyRouteForm(route = null) {
    const modal = document.getElementById('proxyRouteModal');
    if (!modal || !fillProxyRouteForm(route)) return;
    const title = document.getElementById('proxyRouteModalTitle');
    if (title) title.textContent = route ? 'Edit proxy route' : 'Create proxy route';
    modal.hidden = false;
    document.getElementById('proxyRouteName')?.focus();
  }

  function cancelProxyRoute() {
    const modal = document.getElementById('proxyRouteModal');
    if (modal) modal.hidden = true;
  }

  async function testProxyRoute(name) {
    const resultEl = document.getElementById(resultId(name));
    if (!resultEl) return;
    resultEl.hidden = false;
    resultEl.className = 'inline-result compact-result';
    resultEl.textContent = 'Testing route…';
    try {
      const result = await window.api(`/v1/proxy-routes/${encodeURIComponent(name)}/test`, {method: 'POST'});
      if (result.reachable) {
        resultEl.className = 'inline-result compact-result ok-text';
        resultEl.textContent = `Reachable${result.status ? `, HTTP ${result.status}` : ''}`;
      } else {
        resultEl.className = 'inline-result compact-result warn-text';
        resultEl.textContent = `Unreachable: ${result.error || 'unknown error'}`;
      }
    } catch (error) {
      resultEl.className = 'inline-result compact-result warn-text';
      resultEl.textContent = `Error: ${error.message || error}`;
    }
    window.setTimeout(() => { resultEl.hidden = true; }, 5000);
  }

  async function deleteProxyRoute(name) {
    if (!window.confirm(`Delete proxy route ${name}?`)) return;
    try {
      await window.api(`/v1/proxy-routes/${encodeURIComponent(name)}`, {method: 'DELETE'});
      await loadProxyRoutes();
    } catch (error) {
      window.alert(`Delete failed: ${error.message || error}`);
    }
  }

  function editProxyRoute(name) {
    const route = proxyRoutesCache.find((item) => item.name === name);
    if (route) openProxyRouteForm(route);
  }

  function validateRoute({name, target}) {
    if (!name || !target) return 'Name and target are required.';
    try {
      const url = new URL(target);
      if (!['http:', 'https:'].includes(url.protocol)) return 'Target must start with http:// or https://.';
    } catch (_) {
      return 'Target URL is not valid.';
    }
    return '';
  }

  async function saveProxyRoute() {
    const name = document.getElementById('proxyRouteName')?.value?.trim() || '';
    const target = document.getElementById('proxyRouteTarget')?.value?.trim() || '';
    const description = document.getElementById('proxyRouteDescription')?.value?.trim() || '';
    const allowed = normalizeAllowed(document.getElementById('proxyRouteAllowed')?.value || '');
    const validationError = validateRoute({name, target});
    if (validationError) {
      window.showInline?.('proxyRouteFormResult', validationError, 'warn');
      return;
    }
    try {
      const isUpdate = proxyRoutesCache.some((route) => route.name === name);
      const path = isUpdate ? `/v1/proxy-routes/${encodeURIComponent(name)}` : '/v1/proxy-routes';
      const body = isUpdate ? {target, description, allowed} : {name, target, description, allowed};
      await window.api(path, {method: isUpdate ? 'PUT' : 'POST', body: JSON.stringify(body)});
      window.showInline?.('proxyRouteFormResult', isUpdate ? 'Route updated.' : 'Route created.', 'ok');
      cancelProxyRoute();
      await loadProxyRoutes();
    } catch (error) {
      window.showInline?.('proxyRouteFormResult', `Error: ${error.message || error}`, 'warn');
    }
  }

  function handleProxyRouteClick(event) {
    const action = event.target.closest('[data-proxy-action]');
    if (!action) return;
    const name = action.dataset.routeName || '';
    if (action.dataset.proxyAction === 'test') testProxyRoute(name);
    if (action.dataset.proxyAction === 'edit') editProxyRoute(name);
    if (action.dataset.proxyAction === 'delete') deleteProxyRoute(name);
  }

  function bindProxyRoutePage() {
    document.getElementById('openProxyRouteModal')?.addEventListener('click', () => openProxyRouteForm(null));
    document.getElementById('saveProxyRoute')?.addEventListener('click', saveProxyRoute);
    document.getElementById('cancelProxyRoute')?.addEventListener('click', cancelProxyRoute);
    document.getElementById('closeProxyRouteModal')?.addEventListener('click', cancelProxyRoute);
    document.getElementById('proxyRoutesList')?.addEventListener('click', handleProxyRouteClick);
    document.getElementById('proxyRouteModal')?.addEventListener('click', (event) => {
      if (event.target?.id === 'proxyRouteModal') cancelProxyRoute();
    });
  }

  document.addEventListener('DOMContentLoaded', bindProxyRoutePage);
  window.loadProxyRoutes = loadProxyRoutes;
  window.renderProxyRoutes = renderProxyRoutes;
  window.openProxyRouteForm = openProxyRouteForm;
  window.cancelProxyRoute = cancelProxyRoute;
  window.saveProxyRoute = saveProxyRoute;
  window.editProxyRoute = editProxyRoute;
  window.testProxyRoute = testProxyRoute;
  window.deleteProxyRoute = deleteProxyRoute;
})();
