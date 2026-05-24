// Provider and model catalog coordinator.
// Behavior lives in focused provider_* modules loaded before this file.
// This file intentionally remains small so legacy script globals stay stable during the UI refactor.

function refreshProviderAndModelSurfaces() {
  renderProviders();
  renderModels();
  renderModelActiveSessionsPanel();
  renderProfileUsagePanel();
  renderWorkspaceActivityPanel();
}
