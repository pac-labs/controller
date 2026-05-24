// Focused session UI helpers extracted from sessions.js.

function normalizeTimelineBlock(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const block = data.timeline || data.card || data.block || null;
  if (block && typeof block === 'object') return block;
  return null;
}

function renderTimelineBlock(card, event, block) {
  const body = document.createElement('div');
  body.className = 'timeline-card-body';
  const title = block.title || event.message || prettyEventType(event.type);
  appendText(body, 'div', 'timeline-title', title);
  if (block.summary || (event.message && block.title)) appendText(body, 'div', 'timeline-summary', block.summary || event.message);
  const fields = block.fields || block.meta;
  if (fields && typeof fields === 'object' && !Array.isArray(fields)) {
    const grid = document.createElement('div');
    grid.className = 'timeline-fields';
    Object.entries(fields).forEach(([key, value]) => {
      if (value == null || value === '') return;
      const item = document.createElement('div');
      appendText(item, 'span', 'timeline-field-key', key);
      appendText(item, 'span', 'timeline-field-value', value);
      grid.appendChild(item);
    });
    if (grid.children.length) body.appendChild(grid);
  }
  const steps = Array.isArray(block.steps) ? block.steps : [];
  if (steps.length) {
    const list = document.createElement('div');
    list.className = 'timeline-steps';
    steps.forEach(step => {
      const row = document.createElement('div');
      const status = String(step.status || 'info').toLowerCase();
      row.className = `timeline-step ${status}`;
      appendText(row, 'span', 'timeline-step-status', status);
      const text = document.createElement('div');
      appendText(text, 'b', '', step.label || step.title || 'Step');
      appendText(text, 'small', '', step.detail || step.message || '');
      row.appendChild(text);
      list.appendChild(row);
    });
    body.appendChild(list);
  }
  if (block.code || block.output || block.diff) {
    const pre = document.createElement('pre');
    pre.className = 'timeline-code';
    pre.textContent = String(block.code || block.output || block.diff);
    body.appendChild(pre);
  }
  if (Array.isArray(block.links) && block.links.length) {
    const links = document.createElement('div');
    links.className = 'timeline-links';
    block.links.forEach(link => {
      const a = document.createElement('a');
      a.href = String(link.href || link.url || '#');
      a.textContent = String(link.label || link.href || link.url || 'link');
      a.target = '_blank';
      a.rel = 'noreferrer';
      links.appendChild(a);
    });
    body.appendChild(links);
  }
  card.appendChild(body);
}

function sessionEventRole(event) {
  const t = String(event?.type || '').toLowerCase();
  if (t.includes('user_message') || t === 'user') return 'user';
  if (t.includes('tool_result')) return 'tool';
  if (t.includes('result') || t.includes('assistant_message') || t === 'final') return 'assistant';
  if (t.includes('task_queued') || t.includes('prompt')) return 'user';
  if (t.includes('failed') || t.includes('error') || t.includes('stderr') || t.includes('rejected')) return 'error';
  if (t.includes('tool') || t.includes('command') || t.includes('runner') || t.includes('stdout')) return 'tool';
  if (t.includes('thinking') || t.includes('pi.dev') || t.includes('model')) return 'assistant';
  return event?.task_id ? 'assistant' : 'system';
}

function isInternalSessionEvent(event) {
  const t = String(event?.type || '').toLowerCase();
  if (t.includes('user_message')) return false;
  if (t.includes('tool_result')) return true;
  if (t.includes('result') || t.includes('assistant_message') || t === 'final') return false;
  return t.includes('tool') || t.includes('command') || t.includes('runner') ||
    t.includes('stdout') || t.includes('stderr') || t.includes('approval') ||
    t.includes('thinking') || t.includes('intent') || t.includes('routing') || t.includes('task_queued') || t.includes('task_started') ||
    t.includes('task_completed') || t.includes('task_failed') || t.includes('task_approved') ||
    t.includes('task_rejected') || t.includes('task_resumed') || t.includes('subagent_started') ||
    t.includes('context_compacted') || t.includes('checkpoint') || t.includes('batch_result') ||
    t.includes('model_response_empty') || t.includes('tool_call_parse_failed') || t.includes('action_narration_rejected') ||
    t.includes('model_response') || t.includes('model_stream_progress') || t.includes('model_call_') ||
    t.includes('agent_phase') || t.includes('agent_plan') || t.includes('workspace_indexed') ||
    t.includes('web_search') || t.includes('web_fetch') || t.includes('artifact_saved');
}

function sessionEventDetailsText(event, block) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  lines.push(`${prettyEventType(event?.type)} ${formatEventTime(event?.created_at)}`.trim());
  const metaLines = sessionEventMetaLines(event);
  if (metaLines.length) lines.push('', ...metaLines);
  const main = timelineText(event, block);
  if (main) lines.push('', main);
  if (Object.keys(data).length) lines.push('', 'Details:', JSON.stringify(data, null, 2));
  return lines.join('\n');
}

function sessionLifecycleEventIsNoise(event) {
  const t = String(event?.type || '').toLowerCase();
  const msg = String(event?.message || '').toLowerCase();
  return t === 'agent_loop_started' || t === 'agent_stop' || t === 'agent_thinking' ||
    t === 'model_response' || t === 'task_queued' || t === 'task_started' ||
    t === 'task_completed' || t === 'context_compacted' || t === 'checkpoint_saved' ||
    t === 'batch_result' || t === 'model_response_empty' || t === 'tool_call_parse_failed' ||
    t === 'action_narration_rejected' || t === 'full_control_enabled' ||
    msg === 'agent loop started' || msg === 'agent stopped';
}

function sessionThinkingLine(event, block) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const type = prettyEventType(event?.type);
  const text = timelineText(event, block);
  const concise = data.tool ? `Using ${data.tool}` :
    data.command ? `Running ${data.command}` :
    data.path ? `Accessing ${data.path}` :
    data.url ? `Fetching ${data.url}` :
    data.query ? `Searching ${data.query}` :
    text ? String(text).split('\n')[0] :
    type;
  return `${formatEventTime(event?.created_at)} · ${concise}`.trim();
}

function sessionThinkingSummary(event, block) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const type = String(event?.type || '').toLowerCase();
  if (type.includes('approval_required')) {
    const target = data.command || data.path || data.url || data.query || '';
    if (target) return `Approval needed for ${target}`;
    return data.reason ? `Approval needed: ${data.reason}` : 'Approval needed before continuing';
  }
  if (type.includes('task_approved')) return 'Approval granted';
  if (type.includes('task_rejected')) return 'Approval rejected';
  if (type.includes('task_failed')) return event?.message || 'Task failed';
  if (type.includes('task_completed')) return '';
  if (type.includes('agent_thinking')) return '';
  if (type.includes('workspace_indexed')) return '';
  if (type.includes('checkpoint')) return '';
  if (type.includes('batch_result')) return '';
  if (type.includes('context_compacted')) return '';
  if (type.includes('model_response_empty')) return '';
  if (type.includes('tool_call_parse_failed')) return '';
  if (type.includes('action_narration_rejected')) return '';
  if (type.includes('agent_plan')) return String(data.summary || event?.message || 'Plan ready').trim();
  if (type.includes('model_response')) return '';
  if (type.includes('tool_call')) {
    if (data.command) return `Running ${data.command}`;
    if (data.tool === 'list_files') return 'Listing files';
    if (data.tool === 'read_file' || data.tool === 'read_file_chunk') return `Reading ${data.path || 'file'}`;
    if (data.tool === 'workspace_manifest') return 'Inspecting workspace';
    if (data.tool) return `Using ${data.tool}`;
  }
  if (type.includes('agent_intent')) {
    if (data.tool) return `Using ${data.tool}`;
    if (data.command) return `Running ${data.command}`;
    if (data.action_type === 'final') return 'Prepared a final answer';
    return event?.message || 'Choosing next step';
  }
  if (type.includes('agent_routing')) return event?.message || 'Routing task';
  if (type.includes('tool_result')) {
    const text = timelineText(event, block);
    if (!text) return '';
    const normalized = normalizeAssistantText(text).trim();
    if (!normalized) return '';
    if (normalized.length > 120 || normalized.includes('\n\n')) return '';
    return normalized.split('\n')[0];
  }
  if (data.tool) return `Using ${data.tool}`;
  if (data.command) return `Running ${data.command}`;
  if (data.path) return `Working with ${data.path}`;
  if (data.url) return `Fetching ${data.url}`;
  if (data.query) return `Searching ${data.query}`;
  const text = timelineText(event, block);
  if (text) return String(text).split('\n')[0];
  return prettyEventType(event?.type || 'thinking');
}
