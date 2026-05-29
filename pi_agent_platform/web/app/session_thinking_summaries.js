// Focused session UI helpers extracted from sessions.js.

function toolActivityTitle(item) {
  const event = item?.event || {};
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const t = String(event.type || '').toLowerCase();
  if (data.tool) return String(data.tool);
  if (data.command) return 'exec_command';
  if (t.includes('intent')) return 'current_intent';
  if (t.includes('web_search')) return 'search_web';
  if (t.includes('web_fetch')) return 'fetch_web';
  if (t.includes('artifact')) return 'artifact';
  if (t.includes('stdout') || t.includes('stderr')) return 'exec_output';
  if (t.includes('approval')) return 'approval';
  return prettyEventType(event.type || 'tool');
}

function toolActivityBody(item) {
  const event = item?.event || {};
  const block = item?.block;
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  const text = timelineText(event, block);
  if (data.command) lines.push(`$ ${data.command}`);
  if (data.input) lines.push(typeof data.input === 'string' ? data.input : JSON.stringify(data.input, null, 2));
  if (text && !lines.includes(text)) lines.push(text);
  if (data.thought && !lines.includes(String(data.thought))) lines.push(String(data.thought));
  if (data.output && !String(text).includes(String(data.output))) lines.push(String(data.output));
  if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
  if (data.exit_code != null) lines.push(`exit code: ${data.exit_code}`);
  if (!lines.length && event.message) lines.push(event.message);
  return lines.join('\n').trim();
}


function isSessionIntentEvent(event) {
  const t = String(event?.type || '').toLowerCase();
  return t.includes('agent_intent') || t.includes('agent_routing') || t.includes('model_request_config') || t.includes('approval_required') || t.includes('task_failed');
}

function sessionIntentSummary(event, block) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const type = String(event?.type || '').toLowerCase();
  if (type.includes('approval_required')) return sessionThinkingSummary(event, block);
  if (type.includes('task_failed')) return event?.message || 'Task failed';
  if (type.includes('model_request_config')) return 'Asking the model';
  if (type.includes('model_stream_progress')) return `Model streaming response (${data.chars || 0} chars)`;
  if (type.includes('model_call_abandoned')) return 'Provider call timed out; continuing safely';
  if (type.includes('model_call_late_completed')) return data.success === false ? 'Timed-out provider call later failed' : 'Timed-out provider call later completed';
  if (type.includes('agent_phase_running')) return `Still ${agentPhaseLabel(data.phase)} (${formatDurationMs(data.elapsed_ms || 0)})`;
  if (type.includes('agent_phase_started')) return agentPhaseLabel(data.phase);
  if (type.includes('agent_phase_completed')) return `${agentPhaseLabel(data.phase)} complete`;
  if (type.includes('agent_phase_slow')) return `${agentPhaseLabel(data.phase)} was slow`;
  if (type.includes('agent_routing')) return event?.message || 'Routing the request';
  if (type.includes('agent_intent')) return sessionThinkingSummary(event, block) || event?.message || 'Working on the request';
  return '';
}

function modelIntermediateResponseText(event, block = null) {
  const type = String(event?.type || '').toLowerCase();
  if (type.includes('model_response_empty')) return '';
  if (!type.includes('model_response') && !type.includes('model_stream_progress')) return '';
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const raw = String(data.preview || data.intermediate || data.message || event?.message || timelineText(event, block) || '').trim();
  if (!raw) return '';
  const normalized = normalizeAssistantText(raw).trim();
  if (!normalized) return '';
  const compact = normalized.replace(/```[\s\S]*?```/g, '').trim();
  const first = compact.slice(0, 280).trim();
  const lower = first.toLowerCase();
  if (!first) return '';
  if (/^\s*[\[{]/.test(first)) return '';
  if (lower.includes('"type"') && lower.includes('tool_call')) return '';
  if (lower.includes('<|tool_call') || lower.includes('tool_call|>')) return '';
  if (/^call:(?:tool_call:)?[a-z0-9_:-]+/i.test(first)) return '';
  if (/^\s*(tool|command|input|arguments)\s*:/i.test(first)) return '';
  if (/^(thinking|done|ok|okay|yes)[.!]?$/i.test(first)) return '';
  if (first.length < 18) return '';
  const lines = normalized.split('\n').map(line => line.trim()).filter(Boolean);
  const meaningful = lines.slice(0, 4).join('\n');
  return meaningful.length > 900 ? `${meaningful.slice(0, 897).trim()}…` : meaningful;
}

function thinkingGroupIntermediateResponses(group, limit = 3) {
  const rows = Array.isArray(group?.events) ? group.events : [];
  const seen = new Set();
  const items = [];
  rows.forEach((item) => {
    const text = modelIntermediateResponseText(item?.event, item?.block);
    if (!text) return;
    const key = text.replace(/\s+/g, ' ').trim().slice(0, 220);
    if (!key || seen.has(key)) return;
    seen.add(key);
    items.push({text, createdAt: item?.event?.created_at || ''});
  });
  return items.slice(-limit);
}

function thinkingGroupLatestIntermediate(group) {
  const items = thinkingGroupIntermediateResponses(group, 1);
  return items.length ? items[0] : null;
}

function taskStartEventForThinking(event) {
  const t = String(event?.type || '').toLowerCase();
  return t.includes('model_request_config') || t.includes('agent_loop_started') || t.includes('task_started') || t.includes('task_queued') || t.includes('agent_routing') || t.includes('agent_intent');
}

function taskFinishedEventForThinking(event) {
  const t = String(event?.type || '').toLowerCase();
  return t.includes('task_completed') || t.includes('task_failed') || t === 'result' || t === 'final' || t.includes('assistant_message');
}


function agentPhaseLabel(phase) {
  const value = String(phase || '').toLowerCase();
  const labels = {
    prompt_context: 'Preparing context',
    preparing_context: 'Preparing context',
    request_intent_model: 'Classifying the request',
    planning_model: 'Planning with the model',
    decision_model: 'Waiting for model response',
    context_compaction_check: 'Checking context size',
    tool_execution: 'Running a tool',
    resource_flow_tool: 'Creating PAC resource',
    coding_readiness: 'Checking coding-session readiness',
    provider_call: 'Calling model provider',
    model_stream: 'Streaming model response',
  };
  return labels[value] || prettyEventType(value || 'agent phase');
}

function eventTimestampMs(event) {
  const value = event?.created_at;
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function durationBetweenEvents(startEvent, endEvent) {
  const start = eventTimestampMs(startEvent);
  const end = eventTimestampMs(endEvent);
  if (!start || !end || end < start) return '';
  return formatDurationMs(end - start);
}

function relativeEventTime(event, anchorEvent) {
  const current = eventTimestampMs(event);
  const anchor = eventTimestampMs(anchorEvent);
  if (!current || !anchor) return formatEventTime(event?.created_at) || '';
  return `+${formatDurationMs(current - anchor)}`;
}

function phaseKeyForEvent(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  return String(data.phase || data.call_type || data.tool || event?.type || 'phase').toLowerCase();
}

function phaseStatusForEvent(typeLower) {
  if (typeLower.includes('completed') || typeLower.includes('late_completed')) return 'done';
  if (typeLower.includes('failed') || typeLower.includes('error')) return 'failed';
  if (typeLower.includes('slow') || typeLower.includes('abandoned') || typeLower.includes('cancel')) return 'attention';
  return 'running';
}

function latestAgentPhaseRows(events) {
  const source = Array.isArray(events) ? events : [];
  const first = source[0]?.event || null;
  const phases = [];
  const byKey = new Map();
  source.forEach((item) => {
    const event = item?.event || {};
    const type = String(event.type || '').toLowerCase();
    if (!type.includes('agent_phase') && !type.includes('model_stream_progress') && !type.includes('model_call_') && !type.includes('tool_pipeline_') && !type.includes('coding_session_readiness')) return;
    const data = event.data && typeof event.data === 'object' ? event.data : {};
    const phaseKey = phaseKeyForEvent(event);
    const stableKey = `${phaseKey}:${data.tool || data.status || ''}`;
    let phase = byKey.get(stableKey);
    if (!phase) {
      phase = {
        key: stableKey,
        label: type.includes('agent_phase') ? agentPhaseLabel(phaseKey) : sessionThinkingSummary(event, item?.block) || prettyEventType(event.type),
        status: 'running',
        startedEvent: event,
        lastEvent: event,
        count: 0,
        details: [],
      };
      byKey.set(stableKey, phase);
      phases.push(phase);
    }
    phase.lastEvent = event;
    phase.count += 1;
    const nextStatus = phaseStatusForEvent(type);
    if (nextStatus === 'failed' || nextStatus === 'attention' || nextStatus === 'done' || phase.status === 'running') phase.status = nextStatus;
    if (data.elapsed_ms != null) phase.duration = formatDurationMs(data.elapsed_ms);
    if (data.chars != null) phase.details.push(`${data.chars} chars`);
    if (data.status) phase.details.push(String(data.status));
    if (data.tool) phase.details.push(`tool ${data.tool}`);
  });
  return phases.slice(-12).map((phase, index) => {
    const isRunning = phase.status === 'running';
    const duration = phase.duration || durationBetweenEvents(phase.startedEvent, phase.lastEvent) || (isRunning ? formatDurationMs(Date.now() - eventTimestampMs(phase.startedEvent)) : '0s');
    const detailParts = [];
    if (isRunning) detailParts.push('running now');
    else detailParts.push(phase.status === 'done' ? 'completed' : phase.status);
    if (duration) detailParts.push(duration);
    const seen = [...new Set(phase.details.filter(Boolean))].slice(0, 2);
    detailParts.push(...seen);
    return {
      label: phase.label,
      status: phase.status,
      detail: detailParts.join(' · '),
      at: `Step ${index + 1}`,
      relative: relativeEventTime(phase.startedEvent, first),
    };
  });
}

function eventDataPreview(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const shallow = {};
  Object.entries(data).forEach(([key, value]) => {
    if (value == null) return;
    if (typeof value === 'string') shallow[key] = value.length > 1400 ? `${value.slice(0, 1400)}…` : value;
    else if (typeof value === 'number' || typeof value === 'boolean') shallow[key] = value;
    else if (Array.isArray(value)) shallow[key] = value.slice(0, 12);
    else if (typeof value === 'object') shallow[key] = Object.fromEntries(Object.entries(value).slice(0, 16));
  });
  return JSON.stringify(shallow, null, 2);
}

function eventOutcomeLabel(event, block) {
  const type = String(event?.type || '').toLowerCase();
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  if (data.error || type.includes('failed') || type.includes('error')) return data.error || event?.message || 'Failed';
  if (data.stderr) return 'stderr captured';
  if (data.tool) return `${data.tool}`;
  if (data.phase) return agentPhaseLabel(data.phase);
  if (data.status) return String(data.status);
  return sessionThinkingSummary(event, block) || event?.message || prettyEventType(event?.type || 'event');
}

function importantThinkingEvents(events) {
  const rows = Array.isArray(events) ? events : [];
  return rows.filter((item) => {
    const type = String(item?.event?.type || '').toLowerCase();
    return type.includes('tool') || type.includes('approval') || type.includes('failed') || type.includes('error') || type.includes('stderr') || type.includes('stdout') || type.includes('model_call') || type.includes('model_stream') || type.includes('agent_phase') || type.includes('coding_session_readiness') || type.includes('doom_loop') || type.includes('context_') || type.includes('resource_flow');
  }).slice(-36);
}

function thoughtWhatHappenedHtml(events) {
  const rows = Array.isArray(events) ? events : [];
  const last = rows[rows.length - 1]?.event || null;
  const running = latestAgentPhaseRows(rows).filter((row) => row.status === 'running').slice(-2);
  const failures = rows.filter((item) => {
    const type = String(item?.event?.type || '').toLowerCase();
    const data = item?.event?.data && typeof item.event.data === 'object' ? item.event.data : {};
    return type.includes('failed') || type.includes('error') || data.error || data.stderr;
  }).slice(-2);
  const tools = rows.filter((item) => String(item?.event?.data?.tool || '').trim()).map((item) => item.event.data.tool).slice(-4);
  const bullets = [];
  if (running.length) bullets.push(`Current active phase: ${running.map((row) => `${row.label} (${row.detail})`).join(', ')}`);
  else if (last) bullets.push(`Last recorded event: ${prettyEventType(last.type || 'event')}`);
  if (tools.length) bullets.push(`Recent tool activity: ${[...new Set(tools)].join(', ')}`);
  if (failures.length) bullets.push(`Attention needed: ${failures.map((item) => eventOutcomeLabel(item.event, item.block)).join(' · ')}`);
  if (!bullets.length) bullets.push('PAC recorded internal activity, but no user-facing model update was produced. Open the event log below for raw details.');
  return `<div class="thought-modal-explain"><div class="thought-modal-section-title">What happened</div><ul>${bullets.map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ul></div>`;
}

function thoughtEventLogHtml(events) {
  const rows = importantThinkingEvents(events);
  if (!rows.length) return '<div class="tool-activity-empty">No inspectable runtime events were recorded for this step.</div>';
  const anchor = rows[0]?.event || null;
  return `<div class="thought-event-log"><div class="thought-modal-section-title">Inspectable event log</div>${rows.map((item, index) => {
    const event = item.event || {};
    const type = event.type || 'event';
    const status = eventCategory(type);
    const summary = eventOutcomeLabel(event, item.block);
    const body = toolActivityBody(item) || eventDataPreview(event) || 'No additional details.';
    const data = eventDataPreview(event);
    return `<details class="thought-event-item ${escapeHtml(status)}" ${index >= rows.length - 3 ? 'open' : ''}>
      <summary><span class="thought-event-index">${index + 1}</span><span class="thought-event-main"><strong>${escapeHtml(prettyEventType(type))}</strong><small>${escapeHtml(summary)}</small></span><span class="thought-event-time">${escapeHtml(relativeEventTime(event, anchor))}</span></summary>
      <pre>${escapeHtml(body)}</pre>
      ${data && data !== '{}' ? `<details class="thought-event-json"><summary>Raw event data</summary><pre>${escapeHtml(data)}</pre></details>` : ''}
    </details>`;
  }).join('')}</div>`;
}

function sessionThinkingDetailsHtml(events) {
  const rows = (events || []).filter(item => item?.event && isInternalSessionEvent(item.event));
  if (!rows.length) return '<div class="tool-activity-empty">No internal activity was recorded for this answer.</div>';
  const first = rows[0]?.event;
  const last = rows[rows.length - 1]?.event;
  const start = formatEventTime(first?.created_at);
  const end = formatEventTime(last?.created_at);
  const elapsed = durationBetweenEvents(first, last) || '0s';
  const modelNotes = thinkingGroupIntermediateResponses({events: rows}, 6);
  const phaseRows = latestAgentPhaseRows(rows);
  const phaseHtml = phaseRows.length
    ? `<div class="thought-modal-plan thought-runtime-phases"><div class="thought-modal-section-title">Runtime phases</div>${phaseRows.map((phase) => `<div class="thought-modal-plan-item ${escapeHtml(phase.status)}"><span class="thought-modal-plan-index">${escapeHtml(phase.at || '•')}</span><span class="thought-modal-plan-label"><strong>${escapeHtml(phase.label)}</strong>${phase.relative ? `<small>${escapeHtml(phase.relative)}</small>` : ''}</span><span class="thought-modal-plan-state">${escapeHtml(phase.detail || phase.status)}</span></div>`).join('')}</div>`
    : '';
  const notesHtml = modelNotes.length
    ? `<div class="thought-modal-intermediates"><div class="thought-modal-section-title">Model updates shown during the run</div>${modelNotes.map((item, index) => `<div class="thought-modal-intermediate"><span class="thought-modal-plan-index">${index + 1}</span><div class="thought-modal-intermediate-text">${escapeHtml(item.text)}</div></div>`).join('')}</div>`
    : '<div class="tool-activity-empty">No user-facing model updates were produced during this run. Inspectable runtime events are shown below.</div>';
  return `<div class="thought-run-window"><span>Started ${escapeHtml(start || 'unknown')}</span><span>Last event ${escapeHtml(end || 'unknown')}</span><span>Recorded span ${escapeHtml(elapsed)}</span><span>${rows.length} internal events</span></div>${thoughtWhatHappenedHtml(rows)}${phaseHtml}${notesHtml}${thoughtEventLogHtml(rows)}`;
}
