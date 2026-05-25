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

function endpointDisplayName(endpointId) {
  if (!endpointId) return '';
  const found = (window.__pacEndpoints || []).find(e => e.id === endpointId);
  return found?.name || endpointId;
}


let eventsHubSeen = new Set();
let eventsHubFilter = 'all';
let eventsHubPoll = null;
let eventsHubLastEvents = [];
let eventsHubSearch = '';
let eventsHubSource = 'all';
let eventsHubFacetKind = '';
let eventsHubFacetLabel = '';

function isEmergencyEvent(event) {
  const type = String(event?.type || '').toLowerCase();
  const severity = String(event?.severity || event?.data?.severity || event?.data?.level || '').toLowerCase();
  const category = eventCategory(type);
  return category === 'failed'
    || category === 'attention'
    || ['critical', 'error', 'warning', 'warn', 'danger', 'alert'].includes(severity)
    || type.includes('failed')
    || type.includes('error')
    || type.includes('rejected')
    || type.includes('unavailable')
    || type.includes('approval')
    || type.includes('security')
    || type.includes('denied');
}

function eventMatchesFilter(event, filter, emergencyOnly=false) {
  if (shouldSuppressGlobalEvent(event)) return false;
  if (emergencyOnly && !isEmergencyEvent(event)) return false;
  const cat = eventCategory(event?.type);
  const query = String(eventsHubSearch || '').toLowerCase().trim();
  const source = String(eventsHubSource || 'all');
  if (query && !`${event?.type || ''} ${event?.message || ''} ${event?.session_id || ''} ${event?.task_id || ''}`.toLowerCase().includes(query)) return false;
  if (source !== 'all') {
    const sourceKind = String(event?.source?.kind || (event?.session_id && event.session_id !== 'system' ? 'session' : 'system'));
    if (source === 'system' && sourceKind !== 'system') return false;
    if (source === 'sessions' && sourceKind !== 'session') return false;
    if (source === 'endpoints' && sourceKind !== 'endpoint') return false;
    if (source === 'workspaces' && sourceKind !== 'workspace') return false;
    if (source === 'components' && !String(event?.source?.component || '').trim()) return false;
  }
  if (!filter || filter === 'all') return true;
  if (filter === 'emergency') return isEmergencyEvent(event);
  if (filter === 'failed') return cat === 'failed';
  if (filter === 'attention') return cat === 'attention' || cat === 'failed';
  return filter === cat;
}

function eventMetaText(event) {
  const details = event.data && typeof event.data === 'object' ? event.data : {};
  const source = event.source || {};
  const sourceLabel = source.label ? `${source.kind || 'source'}: ${source.label}` : null;
  return [sourceLabel, event.session_id, event.task_id, details.build_id ? `build ${details.build_id}` : null].filter(Boolean).join(' · ');
}

function eventDetailText(event) {
  const details = event.data && typeof event.data === 'object' ? event.data : {};
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
  const chunks = [];
  if (Array.isArray(details.logs)) chunks.push(details.logs.filter(Boolean).join('\n---\n'));
  if (details.stdout) chunks.push(`stdout\n${details.stdout}`);
  if (details.stderr) chunks.push(`stderr\n${details.stderr}`);
  if (details.error) chunks.push(`error: ${details.error}`);
  if (details.output_tail) chunks.push(details.output_tail);
  if (details.pi_container) chunks.push(formatDetails(details.pi_container).join('\n'));
  if (details.details) chunks.push(formatDetails(details.details).join('\n'));
  return chunks.filter(Boolean).join('\n---\n');
}

async function acknowledgeEvent(eventId) {
  if (!isServerBackedEventId(eventId)) return false;
  await api('/v1/events/acknowledge', {method:'POST', body:JSON.stringify({event_ids:[eventId]})});
  eventsHubLastEvents = eventsHubLastEvents.map((event) => event.id === eventId ? {...event, ui_state:{...(event.ui_state || {}), read:true, acknowledged:true}} : event);
  await loadGlobalEvents(true).catch(()=>{});
  if (document.body?.dataset.shellRoute === 'events') renderEventsHub(eventsHubLastEvents, true);
  if (typeof loadNotificationSummary === 'function') await loadNotificationSummary().catch(()=>{});
  return true;
}

async function acknowledgeAllUrgentEvents() {
  await api('/v1/events/urgent/acknowledge-all', {method:'POST'});
  globalEventSeen = new Set();
  await loadGlobalEvents(true).catch(()=>{});
  if (document.body?.dataset.shellRoute === 'events') await loadEventsHub(true).catch(()=>{});
  if (typeof loadNotificationSummary === 'function') await loadNotificationSummary().catch(()=>{});
}

function renderEventCardIntoList(event, options={}) {
  const list = document.getElementById(options.listId || 'globalEvents');
  if (!list || !event) return false;
  if (!eventMatchesFilter(event, options.filter || 'all', Boolean(options.emergencyOnly))) return false;
  const seen = options.seenSet;
  if (seen && event.id && seen.has(event.id)) return false;
  if (seen && event.id) seen.add(event.id);
  const empty = list.querySelector('.empty-events');
  if (empty) empty.remove();
  const cat = eventCategory(event.type);
  const meta = eventMetaText(event);
  const logText = eventDetailText(event);
  const card = document.createElement('div');
  card.className = `event-card ${cat}`;
  if (event?.ui_state?.acknowledged) card.classList.add('acknowledged');
  card.dataset.eventType = String(event.type || 'event');
  if (event.id) card.dataset.eventId = String(event.id);
  const ackAction = options.allowAcknowledge && isServerBackedEventId(event.id) && !event?.ui_state?.acknowledged
    ? '<button class="event-ack-button ghost-button mini-button" type="button">Acknowledge</button>'
    : '';
  card.innerHTML = `<div class="event-card-header"><span class="event-kind"><span class="event-dot"></span>${prettyEventType(event.type)}</span><span class="event-card-actions">${ackAction}<span class="event-time">${formatEventTime(event.created_at)}</span></span></div><div class="event-message"></div>${meta ? `<div class="event-meta"></div>` : ''}${logText ? '<details class="event-details"><summary>Details</summary><pre></pre></details>' : ''}`;
  card.querySelector('.event-message').textContent = event.message || '';
  const metaEl = card.querySelector('.event-meta');
  if (metaEl) metaEl.textContent = meta;
  const pre = card.querySelector('.event-details pre');
  if (pre) pre.textContent = logText;
  card.querySelector('.event-ack-button')?.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    const btn = ev.currentTarget;
    btn.disabled = true;
    btn.textContent = 'Acknowledging…';
    try { await acknowledgeEvent(event.id); } catch (err) { btn.textContent = 'Failed'; btn.title = String(err?.message || err); btn.disabled = false; }
  });
  if (options.prepend !== false && list.firstChild) list.insertBefore(card, list.firstChild); else list.appendChild(card);
  const max = Number(options.maxItems || 160);
  while (list.children.length > max) list.removeChild(list.lastChild);
  if (options.scrollTop !== false) list.scrollTop = 0;
  return true;
}

function renderGlobalEvent(event, prepend=false) {
  return renderEventCardIntoList(event, {
    listId: 'globalEvents',
    prepend,
    filter: globalEventFilter || 'emergency',
    seenSet: globalEventSeen,
    emergencyOnly: true,
    allowAcknowledge: true,
    maxItems: 80,
  });
}

function renderEventsHubGroups(summary=null, facets=null) {
  const el = document.getElementById('eventsHubGroups');
  if (!el) return;
  const sourceLabels = facets?.source_labels || {};
  const groups = Object.keys(sourceLabels).length ? {...sourceLabels, component: facets?.components || []} : (summary?.groups || {});
  const order = [['endpoint', 'Endpoints'], ['workspace', 'Workspaces'], ['session', 'Sessions'], ['component', 'Components'], ['system', 'System']];
  const blocks = order.map(([kind, label]) => {
    const items = groups[kind] || [];
    if (!items.length) return '';
    const entries = items.slice(0, 7).map((item) => {
      const sourceLabel = item.label || kind;
      const active = eventsHubFacetKind === kind && eventsHubFacetLabel === sourceLabel;
      return `<button class="events-group-row ${active ? 'active' : ''}" type="button" data-events-source-kind="${escapeHtml(kind)}" data-events-source-label="${escapeHtml(sourceLabel)}"><span>${escapeHtml(sourceLabel)}</span><strong>${Number(item.count || 0)}</strong></button>`;
    }).join('');
    return `<div class="events-group-block"><b>${escapeHtml(label)}</b>${entries}</div>`;
  }).filter(Boolean);
  el.innerHTML = blocks.length ? blocks.join('') : '<div class="muted small-text">No source groups in the current event window.</div>';
}

function renderEventsHubActiveFacet() {
  const el = document.getElementById('eventsHubActiveFacet');
  if (!el) return;
  if (!eventsHubFacetKind || !eventsHubFacetLabel) {
    el.innerHTML = '<span class="muted small-text">Showing the selected event window. Pick a source group to drill down.</span>';
    return;
  }
  el.innerHTML = `<span>Drill-down: <b>${escapeHtml(eventsHubFacetKind)}</b> · ${escapeHtml(eventsHubFacetLabel)}</span><button id="eventsHubClearFacet" class="ghost-button mini-button" type="button">Clear drill-down</button>`;
  el.querySelector('#eventsHubClearFacet')?.addEventListener('click', () => {
    eventsHubFacetKind = '';
    eventsHubFacetLabel = '';
    loadEventsHub(true).catch(()=>{});
  });
}

function renderEventsHubSummary(events, summary=null) {
  const el = document.getElementById('eventsHubSummary');
  if (!el) return;
  const visible = (events || []).filter(e => !shouldSuppressGlobalEvent(e));
  const categoryCounts = summary?.categories || {};
  const counts = {failed: 0, attention: 0, running: 0, completed: 0, emergency: Number(summary?.emergency || 0)};
  if (summary) {
    counts.failed = Number(categoryCounts.failed || 0);
    counts.attention = Number(categoryCounts.attention || 0);
    counts.running = Number(categoryCounts.running || 0);
    counts.completed = Number(categoryCounts.completed || 0);
  } else {
    visible.forEach((event) => {
      const cat = eventCategory(event.type);
      counts[cat] = (counts[cat] || 0) + 1;
      if (isEmergencyEvent(event)) counts.emergency += 1;
    });
  }
  const sources = summary?.sources || {};
  el.classList.remove('muted');
  renderEventsHubGroups(summary, window.__pacEventsHubFacets || null);
  renderEventsHubActiveFacet();
  el.innerHTML = [
    ['Urgent', counts.emergency, 'Critical or attention-worthy notifications'],
    ['Needs attention', counts.attention, 'Warnings, approvals, reconnects, or unavailable services'],
    ['Running', counts.running, 'Active task and model/tool activity'],
    ['Completed', counts.completed, `Finished work across ${Number(sources.sessions || 0)} session source(s)`],
  ].map(([label, value, detail]) => `<div class="status-card compact"><span>${escapeHtml(label)}</span><strong>${value}</strong><small>${escapeHtml(detail)}</small></div>`).join('');
}

function renderEventsHub(events, reset=true) {
  const list = document.getElementById('eventsHubList');
  if (!list) return;
  if (reset) {
    eventsHubSeen = new Set();
    list.innerHTML = '<div class="empty-events">No matching events.</div>';
  }
  const ordered = [...(events || [])].reverse();
  ordered.forEach((event) => renderEventCardIntoList(event, {
    listId: 'eventsHubList',
    prepend: false,
    filter: eventsHubFilter,
    seenSet: eventsHubSeen,
    emergencyOnly: false,
    maxItems: 220,
    scrollTop: false,
  }));
  if (!list.querySelector('.event-card')) {
    list.innerHTML = '<div class="empty-events"><b>No matching events.</b><br><span>Change the filter or reload the event hub.</span></div>';
  }
}

function shouldSuppressGlobalEvent(event) {
  const type = String(event?.type || '').toLowerCase();
  return type === 'runner_heartbeat' || type === 'endpoint_heartbeat' || type === 'provider_heartbeat';
}



function eventsRetentionFormValue(form, name, fallback) {
  const field = form?.querySelector(`[name="${name}"]`);
  if (!field) return fallback;
  if (field.type === 'checkbox') return field.checked;
  const value = Number(field.value);
  return Number.isFinite(value) ? value : fallback;
}

function showEventsRetentionEditor(policy={}) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay events-retention-editor-overlay';
  overlay.innerHTML = `
    <div class="modal-card events-retention-editor" role="dialog" aria-modal="true" aria-labelledby="eventsRetentionEditorTitle">
      <div class="modal-header">
        <div>
          <h2 id="eventsRetentionEditorTitle">Events retention policy</h2>
          <p class="muted">Control how long normal and urgent operational events are kept in the controller store.</p>
        </div>
        <button class="icon-button" type="button" data-close-retention-editor aria-label="Close">×</button>
      </div>
      <form id="eventsRetentionEditorForm" class="events-retention-editor-form">
        <label class="checkbox-row"><input name="retention_enabled" type="checkbox" ${policy.retention_enabled === false ? '' : 'checked'}> Enable automatic event retention</label>
        <div class="form-grid two-columns">
          <label><span>Normal events, days</span><input name="retain_days" type="number" min="1" max="3650" value="${Number(policy.retain_days || 30)}"></label>
          <label><span>Urgent events, days</span><input name="emergency_retain_days" type="number" min="1" max="3650" value="${Number(policy.emergency_retain_days || 180)}"></label>
          <label><span>Maximum stored events</span><input name="max_events" type="number" min="100" max="1000000" step="100" value="${Number(policy.max_events || 20000)}"></label>
          <label class="checkbox-row inline-checkbox"><input name="prune_on_startup" type="checkbox" ${policy.prune_on_startup === false ? '' : 'checked'}> Prune on startup</label>
        </div>
        <div class="wizard-review-box">
          <strong>Retention model</strong>
          <p>Urgent events live longer than normal lifecycle events. Logs and metrics should stay in their own observability stores instead of being kept as events forever.</p>
        </div>
        <div class="modal-actions">
          <button class="ghost-button" type="button" data-close-retention-editor>Cancel</button>
          <button class="primary-button" type="submit">Save policy</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelectorAll('[data-close-retention-editor]').forEach((button) => button.addEventListener('click', close));
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
  overlay.querySelector('#eventsRetentionEditorForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    submit.textContent = 'Saving…';
    const payload = {
      retention_enabled: eventsRetentionFormValue(form, 'retention_enabled', true),
      retain_days: eventsRetentionFormValue(form, 'retain_days', 30),
      emergency_retain_days: eventsRetentionFormValue(form, 'emergency_retain_days', 180),
      max_events: eventsRetentionFormValue(form, 'max_events', 20000),
      prune_on_startup: eventsRetentionFormValue(form, 'prune_on_startup', true),
    };
    try {
      await api('/v1/events/retention', {method:'PUT', body:JSON.stringify(payload)});
      close();
      await loadEventsRetentionStatus();
      await loadEventsHub(true);
    } catch (err) {
      submit.disabled = false;
      submit.textContent = 'Save policy';
      notify?.(`Failed to save retention policy: ${err.message || err}`);
    }
  });
  setTimeout(() => overlay.querySelector('input[name="retain_days"]')?.focus(), 50);
}

async function loadEventsRetentionStatus() {
  const el = document.getElementById('eventsRetentionStatus');
  if (!el) return;
  try {
    const payload = await api('/v1/events/retention');
    const policy = payload.policy || {};
    const counts = payload.counts || {};
    const total = Number(counts.total || 0);
    const emergency = Number(counts.emergency || 0);
    const prunable = Number(counts.prunable_normal || 0) + Number(counts.prunable_emergency || 0);
    el.classList.remove('muted');
    el.innerHTML = `<span><strong>Retention</strong> · ${total} stored events · ${emergency} urgent · ${prunable} prunable</span><span>${policy.retention_enabled === false ? 'disabled' : `${Number(policy.retain_days || 30)}d normal / ${Number(policy.emergency_retain_days || 180)}d urgent / max ${Number(policy.max_events || 20000)}`}</span><span class="button-row compact-row"><button id="eventsRetentionEdit" class="ghost-button mini-button" type="button">Edit policy</button><button id="eventsRetentionPrune" class="ghost-button mini-button" type="button">Prune now</button></span>`;
    el.querySelector('#eventsRetentionEdit')?.addEventListener('click', () => showEventsRetentionEditor(policy));
    el.querySelector('#eventsRetentionPrune')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = 'Pruning…';
      try {
        const result = await api('/v1/events/retention/prune', {method:'POST'});
        button.textContent = `Pruned ${Number(result?.result?.deleted || 0)}`;
        await loadEventsHub(true);
        await loadEventsRetentionStatus();
      } catch (err) {
        button.disabled = false;
        button.textContent = 'Prune failed';
        button.title = String(err?.message || err);
      }
    });
  } catch (err) {
    el.innerHTML = `<span>Retention status unavailable: ${escapeHtml(err.message || String(err))}</span>`;
  }
}

async function loadEventsHub(reset=true) {
  const list = document.getElementById('eventsHubList');
  if (!list) return;
  if (reset) list.innerHTML = '<div class="empty-events">Loading events…</div>';
  try {
    const params = new URLSearchParams({limit: '260'});
    if (eventsHubFacetKind) params.set('source_kind', eventsHubFacetKind);
    if (eventsHubFacetLabel) params.set('source_label', eventsHubFacetLabel);
    const payload = await api(`/v1/events/summary?${params.toString()}`);
    eventsHubLastEvents = Array.isArray(payload) ? payload : (payload.events || []);
    window.__pacEventsHubFacets = payload.facets || null;
    renderEventsHubSummary(eventsHubLastEvents, payload.summary || null);
    await loadEventsRetentionStatus();
    renderEventsHub(eventsHubLastEvents, true);
  } catch (e) {
    list.innerHTML = `<div class="empty-events">Could not load events: ${escapeHtml(e.message || String(e))}</div>`;
  }
}

async function loadGlobalEvents(reset=false) {
  const list = document.getElementById('globalEvents');
  if (!list) return;
  if (reset) { globalEventSeen = new Set(); list.innerHTML = '<div class="empty-events">No urgent notifications.</div>'; }
  try {
    const payload = await api('/v1/events/urgent?limit=80');
    const events = Array.isArray(payload) ? payload : (payload.events || []);
    eventsFetchFailureCount = 0;
    eventsFetchLastNotice = null;
    const existing = list.querySelector('.events-fetch-error');
    if (existing) existing.remove();
    if (reset) list.innerHTML = '';
    [...events].reverse().forEach(e => renderGlobalEvent(e));
    if (window.__pacLastUiEvent) renderGlobalEvent(window.__pacLastUiEvent);
    if (!list.querySelector('.event-card')) {
      list.innerHTML = '<div class="empty-events"><b>No urgent notifications.</b><br><span>Use Observe → Events for the full event stream.</span></div>';
    }
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
  window.openEventsRail = showRail;
  window.openNotificationDrawer = showRail;
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
    pin.title = eventsRailPinned ? 'Notifications pinned open' : 'Keep notifications open';
  };
  document.addEventListener('pointerdown', (ev) => {
    if (!rail || rail.hidden || eventsRailPinned) return;
    if (rail.contains(ev.target) || open?.contains(ev.target)) return;
    hideRail();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && rail && !rail.hidden && !eventsRailPinned) hideRail();
  });
  document.querySelectorAll('.notification-drawer .event-chip').forEach(chip => {
    chip.onclick = async () => {
      document.querySelectorAll('.notification-drawer .event-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      globalEventFilter = chip.dataset.eventFilter || 'emergency';
      await loadGlobalEvents(true);
    };
  });
  document.querySelectorAll('[data-events-hub-filter]').forEach(chip => {
    chip.onclick = async () => {
      document.querySelectorAll('[data-events-hub-filter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      eventsHubFilter = chip.dataset.eventsHubFilter || 'all';
      renderEventsHub(eventsHubLastEvents, true);
    };
  });
  const clear = document.getElementById('clearEventPanel');
  if (clear) clear.onclick = () => { acknowledgeAllUrgentEvents().catch((err)=>{ const list=document.getElementById('globalEvents'); if(list) list.innerHTML=`<div class="empty-events">Could not acknowledge notifications: ${escapeHtml(err.message || String(err))}</div>`; }); };
  document.getElementById('eventsHubGroups')?.addEventListener('click', (event) => {
    const row = event.target.closest('[data-events-source-kind]');
    if (!row) return;
    eventsHubFacetKind = row.dataset.eventsSourceKind || '';
    eventsHubFacetLabel = row.dataset.eventsSourceLabel || '';
    loadEventsHub(true).catch(()=>{});
  });
  document.getElementById('eventsHubReload')?.addEventListener('click', () => loadEventsHub(true).catch(()=>{}));
  document.getElementById('eventsHubCriticalOnly')?.addEventListener('click', () => {
    eventsHubFilter = eventsHubFilter === 'failed' ? 'all' : 'failed';
    document.querySelectorAll('[data-events-hub-filter]').forEach(c => c.classList.toggle('active', (c.dataset.eventsHubFilter || 'all') === eventsHubFilter));
    renderEventsHub(eventsHubLastEvents, true);
  });
  document.getElementById('eventsHubSearch')?.addEventListener('input', (event) => {
    eventsHubSearch = event.target.value || '';
    renderEventsHub(eventsHubLastEvents, true);
  });
  document.querySelectorAll('[data-events-hub-source]').forEach(chip => {
    chip.onclick = () => {
      document.querySelectorAll('[data-events-hub-source]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      eventsHubSource = chip.dataset.eventsHubSource || 'all';
      renderEventsHub(eventsHubLastEvents, true);
    };
  });
  document.getElementById('eventsHubExport')?.addEventListener('click', () => {
    const lines = Array.from(document.querySelectorAll('#eventsHubList .event-card')).map((card) => card.innerText.trim()).filter(Boolean).join('\n---\n');
    const blob = new Blob([lines || 'No visible events.'], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pac-events-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  });
  if (!globalEventPoll) globalEventPoll = setInterval(() => { loadGlobalEvents(false).catch(()=>{}); if (typeof loadNotificationSummary === 'function') loadNotificationSummary().catch(()=>{}); }, 5000);
  if (!eventsHubPoll) eventsHubPoll = setInterval(() => { if (document.body?.dataset.shellRoute === 'events') loadEventsHub(false).catch(()=>{}); }, 7000);
  loadEventsHub(false).catch(()=>{});
  loadEventsRetentionStatus().catch(()=>{});
}
