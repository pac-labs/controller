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

  async function fetchServiceStatus() {
    return api('/v1/admin/service/status').catch((error) => ({ error: error.message || String(error) }));
  }

  async function fetchTlsStatus() {
    return api('/v1/tls/status').catch((error) => ({ error: error.message || String(error) }));
  }

  function renderServiceSurface(status = null) {
    const surface = ensureSurface('settings-service', 'configServiceSurface', 'config-service-surface');
    if (!surface) return;
    const hasError = !!status?.error;
    surface.innerHTML = `
      <section class="card wide config-route-card">
        <div class="section-heading compact-heading">
          <div>
            <p class="muted small-text">Install mode</p>
            <h2>Service operation mode</h2>
            <p class="muted">Keep the mode decision separate from user settings. Use user service for simple installs and host service for machine-wide startup or port 443.</p>
          </div>
          <button id="refreshConfigService" class="ghost-button" type="button">Refresh service</button>
        </div>
        <div class="config-route-grid">
          ${tile('Configured mode', hasError ? 'Unavailable' : (status?.configured_mode || '—'), hasError ? status.error : 'Saved service preference', hasError ? 'warn' : '')}
          ${tile('System service', status?.system_unit_exists ? 'Present' : 'Missing', status?.system_active || 'systemd unit state')}
          ${tile('User service', status?.user_unit_exists ? 'Present' : 'Missing', status?.user_active || 'user unit state')}
          ${tile('Port', status?.port || '—', status?.can_manage_host_now ? 'Host switch can be managed now' : 'Host switch may require sudo')}
        </div>
      </section>`;
  }

  function renderTrustSurface(status = null) {
    const surface = ensureSurface('settings-tls', 'configTrustSurface', 'config-trust-surface');
    if (!surface) return;
    const hasError = !!status?.error;
    surface.innerHTML = `
      <section class="card wide config-route-card">
        <div class="section-heading compact-heading">
          <div>
            <p class="muted small-text">Trust & certificates</p>
            <h2>Controller TLS trust</h2>
            <p class="muted">Local CA, mDNS certificate state, and Let's Encrypt DNS-01 configuration belong to platform trust configuration.</p>
          </div>
          <button id="refreshConfigTrust" class="ghost-button" type="button">Refresh trust</button>
        </div>
        <div class="config-route-grid">
          ${tile('Local CA', hasError ? 'Unavailable' : (status?.ca_exists ? 'Present' : 'Missing'), hasError ? status.error : (status?.ca_valid_until || 'CA validity not loaded'), status?.ca_exists ? 'ok' : 'warn')}
          ${tile('Server cert', status?.server_cert_exists ? 'Present' : 'Missing', status?.server_valid_until || 'Server certificate validity')}
          ${tile('mDNS', status?.mdns?.enabled === false ? 'Disabled' : 'Enabled', status?.mdns_url || status?.mdns_hostname || 'admin.pac.local')}
          ${tile('Port 443', status?.port_443?.configured ? 'Configured' : 'Not configured', 'Useful for host service deployments')}
        </div>
      </section>`;
  }

  async function renderConfigServicePage() {
    renderServiceSurface(null);
    const status = await fetchServiceStatus();
    renderServiceSurface(status);
    await window.loadServiceModeStatus?.();
  }

  async function renderConfigTrustPage() {
    renderTrustSurface(null);
    const status = await fetchTlsStatus();
    renderTrustSurface(status);
    await window.loadTlsStatus?.();
  }

  function bindServiceTrustPage() {
    document.addEventListener('click', (event) => {
      if (event.target.closest('#refreshConfigService')) window.renderConfigServicePage?.();
      if (event.target.closest('#refreshConfigTrust')) window.renderConfigTrustPage?.();
    });
  }

  bindServiceTrustPage();
  window.renderConfigServicePage = renderConfigServicePage;
  window.renderConfigTrustPage = renderConfigTrustPage;
})();
