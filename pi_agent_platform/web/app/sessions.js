// Session, timeline, approval, composer, and session-file UI helpers extracted from app.js.

let composerAttachedItems = [];

function slashCommandHelpText() {
  const commands = (sessionSlashCommands && sessionSlashCommands.length) ? sessionSlashCommands : Object.values(SESSION_SLASH_COMMANDS);
  return commands.map(c => `${c.label} - ${c.description}`).join('\n');
}

function isHelpSlashCommand(raw) {
  return String(raw || '').trim().toLowerCase() === '/help';
}

function appendText(parent, tag, className, text) {
  if (text == null || text === '') return null;
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = String(text);
  parent.appendChild(el);
  return el;
}

function normalizeAssistantText(text) {
  const normalized = String(text || '')
    .replace(/\$\\rightarrow\$/g, '→')
    .replace(/\$\\leftarrow\$/g, '←')
    .replace(/\{\\rightarrow\}/g, '→')
    .replace(/\{\\leftarrow\}/g, '←')
    .replace(/<\|tool_call\>[\s\S]*?<tool_call\|>/g, '')
    .replace(/<\|tool_call[\s\S]*$/g, '')
    .replace(/^\s*call:(?:tool_call:)?[A-Za-z0-9_:-]+\s*[\[{][\s\S]*$/gm, '')
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const blockLike = (line) => /^\s*(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s+|```|~~~|\|)/.test(line);
  const lines = normalized.split('\n');
  const rebuilt = [];
  let paragraph = '';
  const flushParagraph = () => {
    if (!paragraph) return;
    rebuilt.push(paragraph);
    paragraph = '';
  };
  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      if (rebuilt[rebuilt.length - 1] !== '') rebuilt.push('');
      return;
    }
    if (blockLike(line)) {
      flushParagraph();
      rebuilt.push(line);
      return;
    }
    if (!paragraph) {
      paragraph = trimmed;
      return;
    }
    paragraph += ` ${trimmed}`;
  });
  flushParagraph();
  return rebuilt.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

function appendChatText(parent, role, text) {
  if (text == null || text === '') return null;
  const normalized = (role === 'assistant' || role === 'system' || role === 'error') ? normalizeAssistantText(text) : String(text);
  if (typeof marked !== 'undefined' && (role === 'assistant' || role === 'system' || role === 'error')) {
    const el = document.createElement('div');
    el.className = 'chat-bubble-text markdown-body';
    el.innerHTML = marked.parse(normalized);
    parent.appendChild(el);
    return el;
  }
  return appendText(parent, 'div', 'chat-bubble-text', normalized);
}

function looksLikeInternalResultMessage(event, text = '') {
  const type = String(event?.type || '').toLowerCase();
  if (!(type.includes('result') || type.includes('assistant_message') || type === 'final')) return false;
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  if (data.exit_code != null || data.tool || data.command) return true;
  if (type.includes('task_completed')) return true;
  const normalized = normalizeAssistantText(text).trim();
  if (!normalized) return true;
  if (normalized.length > 140 || normalized.includes('\n\n')) return false;
  return /^(workspace indexed|shell exited|listed\b|listing\b|read\b|wrote\b|written\b|saved\b|created\b|updated\b|deleted\b|renamed\b|moved\b|copied\b|built\b|tested\b|formatted\b|indexed\b|downloaded\b|uploaded\b|complete\b|done\b)/i.test(normalized);
}

function updateLatestAssistantReply(event, text = '') {
  const normalized = normalizeAssistantText(text).trim();
  if (!normalized) return;
  latestAssistantReplyState = {
    eventId: event?.id || '',
    taskId: event?.task_id || '',
    sessionId: event?.session_id || selectedSession?.id || '',
    text: normalized,
    createdAt: event?.created_at || new Date().toISOString(),
  };
  renderComposerReplyActions();
}

function getLatestAssistantReply() {
  return latestAssistantReplyState;
}

async function copyReplyText(text) {
  await navigator.clipboard.writeText(String(text || ''));
  emitUiEvent('reply_copied', 'Assistant reply copied to clipboard.', {text_length: String(text || '').length});
}

function replyFeedbackStorageKey(reply) {
  return `pac_reply_feedback:${reply?.sessionId || ''}:${reply?.eventId || ''}`;
}

function currentReplyFeedback(reply) {
  try { return localStorage.getItem(replyFeedbackStorageKey(reply)) || ''; } catch { return ''; }
}

function setReplyFeedback(reply, value) {
  try { localStorage.setItem(replyFeedbackStorageKey(reply), value); } catch {}
  emitUiEvent('reply_feedback_recorded', `Recorded ${value === 'up' ? 'thumbs up' : 'thumbs down'} for the latest reply.`, {session_id: reply?.sessionId, event_id: reply?.eventId, feedback: value});
  renderComposerReplyActions();
}

async function shareReply(reply) {
  const shareUrl = `${location.origin}${location.pathname}#session=${encodeURIComponent(reply?.sessionId || selectedSession?.id || '')}&event=${encodeURIComponent(reply?.eventId || '')}`;
  const payload = `${reply?.text || ''}\n\nShared from PAC session ${reply?.sessionId || selectedSession?.id || ''}\n${shareUrl}`;
  await navigator.clipboard.writeText(payload);
  emitUiEvent('reply_shared', 'Share text copied to clipboard.', {session_id: reply?.sessionId, event_id: reply?.eventId});
}

async function regenerateLatestReply() {
  const reply = getLatestAssistantReply();
  if (!selectedSession?.id || !reply?.taskId) throw new Error('No recent assistant reply is available to regenerate.');
  const prompt = sessionTaskPrompts.get(reply.taskId);
  if (!prompt) throw new Error('The original prompt for this reply is no longer available.');
  await createSessionTask(selectedSession.id, prompt, {});
}

async function branchLatestReplyToNewSession() {
  const reply = getLatestAssistantReply();
  if (!selectedSession?.id || !reply?.text) throw new Error('No assistant reply is available to branch from.');
  const endpointId = selectedSession.metadata?.preferred_endpoint || '';
  const workspace = selectedSession.workspace_path
    ? {type:'local', path:selectedSession.workspace_path}
    : {type:'profile', profile:selectedSession.workspace_profile || null};
  const payload = {
    name: `${selectedSession.name || 'session'}-branch`,
    agent_profile: selectedSession.agent_profile || null,
    permission_profile: selectedSession.permission_profile || null,
    context_mode: selectedSession.context_mode || null,
    workspace,
    tools: [],
    metadata: {
      preferred_endpoint: endpointId,
      endpoint_locked: !!endpointId,
      agent_enabled: selectedSession.metadata?.agent_enabled !== false,
      execution_mode: selectedSession.metadata?.execution_mode || 'pi.dev',
    },
  };
  if (selectedSession.model) payload.model = selectedSession.model;
  const session = await api('/v1/sessions', {method:'POST', body:JSON.stringify(payload)});
  await loadSessions();
  await selectSession(session.id);
  taskPrompt.value = `Branch from this previous reply and continue the work:\n\n${reply.text}\n\nContinue from here.`;
  autosizeSessionPrompt();
  taskPrompt.focus();
  emitUiEvent('reply_branched', `Created branch session ${session.name || session.id}.`, {source_session: selectedSession?.id, branch_session: session.id});
}

function ensureComposerReplyActions() {
  const composer = document.querySelector('.session-composer.chatgpt-composer');
  if (!composer) return null;
  let row = document.getElementById('composerReplyActions');
  if (row) return row;
  row = document.createElement('div');
  row.id = 'composerReplyActions';
  row.className = 'composer-reply-actions';
  row.hidden = true;
  composer.appendChild(row);
  return row;
}

function renderComposerReplyActions() {
  const row = ensureComposerReplyActions();
  if (!row) return;
  const reply = getLatestAssistantReply();
  if (!reply?.text) {
    row.hidden = true;
    row.innerHTML = '';
    return;
  }
  const feedback = currentReplyFeedback(reply);
  row.hidden = false;
  row.innerHTML = `
    <button type="button" class="reply-action-button" data-reply-action="copy" title="Copy reply" aria-label="Copy reply">⧉</button>
    <button type="button" class="reply-action-button${feedback === 'up' ? ' active' : ''}" data-reply-action="up" title="Thumbs up" aria-label="Thumbs up">▲</button>
    <button type="button" class="reply-action-button${feedback === 'down' ? ' active' : ''}" data-reply-action="down" title="Thumbs down" aria-label="Thumbs down">▼</button>
    <button type="button" class="reply-action-button" data-reply-action="share" title="Share reply" aria-label="Share reply">↗</button>
    <button type="button" class="reply-action-button" data-reply-action="refresh" title="Regenerate reply" aria-label="Regenerate reply">↻</button>
    <button type="button" class="reply-action-button" data-reply-action="branch" title="Branch into new chat" aria-label="Branch into new chat">⑂</button>
  `;
  row.querySelectorAll('[data-reply-action]').forEach((btn) => {
    const glyphs = {copy:'⧉', up:'▲', down:'▼', share:'↗', refresh:'↻', branch:'⑂'};
    const action = btn.dataset.replyAction || '';
    if (glyphs[action]) btn.textContent = glyphs[action];
  });
  row.querySelectorAll('[data-reply-action]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        const action = btn.dataset.replyAction || '';
        if (action === 'copy') await copyReplyText(reply.text);
        else if (action === 'up') setReplyFeedback(reply, 'up');
        else if (action === 'down') setReplyFeedback(reply, 'down');
        else if (action === 'share') await shareReply(reply);
        else if (action === 'refresh') await regenerateLatestReply();
        else if (action === 'branch') await branchLatestReplyToNewSession();
      } catch (error) {
        paneError('Reply action failed', error.message || String(error));
      }
    };
  });
}

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
    t.includes('model_response') || t.includes('agent_plan') || t.includes('workspace_indexed') ||
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
    if (data.action_type === 'final') return '';
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
  if (type.includes('agent_routing')) return event?.message || 'Routing the request';
  if (type.includes('agent_intent')) return sessionThinkingSummary(event, block) || event?.message || 'Working on the request';
  return '';
}

function modelIntermediateResponseText(event, block = null) {
  const type = String(event?.type || '').toLowerCase();
  if (!type.includes('model_response')) return '';
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

function sessionThinkingDetailsHtml(events) {
  const rows = (events || []).filter(item => item?.event && isInternalSessionEvent(item.event));
  if (!rows.length) return '<div class="tool-activity-empty">No internal activity was recorded for this answer.</div>';
  const first = rows[0]?.event;
  const last = rows[rows.length - 1]?.event;
  const start = formatEventTime(first?.created_at);
  const end = formatEventTime(last?.created_at);
  const modelNotes = thinkingGroupIntermediateResponses({events: rows}, 6);
  const notesHtml = modelNotes.length
    ? `<div class="thought-modal-intermediates"><div class="thought-modal-section-title">Model updates shown during the run</div>${modelNotes.map((item, index) => `<div class="thought-modal-intermediate"><span class="thought-modal-plan-index">${index + 1}</span><div class="thought-modal-intermediate-text">${escapeHtml(item.text)}</div></div>`).join('')}</div>`
    : '<div class="tool-activity-empty">No user-facing model updates were produced during this run. Raw model responses remain available in the full session log.</div>';
  return `${notesHtml}<div class="tool-activity-empty">Tool output, stdout, stderr, and raw diagnostics are kept in the full session log.</div><div class="tool-activity-list"><div class="tool-activity-item"><summary><span class="tool-activity-icon">⌁</span><span class="tool-activity-title">Internal events recorded</span><span class="tool-activity-status">${rows.length}</span><span class="tool-activity-time">${escapeHtml(start)} → ${escapeHtml(end)}</span></summary></div></div>`;
}

function openSessionThinkingModal(group) {
  const modal = document.getElementById('sessionEventModal');
  if (!modal || !group) return;
  const title = document.getElementById('sessionEventModalTitle');
  const body = document.getElementById('sessionEventModalBody');
  const duration = formatDurationMs(((group.endedAt || new Date()).getTime()) - (group.startedAt || new Date()).getTime());
  if (title) title.textContent = group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`;
  if (body) {
    body.className = 'modal-scroll-output tool-activity-modal';
    const planSteps = deriveThinkingPlanSteps(group);
    const summary = escapeHtml(group.summary || (group.closed ? 'Completed' : 'Working on the request'));
    body.innerHTML = `
      <div class="thought-modal-summary">
        <div class="thought-modal-kicker">${escapeHtml(group.closed ? 'Completed thought process' : 'Current thought process')}</div>
        <div class="thought-modal-title">${summary}</div>
        <div class="thought-modal-meta">
          <span>${thinkingGroupToolCount(group)} ${thinkingGroupToolCount(group) === 1 ? 'tool/event' : 'tool/events'}</span>
          <span>${escapeHtml(thinkingGroupNeedsApproval(group) ? 'Awaiting approval' : group.closed ? 'Completed' : 'Active')}</span>
        </div>
      </div>
      ${planSteps.length ? `<div class="thought-modal-plan"><div class="thought-modal-section-title">Work plan</div>${planSteps.map((step, index) => `<div class="thought-modal-plan-item ${escapeHtml(step.status)}"><span class="thought-modal-plan-index">${index + 1}</span><span class="thought-modal-plan-label">${escapeHtml(step.label)}</span><span class="thought-modal-plan-state">${escapeHtml(step.status === 'running' ? 'Active' : step.status === 'attention' ? 'Needs approval' : step.status === 'failed' ? 'Failed' : step.status === 'planned' ? 'Planned' : 'Done')}</span></div>`).join('')}</div>` : ''}
      ${sessionThinkingDetailsHtml(group.events || [])}`;
  }
  bindSessionEventModalChrome();
  modal.hidden = false;
}

function thinkingGroupToolCount(group) {
  return (group?.events || []).filter((item) => {
    const t = String(item?.event?.type || '').toLowerCase();
    return t.includes('tool') || t.includes('command') || t.includes('stdout') || t.includes('stderr') || t.includes('web_');
  }).length;
}

function thinkingGroupNeedsApproval(group) {
  const event = group?.lastEvent;
  return !!event && String(event.type || '').toLowerCase().includes('approval_required');
}

function extractWorkPlanStepsFromText(text) {
  const raw = String(text || '').trim();
  if (!raw) return [];
  const normalized = raw.replace(/\r/g, '');
  const candidates = [];
  normalized.split('\n').forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const match = trimmed.match(/^(?:[-*•]|\d+[.)]|\[[ xX-]\])\s*(.+)$/);
    if (match && match[1]) candidates.push(match[1].trim());
  });
  if (!candidates.length && /\b\d+[.)]\s+/.test(normalized)) {
    const inline = normalized.split(/(?=\b\d+[.)]\s+)/g)
      .map((part) => part.replace(/^\d+[.)]\s*/, '').trim())
      .filter(Boolean);
    candidates.push(...inline);
  }
  return candidates
    .map((label) => label.replace(/^(plan|step|task)\s*[:：-]\s*/i, '').trim())
    .filter((label) => label && label.length > 3)
    .slice(0, 8)
    .map((label) => ({label, status: 'planned', time: ''}));
}

function deriveThinkingPlanSteps(group) {
  const rows = Array.isArray(group?.events) ? group.events : [];
  const planEvents = rows.filter((item) => String(item?.event?.type || '').toLowerCase().includes('agent_plan'));
  const steps = [];
  planEvents.forEach((item) => {
    const data = item?.event?.data && typeof item.event.data === 'object' ? item.event.data : {};
    const explicit = Array.isArray(data.steps) ? data.steps : Array.isArray(data.plan_steps) ? data.plan_steps : [];
    explicit.forEach((step) => {
      if (typeof step === 'string') steps.push({label: step.trim(), status: 'planned', time: item.event?.created_at || ''});
      else if (step && typeof step === 'object') steps.push({label: String(step.label || step.title || step.summary || '').trim(), status: String(step.status || 'planned').toLowerCase(), time: item.event?.created_at || ''});
    });
    const text = String(data.plan || data.summary || item?.event?.message || timelineText(item.event, item.block) || '').trim();
    extractWorkPlanStepsFromText(text).forEach((step) => steps.push({...step, time: item.event?.created_at || ''}));
  });
  const deduped = [];
  const seen = new Set();
  for (const step of steps) {
    const label = String(step.label || '').trim();
    if (!label) continue;
    const key = label.toLowerCase().replace(/\s+/g, ' ');
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push({label, status: step.status || 'planned', time: step.time || ''});
  }
  return deduped.slice(0, 8);
}

async function resolveSessionApproval(taskId, approved) {
  if (!taskId) return;
  if (approved) await api(`/v1/tasks/${taskId}/approve`, {method:'POST'});
  else await api(`/v1/tasks/${taskId}/reject?reason=Rejected`, {method:'POST'});
  removeSessionApprovalRow(taskId);
  if (approved) addPendingRow(taskId);
  await loadSessions().catch(()=>{});
  if (selectedSession?.id) await pollSessionEvents(selectedSession.id).catch(()=>{});
  await loadApprovals().catch(()=>{});
}

function updateSessionThinkingRow(group) {
  if (!group?.row) return;
  const event = group.lastIntentEvent || group.lastEvent || group.events?.[group.events.length - 1]?.event;
  const endAt = group.endedAt || new Date();
  const startAt = group.startedAt || sessionEventDate(event) || new Date();
  const duration = formatDurationMs(endAt.getTime() - startAt.getTime());
  const approvalPending = thinkingGroupNeedsApproval(group);
  const taskId = event?.task_id || group.taskId || '';
  const headline = group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`;
  const currentIntent = group.summary || sessionIntentSummary(event, null) || '';
  const latestIntermediate = thinkingGroupLatestIntermediate(group);
  const prompt = taskId ? sessionTaskPrompts.get(taskId) : '';
  const fallbackMessage = currentIntent || prompt || (group.closed ? 'Finished working on the request.' : 'Working on the request.');
  const workMessage = latestIntermediate?.text || fallbackMessage;
  group.row.className = 'chat-message-row assistant thought-history-row assistant-work-row';
  group.row.innerHTML = '';
  const bubble = document.createElement('div');
  bubble.className = `thought-history-line assistant-work-progress ${group.closed ? 'closed' : 'active'}`;
  bubble.innerHTML = `
    <div class="assistant-work-message">${escapeHtml(workMessage)}</div>
    ${currentIntent ? `<div class="assistant-work-intent">${escapeHtml(currentIntent)}</div>` : ''}
    <button type="button" class="thought-history-main assistant-work-disclosure" aria-label="Open thought details" title="Open thought details">
      <span class="thought-history-dot">${group.closed ? '✓' : '<span class="tiny-spinner square" aria-hidden="true"></span>'}</span>
      <span class="thought-history-intent">${escapeHtml(headline)}</span>
      <span class="composer-thinking-chevron">›</span>
    </button>
    ${approvalPending ? '<div class="thought-history-note attention">Awaiting approval</div>' : ''}`;
  const main = bubble.querySelector('.thought-history-main');
  if (main) {
    main.onclick = () => openSessionThinkingModal(group);
    main.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openSessionThinkingModal(group); } };
  }
  group.row.appendChild(bubble);
  if (approvalPending && taskId) {
    const actions = document.createElement('div');
    actions.className = 'thought-actions';
    const approve = document.createElement('button');
    approve.type = 'button';
    approve.className = 'thought-action approve';
    approve.textContent = 'Approve';
    approve.onclick = async (ev) => {
      ev.stopPropagation();
      await resolveSessionApproval(taskId, true);
    };
    const reject = document.createElement('button');
    reject.type = 'button';
    reject.className = 'thought-action reject';
    reject.textContent = 'Reject';
    reject.onclick = async (ev) => {
      ev.stopPropagation();
      await resolveSessionApproval(taskId, false);
    };
    actions.append(approve, reject);
    bubble.appendChild(actions);
  }
}

function ensureSessionThinkingGroup(event) {
  const taskId = event?.task_id || '';
  let group = getThinkingGroup(taskId);
  if (!group || group.closed || (taskId && group.taskId !== taskId)) {
    const el = document.getElementById('events');
    const row = document.createElement('article');
    row.className = 'chat-message-row assistant thought-history-row';
    if (el) el.appendChild(row);
    group = {events: [], startedAt: taskStartEventForThinking(event) ? sessionEventDate(event) : null, endedAt: null, row, closed: false, taskId, summary: ''};
  }
  if (!group.startedAt && taskStartEventForThinking(event)) group.startedAt = sessionEventDate(event);
  if (!group.startedAt) group.startedAt = sessionEventDate(event);
  if (!group.taskId && taskId) group.taskId = taskId;
  if (taskId) sessionThinkingGroups.set(taskId, group);
  removePendingRow(taskId);
  return group;
}

function flushSessionThinkingGroup(endEvent) {
  const group = getThinkingGroup(endEvent?.task_id || '');
  if (!group || group.closed) return;
  if (!group.events.length && endEvent) {
    group.events.push({event: endEvent, block: normalizeTimelineBlock(endEvent)});
    group.lastEvent = endEvent;
  }
  if (!group.events.length) return;
  group.closed = true;
  group.endedAt = endEvent ? sessionEventDate(endEvent) : new Date();
  updateSessionThinkingRow(group);
}

function openSessionEventModal(event, block) {
  const modal = document.getElementById('sessionEventModal');
  if (!modal) return;
  const title = document.getElementById('sessionEventModalTitle');
  const body = document.getElementById('sessionEventModalBody');
  if (title) title.textContent = prettyEventType(event?.type || 'reply details');
  if (body) {
    body.className = 'modal-scroll-output';
    body.textContent = sessionEventDetailsText(event, block);
  }
  bindSessionEventModalChrome();
  modal.hidden = false;
}

function closeSessionEventModal() {
  const modal = document.getElementById('sessionEventModal');
  if (modal) modal.hidden = true;
}

function bindSessionEventModalChrome() {
  const modal = document.getElementById('sessionEventModal');
  const closeButton = document.getElementById('closeSessionEventModal');
  if (closeButton && !closeButton.dataset.sessionCloseBound) {
    closeButton.dataset.sessionCloseBound = '1';
    closeButton.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      closeSessionEventModal();
    });
  }
  if (modal && !modal.dataset.sessionBackdropBound) {
    modal.dataset.sessionBackdropBound = '1';
    modal.addEventListener('click', (ev) => {
      if (ev.target === modal) closeSessionEventModal();
    });
  }
  if (!window.__pacSessionEventEscapeBound) {
    window.__pacSessionEventEscapeBound = true;
    window.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && modal && !modal.hidden) closeSessionEventModal();
    });
  }
}


function timelineText(event, block) {
  if (block) {
    const parts = [block.title, block.summary].filter(Boolean);
    if (Array.isArray(block.steps)) parts.push(...block.steps.map(s => [s.label || s.title, s.detail || s.message].filter(Boolean).join(': ')));
    if (block.output || block.code || block.diff) parts.push(block.output || block.code || block.diff);
    return parts.filter(Boolean).join('\n');
  }
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  if (event.message) lines.push(event.message);
  if (typeof data.message === 'string' && data.message.trim()) lines.push(data.message);
  if (typeof data.text === 'string' && data.text.trim()) lines.push(data.text);
  if (typeof data.content === 'string' && data.content.trim()) lines.push(data.content);
  if (typeof data.response === 'string' && data.response.trim()) lines.push(data.response);
  if (typeof data.answer === 'string' && data.answer.trim()) lines.push(data.answer);
  if (typeof data.output_text === 'string' && data.output_text.trim()) lines.push(data.output_text);
  if (data.result && typeof data.result === 'object') {
    if (typeof data.result.message === 'string' && data.result.message.trim()) lines.push(data.result.message);
    if (typeof data.result.output === 'string' && data.result.output.trim()) lines.push(data.result.output);
    if (typeof data.result.response === 'string' && data.result.response.trim()) lines.push(data.result.response);
  }
  if (Array.isArray(data.content)) {
    const contentText = data.content.map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') return item.text || item.content || item.value || '';
      return '';
    }).filter(Boolean).join('\n');
    if (contentText) lines.push(contentText);
  }
  if (data.command) lines.push(`$ ${data.command}`);
  if (data.tool) lines.push(`tool: ${data.tool}`);
  if (data.output) lines.push(String(data.output));
  if (data.summary && !lines.includes(String(data.summary))) lines.push(String(data.summary));
  if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
  if (data.exit_code != null) lines.push(`exit code: ${data.exit_code}`);
  return [...new Set(lines.map((line) => String(line || '').trim()).filter(Boolean))].join('\n').trim();
}

function sessionEventDate(event) {
  try { return new Date(event?.created_at || Date.now()); } catch { return new Date(); }
}

function formatDurationMs(ms) {
  const safe = Math.max(0, Number(ms) || 0);
  const totalSeconds = Math.floor(safe / 1000);
  if (totalSeconds < 1) return '0s';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function sessionEventMetaLines(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const lines = [];
  const model = data.model || data.session_model || selectedSession?.model;
  const endpoint = data.endpoint_name || endpointDisplayName(data.endpoint_id || data.runner_id || selectedSession?.metadata?.preferred_endpoint);
  const profile = data.agent_profile || selectedSession?.agent_profile;
  if (model) lines.push(`Model: ${model}`);
  if (endpoint) lines.push(`Endpoint: ${endpoint}`);
  if (profile) lines.push(`Profile: ${profile}`);
  if (data.execution_mode) lines.push(`Execution: ${data.execution_mode}`);
  if (data.command) lines.push(`Command: ${data.command}`);
  if (event?.task_id) lines.push(`Task: ${event.task_id}`);
  return lines;
}

function removePendingRow(taskId) {
  if (!taskId) return;
  const group = sessionThinkingGroups.get(taskId);
  if (group?.events?.length || group?.closed) {
    sessionPendingRows.delete(taskId);
    return;
  }
  const row = sessionPendingRows.get(taskId);
  if (row && row.parentElement) row.remove();
  sessionPendingRows.delete(taskId);
}

function removeSessionApprovalRow(taskId) {
  if (!taskId) return;
  const row = sessionApprovalRows.get(taskId);
  if (row && row.parentElement) row.remove();
  sessionApprovalRows.delete(taskId);
}

async function refreshSessionRunButton() {
  const btn = document.getElementById('runTask');
  if (!btn) return;
  if (!selectedSession?.id) {
    activeSessionTaskId = null;
    btn.dataset.mode = 'send';
    btn.textContent = '➤';
    btn.title = 'Send';
    btn.setAttribute('aria-label', 'Send');
    btn.classList.remove('stop-mode');
    btn.disabled = false;
    return;
  }
  if (sessionRunButtonRequest) return sessionRunButtonRequest;
  sessionRunButtonRequest = (async () => {
    try {
      const tasks = await api(`/v1/sessions/${selectedSession.id}/tasks`);
      const ordered = (tasks || []).slice().sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
      const latest = ordered[0] || null;
      const latestStatus = String(latest?.status || '');
      const latestIsActive = ['queued', 'running', 'approval_required'].includes(latestStatus);
      activeSessionTaskId = latestIsActive ? (latest?.id || null) : null;
      if (activeSessionTaskId) {
        btn.dataset.mode = 'stop';
        btn.textContent = '■';
        btn.title = 'Stop';
        btn.setAttribute('aria-label', 'Stop');
        btn.classList.add('stop-mode');
      } else {
        btn.dataset.mode = 'send';
        btn.textContent = '➤';
        btn.title = 'Send';
        btn.setAttribute('aria-label', 'Send');
        btn.classList.remove('stop-mode');
      }
      btn.disabled = false;
    } catch (_) {
    } finally {
      sessionRunButtonRequest = null;
    }
  })();
  return sessionRunButtonRequest;
}

async function stopActiveSessionTask() {
  if (!selectedSession?.id) return;
  if (!activeSessionTaskId) {
    await refreshSessionRunButton().catch(()=>{});
  }
  if (!activeSessionTaskId) return;
  await api(`/v1/tasks/${activeSessionTaskId}/stop`, {method:'POST'});
  await pollSessionEvents(selectedSession.id).catch(()=>{});
  await loadSessions().catch(()=>{});
  await refreshSessionRunButton().catch(()=>{});
}

function approvalPurpose(event) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  return data.command || data.path || data.url || data.query || event?.message || 'Requested action';
}

function renderSessionApprovalRow(event) {
  const el = document.getElementById('events');
  const taskId = event?.task_id || '';
  if (!el || !taskId || sessionApprovalRows.has(taskId)) return;
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const reason = data.reason || '';
  const row = document.createElement('article');
  row.className = 'chat-message-row system approval-row';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble warning approval-bubble';
  bubble.innerHTML = `<div class="chat-bubble-meta"><span>Permission needed</span><span>${escapeHtml(formatEventTime(event.created_at))}</span></div>
    <div class="chat-bubble-text">
      <div class="approval-purpose">${escapeHtml(approvalPurpose(event))}</div>
      ${reason ? `<div class="approval-reason">${escapeHtml(reason)}</div>` : ''}
    </div>`;
  const actions = document.createElement('div');
  actions.className = 'approval-actions';
  const approve = document.createElement('button');
  approve.type = 'button';
  approve.className = 'thought-action approve';
  approve.textContent = 'Approve';
  approve.onclick = async () => { approve.disabled = true; reject.disabled = true; await resolveSessionApproval(taskId, true); };
  const reject = document.createElement('button');
  reject.type = 'button';
  reject.className = 'thought-action reject';
  reject.textContent = 'Reject';
  reject.onclick = async () => { approve.disabled = true; reject.disabled = true; await resolveSessionApproval(taskId, false); };
  actions.append(approve, reject);
  bubble.appendChild(actions);
  row.appendChild(bubble);
  sessionApprovalRows.set(taskId, row);
  el.appendChild(row);
  scrollSessionToBottom();
}

function syncSessionPermissionQuick() {
  const select = document.getElementById('sessionPermissionQuick');
  const button = document.getElementById('applySessionPermission');
  const usageButton = document.getElementById('downloadSessionUsage');
  const diagButton = document.getElementById('downloadSessionDiagnostics');
  if (usageButton) usageButton.disabled = !selectedSession?.id;
  if (diagButton) diagButton.disabled = !selectedSession?.id;
  if (!select || !button) return;
  const profiles = Object.keys(config?.permission_profiles || {});
  select.innerHTML = '';
  if (!selectedSession) {
    opt(select, '', 'No session');
    select.disabled = true;
    button.disabled = true;
    return;
  }
  profiles.forEach((name) => opt(select, name, name));
  select.value = selectedSession.permission_profile || profiles[0] || '';
  select.disabled = !profiles.length;
  button.disabled = !profiles.length || select.value === (selectedSession.permission_profile || '');
}

function ensureSessionWorkspaceChrome() {
  const layout = document.querySelector('#sessions-tab .session-chat-layout');
  const main = document.querySelector('#sessions-tab .session-chat-main');
  if (!layout || !main) return;
  layout.classList.remove('single');
  layout.classList.add('with-sidebar');
  let sidebar = document.querySelector('#sessions-tab .sessions-list-card');
  if (!sidebar) {
    sidebar = document.createElement('aside');
    sidebar.className = 'sessions-list-card';
    sidebar.innerHTML = `<div class="section-heading compact-heading sidebar-heading"><div><h3>Sessions</h3><p class="muted">Select or reopen a session quickly.</p></div><div class="sidebar-heading-actions"></div></div><div id="sessionSidebarList" class="session-sidebar-list muted">No sessions yet.</div>`;
    layout.insertBefore(sidebar, main);
  }
  const pickerWrap = document.querySelector('#sessions-tab .session-picker-wrap');
  if (pickerWrap) pickerWrap.style.display = 'none';
  const sessionMeta = document.querySelector('#sessions-tab .session-session-meta');
  if (sessionMeta) sessionMeta.style.display = 'none';
  const sidebarActions = sidebar.querySelector('.sidebar-heading-actions');
  const openButton = document.getElementById('openSessionModal');
  if (sidebarActions && openButton && openButton.parentElement !== sidebarActions) {
    sidebarActions.appendChild(openButton);
    openButton.classList.add('sidebar-create-session');
  }
  const topQuick = document.querySelector('#sessions-tab .session-quick-controls');
  if (topQuick) topQuick.style.display = 'none';
  const controls = document.querySelector('#sessions-tab .composer-controls.integrated.editor-like');
  const permissionSelect = document.getElementById('sessionPermissionQuick');
  const permissionApply = document.getElementById('applySessionPermission');
  const composerLeftActions = document.querySelector('#sessions-tab .composer-left-actions');
  if (controls && permissionSelect && permissionApply && composerLeftActions && permissionSelect.parentElement !== composerLeftActions) {
    composerLeftActions.appendChild(permissionSelect);
    composerLeftActions.appendChild(permissionApply);
    permissionSelect.title = 'Permissions';
    permissionSelect.classList.add('composer-permission-select');
    permissionApply.classList.add('mini-apply-button', 'composer-mini-button');
  }
  if (!document.getElementById('composerFileInput')) {
    const input = document.createElement('input');
    input.id = 'composerFileInput';
    input.type = 'file';
    input.multiple = true;
    input.hidden = true;
    main.appendChild(input);
  }
  if (!document.getElementById('composerDirectoryInput')) {
    const input = document.createElement('input');
    input.id = 'composerDirectoryInput';
    input.type = 'file';
    input.multiple = true;
    input.hidden = true;
    input.setAttribute('webkitdirectory', '');
    input.setAttribute('directory', '');
    main.appendChild(input);
  }
  const fileInput = document.getElementById('composerFileInput');
  if (fileInput && !fileInput.dataset.bound) {
    fileInput.addEventListener('change', async (ev) => {
      const input = ev.currentTarget;
      const files = Array.from(input.files || []);
      if (files.length) await appendSelectedFilesToPrompt(files, 'Attached files');
      input.value = '';
      input.accept = '';
    });
    fileInput.dataset.bound = '1';
  }
  const dirInput = document.getElementById('composerDirectoryInput');
  if (dirInput && !dirInput.dataset.bound) {
    dirInput.addEventListener('change', async (ev) => {
      const input = ev.currentTarget;
      const files = Array.from(input.files || []);
      if (files.length) await appendSelectedFilesToPrompt(files, 'Attached directory files');
      input.value = '';
    });
    dirInput.dataset.bound = '1';
  }
}

function sessionTimelineNearBottom(el, threshold = 88) {
  if (!el) return true;
  return (el.scrollHeight - el.scrollTop - el.clientHeight) <= threshold;
}

function updateSessionAutoScrollState() {
  const el = document.getElementById('events');
  if (!el) return;
  sessionAutoScrollPinned = sessionTimelineNearBottom(el);
}

function scrollSessionToBottom(force = false) {
  const el = document.getElementById('events');
  if (!el) return;
  if (force || suppressSessionAutoScroll || sessionAutoScrollPinned) el.scrollTop = el.scrollHeight;
  updateSessionAutoScrollState();
}

function bindSessionTimelineScroll() {
  const el = document.getElementById('events');
  if (!el || el.dataset.autoscrollBound) return;
  el.addEventListener('scroll', () => updateSessionAutoScrollState());
  el.dataset.autoscrollBound = '1';
  updateSessionAutoScrollState();
}

function resetSessionTimelineState() {
  sessionThinkingGroups = new Map();
  sessionEventSeen = new Set();
  sessionMessageSeen = new Set();
  sessionPendingRows = new Map();
  sessionApprovalRows = new Map();
  sessionLatestEventId = null;
  sessionHydrationBufferedEvents = [];
}

function getThinkingGroup(taskId) {
  if (taskId && sessionThinkingGroups.has(taskId)) return sessionThinkingGroups.get(taskId);
  const groups = Array.from(sessionThinkingGroups.values());
  return groups.length ? groups[groups.length - 1] : null;
}

function refreshComposerThinkingStatusForTask(taskId='') {
  const group = getThinkingGroup(taskId);
  if (group && Array.isArray(group.events) && group.events.length && !group.closed) {
    const state = deriveComposerThinkingState(group.events.map(item => item?.event).filter(Boolean)) || {};
    state.closed = false;
    state.active = true;
    state.startedAt = group.startedAt || state.startedAt;
    state.summary = group.summary || state.summary || 'Working on the request';
    state.toolCount = thinkingGroupToolCount(group);
    state.approvalPending = thinkingGroupNeedsApproval(group);
    state.planSteps = [];
    state.onOpen = () => openSessionThinkingModal(group);
    renderComposerThinkingStatus(state);
    return;
  }
  renderComposerThinkingStatus(null);
  updateComposerChrome();
}

function renderSessionSnapshotFast(snapshot, sessionId) {
  const timeline = document.getElementById('events');
  if (!timeline) return;
  bindSessionTimelineScroll();
  const events = Array.isArray(snapshot) ? snapshot : [];
  renderComposerThinkingStatus(deriveComposerThinkingState(events));
  const recentChunkSize = 220;
  const tail = events.slice(-recentChunkSize);
  const token = ++sessionHydrationToken;
  sessionHydrationActiveFor = sessionId;
  const wasPinned = sessionAutoScrollPinned || sessionTimelineNearBottom(timeline, 8);
  const previousBottomOffset = Math.max(0, timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight);
  timeline.innerHTML = tail.length ? '' : '<div class="empty-timeline">No session events yet.</div>';
  resetSessionTimelineState();
  suppressSessionAutoScroll = true;
  tail.forEach((ev) => renderSessionTimelineEvent(ev));
  suppressSessionAutoScroll = false;
  if (wasPinned) timeline.scrollTop = timeline.scrollHeight;
  else timeline.scrollTop = Math.max(0, timeline.scrollHeight - timeline.clientHeight - previousBottomOffset);
  updateSessionAutoScrollState();
  if (selectedSession && selectedSession.id === sessionId && sessionHydrationToken === token) {
    sessionHydrationActiveFor = null;
    sessionHydrationBufferedEvents = [];
  }
}

async function applySessionPermissionProfile() {
  if (!selectedSession?.id) return;
  const select = document.getElementById('sessionPermissionQuick');
  const next = select?.value || '';
  if (!next || next === selectedSession.permission_profile) return;
  const updated = await api(`/v1/sessions/${selectedSession.id}`, {method:'PUT', body:JSON.stringify({permission_profile: next})});
  selectedSession = updated;
  const preferredEndpoint = selectedSession.metadata?.preferred_endpoint || '';
  const endpointName = (window.__pacEndpoints || []).find(e => e.id === preferredEndpoint)?.name || preferredEndpoint || 'PAC/local';
  document.getElementById('selectedSession').innerHTML = `<span class="session-lock-dot"></span><span>Profile: ${escapeHtml(selectedSession.agent_profile || 'default')}</span><span>Permissions: ${escapeHtml(selectedSession.permission_profile || '-')}</span><span>Endpoint: ${escapeHtml(endpointName)}</span><span>Mode: ${escapeHtml(selectedSession.metadata?.execution_mode || (selectedSession.metadata?.agent_enabled === false ? 'direct model' : 'pi.dev'))}</span><span>Model: ${escapeHtml(selectedSession.model || '')}</span><span>${escapeHtml(selectedSession.workspace_path || '')}</span>`;
  if (document.getElementById('sessionEndpointLock')) sessionEndpointLock.textContent = `Profile: ${selectedSession.agent_profile || 'default'} · permissions: ${selectedSession.permission_profile || '-'} · endpoint: ${endpointName} · model: ${selectedSession.model || 'session default'}`;
  syncSessionPermissionQuick();
  updateComposerChrome();
  renderSessionSidebar(window.__pacSessions || []);
  emitUiEvent('session_permission_profile_changed', `Session permissions changed to ${next}`, {session_id: selectedSession.id, permission_profile: next});
}

async function pollSessionEvents(sessionId) {
  if (!sessionId || !selectedSession || selectedSession.id !== sessionId) return;
  if (sessionPollRequest) return sessionPollRequest;
  sessionPollRequest = (async () => {
    try {
      const snapshot = await api(`/v1/sessions/${sessionId}/events/snapshot?latest=true&limit=180`);
      renderSessionSnapshotFast(snapshot || [], sessionId);
    } catch (_) {
    } finally {
      suppressSessionAutoScroll = false;
      sessionPollRequest = null;
    }
  })();
  return sessionPollRequest;
}

function startSessionPolling(sessionId) {
  if (sessionPollingActiveFor === sessionId && sessionPoll) return;
  if (sessionPoll) {
    clearInterval(sessionPoll);
    sessionPoll = null;
  }
  if (!sessionId) return;
  sessionPollingActiveFor = sessionId;
  sessionPoll = setInterval(() => { pollSessionEvents(sessionId).catch(()=>{}); }, 1500);
}

function stopSessionPolling() {
  if (sessionPoll) {
    clearInterval(sessionPoll);
    sessionPoll = null;
  }
  sessionPollingActiveFor = null;
}

function addPendingRow(taskId) {
  // The visible thinking timer starts when PAC begins processing/model work,
  // not when the user submits the message. Keep pending state internal until
  // a task/runtime event arrives.
  if (!taskId) return;
  sessionPendingRows.delete(taskId);
}

function renderSessionTimelineEvent(event, options = {}) {
  const el = document.getElementById('events');
  if (!el || !event) return;
  const prepend = !!options.prepend;
  const typeLower = String(event.type || '').toLowerCase();
  if (event.task_id && activeSessionTaskId && event.task_id === activeSessionTaskId && (typeLower.includes('result') || typeLower.includes('task_completed') || typeLower.includes('task_failed'))) {
    activeSessionTaskId = null;
    refreshSessionRunButton().catch(()=>{});
  }
  if (event.id && sessionEventSeen.has(event.id)) return;
  if (event.id) sessionEventSeen.add(event.id);
  if (isServerBackedEventId(event.id)) sessionLatestEventId = event.id;
  const messageKey = `${event.type || ''}:${event.task_id || ''}:${event.message || ''}`;
  if ((event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message' || event.type === 'final') && sessionMessageSeen.has(messageKey)) return;
  if (event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message' || event.type === 'final') sessionMessageSeen.add(messageKey);
  if (typeLower.includes('task_completed') || typeLower.includes('task_failed') || typeLower.includes('result')) removePendingRow(event.task_id);
  if (typeLower.includes('task_approved') || typeLower.includes('task_rejected') || typeLower.includes('task_completed') || typeLower.includes('task_failed') || typeLower.includes('result')) removeSessionApprovalRow(event.task_id);
  const empty = el.querySelector('.empty-timeline');
  if (empty) empty.remove();
  const block = normalizeTimelineBlock(event);
  const role = sessionEventRole(event);
  const text = timelineText(event, block);
  if (event.type === 'user_message' && event.task_id && text) sessionTaskPrompts.set(event.task_id, String(text));
  const internal = isInternalSessionEvent(event) || looksLikeInternalResultMessage(event, text);
  if (internal && prepend) {
    return;
  }
  if (internal) {
    const group = ensureSessionThinkingGroup(event);
    group.events.push({event, block});
    group.lastEvent = event;
    if (isSessionIntentEvent(event)) {
      const nextSummary = sessionIntentSummary(event, block);
      if (nextSummary) {
        group.summary = nextSummary;
        group.lastIntentEvent = event;
      }
    }
    updateSessionThinkingRow(group);
    refreshComposerThinkingStatusForTask(group.taskId);
    if (typeLower.includes('approval_required')) renderSessionApprovalRow(event);
    if (String(event?.type || '').toLowerCase().includes('task_completed') || String(event?.type || '').toLowerCase().includes('task_failed')) {
      flushSessionThinkingGroup(event);
      refreshComposerThinkingStatusForTask(group.taskId);
    }
    while (el.children.length > 250) el.removeChild(el.firstChild);
    scrollSessionToBottom();
    return;
  }
  if (sessionLifecycleEventIsNoise(event)) return;
  flushSessionThinkingGroup(event);
  refreshComposerThinkingStatusForTask(event.task_id || '');
  const row = document.createElement('article');
  row.className = `chat-message-row ${role}`;
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${eventTone(event.type)}`;
  if (role !== 'assistant') {
    const meta = document.createElement('div');
    meta.className = 'chat-bubble-meta';
    const label = role === 'user' ? 'You' : role === 'error' ? 'Error' : role === 'system' ? 'System' : 'Agent';
    meta.innerHTML = `<span>${escapeHtml(label)}</span><span>${escapeHtml(formatEventTime(event.created_at))}</span>`;
    bubble.appendChild(meta);
  }
  if (!text && role === 'assistant' && !block) return;
  if (text) appendChatText(bubble, role, text);
  if (role === 'assistant') {
    bubble.classList.add('copyable-reply');
    updateLatestAssistantReply(event, text);
  }
  if (false && role === 'user' && event.task_id) addPendingRow(event.task_id);
  if (role === 'assistant' || (block && (block.fields || block.meta || block.links))) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'inline-link-button';
    more.textContent = 'ⓘ';
    more.title = role === 'assistant' ? 'Reply details' : 'Open details';
    more.setAttribute('aria-label', role === 'assistant' ? 'Reply details' : 'Open details');
    more.onclick = () => openSessionEventModal(event, block);
    bubble.appendChild(more);
  }
  if (role === 'assistant' && text) {
    const actions = document.createElement('div');
    actions.className = 'reply-action-row';
    const feedback = currentReplyFeedback({sessionId:event.session_id || selectedSession?.id || '', eventId:event.id || ''});
    actions.innerHTML = `
      <button type="button" class="reply-action-button" data-reply-action="copy" title="Copy reply" aria-label="Copy reply">⧉</button>
      <button type="button" class="reply-action-button${feedback === 'up' ? ' active' : ''}" data-reply-action="up" title="Thumbs up" aria-label="Thumbs up">▲</button>
      <button type="button" class="reply-action-button${feedback === 'down' ? ' active' : ''}" data-reply-action="down" title="Thumbs down" aria-label="Thumbs down">▼</button>
      <button type="button" class="reply-action-button" data-reply-action="share" title="Share reply" aria-label="Share reply">↗</button>
      <button type="button" class="reply-action-button" data-reply-action="refresh" title="Regenerate reply" aria-label="Regenerate reply">↻</button>
      <button type="button" class="reply-action-button" data-reply-action="branch" title="Branch into new chat" aria-label="Branch into new chat">⑂</button>`;
    actions.querySelectorAll('[data-reply-action]').forEach((btn) => {
      btn.onclick = async () => {
        const reply = {eventId: event.id || '', taskId: event.task_id || '', sessionId: event.session_id || selectedSession?.id || '', text: normalizeAssistantText(text), createdAt: event.created_at || new Date().toISOString()};
        try {
          const action = btn.dataset.replyAction || '';
          if (action === 'copy') await copyReplyText(reply.text);
          else if (action === 'up') setReplyFeedback(reply, 'up');
          else if (action === 'down') setReplyFeedback(reply, 'down');
          else if (action === 'share') await shareReply(reply);
          else if (action === 'refresh') await regenerateLatestReply();
          else if (action === 'branch') await branchLatestReplyToNewSession();
        } catch (error) {
          paneError('Reply action failed', error.message || String(error));
        }
      };
    });
    actions.querySelectorAll('[data-reply-action]').forEach((btn) => {
      const glyphs = {copy:'⧉', up:'▲', down:'▼', share:'↗', refresh:'↻', branch:'⑂'};
      const action = btn.dataset.replyAction || '';
      if (glyphs[action]) btn.textContent = glyphs[action];
    });
    bubble.appendChild(actions);
  }
  row.appendChild(bubble);
  if (prepend && el.firstChild) el.insertBefore(row, el.firstChild);
  else el.appendChild(row);
  while (el.children.length > 250) el.removeChild(el.firstChild);
  if (!prepend) scrollSessionToBottom();
}

function syncSessionPermissionQuick() {
  const select = document.getElementById('sessionPermissionQuick');
  const button = document.getElementById('applySessionPermission');
  const usageButton = document.getElementById('downloadSessionUsage');
  const diagButton = document.getElementById('downloadSessionDiagnostics');
  if (usageButton) usageButton.disabled = !selectedSession?.id;
  if (diagButton) diagButton.disabled = !selectedSession?.id;
  if (!select || !button) return;
  const profiles = Object.keys(config?.permission_profiles || {});
  select.innerHTML = '';
  if (!selectedSession) {
    opt(select, '', 'No session');
    select.disabled = true;
    button.disabled = true;
    return;
  }
  profiles.forEach((name) => opt(select, name, name));
  select.value = selectedSession.permission_profile || profiles[0] || '';
  const locked = !!selectedSession?.metadata?.system_context;
  select.disabled = !profiles.length || locked;
  button.disabled = !profiles.length || locked || select.value === (selectedSession.permission_profile || '');
  if (locked) select.title = 'PAC/core uses a locked permission profile.';
  else select.title = 'Permissions';
}

async function applySessionPermissionProfile() {
  if (!selectedSession?.id || selectedSession?.metadata?.system_context) return;
  const select = document.getElementById('sessionPermissionQuick');
  const next = select?.value || '';
  if (!next || next === selectedSession.permission_profile) return;
  const updated = await api(`/v1/sessions/${selectedSession.id}`, {method:'PUT', body:JSON.stringify({permission_profile: next})});
  selectedSession = updated;
  renderSelectedSessionSummary(selectedSession);
  syncSessionPermissionQuick();
  updateComposerChrome();
  renderSessionSidebar(window.__pacSessions || []);
  emitUiEvent('session_permission_profile_changed', `Session permissions changed to ${next}`, {session_id: selectedSession.id, permission_profile: next});
}

function openSessionModal() {
  const modal = document.getElementById('sessionModal');
  applySessionBootstrapMode();
  sessionWizardStepIndex = 0;
  renderSessionWizard();
  if (modal) { modal.hidden = false; setTimeout(() => document.getElementById('sessionName')?.focus(), 0); }
}

function closeSessionModal() {
  const modal = document.getElementById('sessionModal');
  if (modal) modal.hidden = true;
}
const SESSION_WIZARD_STEPS = ['Basics', 'Source', 'Runtime', 'Review'];

function renderSessionWizard() {
  const panes = Array.from(document.querySelectorAll('.session-wizard-pane'));
  panes.forEach((pane, index) => { pane.hidden = index !== sessionWizardStepIndex; pane.classList.toggle('active', index === sessionWizardStepIndex); });
  const steps = Array.from(document.querySelectorAll('#sessionWizardStepper .wizard-step'));
  steps.forEach((step, index) => step.classList.toggle('active', index === sessionWizardStepIndex));
  const back = document.getElementById('sessionWizardBack');
  const next = document.getElementById('sessionWizardNext');
  const create = document.getElementById('createSession');
  if (back) back.hidden = sessionWizardStepIndex === 0;
  if (next) next.hidden = sessionWizardStepIndex >= SESSION_WIZARD_STEPS.length - 1;
  if (create) create.hidden = sessionWizardStepIndex !== SESSION_WIZARD_STEPS.length - 1;
  updateSessionWizardReview();
}

function updateSessionWizardReview() {
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value || '-'; };
  const contextLabel = document.getElementById('sessionAgentContext')?.selectedOptions?.[0]?.textContent || '';
  const profileLabel = document.getElementById('agentProfile')?.selectedOptions?.[0]?.textContent || '';
  const workspaceMode = document.getElementById('sessionWorkspaceType')?.value || 'profile';
  const workspaceLabel = workspaceMode === 'git'
    ? (document.getElementById('sessionWorkspaceUrl')?.value || '').trim() || 'git repository'
    : workspaceMode === 'local'
      ? (document.getElementById('sessionWorkspacePath')?.value || '').trim() || 'local workspace'
      : (document.getElementById('workspaceProfile')?.selectedOptions?.[0]?.textContent || '');
  const endpointLabel = document.getElementById('sessionEndpoint')?.selectedOptions?.[0]?.textContent || '';
  const permissionLabel = document.getElementById('permissionOverride')?.selectedOptions?.[0]?.textContent || 'profile default';
  const modeLabel = document.getElementById('contextMode')?.value || 'profile default';
  const modelLabel = document.getElementById('modelOverride')?.selectedOptions?.[0]?.textContent || 'profile default';
  set('sessionWizardReviewName', (document.getElementById('sessionName')?.value || '').trim() || 'web-session');
  set('sessionWizardReviewContext', contextLabel || 'none');
  set('sessionWizardReviewProfile', profileLabel || 'none');
  set('sessionWizardReviewWorkspace', workspaceLabel || 'none');
  set('sessionWizardReviewEndpoint', endpointLabel || 'not selected');
  set('sessionWizardReviewPermission', permissionLabel || 'profile default');
  set('sessionWizardReviewMode', modeLabel || 'profile default');
  set('sessionWizardReviewModel', modelLabel || 'profile default');
}

function advanceSessionWizard(delta = 1) {
  sessionWizardStepIndex = Math.max(0, Math.min(SESSION_WIZARD_STEPS.length - 1, sessionWizardStepIndex + delta));
  renderSessionWizard();
}

async function loadSessions() {
  const sessions = await api('/v1/sessions');
  window.__pacSessions = sessions;
  if (selectedIdeSessionId && !sessions.some((session) => session.id === selectedIdeSessionId)) selectedIdeSessionId = '';
  if (sourceCodingSessionId && !sessions.some((session) => session.id === sourceCodingSessionId)) sourceCodingSessionId = '';
  ensureSessionWorkspaceChrome();
  const dashboard = document.getElementById('sessions');
  const picker = document.getElementById('sessionTopSelect');
  if (dashboard) dashboard.innerHTML = '';
  if (picker) picker.innerHTML = '<option value="">Select session</option>';
  if (!sessions.length) {
    selectedSession = null;
    activeSessionTaskId = null;
    if (dashboard) dashboard.innerHTML = '<div class="muted">No sessions yet. Create one from the Sessions page.</div>';
    if (picker) picker.innerHTML = '<option value="">No sessions yet</option>';
    syncSessionPermissionQuick();
  updateComposerChrome();
    refreshSessionRunButton().catch(()=>{});
    renderModelActiveSessionsPanel();
    renderProfileUsagePanel();
    renderWorkspaceActivityPanel();
    renderSessionSidebar([]);
    const composerContext = document.getElementById('composerAgentContext');
    if (composerContext) composerContext.value = selectedIdeContextId || '';
    renderIdeWorkspaceSelectors();
    updateSourceCodingPanel();
    return;
  }
  sessions.slice().reverse().forEach(s => {
    if (picker) {
      const label = `${s.name || s.id} · ${s.agent_profile || 'profile'} · ${s.model || 'model'}`;
      opt(picker, s.id, label);
    }
    if (dashboard) {
      const row = document.createElement('div'); row.className='row session-row';
      row.innerHTML = `<div><b>${s.name || s.id}</b> <span class="pill">${s.status || 'created'}</span><br><span class="muted">${s.agent_profile || '-'} / ${s.model} / ${s.permission_profile}</span><br><span class="muted">${s.workspace_path || ''}</span></div>`;
      const b=document.createElement('button'); b.textContent='Open'; b.onclick=()=>{ switchToTab('sessions-tab'); selectSession(s.id); };
      row.appendChild(b); dashboard.appendChild(row);
    }
  });
  if (picker && selectedSession?.id) picker.value = selectedSession.id;
  renderSessionSidebar(sessions);
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  renderModelActiveSessionsPanel();
  renderProfileUsagePanel();
  renderWorkspaceActivityPanel();
  updateSourceCodingPanel();
}

async function selectSession(id) {
  ensureSessionWorkspaceChrome();
  sessionHydrationToken += 1;
  selectedSession = await api(`/v1/sessions/${id}`);
  const preferredEndpoint = selectedSession.metadata?.preferred_endpoint || '';
  const currentContextId = selectedSessionContextId();
  renderSelectedSessionSummary(selectedSession);
  if (document.getElementById('sessionTopSelect')) sessionTopSelect.value = selectedSession.id;
  if (document.getElementById('composerAgentContext')) composerAgentContext.value = currentContextId || '';
  if (document.getElementById('taskRunner')) taskRunner.value = preferredEndpoint || '';
  syncSessionPermissionQuick();
  updateComposerChrome();
  const timeline = document.getElementById('events');
  if (timeline) timeline.innerHTML = '<div class="empty-timeline">Waiting for session events.</div>';
  renderComposerThinkingStatus(null);
  updateComposerChrome();
  resetSessionTimelineState();
  renderSessionSidebar(window.__pacSessions || []);
  updateSourceCodingPanel();
  try {
    const snapshot = await api(`/v1/sessions/${id}/events/snapshot?latest=true&limit=220`);
    renderSessionSnapshotFast(snapshot, id);
  } catch (_) {
    suppressSessionAutoScroll = false;
  }
  if (source) {
    source.close();
    source = null;
  }
  if (authStatus?.enabled) {
    startSessionPolling(id);
    pollSessionEvents(id).catch(()=>{});
  } else {
    source = new EventSource(`/v1/sessions/${id}/events`);
    source.onerror = () => {
      if (source) {
        source.close();
        source = null;
      }
      startSessionPolling(id);
    };
    source.onmessage = (e) => { try { appendEvent('message', JSON.parse(e.data)); } catch { appendEvent('message', e.data); } };
    ['user_message','agent_routing','agent_intent','agent_plan','task_queued','stdout','stderr','task_started','task_completed','task_failed','approval_required','task_approved','task_rejected','session_created','agent_loop_started','agent_thinking','model_response','tool_call','tool_result','result','final','full_control_enabled','subagent_started'].forEach((t) => source.addEventListener(t, (e) => { try { appendEvent(t, JSON.parse(e.data)); } catch { appendEvent(t, e.data); } }));
    stopSessionPolling();
  }
  await refreshSessionRunButton().catch(()=>{});
}

function appendEvent(type, payload) {
  const event = normalizeEvent(type, payload);
  if (selectedSession?.id && sessionHydrationActiveFor === selectedSession.id) {
    sessionHydrationBufferedEvents.push(event);
  }
  renderSessionTimelineEvent(event);
  renderGlobalEvent(event);
  if (selectedSession?.id && selectedSession.id === event.session_id) {
    const eventType = String(event?.type || '').toLowerCase();
    if (eventType.includes('result') || eventType.includes('task_completed') || eventType.includes('task_failed')) refreshComposerThinkingStatusForTask(event.task_id);
  }
  const eventType = String(event?.type || type || '').toLowerCase();
  if (
    eventType.includes('approval') ||
    eventType.includes('task_queued') ||
    eventType.includes('task_started') ||
    eventType.includes('task_completed') ||
    eventType.includes('task_failed') ||
    eventType.includes('result') ||
    eventType.includes('agent_stop')
  ) {
    loadApprovals().catch(()=>{});
    refreshSessionRunButton().catch(()=>{});
  }
}

async function loadApprovals() {
  if (approvalsRequest) return approvalsRequest;
  approvalsRequest = (async () => {
    const tasks = await api('/v1/tasks/pending-approvals');
    const el = document.getElementById('approvals'); el.innerHTML = '';
    tasks.forEach(t => {
      const row=document.createElement('div'); row.className='row';
      row.innerHTML=`<div><b>${t.command || t.prompt}</b><br><span class="muted">${t.session_id}</span></div>`;
      const a=document.createElement('button'); a.textContent='Approve'; a.onclick=async()=>{await resolveSessionApproval(t.id, true);};
      const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await resolveSessionApproval(t.id, false);};
      row.append(a,r); el.appendChild(row);
    });
  })();
  try {
    return await approvalsRequest;
  } finally {
    approvalsRequest = null;
  }
}
document.getElementById('refresh').onclick=()=>init();
const themeModeSelect = document.getElementById('themeMode');
if (themeModeSelect) themeModeSelect.onchange = () => applyThemeMode(themeModeSelect.value || 'system');
const authTokenInput = document.getElementById('token');
if (authTokenInput) authTokenInput.addEventListener('input', () => renderHeaderAuthBox());
document.getElementById('loginBtn')?.addEventListener('click', () => openLoginModal(authStatus?.needs_setup ? 'setup' : 'login'));
document.getElementById('userChipLogout')?.addEventListener('click', () => {
  document.getElementById('userMenu')?.setAttribute('hidden', '');
  document.getElementById('userChip')?.setAttribute('aria-expanded', 'false');
  document.querySelector('.user-menu-wrap')?.classList.remove('open');
  logoutUser();
});
document.querySelectorAll('.settings-sub-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchSettingsPanel(btn.dataset.settingsPanel));
});
document.getElementById('userChip')?.addEventListener('click', (ev) => {
  ev.stopPropagation();
  const menu = document.getElementById('userMenu');
  const chip = document.getElementById('userChip');
  const wrap = chip?.closest('.user-menu-wrap');
  if (!menu || !chip || chip.hidden) return;
  const open = !menu.hasAttribute('hidden');
  if (open) {
    menu.setAttribute('hidden', '');
    chip.setAttribute('aria-expanded', 'false');
    wrap?.classList.remove('open');
  } else {
    menu.removeAttribute('hidden');
    chip.setAttribute('aria-expanded', 'true');
    wrap?.classList.add('open');
  }
});
document.getElementById('userMenuSettings')?.addEventListener('click', () => {
  document.getElementById('userMenu')?.setAttribute('hidden', '');
  document.getElementById('userChip')?.setAttribute('aria-expanded', 'false');
  document.querySelector('.user-menu-wrap')?.classList.remove('open');
  openPersonalSettingsModal().catch((e)=>paneError('Personal settings could not be opened', e.message || String(e)));
});
document.addEventListener('click', (ev) => {
  const menu = document.getElementById('userMenu');
  const chip = document.getElementById('userChip');
  if (!menu || !chip) return;
  if (!menu.hasAttribute('hidden') && !menu.contains(ev.target) && !chip.contains(ev.target)) {
    menu.setAttribute('hidden', '');
    chip.setAttribute('aria-expanded', 'false');
    chip.closest('.user-menu-wrap')?.classList.remove('open');
  }
});
if (document.getElementById('dismissSetupWizard')) document.getElementById('dismissSetupWizard').onclick = () => hideSetupWizard();
if (document.getElementById('setupWizardBack')) document.getElementById('setupWizardBack').onclick = () => { setupWizardStepIndex = Math.max(0, setupWizardStepIndex - 1); renderSetupWizard(); };
if (document.getElementById('setupWizardNext')) document.getElementById('setupWizardNext').onclick = () => advanceSetupWizard(1).catch(e => paneError('Setup step failed', e.message || String(e)));
if (document.getElementById('setupWizardDone')) document.getElementById('setupWizardDone').onclick = () => completeSetupWizard().catch(e => paneError('Setup completion failed', e.message || String(e)));
if (document.getElementById('recheckSetupWizard')) document.getElementById('recheckSetupWizard').onclick = () => completeSetupWizard().catch(e => paneError('Setup recheck failed', e.message || String(e)));
document.getElementById('createSession').onclick=async()=>{
  const btn = document.getElementById('createSession');
  const status = document.getElementById('sessionCreateStatus');
  try {
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Creating…';
    const contextId = document.getElementById('sessionAgentContext')?.value || '';
    if (contextId) {
      const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(contextId)}/session`, {method:'POST'});
      const s = ensured.session;
      if (status) status.textContent = 'Created.';
      closeSessionModal();
      await loadSessions(); await loadDashboardMetrics(); switchToTab('sessions-tab'); await selectSession(s.id);
      return;
    }
    const workspaceType = document.getElementById('sessionWorkspaceType')?.value || 'profile';
    const workspace = workspaceType === 'git' ? {type:'git', url:sessionWorkspaceUrl.value.trim(), branch:sessionWorkspaceBranch.value.trim() || null, path:sessionWorkspacePath.value.trim() || null} : (workspaceType === 'local' ? {type:'local', path:sessionWorkspacePath.value.trim() || null} : {type:'profile', profile:workspaceProfile.value || null});
    const endpointId = document.getElementById('sessionEndpoint')?.value || '';
    if (!endpointId) throw new Error('Select the endpoint this session should use.');
    const body={name:sessionName.value || 'web-session', agent_profile:agentProfile.value || null, workspace, tools:[], metadata:{preferred_endpoint:endpointId, endpoint_locked:true, agent_enabled:true, execution_mode:'pi.dev'}};
    if (modelOverride.value) body.model=modelOverride.value;
    if (permissionOverride.value) body.permission_profile=permissionOverride.value;
    if (contextMode.value) body.context_mode=contextMode.value;
    const s=await api('/v1/sessions',{method:'POST',body:JSON.stringify(body)});
    if (status) status.textContent = 'Created.';
    closeSessionModal();
    await loadSessions(); await loadDashboardMetrics(); switchToTab('sessions-tab'); await selectSession(s.id);
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message}`;
    await loadGlobalEvents(true).catch(()=>{});
  } finally {
    if (btn) btn.disabled = false;
  }
};

async function sendSessionComposer(){
  const rawPrompt = (taskPrompt.value || '').trim();
  if(!rawPrompt) return;
  if (isHelpSlashCommand(rawPrompt)) {
    alert(slashCommandHelpText());
    return;
  }
  const contextId = (document.getElementById('composerAgentContext')?.value || '').trim();
  if (contextId && (!selectedSession || selectedSessionContextId() !== contextId)) {
    const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(contextId)}/session`, {method:'POST'});
    await loadSessions();
    if (ensured.session?.id) await selectSession(ensured.session.id);
  }
  if(!selectedSession) return alert('Select a session or choose an agent context first.');
  const metadata={};
  const runnerChoice = selectedSession.metadata?.preferred_endpoint || taskRunner.value || '';
  if(runnerChoice){
    metadata.runner_id=runnerChoice;
    metadata.execution_mode = (taskExecution.value === 'container' || taskExecution.value === 'pi_container') ? taskExecution.value : 'pi_container';
    if(taskImage.value) metadata.container_image=taskImage.value;
  }
  if (document.getElementById('taskModel')?.value) metadata.model = taskModel.value;
  taskPrompt.value='';
  taskCommand.value='';
  composerAttachedItems = [];
  renderComposerAttachmentTray();
  autosizeSessionPrompt();
  await createSessionTask(selectedSession.id, rawPrompt, metadata);
}

async function createSessionTask(sessionId, rawPrompt, metadata = {}) {
  if (sessionHydrationActiveFor === sessionId) {
    sessionHydrationToken += 1;
    sessionHydrationActiveFor = null;
    sessionHydrationBufferedEvents = [];
  }
  const created = await api(`/v1/sessions/${sessionId}/tasks`,{method:'POST',body:JSON.stringify({prompt:rawPrompt,command:'',metadata})});
  if (created && created.id) {
    activeSessionTaskId = created.id;
    refreshSessionRunButton().catch(()=>{});
    const localEvent = {
      id: `local_user_${created.id}`,
      session_id: sessionId,
      task_id: created.id,
      type: 'user_message',
      message: rawPrompt,
      created_at: created.created_at || new Date().toISOString(),
      data: {role:'user', model: metadata.model || selectedSession?.model, endpoint_id: metadata.runner_id || selectedSession?.metadata?.preferred_endpoint, command:'', execution_mode: metadata.execution_mode, stored:true, pi_dev_enabled:selectedSession?.metadata?.agent_enabled !== false, routing:'pi.dev'}
    };
    renderSessionTimelineEvent(localEvent);
    renderComposerThinkingStatus({active:true, summary:'Planning the work', startedAt: localEvent.created_at, toolCount:0, approvalPending:false, planSteps: []});
    pollSessionEvents(sessionId).catch(()=>{});
  }
}

const composerAddContextBtn = document.getElementById('composerAddContext');
const composerContextMenu = document.getElementById('composerContextMenu');
if (composerAddContextBtn && composerContextMenu) {
  composerAddContextBtn.onclick = (ev) => { ev.stopPropagation(); composerContextMenu.hidden = !composerContextMenu.hidden; };
  composerContextMenu.onclick = (ev) => ev.stopPropagation();
  composerContextMenu.querySelectorAll('button').forEach((btn) => {
    btn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const rawText = (btn.textContent || '').toLowerCase();
      const action =
        btn.dataset.contextAction ||
        btn.getAttribute('data-context-action') ||
        (rawText.includes('files') ? 'files' :
        rawText.includes('image') ? 'image' :
        rawText.includes('branch') ? 'branch_diff' :
        rawText.includes('symbol') ? 'symbols' :
        rawText.includes('thread') ? 'threads' :
        rawText.includes('rule') ? 'rules' :
        rawText.includes('selection') ? 'selection' :
        rawText.includes('/ slash') ? 'slash_help' : '');
      composerContextMenu.hidden = true;
      handleComposerContextAction(action);
    });
  });
  document.addEventListener('click', () => { composerContextMenu.hidden = true; });
}
const sessionTopSelect = document.getElementById('sessionTopSelect');
if (sessionTopSelect) sessionTopSelect.onchange = () => { if (sessionTopSelect.value) { switchToTab('sessions-tab'); selectSession(sessionTopSelect.value); } };
const sessionPermissionQuick = document.getElementById('sessionPermissionQuick');
if (sessionPermissionQuick) sessionPermissionQuick.onchange = () => {
  const apply = document.getElementById('applySessionPermission');
  if (apply) apply.disabled = !selectedSession || sessionPermissionQuick.value === (selectedSession.permission_profile || '');
};
const applySessionPermissionBtn = document.getElementById('applySessionPermission');
if (applySessionPermissionBtn) applySessionPermissionBtn.onclick = () => applySessionPermissionProfile().catch((e) => paneError('Session permission update failed', e.message || String(e)));

function openContainerDestinationModal() {
  const modal = document.getElementById('containerDestinationModal');
  const input = document.getElementById('containerDestinationImage');
  if (input) input.value = document.getElementById('taskImage')?.value || '';
  if (modal) modal.hidden = false;
  setTimeout(() => input?.focus(), 20);
}

function closeContainerDestinationModal() { const modal = document.getElementById('containerDestinationModal'); if (modal) modal.hidden = true; }
const taskExecutionSelect = document.getElementById('taskExecution');
if (taskExecutionSelect) taskExecutionSelect.onchange = () => { if (taskExecutionSelect.value === 'container') openContainerDestinationModal(); updateComposerChrome(); };
const composerDestinationBtn = document.getElementById('composerDestinationButton');
if (composerDestinationBtn) composerDestinationBtn.onclick = openContainerDestinationModal;
const composerSlashHelpBtn = document.getElementById('composerSlashHelp');
if (composerSlashHelpBtn) composerSlashHelpBtn.onclick = () => alert(slashCommandHelpText());
const closeContainerDestinationBtn = document.getElementById('closeContainerDestinationModal');
if (closeContainerDestinationBtn) closeContainerDestinationBtn.onclick = closeContainerDestinationModal;
const saveContainerDestinationBtn = document.getElementById('saveContainerDestination');
if (saveContainerDestinationBtn) saveContainerDestinationBtn.onclick = () => {
  const image = (document.getElementById('containerDestinationImage')?.value || '').trim();
  if (!image) return alert('Container image is required for container destination.');
  if (document.getElementById('taskImage')) taskImage.value = image;
  if (document.getElementById('taskExecution')) taskExecution.value = 'container';
  const hint = document.getElementById('sessionEndpointLock');
  if (hint) hint.textContent = `${hint.textContent.split(' · container:')[0]} · container: ${image}`;
  rememberComposerAttachment(`container: ${image}`, 'runtime');
  updateComposerChrome();
  closeContainerDestinationModal();
};
const clearContainerDestinationBtn = document.getElementById('clearContainerDestination');
if (clearContainerDestinationBtn) clearContainerDestinationBtn.onclick = () => {
  if (document.getElementById('taskImage')) taskImage.value = '';
  if (document.getElementById('taskExecution')) taskExecution.value = 'host';
  updateComposerChrome();
  closeContainerDestinationModal();
};
const runTaskBtn = document.getElementById('runTask');

function composerSetText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function composerEndpointLabel() {
  if (!selectedSession) return 'not selected';
  const endpointId = selectedSession.metadata?.preferred_endpoint || '';
  if (!endpointId) return 'not locked';
  const endpoint = (window.__pacEndpoints || []).find((item) => item.id === endpointId || item.name === endpointId);
  return endpoint?.name || endpointId;
}

function composerContextLabel() {
  const contextId = selectedSessionContextId?.() || document.getElementById('composerAgentContext')?.value || '';
  if (!contextId) return selectedSession ? 'session' : 'none';
  const contexts = window.__pacAgentContexts || [];
  const context = contexts.find((item) => item.id === contextId || item.name === contextId);
  return context?.name || contextId;
}

function updateComposerChrome() {
  const prompt = document.getElementById('taskPrompt');
  const runButton = document.getElementById('runTask');
  const hasPrompt = !!String(prompt?.value || '').trim();
  const stopping = runButton?.dataset.mode === 'stop';
  const mode = selectedSession?.metadata?.composer_intent || (hasPrompt ? 'Composing' : 'Chat');
  composerSetText('composerModePill', stopping ? 'Running task' : mode);
  composerSetText('composerContextPill', `Context: ${composerContextLabel()}`);
  composerSetText('composerModelPill', `Model: ${document.getElementById('taskModel')?.value || selectedSession?.model || 'session default'}`);
  composerSetText('composerEndpointPill', `Endpoint: ${composerEndpointLabel()}`);
  const status = document.getElementById('composerFooterStatus');
  if (status) {
    if (!selectedSession) status.textContent = 'Select or create a session to start.';
    else if (stopping) status.textContent = 'Task is running. Stop is available.';
    else if (hasPrompt) status.textContent = 'Ready to send.';
    else status.textContent = 'Ready. Add context or type a message.';
  }
  if (runButton && !stopping) runButton.disabled = !hasPrompt;
}

function renderComposerAttachmentTray() {
  const tray = document.getElementById('composerAttachmentTray');
  if (!tray) return;
  tray.innerHTML = '';
  tray.hidden = composerAttachedItems.length === 0;
  composerAttachedItems.slice(-10).forEach((item, index) => {
    const chip = document.createElement('span');
    chip.className = 'composer-attachment-chip';
    const label = document.createElement('span');
    label.textContent = item.label;
    chip.appendChild(label);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.title = 'Remove attachment marker';
    remove.textContent = '×';
    remove.onclick = () => {
      composerAttachedItems.splice(index, 1);
      renderComposerAttachmentTray();
      updateComposerChrome();
    };
    chip.appendChild(remove);
    tray.appendChild(chip);
  });
}

function rememberComposerAttachment(label, kind='context') {
  composerAttachedItems.push({label, kind, addedAt: new Date().toISOString()});
  renderComposerAttachmentTray();
  updateComposerChrome();
}

function autosizeSessionPrompt() {
  const el = document.getElementById('taskPrompt');
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(220, Math.max(56, el.scrollHeight)) + 'px';
  updateComposerChrome();
}

function appendPromptContextBlock(label, content) {
  const prompt = document.getElementById('taskPrompt');
  if (!prompt) return;
  const block = `
[${label}]
${content}
`;
  prompt.value = `${prompt.value || ''}${block}`.trimStart();
  autosizeSessionPrompt();
  prompt.focus();
  rememberComposerAttachment(label, 'context');
}

function handleComposerContextAction(action) {
  const fileInput = document.getElementById('composerFileInput');
  const dirInput = document.getElementById('composerDirectoryInput');
  if (action === 'slash_help') {
    alert(slashCommandHelpText());
    return;
  }
  if (action === 'files') {
    fileInput?.click();
    return;
  }
  if (action === 'directories') {
    dirInput?.click();
    return;
  }
  if (action === 'image') {
    if (fileInput) {
      fileInput.accept = 'image/*';
      fileInput.click();
    }
    return;
  }
  if (action === 'branch_diff') {
    appendPromptContextBlock('Context request', 'Please inspect the current branch diff for this session workspace before answering.');
    return;
  }
  if (action === 'symbols') {
    appendPromptContextBlock('Context request', 'Please inspect the relevant symbols, functions, and files in this workspace before answering.');
    return;
  }
  if (action === 'threads') {
    appendPromptContextBlock('Context request', 'Please consider prior thread context and summarize the relevant decisions before continuing.');
    return;
  }
  if (action === 'rules') {
    appendPromptContextBlock('Context request', 'Please follow the configured session and repository rules while answering.');
    return;
  }
  if (action === 'selection') {
    appendPromptContextBlock('Context request', 'Please work from the currently selected text or file context.');
    return;
  }
}

async function appendSelectedFilesToPrompt(files, label='Attached files') {
  if (!files?.length) return;
  const summaries = [];
  for (const file of Array.from(files).slice(0, 8)) {
    if (file.type && file.type.startsWith('image/')) {
      summaries.push(`${file.name} [image attachment]`);
      continue;
    }
    try {
      const text = await file.text();
      const trimmed = text.length > 6000 ? `${text.slice(0, 6000)}\n... [truncated]` : text;
      summaries.push(`--- ${file.name} ---\n${trimmed}`);
    } catch (_) {
      summaries.push(`${file.name} [binary or unreadable attachment]`);
    }
  }
  appendPromptContextBlock(label, summaries.join('\n\n'));
  Array.from(files).slice(0, 8).forEach((file) => rememberComposerAttachment(`${file.name}${file.type?.startsWith('image/') ? ' · image' : ''}`, file.type?.startsWith('image/') ? 'image' : 'file'));
}

if (runTaskBtn) runTaskBtn.onclick = async () => {
  try {
    if (runTaskBtn.dataset.mode === 'stop') await stopActiveSessionTask();
    else await sendSessionComposer();
  } catch (e) {
    alert(e.message);
  }
};
const taskPromptInput = document.getElementById('taskPrompt');
if (taskPromptInput) {
  taskPromptInput.addEventListener('input', autosizeSessionPrompt);
  taskPromptInput.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
      ev.preventDefault();
      const hasPrompt = !!String(taskPromptInput.value || '').trim();
      ((hasPrompt || runTaskBtn?.dataset.mode !== 'stop') ? sendSessionComposer() : stopActiveSessionTask()).catch(e=>alert(e.message));
      return;
    }
    if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
      ev.preventDefault();
      sendSessionComposer().catch(e=>alert(e.message));
    }
  });
  autosizeSessionPrompt();
  updateComposerChrome();
}
const taskCommandInput = document.getElementById('taskCommand');
if (taskCommandInput) taskCommandInput.addEventListener('keydown', (ev) => { if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { ev.preventDefault(); sendSessionComposer().catch(e=>alert(e.message)); } });

const downloadSessionUsageBtn = document.getElementById('downloadSessionUsage');
if (downloadSessionUsageBtn) downloadSessionUsageBtn.onclick = downloadSelectedSessionUsage;
const downloadSessionDiagnosticsBtn = document.getElementById('downloadSessionDiagnostics');
if (downloadSessionDiagnosticsBtn) downloadSessionDiagnosticsBtn.onclick = downloadSelectedSessionDiagnostics;


async function downloadSelectedSessionUsage() {
  if (!selectedSession?.id) return;
  const usage = await api(`/v1/sessions/${encodeURIComponent(selectedSession.id)}/model-usage?since_hours=2160&limit=10000`);
  const blob = new Blob([JSON.stringify(usage, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `pac-model-usage-${selectedSession.id}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}


function downloadSelectedSessionDiagnostics() {
  if (!selectedSession?.id) return;
  const url = `/v1/sessions/${encodeURIComponent(selectedSession.id)}/diagnostics.zip?include_events=1000&full=false&include_workspace_state=true`;
  const a = document.createElement('a');
  a.href = url;
  a.download = `pac-diagnostics-${selectedSession.id}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function openGitDiffModal(){
  if(!selectedSession) return;
  const modal = document.getElementById('gitDiffModal');
  const pre = document.getElementById('gitDiffBody');
  if (pre) pre.textContent = 'Checking for workspace changes…';
  if (modal) modal.hidden = false;
  try {
    const d=await api(`/v1/sessions/${selectedSession.id}/diff`);
    const text = (d.diff || '').trim();
    if (pre) pre.textContent = text || 'No git changes detected for this session workspace.';
  } catch(e) { if (pre) pre.textContent = `Unable to load git diff: ${e.message}`; }
}

function closeGitDiffModal(){ const modal = document.getElementById('gitDiffModal'); if (modal) modal.hidden = true; }
function applySessionBootstrapMode() {
  const mode = document.getElementById('sessionBootstrapMode')?.value || 'profile';
  const sourceLabel = document.getElementById('sessionSourceContext')?.closest('label');
  if (sourceLabel) sourceLabel.style.display = mode === 'source-context' ? '' : '';
}

async function applySessionSourceContext(name) {
  if (!name) return;
  const resolved = await api(`/v1/source-contexts/resolve?name=${encodeURIComponent(name)}&include_secrets=false`);
  const ctx = resolved?.context || {};
  if (ctx.profile && document.getElementById('agentProfile')) agentProfile.value = ctx.profile;
  if (ctx.workspace_profile && document.getElementById('workspaceProfile')) workspaceProfile.value = ctx.workspace_profile;
  if (ctx.preferred_endpoint && document.getElementById('sessionEndpoint')) sessionEndpoint.value = ctx.preferred_endpoint;
  if ((ctx.workspace_profile || ctx.path_prefix) && document.getElementById('sessionWorkspaceType')) sessionWorkspaceType.value = ctx.workspace_profile ? 'profile' : 'local';
  if (ctx.path_prefix && document.getElementById('sessionWorkspacePath') && !sessionWorkspacePath.value) sessionWorkspacePath.value = ctx.path_prefix;
  const status = document.getElementById('sessionCreateStatus');
  if (status) status.textContent = `Loaded source context ${name}.`;
}

async function loadApprovals() {
  if (approvalsRequest) return approvalsRequest;
  approvalsRequest = (async () => {
    const [tasks, accessRequests] = await Promise.all([
      api('/v1/tasks/pending-approvals'),
      api('/v1/access-requests').catch(() => []),
    ]);
    const targets = [document.getElementById('approvals'), document.getElementById('approvalsSettings')].filter(Boolean);
    targets.forEach((el) => {
      el.innerHTML = '';
      accessRequests.forEach((req) => {
        const row=document.createElement('div'); row.className='row';
        row.innerHTML=`<div><b>${escapeHtml(req.username || req.user_id)}</b><br><span class="muted">${escapeHtml(`${req.access} ${req.resource_type} ${req.resource_id}`)}</span>${req.reason ? `<br><span class="muted">${escapeHtml(req.reason)}</span>` : ''}</div>`;
        const a=document.createElement('button'); a.textContent='Grant access'; a.onclick=async()=>{await api(`/v1/access-requests/${encodeURIComponent(req.id)}/approve`, {method:'POST'}); await fetchAuthStatus(); renderAuthInfo(); await loadApprovals(); await loadUsersList().catch(()=>{});};
        const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await api(`/v1/access-requests/${encodeURIComponent(req.id)}/reject`, {method:'POST'}); await fetchAuthStatus(); renderAuthInfo(); await loadApprovals();};
        row.append(a,r); el.appendChild(row);
      });
      tasks.forEach((t) => {
        const row=document.createElement('div'); row.className='row';
        row.innerHTML=`<div><b>${t.command || t.prompt}</b><br><span class="muted">${t.session_id}</span></div>`;
        const a=document.createElement('button'); a.textContent='Approve'; a.onclick=async()=>{await resolveSessionApproval(t.id, true);};
        const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await resolveSessionApproval(t.id, false);};
        row.append(a,r); el.appendChild(row);
      });
      if (!accessRequests.length && !tasks.length) {
        el.innerHTML = '<div class="muted small-text">No pending approvals.</div>';
      }
    });
  })();
  try {
    return await approvalsRequest;
  } finally {
    approvalsRequest = null;
  }
}

function resetSessionTimelineState() {
    sessionThinkingGroups = new Map();
    sessionEventSeen = new Set();
    sessionMessageSeen = new Set();
    sessionPendingRows = new Map();
    sessionApprovalRows = new Map();
    sessionLatestEventId = null;
    sessionHydrationBufferedEvents = [];
    sessionTaskPrompts = new Map();
    latestAssistantReplyState = null;
    renderComposerReplyActions();
}

function refreshComposerThinkingStatusForTask(taskId='') {
  const group = getThinkingGroup(taskId);
  if (group && Array.isArray(group.events) && group.events.length && !group.closed) {
    const state = deriveComposerThinkingState(group.events.map(item => item?.event).filter(Boolean)) || {};
    state.closed = false;
    state.active = true;
    state.startedAt = group.startedAt || state.startedAt;
    state.summary = group.summary || state.summary || 'Working on the request';
    state.toolCount = thinkingGroupToolCount(group);
    state.approvalPending = thinkingGroupNeedsApproval(group);
    state.planSteps = [];
    state.onOpen = () => openSessionThinkingModal(group);
    renderComposerThinkingStatus(state);
    return;
  }
  renderComposerThinkingStatus(null);
  updateComposerChrome();
}

try { bindSessionEventModalChrome(); } catch (_) {}
