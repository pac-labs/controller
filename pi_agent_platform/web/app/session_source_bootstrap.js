// Session source-context bootstrap helpers

function applySessionBootstrapMode() {
  const mode = document.getElementById('sessionBootstrapMode')?.value || 'profile';
  const sourceLabel = document.getElementById('sessionSourceContext')?.closest('label');
  if (sourceLabel) sourceLabel.style.display = mode === 'source-context' ? '' : '';
}

async function applySessionSourceContext(name) {
  if (!name) return;
  const resolved = await api(`/v1/source-contexts/resolve?name=${encodeURIComponent(name)}&include_secrets=false`);
  const ctx = resolved?.context || {};
  if (ctx.profile && document.getElementById('agentProfile')) agentProfile.value = ctx.profile;
  if (ctx.workspace_profile && document.getElementById('workspaceProfile')) workspaceProfile.value = ctx.workspace_profile;
  if (ctx.preferred_endpoint && document.getElementById('sessionEndpoint')) sessionEndpoint.value = ctx.preferred_endpoint;
  if ((ctx.workspace_profile || ctx.path_prefix) && document.getElementById('sessionWorkspaceType')) sessionWorkspaceType.value = ctx.workspace_profile ? 'profile' : 'local';
  if (ctx.path_prefix && document.getElementById('sessionWorkspacePath') && !sessionWorkspacePath.value) sessionWorkspacePath.value = ctx.path_prefix;
  const status = document.getElementById('sessionCreateStatus');
  if (status) status.textContent = `Loaded source context ${name}.`;
}

