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
    prompt_context: 'preparing context',
    planning_model: 'planning with the model',
    decision_model: 'asking the model',
    context_compaction_check: 'checking context size',
    tool_execution: 'running a tool',
  };
  return labels[value] || prettyEventType(value || 'agent phase');
}

function latestAgentPhaseRows(events) {
  const rows = [];
  const seen = new Set();
  (events || []).forEach((item) => {
    const event = item?.event || {};
    const type = String(event.type || '').toLowerCase();
    if (!type.includes('agent_phase') && !type.includes('model_stream_progress') && !type.includes('model_call_')) return;
    const data = event.data && typeof event.data === 'object' ? event.data : {};
    const phase = data.phase || data.call_type || event.type;
    const key = `${event.type}:${phase}:${data.step || ''}:${data.elapsed_ms || data.chars || ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    let label = type.includes('agent_phase') ? agentPhaseLabel(phase) : sessionThinkingSummary(event, item?.block);
    let status = type.includes('completed') || type.includes('late_completed') ? 'done' : type.includes('slow') || type.includes('abandoned') ? 'attention' : 'running';
    let detail = '';
    if (data.elapsed_ms != null) detail = formatDurationMs(data.elapsed_ms);
    if (data.chars != null) detail = `${data.chars} chars`;
    rows.push({label, status, detail, at: formatEventTime(event.created_at)});
  });
  return rows.slice(-10);
}

function sessionThinkingDetailsHtml(events) {
  const rows = (events || []).filter(item => item?.event && isInternalSessionEvent(item.event));
  if (!rows.length) return '<div class="tool-activity-empty">No internal activity was recorded for this answer.</div>';
  const first = rows[0]?.event;
  const last = rows[rows.length - 1]?.event;
  const start = formatEventTime(first?.created_at);
  const end = formatEventTime(last?.created_at);
  const modelNotes = thinkingGroupIntermediateResponses({events: rows}, 6);
  const phaseRows = latestAgentPhaseRows(rows);
  const phaseHtml = phaseRows.length
    ? `<div class="thought-modal-plan"><div class="thought-modal-section-title">Runtime phases</div>${phaseRows.map((phase) => `<div class="thought-modal-plan-item ${escapeHtml(phase.status)}"><span class="thought-modal-plan-index">${escapeHtml(phase.at || '•')}</span><span class="thought-modal-plan-label">${escapeHtml(phase.label)}</span><span class="thought-modal-plan-state">${escapeHtml(phase.detail || phase.status)}</span></div>`).join('')}</div>`
    : '';
  const notesHtml = modelNotes.length
    ? `<div class="thought-modal-intermediates"><div class="thought-modal-section-title">Model updates shown during the run</div>${modelNotes.map((item, index) => `<div class="thought-modal-intermediate"><span class="thought-modal-plan-index">${index + 1}</span><div class="thought-modal-intermediate-text">${escapeHtml(item.text)}</div></div>`).join('')}</div>`
    : '<div class="tool-activity-empty">No user-facing model updates were produced during this run. Raw model responses remain available in the full session log.</div>';
  return `${phaseHtml}${notesHtml}<div class="tool-activity-empty">Tool output, stdout, stderr, and raw diagnostics are kept in the full session log.</div><div class="tool-activity-list"><div class="tool-activity-item"><summary><span class="tool-activity-icon">⌁</span><span class="tool-activity-title">Internal events recorded</span><span class="tool-activity-status">${rows.length}</span><span class="tool-activity-time">${escapeHtml(start)} → ${escapeHtml(end)}</span></summary></div></div>`;
}
