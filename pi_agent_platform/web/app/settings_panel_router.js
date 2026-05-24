(function () {
  const PANEL_LOADERS = {
    credentials: () => window.renderConfigCredentials?.(),
    approvals: () => window.loadApprovals?.(),
    users: () => window.renderConfigDirectoryPage?.(),
    'pi-dev': () => window.renderConfigRuntimePage?.(),
    endpoint: () => window.renderConfigEndpointPage?.(),
    service: () => window.renderConfigServicePage?.(),
    tls: () => window.renderConfigTrustPage?.(),
    'proxy-routes': () => window.loadProxyRoutes?.(),
    config: () => {
      const editor = document.getElementById('configEditor');
      if (editor) editor.value = JSON.stringify(window.config || {}, null, 2);
      window.renderSystemInfo?.();
    },
  };

  function panelIdFor(name) {
    return name === 'proxy-routes' ? 'proxy-routes-panel' : `settings-${name}`;
  }

  function hidePanels() {
    document.querySelectorAll('.settings-panel').forEach((panel) => {
      panel.style.display = 'none';
      panel.hidden = true;
      panel.classList.remove('active');
    });
  }

  function activateButton(name) {
    document.querySelectorAll('.settings-sub-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.settingsPanel === name);
    });
  }

  function showPanel(name) {
    const panel = document.getElementById(panelIdFor(name));
    if (!panel) return false;
    panel.hidden = false;
    panel.style.display = 'block';
    panel.classList.add('active');
    return true;
  }

  function loadPanel(name) {
    const loader = PANEL_LOADERS[name];
    if (!loader) return;
    try {
      const result = loader();
      if (result && typeof result.catch === 'function') result.catch(() => {});
    } catch (_) {}
  }

  function switchSettingsPanel(name = 'updates') {
    hidePanels();
    activateButton(name);
    if (!showPanel(name)) showPanel('updates');
    loadPanel(name);
    window.renderConfigPageShell?.(name);
  }

  window.switchSettingsPanel = switchSettingsPanel;
})();
