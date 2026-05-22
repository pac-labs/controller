// Extracted from /ui/app.js during the v1.0.283 final app.js cleanup pass.
// Kept as classic-script globals so existing inline handlers and boot wiring continue to work.

function eventCategory(type) {
  const t = String(type || '').toLowerCase();
  if (t.includes('source') && (t.includes('saved') || t.includes('initialized') || t.includes('built') || t.includes('completed'))) return 'completed';
  if (t.includes('reconnecting') || t.includes('updating') || t.includes('unavailable') || t.includes('attention')) return 'attention';
  if (t.includes('failed') || t.includes('stderr') || t.includes('rejected') || t.includes('error')) return 'failed';
  if (t.includes('approval') || t.includes('full_control')) return 'attention';
  if (t.includes('completed') || t === 'result' || t.includes('approved')) return 'completed';
  if (t.includes('started') || t.includes('running') || t.includes('tool') || t.includes('stdout') || t.includes('thinking') || t.includes('model')) return 'running';
  return 'running';
}

function prettyEventType(type) {
  return String(type || 'event').replaceAll('_',' ');
}

function formatEventTime(value) {
  if (!value) return '';
  try { return new Date(value).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'}); } catch { return ''; }
}

function normalizeEvent(type, payload) {
  if (payload && typeof payload === 'object' && payload.type) return payload;
  return {id:`local_${Date.now()}_${Math.random()}`, type, message:String(payload || ''), created_at:new Date().toISOString(), session_id:selectedSession?.id || null};
}

function isServerBackedEventId(eventId) {
  const value = String(eventId || '').trim();
  return !!value && !value.startsWith('local_');
}

function eventTone(type) {
  const cat = eventCategory(type);
  if (cat === 'completed') return 'ok';
  if (cat === 'failed') return 'danger';
  if (cat === 'attention') return 'warn';
  return 'info';
}

function openUpdateConfirmOverlay(meta) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  const title = document.getElementById('updateConfirmTitle');
  const message = document.getElementById('updateConfirmMessage');
  const body = document.getElementById('updateConfirmBody');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  const currentVersion = String(meta?.current_version || config?.version || config?.setup_status?.version || '-');
  const nextVersion = String(meta?.latest_version || '').trim();
  if (title) title.textContent = 'Apply PAC release';
  if (message) message.textContent = `Install ${nextVersion ? `v${nextVersion}` : 'the latest release'} and restart PAC?`;
  if (body) {
    const bullets = Array.isArray(meta?.compare_changes) ? meta.compare_changes.slice(0, 8) : [];
    body.innerHTML = `
      <div class="updates-detail-copy">
        <div>Current version: <b>v${escapeHtml(currentVersion)}</b></div>
        <div>Target version: <b>${escapeHtml(nextVersion ? `v${nextVersion}` : 'latest')}</b></div>
        ${bullets.length ? `<div style="margin-top:.65rem"><b>Included changes</b></div><ul>${bullets.map((change) => `<li>${escapeHtml(String(change))}</li>`).join('')}</ul>` : ''}
      </div>`;
  }
  if (proceed) {
    proceed.disabled = false;
    proceed.textContent = 'Apply and restart';
  }
  if (cancel) cancel.hidden = false;
  overlay.hidden = false;
  delete overlay.dataset.locked;
}

function closeUpdateConfirmOverlay(force = false) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  if (force || !overlay.dataset.locked) {
    overlay.hidden = true;
    delete overlay.dataset.locked;
  }
}

function setUpdateConfirmOverlayRestarting(version, seconds = 18) {
  const overlay = document.getElementById('updateConfirmOverlay');
  if (!overlay) return;
  const title = document.getElementById('updateConfirmTitle');
  const message = document.getElementById('updateConfirmMessage');
  const body = document.getElementById('updateConfirmBody');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  overlay.hidden = false;
  overlay.dataset.locked = 'true';
  if (title) title.textContent = 'Restarting PAC';
  if (message) message.textContent = `${version ? `v${version}` : 'The release'} is being applied.`;
  if (body) {
    body.innerHTML = `<div class="updates-detail-copy"><div>PAC is restarting.</div><div>Refresh when the UI returns.</div></div>`;
  }
  if (proceed) {
    proceed.disabled = true;
    proceed.textContent = 'Restarting…';
  }
  if (cancel) cancel.hidden = true;
}

function endpointDisplayName(endpointId) {
  if (!endpointId) return '';
  const found = (window.__pacEndpoints || []).find(e => e.id === endpointId);
  return found?.name || endpointId;
}

function renderGlobalEvent(event, prepend=false) {
  const list = document.getElementById('globalEvents');
  if (!list || !event) return;
  if (shouldSuppressGlobalEvent(event)) return;
  if (event.id && globalEventSeen.has(event.id)) return;
  if (event.id) globalEventSeen.add(event.id);
  const cat = eventCategory(event.type);
  if (globalEventFilter !== 'all' && globalEventFilter !== cat && !(globalEventFilter === 'attention' && cat === 'failed')) return;
  const empty = list.querySelector('.empty-events');
  if (empty) empty.remove();
  const card = document.createElement('div');
  card.className = `event-card ${cat}`;
  const details = event.data && typeof event.data === 'object' ? event.data : {};
  const metaParts = [event.session_id, event.task_id, details.build_id ? `build ${details.build_id}` : null].filter(Boolean);
  const meta = metaParts.join(' · ');
  const formatDetails = (value, prefix='') => {
    if (value == null) return [];
    if (typeof value === 'string') return value ? [value] : [];
    if (Array.isArray(value)) return value.flatMap((item, idx) => formatDetails(item, `${prefix}${idx}. `));
    if (typeof value === 'object') {
      const lines = [];
      Object.entries(value).forEach(([key, val]) => {
        const label = prefix ? `${prefix}${key}` : key;
        if (val == null || val === '') return;
        if (typeof val === 'object') lines.push(...formatDetails(val, `${label}.`));
        else lines.push(`${label}: ${String(val)}`);
      });
      return lines;
    }
    return [`${prefix}${String(value)}`];
  };
  const logChunks = [];
  if (Array.isArray(details.logs)) logChunks.push(details.logs.filter(Boolean).join('\n---\n'));
  if (details.stdout) logChunks.push(`stdout\n${details.stdout}`);
  if (details.stderr) logChunks.push(`stderr\n${details.stderr}`);
  if (details.error) logChunks.push(`error: ${details.error}`);
  if (details.output_tail) logChunks.push(details.output_tail);
  if (details.pi_container) logChunks.push(formatDetails(details.pi_container).join('\n'));
  if (details.details) logChunks.push(formatDetails(details.details).join('\n'));
  const logText = logChunks.filter(Boolean).join('\n---\n');
  card.innerHTML = `<div class="event-card-header"><span class="event-kind"><span class="event-dot"></span>${prettyEventType(event.type)}</span><span class="event-time">${formatEventTime(event.created_at)}</span></div><div class="event-message"></div>${meta ? `<div class="event-meta"></div>` : ''}${logText ? '<details class="event-details"><summary>Details</summary><pre></pre></details>' : ''}`;
  card.querySelector('.event-message').textContent = event.message || '';
  const metaEl = card.querySelector('.event-meta');
  if (metaEl) metaEl.textContent = meta;
  const pre = card.querySelector('.event-details pre');
  if (pre) pre.textContent = logText;
  if (list.firstChild) list.insertBefore(card, list.firstChild); else list.appendChild(card);
  while (list.children.length > 120) list.removeChild(list.lastChild);
  list.scrollTop = 0;
}

function shouldSuppressGlobalEvent(event) {
  const type = String(event?.type || '').toLowerCase();
  return type === 'runner_heartbeat' || type === 'endpoint_heartbeat' || type === 'provider_heartbeat';
}

async function loadGlobalEvents(reset=false) {
  const list = document.getElementById('globalEvents');
  if (!list) return;
  if (reset) { globalEventSeen = new Set(); list.innerHTML = '<div class="empty-events">No events yet.</div>'; }
  try {
    const events = await api('/v1/events/recent?limit=100');
    eventsFetchFailureCount = 0;
    eventsFetchLastNotice = null;
    const existing = list.querySelector('.events-fetch-error');
    if (existing) existing.remove();
    if (reset) list.innerHTML = '';
    [...events].reverse().forEach(e => renderGlobalEvent(e));
    if (!list.children.length) list.innerHTML = '<div class="empty-events">No events yet.</div>';
  } catch (e) {
    eventsFetchFailureCount += 1;
    const msg = String(e.message || e);
    const failed = eventsFetchFailureCount >= 10;
    const type = failed ? 'events_fetch_failed' : 'events_reconnecting';
    const message = failed ? 'Events could not reconnect after several attempts.' : 'PAC is reconnecting after an update or restart.';
    const signature = `${type}:${eventsFetchFailureCount}:${msg}`;
    if (eventsFetchLastNotice !== signature) {
      eventsFetchLastNotice = signature;
      const existing = list.querySelector('.events-fetch-error');
      if (existing) existing.remove();
      const cls = failed ? 'failed' : 'attention';
      const html = `<div class="event-card ${cls} events-fetch-error"><div class="event-card-header"><span class="event-kind"><span class="event-dot"></span>${prettyEventType(type)}</span><span class="event-time">${formatEventTime(new Date().toISOString())}</span></div><div class="event-message"></div><div class="event-meta"></div></div>`;
      list.insertAdjacentHTML('afterbegin', html);
      const card = list.querySelector('.events-fetch-error');
      if (card) {
        card.querySelector('.event-message').textContent = message;
        card.querySelector('.event-meta').textContent = `attempt ${eventsFetchFailureCount}/10 · ${msg}`;
      }
    }
  }
}

function setupEventsRail() {
  const rail = document.getElementById('eventsRail');
  const open = document.getElementById('openEventsPanel');
  const close = document.getElementById('closeEventsPanel');
  const pin = document.getElementById('pinEventsPanel');
  const showRail = async () => {
    if (!rail) return;
    rail.hidden = false;
    requestAnimationFrame(() => rail.classList.add('open'));
    if (typeof loadNotificationSummary === 'function') await loadNotificationSummary().catch(()=>{});
    await loadGlobalEvents(true).catch(()=>{});
  };
  const hideRail = () => {
    if (!rail) return;
    rail.classList.remove('open');
    window.setTimeout(() => { if (!rail.classList.contains('open')) rail.hidden = true; }, 190);
  };
  if (open && rail) open.onclick = async (ev) => { ev.stopPropagation(); await showRail(); };
  if (close && rail) close.onclick = (ev) => { ev.stopPropagation(); eventsRailPinned = false; rail.classList.remove('pinned'); if (pin) pin.setAttribute('aria-pressed', 'false'); hideRail(); };
  if (pin && rail) pin.onclick = (ev) => {
    ev.stopPropagation();
    eventsRailPinned = !eventsRailPinned;
    rail.classList.toggle('pinned', eventsRailPinned);
    pin.setAttribute('aria-pressed', eventsRailPinned ? 'true' : 'false');
    pin.title = eventsRailPinned ? 'Events pinned open' : 'Keep events open';
  };
  document.addEventListener('pointerdown', (ev) => {
    if (!rail || rail.hidden || eventsRailPinned) return;
    if (rail.contains(ev.target) || open?.contains(ev.target)) return;
    hideRail();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && rail && !rail.hidden && !eventsRailPinned) hideRail();
  });
  document.querySelectorAll('.event-chip').forEach(chip => {
    chip.onclick = async () => {
      document.querySelectorAll('.event-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      globalEventFilter = chip.dataset.eventFilter || 'all';
      await loadGlobalEvents(true);
    };
  });
  const clear = document.getElementById('clearEventPanel');
  if (clear) clear.onclick = () => { globalEventSeen = new Set(); const list=document.getElementById('globalEvents'); if(list) list.innerHTML='<div class="empty-events">Cleared visible events.</div>'; };
  if (!globalEventPoll) globalEventPoll = setInterval(() => { loadGlobalEvents(false).catch(()=>{}); if (typeof loadNotificationSummary === 'function') loadNotificationSummary().catch(()=>{}); }, 3500);
}

