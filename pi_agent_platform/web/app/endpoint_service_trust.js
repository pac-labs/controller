// Service mode, TLS/trust, endpoint connection, and local integration helpers.

function renderZedConfigExamples() {
  const publicUrl = (config.server?.public_url || 'https://localhost').replace(/\/$/, '');
  const local = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'C:/tools/pac.exe',
        args: ['--base-url', publicUrl, '--insecure'],
        env: {}
      }
    }
  };
  const remote = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'npx',
        args: ['-y', 'mcp-remote', `${publicUrl}/mcp`, '--insecure'],
        env: {}
      }
    }
  };
  const localEl = document.getElementById('zedMcpConfigLocal');
  const remoteEl = document.getElementById('zedMcpConfigRemote');
  if (localEl) localEl.textContent = JSON.stringify(local, null, 2);
  if (remoteEl) remoteEl.textContent = JSON.stringify(remote, null, 2);
}


async function loadServiceModeStatus() {
  const info = document.getElementById('serviceModeInfo');
  if (!info) return;
  try {
    const svc = await api('/v1/admin/service/status');
    const rows = {
      'Configured mode': svc.configured_mode || '-',
      'System service': svc.system_unit_exists ? `present / ${svc.system_active || '-'}` : `missing / ${svc.system_active || '-'}`,
      'User service': svc.user_unit_exists ? `present / ${svc.user_active || '-'}` : `missing / ${svc.user_active || '-'}`,
      'Port': svc.port || '-',
      'Host switch allowed now': svc.can_manage_host_now ? 'yes' : 'needs sudo/manual command',
      'System unit': svc.system_unit || '-',
      'User unit': svc.user_unit || '-',
    };
    info.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('');
    const result = document.getElementById('serviceModeResult');
    if (result && svc.manual_host_command) result.textContent = `Host service manual command if sudo is needed:\n${svc.manual_host_command}`;
  } catch (e) {
    info.innerHTML = `<div><span>Status</span><code>Could not load service status: ${escapeHtml(e.message)}</code></div>`;
  }
}

async function setServiceMode(mode) {
  const result = document.getElementById('serviceModeResult');
  if (mode === 'host' && !confirm('Switch PAC to host/system service? This requires sudo/root or passwordless sudo, uses port 443, and will restart PAC.')) return;
  if (mode === 'user' && !confirm('Switch PAC to user service? This will move PAC back to the user systemd service, use 8443, and restart PAC.')) return;
  if (result) result.textContent = `Switching PAC to ${mode} service mode…`;
  const payload = await api('/v1/admin/service/mode', {method:'POST', body:JSON.stringify({mode})});
  if (result) result.textContent = payload?.message || payload?.status || `Service mode ${mode} requested. Details are in Events.`; emitUiEvent('service_mode_changed', result ? result.textContent : 'Service mode changed', payload);
  if (payload.restart_scheduled) scheduleHiddenReloadAfterRestart(18);
  await loadServiceModeStatus();
  await loadControllerHarnessStatus();
}

async function loadTlsStatus() {
  const el = document.getElementById('tlsInfo');
  if (!el) return;
  try {
    const tls = await api('/v1/tls/status');
    const rows = {
      'CA': tls.ca_exists ? 'present' : 'missing',
      'CA valid until': tls.ca_valid_until || '-',
      'Server cert': tls.server_cert_exists ? 'present' : 'missing',
      'Server valid until': tls.server_valid_until || '-',
      'mDNS name': tls.mdns_hostname || 'admin.pac.local',
      'mDNS URL': tls.mdns_url || '-',
      'mDNS enabled': tls.mdns?.enabled === false ? 'no' : 'yes',
      'mDNS state': tls.mdns_status?.state || '-',
      'mDNS message': tls.mdns_status?.message || '-',
      'Port 443': tls.port_443?.configured ? 'configured' : 'not configured',
      'CA file': tls.ca_cert_file || '-',
      'Server cert file': tls.server_cert_file || '-',
      'Details': tls.details_file || '-',
    };
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(v)}</code></div>`).join('');
  } catch (e) {
    el.innerHTML = `<div><span>Status</span><code>Could not load TLS status: ${escapeHtml(e.message)}</code></div>`;
  }
}

function renderSystemInfo() {
  const pacp = config.pacp || {};
  const rows = {
    'Backend version': currentVersionInfo?.version || config.version || '-',
    'UI build': currentVersionInfo?.ui_build || '-',
    'UI updated': currentVersionInfo?.ui_updated_at || '-',
    'PAC home': pacp.home || '-',
    'Config': pacp.config_path || '-',
    'Single-instance lock': pacp.single_instance_lock || '-',
    'Public URL': config.server?.public_url || '-',
    'Workspace root': config.server?.default_workspace_root || '-',
  };
  for (const id of ['systemInfo','pacpInfo']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${v}</code></div>`).join('');
  }
}


function renderEndpointConnectionSettings() {
  const urlInput = document.getElementById('endpointPublicUrl');
  const mdnsInput = document.getElementById('endpointMdnsEnabled');
  if (urlInput) urlInput.value = config.server?.public_url || '';
  if (mdnsInput) mdnsInput.checked = config.mdns?.enabled !== false;

  // Load letsencrypt status
  api('/v1/server/letsencrypt/status').then(data => {
    const emailEl = document.getElementById('leEmail');
    if (emailEl) emailEl.value = data.email || '';
    const domainEl = document.getElementById('leDomain');
    if (domainEl && !domainEl.value) domainEl.value = data.domain || 'pac.thebigtree.life';
    const zoneEl = document.getElementById('leZoneId');
    if (zoneEl && !zoneEl.value) zoneEl.value = '';
    const statusEl = document.getElementById('leStatus');
    if (statusEl) {
      if (data.cert_exists) {
        const info = data.cert_info || {};
        statusEl.textContent = `Certificate present for ${data.domain || 'unknown'}. Valid until ${info.not_after || '?'}`;
      } else if (data.enabled) {
        statusEl.textContent = 'LE enabled but no cert file found.';
      } else {
        statusEl.textContent = 'No LE certificate installed. Enter your Cloudflare details and click Obtain.';
      }
    }
    const cfTestEl = document.getElementById('leCloudflareTest');
    if (cfTestEl) {
      cfTestEl.textContent = data.cloudflare_configured ? 'Cloudflare: configured' : 'Cloudflare: not configured yet';
    }
  }).catch(() => {});
}

async function saveEndpointConnectionSettings() {
  const result = document.getElementById('endpointConnectionResult');
  let publicUrl = (document.getElementById('endpointPublicUrl')?.value || '').trim();
  const mdnsEnabled = !!document.getElementById('endpointMdnsEnabled')?.checked;
  if (!publicUrl) return paneError('Enter the controller URL endpoints should use');
  if (!/^https?:\/\//i.test(publicUrl)) publicUrl = `https://${publicUrl}`;
  const payload = await api('/v1/server/connection', {method:'POST', body:JSON.stringify({public_url: publicUrl, mdns_enabled: mdnsEnabled})});
  if (result) result.textContent = `${payload.message || 'Endpoint connection settings saved.'}\nSaved URL: ${payload.public_url || publicUrl}`;
  await loadConfig();
  await loadGlobalEvents(true).catch(()=>{});
}

async function loadWorkspaceCatalogs() {
  const [templateData, workspaceData, contextData, groupsData, storageData] = await Promise.all([
    api('/v1/workspace-templates').catch(() => ({templates: []})),
    api('/v1/my-workspaces').catch(() => ({items: []})),
    api('/v1/agent-contexts').catch(() => ({items: []})),
    api('/v1/directory/groups').catch(() => []),
    api('/v1/shared-storages').catch(() => ({items: []})),
  ]);
  workspaceTemplates = Array.isArray(templateData?.templates) ? templateData.templates : [];
  personalWorkspaces = Array.isArray(workspaceData?.items) ? workspaceData.items : [];
  agentContexts = Array.isArray(contextData?.items) ? contextData.items : [];
  sharedStorages = Array.isArray(storageData?.items) ? storageData.items : [];
  window.__pacGroups = Array.isArray(groupsData) ? groupsData : [];
  if (selectedIdeWorkspaceId && !personalWorkspaces.some((item) => item.id === selectedIdeWorkspaceId)) selectedIdeWorkspaceId = '';
  if (!selectedIdeWorkspaceId && personalWorkspaces.length) {
    selectedIdeWorkspaceId = (personalWorkspaces.find((item) => item.pinned) || personalWorkspaces[0]).id;
  }
  if (selectedIdeContextId && !agentContexts.some((item) => item.id === selectedIdeContextId)) selectedIdeContextId = '';
  if (!selectedIdeContextId && agentContexts.length) {
    const defaultContexts = agentContexts.filter((item) => !isProtectedAgentContext(item));
    selectedIdeContextId = ((defaultContexts.find((item) => item.pinned) || defaultContexts[0]) || (agentContexts.find((item) => item.pinned) || agentContexts[0])).id;
  }
}



// --- Let's Encrypt DNS-01 handlers ---
if (document.getElementById('leEnableBtn')) {
    document.getElementById('leEnableBtn').onclick = async () => {
        const email = document.getElementById('leEmail')?.value?.trim();
        const domain = document.getElementById('leDomain')?.value?.trim();
        const apiToken = document.getElementById('leApiToken')?.value?.trim();
        const zoneId = document.getElementById('leZoneId')?.value?.trim();
        const staging = !!document.getElementById('leStaging')?.checked;
        const statusEl = document.getElementById('leStatus');

        if (!email || !domain || !apiToken || !zoneId) {
            statusEl.textContent = 'All fields are required'; return;
        }

        statusEl.textContent = 'Requesting certificate via Cloudflare DNS-01... (this can take 2-3 minutes)';

        try {
            const result = await api('/v1/server/letsencrypt/enable', {
                method: 'POST',
                body: JSON.stringify({email, domain, cloudflare_api_token: apiToken, cloudflare_zone_id: zoneId, staging, auto_enable: true})
            });
            statusEl.textContent = result.ok ? `Success! Certificate installed for ${domain}` : `Failed: ${result.error}`;
            if (result.ok && result.cert_file) {
                await api('/v1/server/connection', {method:'POST', body: JSON.stringify({public_url: `https://${domain}`})}).catch(()=>{});
            }
        } catch(e) {
            statusEl.textContent = 'Error: ' + e.message;
        }
    };
}

if (document.getElementById('leDisableBtn')) {
    document.getElementById('leDisableBtn').onclick = async () => {
        const result = await api('/v1/server/letsencrypt/disable', {method:'POST'});
        document.getElementById('leStatus').textContent = result.message || 'Done';
    };
}

if (document.getElementById('leTestCfBtn')) {
    document.getElementById('leTestCfBtn').onclick = async () => {
        const apiToken = document.getElementById('leApiToken')?.value?.trim();
        const zoneId = document.getElementById('leZoneId')?.value?.trim();
        if (!apiToken || !zoneId) {
            document.getElementById('leCloudflareTest').textContent = 'Enter API token and Zone ID first'; return;
        }
        document.getElementById('leCloudflareTest').textContent = 'Testing...';
        try {
            const result = await api(`/v1/server/letsencrypt/test-cloudflare?api_token=${encodeURIComponent(apiToken)}&zone_id=${encodeURIComponent(zoneId)}`, {method:'POST'});
            document.getElementById('leCloudflareTest').textContent = result.ok ? `✓ Cloudflare OK — zone: ${result.zone}` : `✗ Cloudflare error: ${result.error}`;
        } catch(e) {
            document.getElementById('leCloudflareTest').textContent = 'Error: ' + e.message;
        }
    };
}

