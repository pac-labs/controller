// Endpoint target and default command helpers shared by endpoint onboarding and command flows.

function endpointOsFamily(endpoint) {
  const values = [endpoint?.metadata?.os_family, endpoint?.metadata?.os, endpoint?.metadata?.onboarding_target, ...(endpoint?.labels || [])].map(v => String(v || '').toLowerCase());
  if (values.some(v => v.includes('windows') || v === 'win32' || v === 'win64')) return 'windows';
  if (values.some(v => v.includes('darwin') || v.includes('macos') || v === 'mac')) return 'darwin';
  if (values.some(v => v.includes('linux'))) return 'linux';
  return 'unknown';
}
function endpointDefaultCommand(endpoint) {
  return endpointOsFamily(endpoint) === 'windows' ? 'Get-Location; Get-ChildItem -Force | Select-Object -First 20' : 'pwd && ls -la';
}
function endpointDefaultWorkspaceForTarget(target) {
  return String(target || '').toLowerCase().includes('windows') ? 'C:\\PAC\\workspace' : '$HOME/pac-workspace';
}
