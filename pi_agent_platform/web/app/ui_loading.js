// PAC v1.0.344: shared loader markup for loading, progress, and thinking states.
(function () {
  function escapeLoaderText(value) {
    if (typeof escapeHtml === 'function') return escapeHtml(value);
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }

  function iconHtml(size = 'small', label = 'Loading') {
    const safeLabel = escapeLoaderText(label || 'Loading');
    const sizeClass = size ? ` is-${String(size).replace(/[^a-z0-9_-]/gi, '')}` : '';
    return `<span class="pac-loader-icon${sizeClass}" role="img" aria-label="${safeLabel}"></span>`;
  }

  function lineHtml(label = 'Loading…', options = {}) {
    const size = options.size || 'small';
    const className = options.className || 'pac-loading-line';
    return `<span class="${className}">${iconHtml(size, label)}<span>${escapeLoaderText(label)}</span></span>`;
  }

  function setLoading(target, label = 'Loading…', options = {}) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    el.classList.add(options.block ? 'pac-loading-block' : 'pac-loading-placeholder');
    el.innerHTML = lineHtml(label, {size: options.size || 'small'});
  }

  function markStatus(target, label, loading = true) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    if (loading) {
      el.innerHTML = lineHtml(label, {size: 'tiny', className: 'pac-status-loading'});
      el.dataset.pacLoading = '1';
    } else {
      el.textContent = label || '';
      delete el.dataset.pacLoading;
    }
  }

  function enhanceStaticPlaceholders(root = document) {
    root.querySelectorAll('[data-pac-loading]').forEach((el) => {
      const label = el.getAttribute('data-pac-loading') || el.textContent || 'Loading…';
      setLoading(el, label, {size: el.getAttribute('data-pac-loading-size') || 'small'});
    });
  }

  window.PACLoading = { iconHtml, lineHtml, set: setLoading, status: markStatus, enhance: enhanceStaticPlaceholders };
  window.pacLoaderIconHtml = iconHtml;
  window.pacLoadingLineHtml = lineHtml;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enhanceStaticPlaceholders());
  else enhanceStaticPlaceholders();
})();
