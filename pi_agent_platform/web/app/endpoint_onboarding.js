// Endpoint onboarding panel and install-kit generation flow.

function switchEndpointPanel(panelId = 'endpointInventoryPanel') {
  document.querySelectorAll('#endpointSubnav .subtab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.endpointPanel === panelId);
  });
  document.querySelectorAll('#runners-tab .endpoint-subpanel').forEach(panel => {
    const active = panel.id === panelId;
    panel.hidden = !active;
    panel.classList.toggle('active', active);
  });
}
function wizardEndpointBody() {
  const chosenTools = selectedWizardToolNames();
  return {
    name: wizardRunnerName.value || 'remote-endpoint',
    labels: wizardRunnerLabels.value.split(',').map(x => x.trim()).filter(Boolean),
    endpoint: null,
    allow_host_execution: true,
    allow_container_execution: true,
    agent_enabled: false,
    metadata: {
      agent_tools: chosenTools,
      tool_packages: packageNamesForTools(chosenTools),
      default_workspace: document.getElementById('wizardRunnerDefaultWorkspace')?.value || null,
      desired_workspace_root: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
      onboarding_target: document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64',
      onboarding_mode: 'wizard',
    },
  };
}
async function saveWizardEndpointProfile() {
  const body = wizardEndpointBody();
  return api('/v1/endpoints', {method:'POST', body:JSON.stringify(body)});
}
function renderEndpointInstallKit(data) {
  const artifact = document.getElementById('endpointWizardArtifact');
  const linux = document.getElementById('endpointWizardLinux');
  const powershell = document.getElementById('endpointWizardPowerShell');
  const notes = document.getElementById('endpointWizardNotes');
  if (artifact) {
    artifact.textContent = data.artifact_missing
      ? `Build failed or no artifact was produced for ${data.target}.`
      : `Artifact: ${data.artifact?.name || '-'}\nVersion: ${data.build_result?.version || data.artifact?.version || '-'}\nCompiled URL: ${data.build_result?.compiled_server_url || data.public_url || '-'}\nCompiled endpoint: ${data.build_result?.compiled_endpoint_name || data.endpoint_name || '-'}\nRunner default: ${data.build_result?.compiled_runner_enabled === false ? 'disabled' : 'enabled'}\nWorkspace default: ${data.build_result?.compiled_workspace_root || '-'}\nDownload: ${data.download_url || '-'}\nToken: ${data.token_kind || '-'}${data.expires_at ? `\nExpires: ${data.expires_at}` : ''}`;
  }
  if (linux) linux.value = data.commands?.linux || '';
  if (powershell) powershell.value = data.commands?.powershell || '';
  if (notes) notes.textContent = Array.isArray(data.notes) ? data.notes.join('\n') : (data.message || '');
}

document.querySelectorAll('#endpointSubnav .subtab').forEach(btn => {
  btn.onclick = () => switchEndpointPanel(btn.dataset.endpointPanel || 'endpointInventoryPanel');
});
const switchToEndpointOnboardingBtn = document.getElementById('switchToEndpointOnboarding');
if (switchToEndpointOnboardingBtn) switchToEndpointOnboardingBtn.onclick = () => switchEndpointPanel('endpointOnboardingPanel');
const wizardRunnerTargetSelect = document.getElementById('wizardRunnerTarget');
if (wizardRunnerTargetSelect) wizardRunnerTargetSelect.onchange = () => {
  const workspace = document.getElementById('wizardRunnerWorkspace');
  const labels = document.getElementById('wizardRunnerLabels');
  const target = wizardRunnerTargetSelect.value || 'linux/amd64';
  if (workspace && !workspace.value.trim()) workspace.value = endpointDefaultWorkspaceForTarget(target);
  if (labels) {
    const wanted = target.includes('windows') ? ['windows', 'remote-execution'] : [target.split('/')[0], 'remote-execution'];
    const existing = labels.value.split(',').map(x => x.trim()).filter(Boolean);
    labels.value = Array.from(new Set([...existing, ...wanted])).join(', ');
  }
};
const saveWizardEndpointBtn = document.getElementById('saveWizardEndpoint');
if (saveWizardEndpointBtn) saveWizardEndpointBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    saveWizardEndpointBtn.disabled = true;
    if (status) status.textContent = 'Saving endpoint profile…';
    const endpoint = await saveWizardEndpointProfile();
    if (status) status.textContent = `Saved endpoint profile: ${endpoint.name || endpoint.id}`;
    await loadRunners();
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    saveWizardEndpointBtn.disabled = false;
  }
};
const buildWizardEndpointBinaryBtn = document.getElementById('buildWizardEndpointBinary');
if (buildWizardEndpointBinaryBtn) buildWizardEndpointBinaryBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    buildWizardEndpointBinaryBtn.disabled = true;
    if (status) status.textContent = 'Building pac-endpoint…';
    const target = document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64';
    const endpointName = document.getElementById('wizardRunnerName')?.value || 'remote-endpoint';
    const endpointSlug = endpointName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'endpoint';
    const result = await api('/v1/sources/build-binary', {method:'POST', body:JSON.stringify({
      path:'binaries/pac-endpoint',
      targets:[target],
      server_url:(config.server?.public_url || '').replace(/\/$/, ''),
      binary_name:`pac-endpoint-${endpointSlug}`,
      endpoint_name:endpointName,
      runner_enabled: !!document.getElementById('wizardRunnerEnabled')?.checked,
      workspace_path: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
    })});
    if (status) status.textContent = result.ok ? `Built preconfigured pac-endpoint for ${endpointName} (${target})` : `Build failed for ${target}`;
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    buildWizardEndpointBinaryBtn.disabled = false;
  }
};
const generateWizardEndpointKitBtn = document.getElementById('generateWizardEndpointKit');
if (generateWizardEndpointKitBtn) generateWizardEndpointKitBtn.onclick = async()=> {
  const status = document.getElementById('endpointWizardStatus');
  try {
    generateWizardEndpointKitBtn.disabled = true;
    if (status) status.textContent = 'Generating install kit…';
    await saveWizardEndpointProfile().catch(()=>null);
    const payload = {
      endpoint_name: document.getElementById('wizardRunnerName')?.value || 'remote-endpoint',
      target: document.getElementById('wizardRunnerTarget')?.value || 'linux/amd64',
      ttl_hours: Number(document.getElementById('wizardTokenTtl')?.value || 24) || 24,
      workspace_path: document.getElementById('wizardRunnerWorkspace')?.value?.trim() || null,
      runner_enabled: !!document.getElementById('wizardRunnerEnabled')?.checked,
    };
    const data = await api('/v1/endpoints/onboarding-kit', {method:'POST', body:JSON.stringify(payload)});
    renderEndpointInstallKit(data);
    if (status) status.textContent = data.artifact_missing ? 'Install kit generated. Build the binary first.' : 'Install kit generated.';
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
  } finally {
    generateWizardEndpointKitBtn.disabled = false;
  }
};

const wizardRunnerToolsInput = document.getElementById('wizardRunnerTools');
if (wizardRunnerToolsInput) wizardRunnerToolsInput.addEventListener('change', () => window.updateWizardToolPackagePreview?.());
