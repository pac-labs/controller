(function () {
  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function ensureSurface(panelId, surfaceId, className) {
    const main = document.querySelector(`#${panelId} .settings-main`);
    if (!main) return null;
    let surface = document.getElementById(surfaceId);
    if (!surface) {
      surface = document.createElement('section');
      surface.id = surfaceId;
      surface.className = `config-route-surface ${className}`;
      main.insertBefore(surface, main.firstElementChild || null);
    }
    return surface;
  }

  function tile(label, value, copy, tone = '') {
    return `<article class="config-route-tile ${esc(tone)}"><b>${esc(value)}</b><span>${esc(label)}</span><small>${esc(copy)}</small></article>`;
  }

  function getHarnessConfig() {
    return window.config?.controller_harness || {};
  }

  function renderRuntimeSurface(status = null) {
    const surface = ensureSurface('settings-pi-dev', 'configRuntimeSurface', 'config-runtime-surface');
    if (!surface) return;
    const harness = getHarnessConfig();
    const runner = status?.runner || {};
    const session = status?.session || {};
    const diagnostics = status?.diagnostics || {};
    surface.innerHTML = `
      <section class="card wide config-route-card">
        <div class="section-heading compact-heading">
          <div>
            <p class="muted small-text">Controller runtime</p>
            <h2>Built-in PAC agent runtime</h2>
            <p class="muted">This page controls the controller-side PAC wrapper and pi.dev session used for local controller work. Endpoints still execute their own tools locally.</p>
          </div>
          <button id="refreshConfigRuntime" class="ghost-button" type="button">Refresh runtime</button>
        </div>
        <div class="config-route-grid">
          ${tile('Runtime state', status ? (status.ok ? 'Ready' : 'Needs setup') : 'Not checked', status?.message || 'Refresh to inspect wrapper and session health.', status?.ok ? 'ok' : 'warn')}
          ${tile('Runner', runner.name || harness.runner_id || 'local-PAC', 'Controller runner identity')}
          ${tile('Session', session.name || harness.session_name || 'PAC controller pi.dev', 'Managed controller session')}
          ${tile('Wrapper log', diagnostics.wrapper_log || '—', 'Latest local wrapper log path')}
        </div>
      </section>`;
  }

  async function renderConfigRuntimePage() {
    renderRuntimeSurface(null);
    let status = null;
    try {
      status = await window.loadControllerHarnessStatus?.();
    } catch (_) {}
    renderRuntimeSurface(status);
    window.renderControllerHarnessSettings?.(status);
  }

  function renderEndpointSurface() {
    const surface = ensureSurface('settings-endpoint', 'configEndpointSurface', 'config-endpoint-surface');
    if (!surface) return;
    const url = window.config?.server?.public_url || 'not configured';
    const mdnsEnabled = window.config?.mdns?.enabled !== false;
    surface.innerHTML = `
      <section class="card wide config-route-card">
        <div class="section-heading compact-heading">
          <div>
            <p class="muted small-text">Endpoint join path</p>
            <h2>Endpoint connection settings</h2>
            <p class="muted">Choose the controller URL endpoint binaries should use when they register and receive workload dispatch.</p>
          </div>
        </div>
        <div class="config-route-grid">
          ${tile('Public URL', url, 'Used by endpoint binaries and remote tools')}
          ${tile('mDNS discovery', mdnsEnabled ? 'Enabled' : 'Disabled', 'Local discovery hint for nearby endpoints', mdnsEnabled ? 'ok' : 'warn')}
        </div>
      </section>`;
    window.renderEndpointConnectionSettings?.();
  }

  function bindRuntimePage() {
    document.addEventListener('click', (event) => {
      if (event.target.closest('#refreshConfigRuntime')) window.renderConfigRuntimePage?.();
    });
  }

  bindRuntimePage();
  window.renderConfigRuntimePage = renderConfigRuntimePage;
  window.renderConfigEndpointPage = renderEndpointSurface;
})();
