// Environment debug bundle generation for the global Downloads modal.
(function () {
  function esc(value) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[char]));
  }

  function tokenHeaders() {
    if (typeof window.tokenHeaders === 'function') return window.tokenHeaders();
    try {
      const token = localStorage.getItem('pac_auth_token') || localStorage.getItem('pacToken') || '';
      return token ? {Authorization: `Bearer ${token}`} : {};
    } catch (_) {
      return {};
    }
  }

  function bytesLabel(bytes) {
    const n = Number(bytes || 0);
    if (!n) return '0 bytes';
    if (n < 1024) return `${n} bytes`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  function statusText(message, busy=false) {
    const el = document.getElementById('environmentDebugBundleStatus');
    if (!el) return;
    el.textContent = message;
    el.dataset.busy = busy ? 'true' : '';
  }

  function renderBundles(bundles) {
    const list = document.getElementById('environmentDebugBundleList');
    if (!list) return;
    if (!Array.isArray(bundles) || !bundles.length) {
      list.innerHTML = '<span class="muted small-text">No generated environment debug bundles yet. Generate one first, then the download button appears here.</span>';
      return;
    }
    list.innerHTML = bundles.slice(0, 8).map((bundle, index) => {
      const label = index === 0 ? 'Download latest debug bundle' : 'Download debug bundle';
      const created = bundle.created_at ? new Date(bundle.created_at).toLocaleString() : '';
      return `<span class="download-artifact environment-debug-artifact"><button class="download-pill environment-debug-download" type="button" data-bundle-id="${esc(bundle.id || bundle.name)}" title="${esc(bundle.name)}"><span>${esc(label)}</span><small>${esc(bytesLabel(bundle.size))}</small></button><span class="muted small-text">${esc(created)}</span></span>`;
    }).join('');
  }

  async function loadEnvironmentDebugBundles() {
    const list = document.getElementById('environmentDebugBundleList');
    if (!list || typeof window.api !== 'function') return;
    try {
      const data = await window.api('/v1/debug-bundles');
      renderBundles(data.bundles || []);
    } catch (err) {
      list.textContent = `Could not load debug bundles: ${err.message}`;
    }
  }

  async function downloadBundle(bundleId) {
    if (!bundleId) return;
    statusText('Preparing debug bundle download...', true);
    try {
      const url = `/v1/debug-bundles/${encodeURIComponent(bundleId)}/download`;
      const response = await fetch(url, {headers: tokenHeaders()});
      if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = String(bundleId).endsWith('.zip') ? bundleId : `${bundleId}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 15000);
      statusText(`Debug bundle downloaded: ${bundleId}`, false);
    } catch (err) {
      statusText(`Debug bundle download failed: ${err.message}`, false);
      if (typeof window.paneError === 'function') window.paneError('Debug bundle download failed', err.message);
    }
  }

  async function generateEnvironmentDebugBundle() {
    const button = document.getElementById('generateEnvironmentDebugBundle');
    if (!button || typeof window.api !== 'function') return;
    button.disabled = true;
    statusText('Generating environment debug bundle. This may take a few seconds...', true);
    try {
      const result = await window.api('/v1/debug-bundles/environment', {method: 'POST'});
      const bundle = result.bundle || {};
      const suffix = result.generation_error ? ' It contains generation-error details, but is still downloadable.' : '';
      statusText(`Debug bundle ready: ${bundle.name || 'environment bundle'} (${bytesLabel(bundle.size)}).${suffix}`, false);
      renderBundles(bundle.name ? [bundle] : []);
      await loadEnvironmentDebugBundles();
      if (typeof window.emitUiEvent === 'function') {
        window.emitUiEvent('environment_debug_bundle_generated', `Environment debug bundle generated: ${bundle.name || 'ready'}`, result);
      }
    } catch (err) {
      statusText(`Debug bundle generation failed: ${err.message}`, false);
      if (typeof window.paneError === 'function') window.paneError('Debug bundle generation failed', err.message);
    } finally {
      button.disabled = false;
    }
  }

  function bind() {
    document.getElementById('generateEnvironmentDebugBundle')?.addEventListener('click', generateEnvironmentDebugBundle);
    document.getElementById('refreshEnvironmentDebugBundles')?.addEventListener('click', loadEnvironmentDebugBundles);
    document.getElementById('environmentDebugBundleList')?.addEventListener('click', (event) => {
      const button = event.target?.closest?.('.environment-debug-download');
      if (!button) return;
      downloadBundle(button.dataset.bundleId || '');
    });
  }

  window.loadEnvironmentDebugBundles = loadEnvironmentDebugBundles;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
