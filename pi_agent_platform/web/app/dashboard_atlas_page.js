(function () {
  const ATLAS_ROUTE_HELP_KEY = 'pac-atlas-route-help-dismissed-v1';

  function isAtlasRoute() {
    return document.body?.dataset?.shellRoute === 'atlas' || document.body?.classList.contains('shell-route-atlas');
  }

  function dismissedHelp() {
    try { return localStorage.getItem(ATLAS_ROUTE_HELP_KEY) === '1'; } catch (_) { return false; }
  }

  function dismissHelp() {
    try { localStorage.setItem(ATLAS_ROUTE_HELP_KEY, '1'); } catch (_) {}
    document.getElementById('atlasRouteHelp')?.remove();
  }

  function atlasHelpHtml() {
    if (!isAtlasRoute() || dismissedHelp()) return '';
    return `<aside id="atlasRouteHelp" class="atlas-route-help" aria-label="Atlas controls help">
      <div><b>Atlas controls</b><span>Mouse wheel zooms, drag empty space pans. Use Fit after a refresh or when detail changes.</span></div>
      <button id="dismissAtlasRouteHelp" class="ghost-button mini-button" type="button">Hide</button>
    </aside>`;
  }

  function ensureRouteHelp(container) {
    if (!container || container.querySelector('#atlasRouteHelp')) return;
    const toolbar = container.querySelector('.atlas-toolbar');
    if (!toolbar) return;
    toolbar.insertAdjacentHTML('afterend', atlasHelpHtml());
    document.getElementById('dismissAtlasRouteHelp')?.addEventListener('click', dismissHelp);
  }

  function autoFitOnFirstAtlasRoute(container) {
    if (!isAtlasRoute() || !container) return;
    if (container.dataset.atlasRouteFitDone === '1') return;
    container.dataset.atlasRouteFitDone = '1';
    window.setTimeout(() => {
      if (typeof fitAtlasViewport === 'function') fitAtlasViewport(container);
    }, 80);
  }

  function afterRender(container) {
    ensureRouteHelp(container);
    autoFitOnFirstAtlasRoute(container);
  }

  window.PacDashboardAtlasPage = {afterRender, isAtlasRoute};
})();
