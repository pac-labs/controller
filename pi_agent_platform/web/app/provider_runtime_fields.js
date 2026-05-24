// Provider runtime/device form collection and formatting helpers.
function providerRuntime(p) { return p?.runtime || {}; }
function providerDevice(p) { return providerRuntime(p).device || {}; }
function providerHost(p) { return providerRuntime(p).host || {}; }
function fmtProviderDevice(p) {
  const d = providerDevice(p);
  const bits = [d.category || 'unknown'];
  if (d.vendor) bits.push(d.vendor);
  if (d.model) bits.push(d.model);
  if (d.memory_gb || d.memoryGB) bits.push(`${d.memory_gb || d.memoryGB}GB`);
  if (d.shared) bits.push('shared');
  return bits.filter(Boolean).join(' · ');
}
function providerCapabilityPills(p) {
  const r = providerRuntime(p), d = r.device || {}, h = r.host || {};
  const accelerators = Array.isArray(r.accelerators) ? r.accelerators : [];
  const pills = [r.execution_type || r.executionType || 'unknown', d.category || 'unknown-device', h.kind || 'unknown-host', ...accelerators].filter(Boolean);
  return pills.map(x => `<span class="pill provider-capability-pill">${escapeHtml(String(x))}</span>`).join('');
}

function collectProviderRuntimeFields(existing={}) {
  const mem = Number(document.getElementById('providerDeviceMemory')?.value || 0);
  return {
    ...(existing || {}),
    execution_type: document.getElementById('providerExecutionType')?.value || 'unknown',
    provider_class: document.getElementById('providerClass')?.value.trim() || null,
    device: {
      ...((existing || {}).device || {}),
      category: document.getElementById('providerDeviceCategory')?.value || 'unknown',
      vendor: document.getElementById('providerDeviceVendor')?.value.trim() || null,
      model: document.getElementById('providerDeviceModel')?.value.trim() || null,
      memory_gb: mem || null,
      shared: !!document.getElementById('providerDeviceShared')?.checked,
    },
    host: {
      ...((existing || {}).host || {}),
      kind: document.getElementById('providerHostKind')?.value || 'unknown',
      os: document.getElementById('providerHostOs')?.value.trim() || null,
      arch: document.getElementById('providerHostArch')?.value.trim() || null,
    },
    accelerators: (document.getElementById('providerAccelerators')?.value || '').split(',').map(x=>x.trim()).filter(Boolean),
  };
}
function fillProviderRuntimeFields(runtime={}) {
  const d = runtime.device || {}, h = runtime.host || {};
  const set = (id, val) => { const el=document.getElementById(id); if (el) el.value = val ?? ''; };
  set('providerExecutionType', runtime.execution_type || runtime.executionType || 'unknown');
  set('providerClass', runtime.provider_class || runtime.providerClass || '');
  set('providerDeviceCategory', d.category || 'unknown');
  set('providerDeviceVendor', d.vendor || '');
  set('providerDeviceModel', d.model || '');
  set('providerDeviceMemory', d.memory_gb || d.memoryGB || '');
  const shared = document.getElementById('providerDeviceShared'); if (shared) shared.checked = !!d.shared;
  set('providerHostKind', h.kind || 'unknown');
  set('providerHostOs', h.os || '');
  set('providerHostArch', h.arch || '');
  set('providerAccelerators', Array.isArray(runtime.accelerators) ? runtime.accelerators.join(', ') : '');
}
