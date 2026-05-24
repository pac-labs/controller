// Provider card rendering and live preview helpers.
function providerStatus(p) {
  if (p.enabled === false) return 'disabled';
  return p.status || 'unknown';
}
function providerStatusClass(status) {
  if (status === 'connected') return 'ok';
  if (status === 'failed') return 'failed';
  if (status === 'disabled') return '';
  return 'attention';
}

function providerHealthSummary(name, provider) {
  const health = providerHealthCache.get(name) || {};
  const inspect = health.inspect || {};
  const models = Array.isArray(health.models) ? health.models : [];
  if (provider?.enabled === false) return {pill:'disabled', klass:'warn-pill', detail:'Provider disabled'};
  if (health.ok === true) {
    const bits = [`${models.length} live model${models.length === 1 ? '' : 's'}`];
    if (provider?.type === 'lmstudio' && inspect.ok) bits.push('LM Studio responding');
    return {pill:'healthy', klass:'ok-pill', detail:bits.join(' · ')};
  }
  if (health.ok === false) {
    const reason = health.error || health.response?.error || inspect.error || provider?.last_error || 'provider check failed';
    return {pill:'failed', klass:'danger-pill', detail:reason};
  }
  return {pill:'checking', klass:'ghost-pill', detail:'Checking provider health…'};
}

function renderProviders() {
  const el = document.getElementById('providers'); if (!el) return; el.innerHTML = '';
  const entries = Object.entries(config.providers || {});
  if (!entries.length) {
    el.innerHTML = '<div class="empty-events">No providers configured yet.</div>';
    const live = document.getElementById('providersLive');
    if (live) live.innerHTML = '<div class="muted small-text">No providers configured.</div>';
    return;
  }
  for (const [name,p] of entries) {
    const status = providerStatus(p);
    const r = providerRuntime(p);
    const h = providerHost(p);
    const health = providerHealthSummary(name, p);
    const card = document.createElement('div'); card.className='provider-card';
    card.innerHTML = `
      <div class="provider-card-head">
        <div class="provider-title-block"><h3>${escapeHtml(name)}</h3><span class="muted">${escapeHtml(p.type || 'provider')}</span></div>
        <span class="pill ${providerStatusClass(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="provider-health-strip"><span class="pill ${escapeHtml(health.klass)}">${escapeHtml(health.pill)}</span><span class="small-text">${escapeHtml(health.detail)}</span></div>
      <div class="provider-device-panel">
        <b>${escapeHtml(fmtProviderDevice(p))}</b>
        <small>${escapeHtml(r.execution_type || r.executionType || 'unknown')} inference · ${escapeHtml(h.kind || 'unknown host')}${h.os ? ` · ${escapeHtml(h.os)}` : ''}${h.arch ? ` · ${escapeHtml(h.arch)}` : ''}</small>
      </div>
      <div class="provider-meta-line"><span>${escapeHtml(p.base_url || 'no base URL')}</span></div>
      <div class="provider-pill-list">${providerCapabilityPills(p)}</div>
      ${p.last_error ? `<div class="failed-text small-text">${escapeHtml(p.last_error)}</div>` : ''}
      <div class="remote-models muted" id="providerModels_${name}">${p.enabled === false ? 'provider disabled' : 'checking endpoint…'}</div>`;
    const actions = document.createElement('div'); actions.className='provider-actions button-row';
    const label = document.createElement('label'); label.className='switch'; label.title='Connect/disconnect provider';
    const input = document.createElement('input'); input.type='checkbox'; input.checked = p.enabled !== false && status === 'connected';
    const slider = document.createElement('span'); slider.className='switch-slider';
    input.onchange = async(ev)=>{ ev.stopPropagation(); input.disabled=true; try { await toggleProvider(name, input.checked); } catch(e){ alert(e.message); input.checked=false; } finally { input.disabled=false; } };
    label.appendChild(input); label.appendChild(slider);
    const probe=document.createElement('button'); probe.textContent='Check health'; probe.className='ghost-button'; probe.onclick=(ev)=>{ ev.stopPropagation(); refreshProviderHealth(name, p).catch(e=>alert(e.message)); };
    if (p.type === 'lmstudio') {
      const inspect=document.createElement('button'); inspect.textContent='Inspect'; inspect.className='ghost-button'; inspect.onclick=(ev)=>{ ev.stopPropagation(); inspectLmStudioProvider(name).catch(e=>alert(e.message)); };
      const script=document.createElement('button'); script.textContent='Companion'; script.className='ghost-button'; script.onclick=(ev)=>{ ev.stopPropagation(); showLmStudioCompanionScript(name).catch(e=>alert(e.message)); };
      const load=document.createElement('button'); load.textContent='Load'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); lmStudioLoadModel(name).catch(e=>alert(e.message)); };
      actions.appendChild(probe); actions.appendChild(inspect); actions.appendChild(script); actions.appendChild(load);
    } else {
      actions.appendChild(probe);
    }
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.onclick=(ev)=>{ ev.stopPropagation(); openProviderModal(name); };
    const del=document.createElement('button'); del.textContent='Delete'; del.className='danger-button'; del.onclick=(ev)=>{ ev.stopPropagation(); deleteProvider(name).catch(e=>alert(e.message)); };
    actions.appendChild(label); actions.appendChild(edit); actions.appendChild(del); card.appendChild(actions); el.appendChild(card);
    if (p.enabled !== false) {
      refreshProviderModelPreview(name).catch(()=>{});
      if (!providerHealthCache.has(name)) refreshProviderHealth(name, p).catch(()=>{});
    }
  }
  renderProvidersLivePanel().catch(()=>{});
}
async function refreshProviderModelPreview(name) {
  const target = document.getElementById(`providerModels_${name}`);
  if (!target) return;
  const result = await fetchProviderModels(name);
  if (!result.ok) { target.textContent = `model list unavailable: ${result.error || result.response?.error || 'unknown error'}`; return; }
  const models = result.models || [];
  target.textContent = models.length ? `server models: ${models.slice(0,5).map(m => m.id || m.name).join(', ')}${models.length > 5 ? ` +${models.length-5} more` : ''}` : 'server returned no models';

}
