// Endpoint command modal and command queue flow.

function ensureEndpointCommandModal() {
  let modal = document.getElementById('endpointCommandModal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'endpointCommandModal';
  modal.className = 'modal-backdrop';
  modal.hidden = true;
  modal.innerHTML = `<section class="modal-card endpoint-command-modal" role="dialog" aria-modal="true" aria-labelledby="endpointCommandTitle">
    <div class="section-heading"><div><h2 id="endpointCommandTitle">Queue endpoint command</h2><p class="muted">Run a scoped command through the endpoint job queue. Progress opens in a live modal after the job is queued.</p></div><button id="closeEndpointCommandModal" class="ghost-button">Close</button></div>
    <div class="form-grid">
      <label>Endpoint <input id="endpointCommandTarget" readonly /></label>
      <label>Mode <select id="endpointCommandMode"><option value="host">Host shell</option><option value="container">Container</option><option value="pi_container">pi.dev container</option></select></label>
      <label>Container image <input id="endpointCommandImage" placeholder="optional for container mode" /></label>
      <label>Workspace path <input id="endpointCommandWorkspace" placeholder="optional endpoint workspace" /></label>
      <label class="wide-label">Command <textarea id="endpointCommandText" rows="8" spellcheck="false"></textarea></label>
    </div>
    <div class="button-row"><button id="queueEndpointCommand">Queue command</button><span id="endpointCommandStatus" class="muted"></span></div>
  </section>`;
  document.body.appendChild(modal);
  document.getElementById('closeEndpointCommandModal').onclick = closeEndpointCommandModal;
  modal.onclick = (ev) => { if (ev.target === modal) closeEndpointCommandModal(); };
  document.getElementById('queueEndpointCommand').onclick = queueEndpointCommandFromModal;
  return modal;
}
function openEndpointCommandModal(id) {
  commandEndpointId = id;
  const r = (window.__pacEndpoints || []).find(x => x.id === id);
  const modal = ensureEndpointCommandModal();
  if (document.getElementById('endpointCommandTarget')) endpointCommandTarget.value = r ? `${r.name} (${r.id})` : id;
  if (document.getElementById('endpointCommandMode')) endpointCommandMode.value = 'host';
  if (document.getElementById('endpointCommandImage')) endpointCommandImage.value = '';
  if (document.getElementById('endpointCommandWorkspace')) endpointCommandWorkspace.value = r?.metadata?.default_workspace || '';
  if (document.getElementById('endpointCommandText')) endpointCommandText.value = endpointDefaultCommand(r);
  if (document.getElementById('endpointCommandStatus')) endpointCommandStatus.textContent = '';
  modal.hidden = false;
}
function closeEndpointCommandModal() {
  const modal = document.getElementById('endpointCommandModal');
  if (modal) modal.hidden = true;
}

const closeEndpointBtn = document.getElementById('closeEndpointModal');
if (closeEndpointBtn) closeEndpointBtn.onclick = closeEndpointModal;
const endpointModal = document.getElementById('endpointModal');
if (endpointModal) endpointModal.onclick = (ev) => { if (ev.target === endpointModal) closeEndpointModal(); };
async function queueEndpointCommandFromModal(){
  const button = document.getElementById('queueEndpointCommand');
  const status = document.getElementById('endpointCommandStatus');
  try {
    if (button) button.disabled = true;
    if (status) PACLoading.status(status, 'Queueing…');
    const mode = document.getElementById('endpointCommandMode')?.value || 'host';
    const selected = (window.__pacEndpoints || []).find(x => x.id === commandEndpointId);
    const shell = endpointOsFamily(selected) === 'windows' ? 'powershell' : 'sh';
    const body = {prompt:'Endpoint command', command:document.getElementById('endpointCommandText')?.value || endpointDefaultCommand(selected), execution_mode:mode, container_image:document.getElementById('endpointCommandImage')?.value || null, workspace_path:document.getElementById('endpointCommandWorkspace')?.value || null, metadata:{source_endpoint_id:'controller', shell}};
    const job = await api(`/v1/endpoints/${encodeURIComponent(commandEndpointId)}/commands`, {method:'POST', body:JSON.stringify(body)});
    if (status) PACLoading.status(status, 'Opening progress…');
    closeEndpointCommandModal();
    if (typeof watchEndpointJob === 'function') watchEndpointJob(job, {title:'Endpoint command progress', subtitle:selected?.name || commandEndpointId});
    await loadGlobalEvents(true).catch(()=>{});
  } catch(e) { if (status) status.textContent = `Failed: ${e.message}`; } finally { if (button) button.disabled = false; }
}
const closeEndpointCommandBtn = document.getElementById('closeEndpointCommandModal');
if (closeEndpointCommandBtn) closeEndpointCommandBtn.onclick = closeEndpointCommandModal;
const endpointCommandModal = document.getElementById('endpointCommandModal');
if (endpointCommandModal) endpointCommandModal.onclick = (ev) => { if (ev.target === endpointCommandModal) closeEndpointCommandModal(); };
const queueEndpointCommandBtn = document.getElementById('queueEndpointCommand');
if (queueEndpointCommandBtn) queueEndpointCommandBtn.onclick = queueEndpointCommandFromModal;
