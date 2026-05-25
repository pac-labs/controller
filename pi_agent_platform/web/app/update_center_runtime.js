(function () {
  function text(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setState(key, state) {
    const card = document.querySelector(`[data-update-summary="${key}"]`);
    if (!card) return;
    card.dataset.state = state || 'neutral';
  }

  function refreshFromVersionInfo(versionInfo) {
    if (!versionInfo) return;
    const backend = versionInfo.version || 'unknown';
    const ui = versionInfo.ui_build || 'unknown';
    text('pacCurrentVersion', `v${backend}`);
    text('pacUiBuildVersion', ui);
    text('pacVersionHint', versionInfo.git_commit ? `commit ${String(versionInfo.git_commit).slice(0, 12)}` : 'Running controller build');
    text('pacUiBuildHint', versionInfo.ui_updated_at ? `updated ${versionInfo.ui_updated_at}` : 'Loaded shell bundle');
    setState('version', backend === 'unknown' ? 'warn' : 'ok');
    setState('ui', ui === 'unknown' ? 'warn' : 'ok');
  }

  function refreshArchives(data) {
    const archives = Array.isArray(data?.archives) ? data.archives : [];
    text('pacArchiveStatus', archives.length ? `${archives.length} backup${archives.length === 1 ? '' : 's'}` : 'none');
    text('pacArchiveHintSummary', archives.length ? `latest ${archives[0]?.stamp || 'available'}` : 'Created after app updates');
    setState('archives', archives.length ? 'ok' : 'neutral');
  }

  function refreshRelease(meta) {
    if (!meta) return;
    if (!meta.ok) {
      text('pacReleaseSummary', 'check failed');
      text('pacReleaseSummaryHint', meta.error || 'Release check failed');
      setState('release', 'warn');
      return;
    }
    if (meta.has_update) {
      text('pacReleaseSummary', `v${meta.latest_version || 'available'}`);
      text('pacReleaseSummaryHint', 'New release is ready to preview');
      setState('release', 'attention');
      return;
    }
    text('pacReleaseSummary', 'up to date');
    text('pacReleaseSummaryHint', meta.latest_version ? `latest v${meta.latest_version}` : 'No newer release found');
    setState('release', 'ok');
  }

  function bind() {
    refreshFromVersionInfo(window.currentVersionInfo);
  }

  window.PacUpdateCenter = {refreshFromVersionInfo, refreshArchives, refreshRelease};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
