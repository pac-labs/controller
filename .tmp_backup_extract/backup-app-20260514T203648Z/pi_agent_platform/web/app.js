const PROVIDER_PRESETS = {
  'openai': {name:'openai', type:'openai', base_url:'https://api.openai.com/v1', api_key_env:'OPENAI_API_KEY'},
  'openai-codex': {name:'openai-codex', type:'openai-codex', base_url:'https://api.openai.com/v1', api_key_env:'OPENAI_API_KEY'},
  'anthropic': {name:'anthropic', type:'anthropic', base_url:'https://api.anthropic.com/v1', api_key_env:'ANTHROPIC_API_KEY'},
  'minimax': {name:'minimax', type:'minimax', base_url:'https://api.minimax.io/anthropic/v1', api_key_env:'MINIMAX_API_KEY'},
  'gemini': {name:'gemini', type:'gemini', base_url:'https://generativelanguage.googleapis.com/v1beta', api_key_env:'GEMINI_API_KEY'},
  'groq': {name:'groq', type:'groq', base_url:'https://api.groq.com/openai/v1', api_key_env:'GROQ_API_KEY'},
  'openrouter': {name:'openrouter', type:'openrouter', base_url:'https://openrouter.ai/api/v1', api_key_env:'OPENROUTER_API_KEY'},
  'deepseek': {name:'deepseek', type:'deepseek', base_url:'https://api.deepseek.com/v1', api_key_env:'DEEPSEEK_API_KEY'},
  'mistral': {name:'mistral', type:'mistral', base_url:'https://api.mistral.ai/v1', api_key_env:'MISTRAL_API_KEY'},
  'lmstudio': {name:'lmstudio', type:'lmstudio', base_url:'http://localhost:1234/v1', api_key_env:''},
  'ollama': {name:'ollama', type:'ollama', base_url:'http://localhost:11434', api_key_env:''},
  'vllm': {name:'vllm', type:'vllm', base_url:'http://localhost:8000/v1', api_key_env:''},
  'custom-openai': {name:'custom-openai', type:'openai-compatible', base_url:'', api_key_env:''},
  'custom-anthropic': {name:'custom-anthropic', type:'anthropic-compatible', base_url:'', api_key_env:''},
};
function applyProviderPreset(key) {
  const preset = PROVIDER_PRESETS[key];
  if (!preset) return;
  if (!providerName.value.trim()) providerName.value = preset.name;
  providerType.value = preset.type;
  providerBaseUrl.value = preset.base_url || '';
  providerApiKeyEnv.value = preset.api_key_env || '';
  if (!providerTimeout.value) providerTimeout.value = 30;
  setModalStatus('providerModalStatus', `${preset.name} preset loaded`);
}

let config = null;
let selectedSession = null;
let selectedSourcePath = null;
let selectedSourceFolder = '';
let selectedBinaryArtifactFilter = '';
let sourceOpenTabs = [];
let sourceFileState = new Map();
let selectedSourceEntry = '';
let sourceExpandedDirs = new Set(['']);
let sourceTreeCache = new Map();
let source = null;
let globalEventSeen = new Set();
let globalEventFilter = 'all';
let globalEventPoll = null;
let eventsRailPinned = false;
let editingEndpointId = null;
let commandEndpointId = null;
let eventsFetchFailureCount = 0;
let eventsFetchLastNotice = null;
let sessionThinkingGroup = null;
let sessionEventSeen = new Set();
let sessionMessageSeen = new Set();
let sessionPendingRows = new Map();

const SESSION_SLASH_COMMANDS = {
  command: {kind:'tool', label:'/command <tool> [args]', description:'Run a registered endpoint tool on the locked host endpoint. Example: /command rg TODO'},
  rg: {kind:'tool', tool:'rg', label:'/rg <pattern> [path]', description:'Run ripgrep on the endpoint workspace.'},
  fd: {kind:'tool', tool:'fd', label:'/fd <pattern>', description:'Find files with fd on the endpoint workspace.'},
  jq: {kind:'tool', tool:'jq', label:'/jq <filter>', description:'Run jq on JSON input or files.'},
  git: {kind:'tool', tool:'git', label:'/git <args>', description:'Run git in the endpoint workspace.'},
  delta: {kind:'tool', tool:'delta', label:'/delta [args]', description:'Render diffs with delta on the endpoint.'},
  bat: {kind:'tool', tool:'bat', label:'/bat <file>', description:'Preview a file with bat or batcat.'},
  bad: {kind:'tool', tool:'bat', label:'/bad <file>', description:'Typo alias for /bat.'},
  just: {kind:'tool', tool:'just', label:'/just <recipe>', description:'Run a just recipe in the endpoint workspace.'},
  compact: {kind:'session', label:'/compact', description:'Compact the session context/history before the next model turn.'},
  subagent: {kind:'pi.dev', label:'/subagent <instruction>', description:'Create a scoped subagent task for one specific objective.'},
  help: {kind:'help', label:'/help', description:'Show available slash commands.'},
};
function shellSplit(input) {
  const out = [];
  let cur = '';
  let quote = null;
  let esc = false;
  for (const ch of String(input || '')) {
    if (esc) { cur += ch; esc = false; continue; }
    if (ch === '\\') { esc = true; continue; }
    if (quote) { if (ch === quote) quote = null; else cur += ch; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (/\s/.test(ch)) { if (cur) { out.push(cur); cur = ''; } continue; }
    cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}
function parseSessionSlashCommand(raw) {
  const text = String(raw || '').trim();
  if (!text.startsWith('/')) return null;
  const parts = shellSplit(text.slice(1));
  const verb = (parts.shift() || '').toLowerCase();
  const spec = SESSION_SLASH_COMMANDS[verb];
  if (!spec) return {kind:'unknown', verb, prompt:text, error:`Unknown slash command: /${verb}. Use /help.`};
  if (spec.kind === 'help') {
    return {kind:'help', verb, prompt:'Show slash command help'};
  }
  if (spec.kind === 'session' && verb === 'compact') {
    return {kind:'compact', verb, prompt:'Compact session context', metadata:{slash_command:'compact', context_action:'compact'}};
  }
  if (spec.kind === 'pi.dev' && verb === 'subagent') {
    const instruction = parts.join(' ').trim();
    return {kind:'subagent', verb, prompt: instruction ? `Subagent: ${instruction}` : 'Subagent task', metadata:{slash_command:'subagent', subagent:true, subagent_instruction:instruction}};
  }
  if (verb === 'command') {
    const tool = (parts.shift() || '').trim();
    if (!tool) return {kind:'unknown', verb, prompt:text, error:'Usage: /command <tool> [args]'};
    return {kind:'tool', verb, tool, args:parts, prompt:`Run endpoint tool: ${tool} ${parts.join(' ')}`.trim(), metadata:{slash_command:'command', tool_name:tool, args:parts, tool_invocation:true}};
  }
  if (spec.kind === 'tool') {
    return {kind:'tool', verb, tool:spec.tool || verb, args:parts, prompt:`Run endpoint tool: ${spec.tool || verb} ${parts.join(' ')}`.trim(), metadata:{slash_command:verb, tool_name:spec.tool || verb, args:parts, tool_invocation:true}};
  }
  return null;
}
function slashCommandHelpText() {
  return Object.values(SESSION_SLASH_COMMANDS).map(c => `${c.label} — ${c.description}`).join('\n');
}


async function loadVersion(){
  try {
    const v = await api('/v1/version');
    document.querySelectorAll('.app-version').forEach(el => el.textContent = 'v' + (v.version || '1.0.98'));
  } catch (_) {}
}


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

function eventTone(type) {
  const cat = eventCategory(type);
  if (cat === 'completed') return 'ok';
  if (cat === 'failed') return 'danger';
  if (cat === 'attention') return 'warn';
  return 'info';
}
function appendText(parent, tag, className, text) {
  if (text == null || text === '') return null;
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = String(text);
  parent.appendChild(el);
  return el;
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
  if (t.includes('result') || t.includes('assistant_message')) return 'assistant';
  if (t.includes('task_queued') || t.includes('prompt')) return 'user';
  if (t.includes('failed') || t.includes('error') || t.includes('stderr') || t.includes('rejected')) return 'error';
  if (t.includes('tool') || t.includes('command') || t.includes('runner') || t.includes('stdout')) return 'tool';
  if (t.includes('thinking') || t.includes('pi.dev') || t.includes('model')) return 'assistant';
  return event?.task_id ? 'assistant' : 'system';
}
function isInternalSessionEvent(event) {
  const t = String(event?.type || '').toLowerCase();
  if (t.includes('user_message')) return false;
  if (t.includes('result') || t.includes('assistant_message')) return false;
  // Only tool/command activity belongs in the ChatGPT-like thought panel.
  // Lifecycle/model chatter is intentionally hidden from the visible session.
  return t.includes('tool') || t.includes('command') || t.includes('runner') ||
    t.includes('stdout') || t.includes('stderr') ||
    t.includes('web_search') || t.includes('web_fetch') || t.includes('artifact_saved')
    || t.includes('tool_approval_responded');
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
    t === 'task_completed' || t === 'context_compacted' || t === 'full_control_enabled' ||
    t === 'agent_routing' || t === 'agent_stop' || msg === 'agent loop started' || msg === 'agent stopped';
}
function sessionThinkingLine(event, block) {
  const data = event?.data && typeof event.data === 'object' ? event.data : {};
  const type = prettyEventType(event?.type);
  const text = timelineText(event, block);
  const concise = data.tool ? `Used ${data.tool}` : data.command ? `Ran command` : text ? String(text).split('\n')[0] : type;
  return `${formatEventTime(event?.created_at)} · ${concise}`.trim();
}
function toolActivityTitle(item) {
  const event = item?.event || {};
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const t = String(event.type || '').toLowerCase();
  if (data.tool) return String(data.tool);
  if (data.command) return 'exec_command';
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
  if (data.output && !String(text).includes(String(data.output))) lines.push(String(data.output));
  if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
  if (data.exit_code != null) lines.push(`exit code: ${data.exit_code}`);
  if (!lines.length && event.message) lines.push(event.message);
  return lines.join('\n').trim();
}
function sessionThinkingDetailsHtml(events) {
  const rows = (events || []).filter(item => item?.event && isInternalSessionEvent(item.event));
  if (!rows.length) return '<div class="tool-activity-empty">No tool activity was recorded for this answer.</div>';
  return `<div class="tool-activity-list">${rows.map((item) => {
    const title = escapeHtml(toolActivityTitle(item));
    const time = escapeHtml(formatEventTime(item.event?.created_at));
    const body = escapeHtml(toolActivityBody(item));
    const status = item.event?.data?.exit_code != null ? `exit ${escapeHtml(String(item.event.data.exit_code))}` : prettyEventType(item.event?.type);
    return `<details class="tool-activity-item"><summary><span class="tool-activity-icon">⌁</span><span class="tool-activity-title">${title}</span><span class="tool-activity-status">${escapeHtml(status)}</span><span class="tool-activity-time">${time}</span></summary>${body ? `<pre>${body}</pre>` : ''}</details>`;
  }).join('')}</div>`;
}
function openSessionThinkingModal(group) {
  const modal = document.getElementById('sessionEventModal');
  if (!modal || !group) return;
  const title = document.getElementById('sessionEventModalTitle');
  const body = document.getElementById('sessionEventModalBody');
  if (title) title.textContent = 'Tool activity';
  if (body) {
    body.className = 'modal-scroll-output tool-activity-modal';
    body.innerHTML = sessionThinkingDetailsHtml(group.events || []);
  }
  modal.hidden = false;
}
function ensureSessionThinkingGroup(event) {
  if (!sessionThinkingGroup || sessionThinkingGroup.closed) {
    sessionThinkingGroup = {events: [], startedAt: sessionEventDate(event), endedAt: null, row: null, closed: false};
  }
  if (!sessionThinkingGroup.startedAt) sessionThinkingGroup.startedAt = sessionEventDate(event);
  return sessionThinkingGroup;
}
function flushSessionThinkingGroup(endEvent) {
  const el = document.getElementById('events');
  const group = sessionThinkingGroup;
  if (!el || !group || group.closed || !group.events.length) return;
  group.closed = true;
  group.endedAt = endEvent ? sessionEventDate(endEvent) : new Date();
  const started = group.startedAt || sessionEventDate(group.events[0].event);
  const ended = group.endedAt || started;
  // Always remove thinking-live rows on flush (spinner cleanup — always needed)
  const liveRows = el.querySelectorAll('.thinking-live');
  liveRows.forEach(r => r.remove());
  const oldSpinners = el.querySelectorAll('.thought-line.loading');
  oldSpinners.forEach(r => r.remove());
  const toolCount = (group.events || []).filter(item => item?.event && isInternalSessionEvent(item.event)).length;
  // Also remove any stale thought-line buttons first
  const oldBtn = el.querySelector('.thought-line');
  if (oldBtn) oldBtn.remove();
  // Create the "Thought for Xs · N steps" button
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'thought-line';
  btn.style.cssText = 'position:absolute;bottom:4px;left:12px;z-index:10;opacity:0.8;';
  btn.innerHTML = '<span>Thought for ' + escapeHtml(formatDurationMs(ended.getTime() - started.getTime())) + '</span><span class="thought-tool-count">' + toolCount + ' tool ' + (toolCount === 1 ? 'step' : 'steps') + '</span>';
  btn.onclick = () => openSessionThinkingModal(group);
  btn.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') openSessionThinkingModal(group); };
  group.row = btn;
  // Anchor to events container
  const container = el.parentElement;
  if (container) {
    container.style.position = 'relative';
    el.style.position = 'relative';
    el.style.paddingBottom = '48px';
    el.appendChild(btn);
    el.scrollTop = el.scrollHeight;
  } else {
    el.appendChild(btn);
  }
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
  modal.hidden = false;
}
function closeSessionEventModal() {
  const modal = document.getElementById('sessionEventModal');
  if (modal) modal.hidden = true;
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
  if (data.command) lines.push(`$ ${data.command}`);
  if (data.tool) lines.push(`tool: ${data.tool}`);
  if (data.output) lines.push(String(data.output));
  if (data.stderr) lines.push(`stderr:\n${data.stderr}`);
  if (data.exit_code != null) lines.push(`exit code: ${data.exit_code}`);
  return lines.join('\n').trim();
}

function sessionEventDate(event) {
  try { return new Date(event?.created_at || Date.now()); } catch { return new Date(); }
}
function formatDurationMs(ms) {
  const safe = Math.max(0, Number(ms) || 0);
  if (safe < 1000) return `${Math.round(safe)}ms`;
  return `${(safe / 1000).toFixed(safe < 10000 ? 1 : 0)}s`;
}
function endpointDisplayName(endpointId) {
  if (!endpointId) return '';
  const found = (window.__pacEndpoints || []).find(e => e.id === endpointId);
  return found?.name || endpointId;
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
  const row = sessionPendingRows.get(taskId);
  if (row && row.parentElement) row.remove();
  sessionPendingRows.delete(taskId);
}
function addPendingRow(taskId) {
  const el = document.getElementById('events');
  if (!el || !taskId || sessionPendingRows.has(taskId)) return;
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'thought-line loading';
  row.innerHTML = '<span class="tiny-spinner" aria-hidden="true"></span><span>Thinking…</span>';
  row.onclick = () => {
    const group = sessionThinkingGroup && !sessionThinkingGroup.closed ? sessionThinkingGroup : {events: [], startedAt: new Date(), endedAt: null};
    openSessionThinkingModal(group);
  };
  sessionPendingRows.set(taskId, row);
  el.appendChild(row);
  el.scrollTop = el.scrollHeight;
}
function renderSessionTimelineEvent(event) {
  const el = document.getElementById('events');
  if (!el || !event) return;
  if (event.id && sessionEventSeen.has(event.id)) return;
  if (event.id) sessionEventSeen.add(event.id);
  const messageKey = `${event.type || ''}:${event.task_id || ''}:${event.message || ''}`;
  if ((event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message') && sessionMessageSeen.has(messageKey)) return;
  if (event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message') sessionMessageSeen.add(messageKey);
  const typeLower = String(event.type || '').toLowerCase();
  if (typeLower.includes('task_completed') || typeLower.includes('task_failed') || typeLower.includes('result')) removePendingRow(event.task_id);
  // agent_thinking: single live "Thinking…" row — updated in place, never duplicated
  if (event.type === 'agent_thinking') {
    const el = document.getElementById('events');
    if (!el) return;
    if (sessionThinkingGroup && !sessionThinkingGroup.closed) {
      sessionThinkingGroup.events.push({event, block: null});
    }
    // Skip rendering spinner if thinking group is already closed (historical event)
    if (sessionThinkingGroup && sessionThinkingGroup.isHistorical) { return; }
    // Always remove any existing thinking-live rows first (prevents duplicates/stacking)
    const existing = el.querySelectorAll('.thinking-live');
    existing.forEach(r => r.remove());
    const oldSpinners = el.querySelectorAll('.thought-line.loading');
    oldSpinners.forEach(r => r.remove());
    // Create fresh thinking row
    const row = document.createElement('div');
    row.className = 'thinking-live';
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 12px;color:rgba(148,163,184,0.55);font-size:0.8em;';
    const data = event.data || {};
    const thinkText = data.thinking || data.model || data.step || '';
    const label = thinkText ? 'Thinking… ' + escapeHtml(String(thinkText).substring(0, 60)) : 'Thinking…';
    row.innerHTML = '<span style="width:10px;height:10px;border-radius:50%;border:2px solid rgba(148,163,184,0.35);border-top-color:rgba(148,163,184,0.7);animation:pac-spin 0.7s linear infinite;display:inline-block;"></span><span>' + label + '</span>';
    el.appendChild(row);
    el.scrollTop = el.scrollHeight;
    return;
  }
  if (sessionLifecycleEventIsNoise(event)) return;
  const empty = el.querySelector('.empty-timeline');
  if (empty) empty.remove();
  const block = normalizeTimelineBlock(event);
  const role = sessionEventRole(event);
  const internal = isInternalSessionEvent(event);
  if (internal) {
    const group = ensureSessionThinkingGroup(event);
    group.events.push({event, block});
    // When agent finishes with assistant_message/result: transform thinking-live into "Thought for Xs"
    if (event.type === 'assistant_message' || event.type === 'result') {
      const rows = el.querySelectorAll('.thinking-live');
      rows.forEach(r => r.remove());
      // Always show "Thought for Xs" — with or without tool steps
      flushSessionThinkingGroup(event);
    } else if (String(event?.type || '').toLowerCase().includes('task_completed') || String(event?.type || '').toLowerCase().includes('task_failed')) {
      flushSessionThinkingGroup(event);
    }
    while (el.children.length > 250) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
    return;
  }
  flushSessionThinkingGroup(event);
      // tool_approval_required: left-aligned standalone chat bubble asking for permission
  if (event.type === 'tool_approval_required') {
    const el = document.getElementById('events');
    if (!el) return;
    const tool = event.data?.tool || 'unknown';
    const toolInput = event.data?.input || {};
    const reason = event.data?.reason || '';
    const sessionId = event.session_id;
    const taskId = event.task_id;
    const isPending = !event.data?.__responded;

    let purpose = '';
    if (toolInput.query) purpose = String(toolInput.query).substring(0, 80);
    else if (toolInput.url) purpose = String(toolInput.url).substring(0, 80);
    else if (toolInput.command) purpose = String(toolInput.command).substring(0, 80);
    else if (toolInput.path) purpose = String(toolInput.path);
    else if (toolInput.name) purpose = String(toolInput.name);
    else purpose = reason || tool;

    const card = document.createElement('article');
    card.className = 'chat-message-row system';
    card.style.marginTop = '4px';
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble warning';

    const timeLabel = escapeHtml(formatEventTime(event.created_at));
    bubble.innerHTML =
      '<div class="chat-bubble-meta"><span>&#128275; Permission needed</span><span>' + timeLabel + '</span></div>' +
      '<div class="chat-bubble-text">' +
      '<div style="margin-bottom:4px"><span style="font-family:monospace;font-size:0.75em;background:rgba(255,200,0,0.15);padding:1px 6px;border-radius:3px;color:rgba(255,200,0,0.9)">' + escapeHtml(tool) + '</span></div>' +
      '<div style="font-size:0.9em;line-height:1.4;margin-bottom:4px;">' + escapeHtml(purpose) + '</div>' +
      (reason && purpose.indexOf(reason) === -1 ? '<div style="font-size:0.8em;color:rgba(255,255,255,0.45);margin-bottom:4px;">' + escapeHtml(reason) + '</div>' : '') +
      '</div>';

    if (isPending && sessionId && taskId) {
      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:8px;margin-top:6px;align-items:center;';

      const yesBtn = document.createElement('button');
      yesBtn.textContent = '✓ Approve';
      yesBtn.className = 'approval-yes';
      yesBtn.onclick = async () => {
        yesBtn.disabled = true; noBtn.disabled = true;
        try {
          await api('/v1/sessions/' + sessionId + '/tool-approvals/' + taskId, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({decision: 'approved', reason: 'Approved via session chat'}),
          });
          card.remove();
        } catch(e) { console.error('approval failed', e); }
      };

      const noBtn = document.createElement('button');
      noBtn.textContent = '✗ Deny';
      noBtn.className = 'approval-no';
      noBtn.onclick = async () => {
        yesBtn.disabled = true; noBtn.disabled = true;
        try {
          await api('/v1/sessions/' + sessionId + '/tool-approvals/' + taskId, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({decision: 'denied', reason: 'Denied via session chat'}),
          });
          card.remove();
        } catch(e) { console.error('denial failed', e); }
      };

      btnRow.appendChild(yesBtn);
      btnRow.appendChild(noBtn);
      bubble.appendChild(btnRow);
    } else {
      const resp = event.data?.decision || '';
      const sc = resp === 'approved' ? '#6fbe6f' : resp === 'denied' ? '#be6f6f' : 'rgba(255,255,255,0.35)';
      const st = resp === 'approved' ? '✓ Approved' : resp === 'denied' ? '✗ Denied' : 'Pending';
      bubble.innerHTML += '<div style="font-size:0.8em;color:' + sc + ';margin-top:4px;">' + st + '</div>';
    }

    card.appendChild(bubble);
    el.appendChild(card);
    el.scrollTop = el.scrollHeight;
    return;
  }

  // tool_approval_responded: already handled by card.remove() above
  if (event.type === 'tool_approval_responded') { return; }

  const row = document.createElement('article');
  row.className = `chat-message-row ${role}`;
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${eventTone(event.type)}`;
  const meta = document.createElement('div');
  meta.className = 'chat-bubble-meta';
  const label = role === 'user' ? 'You' : role === 'error' ? 'Error' : role === 'system' ? 'System' : 'Agent';
  meta.innerHTML = `<span>${escapeHtml(label)}</span><span>${escapeHtml(formatEventTime(event.created_at))}</span>`;
  bubble.appendChild(meta);
  const text = timelineText(event, block);
  if (text) {
    if (typeof marked !== 'undefined' && (role === 'assistant' || role === 'system' || role === 'error')) {
      // Render markdown for agent/system/error messages
      const mdDiv = document.createElement('div');
      mdDiv.className = 'chat-bubble-text markdown-body';
      mdDiv.innerHTML = marked.parse(String(text));
      bubble.appendChild(mdDiv);
    } else {
      appendText(bubble, 'div', 'chat-bubble-text', text);
    }
  }
  if (role === 'assistant') {
    bubble.tabIndex = 0;
    bubble.classList.add('selectable-reply');
    bubble.title = 'Click to see model, endpoint and event details';
    bubble.onclick = () => openSessionEventModal(event, block);
    bubble.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') openSessionEventModal(event, block); };
  }
  if (role === 'user' && event.task_id) addPendingRow(event.task_id);
  if (block && (block.fields || block.meta || block.links)) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'inline-link-button';
    more.textContent = 'Open details';
    more.onclick = () => openSessionEventModal(event, block);
    bubble.appendChild(more);
  }
  row.appendChild(bubble);
  el.appendChild(row);
  while (el.children.length > 250) el.removeChild(el.firstChild);
  el.scrollTop = el.scrollHeight;
}

function renderGlobalEvent(event, prepend=false) {
  const list = document.getElementById('globalEvents');
  if (!list || !event) return;
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
  if (!globalEventPoll) globalEventPoll = setInterval(() => loadGlobalEvents(false).catch(()=>{}), 3500);
}

function setupTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.tab).classList.add('active');
      if (btn.dataset.tab === 'settings-tab') switchSettingsPanel('updates');
    };
  });
}

// ============================================================
// User auth state — login chip, token persistence, login modal
// ============================================================
const AUTH_TOKEN_KEY = 'pac_auth_token';

function getStoredToken() { return localStorage.getItem(AUTH_TOKEN_KEY) || ''; }
function setStoredToken(token) { token ? localStorage.setItem(AUTH_TOKEN_KEY, token) : localStorage.removeItem(AUTH_TOKEN_KEY); }

async function fetchCurrentUser() {
  const token = getStoredToken();
  if (!token) { showLoginModal(); return null; }
  try {
    const user = await api('/v1/auth/me');
    if (!user || !user.id) { showLoginModal(); return null; }
    return user;
  }
  catch { showLoginModal(); setStoredToken(''); return null; }
}

function showUserChip(user) {
  const chip = document.getElementById('userChip');
  const name = document.getElementById('userChipName');
  const loginBtn = document.getElementById('loginBtn');
  if (!chip || !name) return;
  if (user) {
    name.textContent = user.display_name || user.username;
    chip.style.display = 'flex';
    if (loginBtn) loginBtn.style.display = 'none';
  } else {
    chip.style.display = 'none';
    if (loginBtn) loginBtn.style.display = '';
  }
}

async function updateUserChip() { const user = await fetchCurrentUser(); showUserChip(user); return user; }

function logoutUser() { setStoredToken(''); showUserChip(null); init(); }

function openLoginModal() {
  let modal = document.getElementById('loginModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'loginModal';
    modal.className = 'modal-backdrop';
    modal.innerHTML = '<div class=modal-card style=max-width:360px><div class=modal-header><h2>Login to PAC</h2><button class="ghost-button small-ghost" onclick=closeLoginModal()>✕</button></div><div class=form-grid style=gap:.6rem><label>Username <input id=loginUsername placeholder=username /></label><label>Password <input id=loginPassword type=password placeholder=password /></label></div><div id=loginError class="muted small-text" style=margin-top:.5rem;color:#fca5a5></div><div class=button-row style=margin-top:.75rem><button id=doLoginBtn class=ghost-button>Login</button><button class="ghost-button small-ghost" onclick=closeLoginModal()>Cancel</button></div></div>';
    document.body.appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) closeLoginModal(); });
    document.getElementById('doLoginBtn').addEventListener('click', doLogin);
    document.getElementById('loginPassword').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
    document.getElementById('loginUsername').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('loginPassword').focus(); });
  }
  modal.style.display = 'flex';
  document.getElementById('loginUsername').focus();
}

function closeLoginModal() {
  const m = document.getElementById('loginModal');
  if (m) m.style.display = 'none';
  const ie = document.getElementById('loginError');
  if (ie) ie.textContent = '';
}

async function doLogin() {
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errorEl = document.getElementById('loginError');
  if (!username || !password) { errorEl.textContent = 'username and password required'; return; }
  try {
    const r = await fetch('/v1/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username, password})});
    const data = await r.json();
    if (!r.ok || !data.ok) { throw new Error(data.error || 'Login failed'); }
    setStoredToken(data.token);
    localStorage.setItem('pac_user', JSON.stringify(data.user));
    closeLoginModal();
    showUserChip(data.user);
    setupTabs(); setupEventsRail();
    await loadConfig();
    await updateUserChip();
    await loadSessions(); await loadApprovals(); await loadRunners();
    // Auto-select pi.dev session on startup
    setTimeout(async () => {
      const sessions = await api('/v1/sessions');
      const piDev = sessions.find(s => (s.metadata && s.metadata.agent_profile === 'main-pi-dev') || (s.agent_profile || '').includes('main-pi-dev'));
      if (piDev && !selectedSession) selectSession(piDev.id);
    }, 300);
    refreshDashboardMetricsOnStartup();
    await loadGlobalEvents(true);
    loadMcpBuildStatus().catch(()=>{});
    await loadBinaryFolderFilters().catch(()=>{});
    await loadSourceBinaryArtifacts().catch(()=>{});
    updateSourceActions();
  } catch(e) { errorEl.textContent = e.message; }
}

document.getElementById('loginBtn')?.addEventListener('click', openLoginModal);

async function api(path, opts = {}) {
  const token = getStoredToken();
  opts.headers = {...(opts.headers || {}), ...(token ? {'Authorization': `Bearer ${token}`} : {})};
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
  const r = await fetch(path, opts);
  if (r.status === 401) { setStoredToken(''); showUserChip(null); }
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
}
function opt(select, value, label) { const o = document.createElement('option'); o.value=value; o.textContent=label || value; select.appendChild(o); }
function fillSelects() {
  for (const id of ['agentProfile','workspaceProfile']) { const el=document.getElementById(id); if(el) el.innerHTML = ''; }
  if (document.getElementById('taskRunner')) document.getElementById('taskRunner').innerHTML = '<option value="">PAC/local</option>'; 
  document.getElementById('modelOverride').innerHTML = '<option value="">profile default</option>';
  if (document.getElementById('taskModel')) document.getElementById('taskModel').innerHTML = '<option value="">session model</option>';
  if (document.getElementById('sessionEndpoint')) document.getElementById('sessionEndpoint').innerHTML = '<option value="">select endpoint</option>';
  if (document.getElementById('sessionTopSelect')) document.getElementById('sessionTopSelect').innerHTML = '<option value="">Select session</option>';
  document.getElementById('permissionOverride').innerHTML = '<option value="">profile default</option>';
  if (document.getElementById('profileModel')) profileModel.innerHTML = '';
  if (document.getElementById('profileContextProfile')) profileContextProfile.innerHTML = '';
  if (document.getElementById('profilePermission')) profilePermission.innerHTML = '';
  if (document.getElementById('profileTools') && profileTools.tagName === 'SELECT') profileTools.innerHTML = '';
  if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') runnerTools.innerHTML = '';
  if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.innerHTML = '<option value="">auto</option>';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.innerHTML = '<option value="">none</option>';
  if (document.getElementById('toolPackage')) toolPackage.innerHTML = '<option value="">none</option>';
  Object.entries(config.agent_profiles || {}).forEach(([k,p]) => { if (p?.model && modelAvailability(p.model).ok) { opt(agentProfile,k); const wd=document.getElementById('workspaceDefaultProfile'); if (wd) opt(wd,k); } });
  Object.keys(config.workspaces || {}).forEach(k => { if (document.getElementById('workspaceProfile')) opt(workspaceProfile,k); if (document.getElementById('runnerDefaultWorkspace')) opt(runnerDefaultWorkspace,k); if (document.getElementById('profileWorkspace')) opt(profileWorkspace,k); });
  Object.keys(config.models || {}).forEach(k => { if (modelAvailability(k).ok) { opt(modelOverride,k); if (document.getElementById('taskModel')) opt(taskModel,k); } if (document.getElementById('profileModel')) opt(profileModel,k, `${k}${modelAvailability(k).ok ? '' : ' (not available)'}`); });
  if (document.getElementById('modelProvider')) { modelProvider.innerHTML=''; Object.keys(config.providers || {}).forEach(k => opt(modelProvider,k)); }
  fillModelEndpointOptions();
  Object.keys(config.permission_profiles || {}).forEach(k => { opt(permissionOverride,k); if (document.getElementById('profilePermission')) opt(profilePermission,k); });
  Object.keys(config.context_profiles || {}).forEach(k => { if (document.getElementById('profileContextProfile')) opt(profileContextProfile,k); });
  Object.keys(config.tool_packages || {}).forEach(k => { if (document.getElementById('toolPackage')) opt(toolPackage,k); });
  Object.entries(config.tools || {}).forEach(([k,t]) => {
    const label = `${k}${t.package ? ' · '+t.package : ''}${t.enabled === false ? ' (disabled)' : ''}`;
    if (document.getElementById('profileTools') && profileTools.tagName === 'SELECT') opt(profileTools,k,label);
    if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') opt(runnerTools,k,label);
  });
}
function emitUiEvent(type, message, data=null) {
  renderGlobalEvent({
    id: `${type}_${Date.now()}_${Math.random()}`,
    type,
    message: message || prettyEventType(type),
    created_at: new Date().toISOString(),
    session_id: 'system',
    data: data ? {details: data} : {},
  }, true);
}
function showInline(id, obj) {
  if (id === 'modelFormResult') {
    const message = typeof obj === 'string' ? obj : (obj?.message || obj?.status || 'Model action completed');
    emitUiEvent('model_action', message, obj);
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.hidden = true; }
    return;
  }
  const el = document.getElementById(id);
  if (!el) return;
  el.hidden = false;
  if (typeof obj === 'string') { el.textContent = obj; } else { el.textContent = obj?.message || obj?.status || 'Done. Details were added to Events.'; emitUiEvent('ui_action_completed', el.textContent, obj); }
}
function paneError(message, details=null) {
  renderGlobalEvent({
    id: `ui_error_${Date.now()}_${Math.random()}`,
    type: 'ui_error',
    message: message || 'Request failed',
    created_at: new Date().toISOString(),
    data: details ? {details} : {},
  }, true);
}
async function runWithPaneError(fn, message='Action failed') {
  try { return await fn(); }
  catch (e) { paneError(message, e.message || String(e)); return null; }
}

function modelAvailability(name) {
  const m = config.models?.[name];
  if (!m) return {ok:false, reason:'not configured'};
  const p = config.providers?.[m.provider];
  if (!p) return {ok:false, reason:`missing provider ${m.provider}`};
  if (p.enabled === false || p.status === 'disabled' || p.status === 'failed') return {ok:false, reason:`provider ${p.status || 'disabled'}`};
  const live = p.cached_models || [];
  if (live.length) {
    const wanted = String(m.model || name);
    const ids = live.map(x => String(x.id || x.name || x.model || '')).filter(Boolean);
    if (!ids.includes(wanted)) return {ok:false, reason:`not returned by provider (${wanted})`};
  }
  return {ok:true, reason:'available'};
}

function csv(value) { return (value || '').split(',').map(x => x.trim()).filter(Boolean); }
function modelSummaryLine(model) {
  const bits = [];
  if (model.object) bits.push(model.object);
  if (model.owned_by) bits.push(`owner: ${model.owned_by}`);
  if (model.size) bits.push(`size: ${model.size}`);
  return bits.join(' · ');
}
async function fetchProviderModels(name) {
  try { return await api(`/v1/providers/${name}/models`); }
  catch (e) { return {ok:false, error:e.message, models:[]}; }
}
function providerStatus(p) {
  if (p.enabled === false) return 'disabled';
  // Show actual server status if live_status is available from backend
  if (p.live_status === false || p.live_status === 'offline') return 'offline';
  if (p.live_status === true || p.live_status === 'online') return 'connected';
  return p.status || 'unknown';
}
function providerStatusClass(status) {
  if (status === 'connected') return 'ok';
  if (status === 'offline') return 'offline';
  if (status === 'failed') return 'failed';
  if (status === 'disabled') return '';
  return 'attention';
}
async function toggleProvider(name, enabled) {
  await api(`/v1/providers/${name}/toggle`, {method:'POST', body:JSON.stringify({enabled})});
  await loadConfig();
  const el = document.getElementById('providerFormResult');
  if (el) el.textContent = '';
}
async function deleteProvider(name) {
  if (!confirm(`Delete provider '${name}'? Models using this provider will also be removed.`)) return;
  await api(`/v1/providers/${name}`, {method:'DELETE'});
  await loadConfig();
  showInline('providerFormResult', `Deleted provider ${name}`);
}
async function inspectLmStudioProvider(name) {
  const r = await api(`/v1/providers/${name}/lmstudio/inspect`);
  showInline('providerFormResult', r);
  await loadConfig();
}
async function showLmStudioCompanionScript(name) {
  const r = await api(`/v1/providers/${name}/lmstudio/companion-script`);
  const text = r.script || '';
  const blob = new Blob([text], {type:'text/x-python'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `pac-lmstudio-companion-${name}.py`; a.click();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
  showInline('providerFormResult', `Companion script generated for ${name}. Run it manually on the LM Studio host.`);
}
async function lmStudioLoadModel(name) {
  const model = prompt('Model id to load, for example openai/gpt-oss-20b');
  if (!model) return;
  const context = prompt('Context length', '16384');
  const r = await api(`/v1/providers/${name}/lmstudio/load`, {method:'POST', body:JSON.stringify({model, context_length:Number(context||0)||undefined, flash_attention:true, echo_load_config:true})});
  showInline('providerFormResult', r);
  await loadConfig();
}
async function lmStudioUnloadModel(name) {
  const instance_id = prompt('Instance id / loaded model id to unload');
  if (!instance_id) return;
  const r = await api(`/v1/providers/${name}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id})});
  showInline('providerFormResult', r);
  await loadConfig();
}
async function lmStudioDownloadModel(name) {
  const model = prompt('Model id to download, for example ibm/granite-4-micro');
  if (!model) return;
  const r = await api(`/v1/providers/${name}/lmstudio/download`, {method:'POST', body:JSON.stringify({model})});
  showInline('providerFormResult', r);
}

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

function renderProviders() {
  const el = document.getElementById('providers'); if (!el) return; el.innerHTML = '';
  const entries = Object.entries(config.providers || {});
  if (!entries.length) { el.innerHTML = '<div class="empty-events">No providers configured yet.</div>'; return; }
  for (const [name,p] of entries) {
    const status = providerStatus(p);
    const r = providerRuntime(p);
    const h = providerHost(p);
    const card = document.createElement('div'); card.className='provider-card';
    card.innerHTML = `
      <div class="provider-card-head">
        <div class="provider-title-block"><h3>${escapeHtml(name)}</h3><span class="muted">${escapeHtml(p.type || 'provider')}</span></div>
        <span class="pill ${providerStatusClass(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="provider-device-panel">
        <b>${escapeHtml(fmtProviderDevice(p))}</b>
        <small>${escapeHtml(r.execution_type || r.executionType || 'unknown')} inference · ${escapeHtml(h.kind || 'unknown host')}${h.os ? ` · ${escapeHtml(h.os)}` : ''}${h.arch ? ` · ${escapeHtml(h.arch)}` : ''}</small>
      </div>
      <div class="provider-meta-line"><span>${escapeHtml(p.base_url || 'no base URL')}</span></div>
      ${p.live_status ? `<div class="provider-live-status ${p.live_status === 'online' ? 'live-online' : 'live-offline'}">
        <span class="live-dot"></span>
        <span>${p.live_status === 'online' ? 'LM Studio running — ' + (p.loaded_models?.length ? p.loaded_models.length + ' model(s) loaded: ' + p.loaded_models.join(', ') : 'no models loaded') : 'LM Studio offline'}</span>
      </div>` : ''}
      <div class="provider-pill-list">${providerCapabilityPills(p)}</div>
      ${p.last_error && p.live_status !== 'offline' ? `<div class="failed-text small-text">${escapeHtml(p.last_error)}</div>` : ''}
      <div class="remote-models muted" id="providerModels_${name}">${p.enabled === false ? 'provider disabled' : (p.live_status === 'offline' ? 'server unreachable' : 'checking endpoint…')}</div>`;
    const actions = document.createElement('div'); actions.className='provider-actions button-row';
    const label = document.createElement('label'); label.className='switch'; label.title='Connect/disconnect provider';
    const input = document.createElement('input'); input.type='checkbox'; input.checked = p.enabled !== false && status === 'connected';
    const slider = document.createElement('span'); slider.className='switch-slider';
    input.onchange = async(ev)=>{ ev.stopPropagation(); input.disabled=true; try { await toggleProvider(name, input.checked); } catch(e){ alert(e.message); input.checked=false; } finally { input.disabled=false; } };
    label.appendChild(input); label.appendChild(slider);
    if (p.type === 'lmstudio') {
      const inspect=document.createElement('button'); inspect.textContent='Inspect'; inspect.className='ghost-button'; inspect.onclick=(ev)=>{ ev.stopPropagation(); inspectLmStudioProvider(name).catch(e=>alert(e.message)); };
      const script=document.createElement('button'); script.textContent='Companion'; script.className='ghost-button'; script.onclick=(ev)=>{ ev.stopPropagation(); showLmStudioCompanionScript(name).catch(e=>alert(e.message)); };
      const load=document.createElement('button'); load.textContent='Load'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); lmStudioLoadModel(name).catch(e=>alert(e.message)); };
      actions.appendChild(inspect); actions.appendChild(script); actions.appendChild(load);
    }
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.onclick=(ev)=>{ ev.stopPropagation(); openProviderModal(name); };
    const del=document.createElement('button'); del.textContent='Delete'; del.className='danger-button'; del.onclick=(ev)=>{ ev.stopPropagation(); deleteProvider(name).catch(e=>alert(e.message)); };
    actions.appendChild(label); actions.appendChild(edit); actions.appendChild(del); card.appendChild(actions); el.appendChild(card);
    if (p.enabled !== false) refreshProviderModelPreview(name).catch(()=>{});
  }
}
async function refreshProviderModelPreview(name) {
  const target = document.getElementById(`providerModels_${name}`);
  if (!target) return;
  const result = await fetchProviderModels(name);
  if (!result.ok) { target.textContent = `model list unavailable: ${result.error || result.response?.error || 'unknown error'}`; return; }
  const models = result.models || [];
  target.textContent = models.length ? `server models: ${models.slice(0,5).map(m => m.id || m.name).join(', ')}${models.length > 5 ? ` +${models.length-5} more` : ''}` : 'server returned no models';
}
function modelScores() { return window.__modelScores || {}; }
function capabilityTag(cap) {
  const map = {
    vision: {label: 'Vision', color: '#7c3aed'},
    image_input: {label: 'Image Input', color: '#7c3aed'},
    json: {label: 'JSON', color: '#0891b2'},
    streaming: {label: 'Streaming', color: '#059669'},
    reasoning: {label: 'Reasoning', color: '#d97706'},
    tool_use: {label: 'Tool Use', color: '#dc2626'},
    tools: {label: 'Tool Use', color: '#dc2626'},
    agentic: {label: 'Agentic', color: '#9333ea'},
    coding: {label: 'Coding', color: '#0ea5e9'},
    function_calling: {label: 'Function Calling', color: '#ea580c'},
  };
  const c = map[cap] || {label: cap, color: '#6b7280'};
  return `<span class="model-cap-tag" style="background:${c.color}22;color:${c.color};border-color:${c.color}55">${c.label}</span>`;
}
function modelScoreIndicators(name) {
  const scores = modelScores();
  const s = scores[name] || {};
  const speed = s.speed_score;
  const config = s.config_score;
  const speedTip = speed != null ? `Speed score: ${speed}/100 — ${speed >= 80 ? 'well tuned' : speed >= 50 ? 'average' : 'below expected'}` : 'No performance data yet';
  const configTip = config != null ? `Config score: ${config}/100 — ${config >= 80 ? 'optimally configured' : config >= 50 ? 'partially tuned' : 'needs review'}` : 'Not yet analyzed by model skill';
  const speedClass = speed == null ? 'score-null' : speed >= 80 ? 'score-ok' : speed >= 50 ? 'score-warn' : 'score-bad';
  const configClass = config == null ? 'score-null' : config >= 80 ? 'score-ok' : config >= 50 ? 'score-warn' : 'score-bad';
  return `<span class="model-score-indicators" title="${speedTip}">
    <span class="score-dot ${speedClass}" title="Speed — ${speedTip}"></span>
    <span class="score-dot ${configClass}" title="Config — ${configTip}"></span>
  </span>`;
}
function renderModels() {
  const el = document.getElementById('models-configured'); if (!el) return; el.innerHTML = '';
  const models = Object.entries(config.models || {});
  if (!models.length) {
    el.innerHTML = '<div class="muted small-text" style="padding:1rem">No models configured yet.</div>';
    return;
  }
  for (const [name,m] of models) {
    const av = modelAvailability(name);
    const provider = config.providers?.[m.provider || ''];
    const caps = m.capabilities || {};
    const capsHtml = Object.entries(caps).filter(([k,v]) => v === true).map(([k]) => capabilityTag(k)).join(' ') ||
      (provider?.type === 'lmstudio' ? '<span class="muted small-text">no capabilities set</span>' : '');
    const lmSettings = (provider?.type === 'lmstudio') ? [
      m.lm_context_length ? `ctx:${m.lm_context_length}` : null,
      m.lm_gpu_offload != null ? `offload:${m.lm_gpu_offload}` : null,
      m.lm_temperature != null ? `temp:${m.lm_temperature}` : null,
      m.lm_flash_attention ? 'flash-attn' : null,
      m.lm_kv_gpu ? 'kv-gpu' : null,
    ].filter(Boolean).join(' · ') : null;

    const wrap=document.createElement('div'); wrap.className='model-card clickable-row' + (av.ok ? '' : ' model-card-unavailable');
    wrap.innerHTML = `<div class="model-card-header">
      <div class="model-card-name-row">
        <code class="model-card-name">${escapeHtml(name)}</code>
        <span class="model-provider-badge">${escapeHtml(m.provider || '-')}</span>
        ${modelScoreIndicators(name)}
        ${av.ok ? '' : `<span class="warn-text small-text" style="margin-left:6px">[${av.reason || 'unavailable'}]</span>`}
      </div>
    </div>
    <div class="model-card-body">
      <div class="model-card-meta">
        <span class="model-meta-item"><span class="muted">Model ID</span> <code>${escapeHtml(m.model || '-')}</code></span>
        <span class="model-meta-item"><span class="muted">Format</span> <span>${escapeHtml(m.format || 'chat')}</span></span>
        <span class="model-meta-item"><span class="muted">Arch</span> <span>${escapeHtml(m.architecture || '-')}</span></span>
        ${m.parameter_count ? `<span class="model-meta-item"><span class="muted">Params</span> <span>${escapeHtml(m.parameter_count)}</span></span>` : ''}
      </div>
      <div class="model-card-caps">${capsHtml}</div>
      <div class="model-card-context">
        <span class="model-meta-item"><span class="muted">Context</span> <span>${m.context_window?.toLocaleString() || '-'}</span></span>
        <span class="model-meta-item"><span class="muted">Max out</span> <span>${m.max_output_tokens?.toLocaleString() || '-'}</span></span>
      </div>
      ${lmSettings ? `<div class="model-card-lm-settings"><span class="muted small-text">LM Studio:</span> ${escapeHtml(lmSettings)}</div>` : ''}
    </div>`;
    wrap.onclick=()=>openModelModal(name);
    const actions=document.createElement('div'); actions.className='button-row';
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.className='ghost-button'; edit.onclick=(ev)=>{ ev.stopPropagation(); openModelModal(name); };
    const test=document.createElement('button'); test.textContent='Test'; test.className='ghost-button'; test.onclick=(ev)=>{ ev.stopPropagation(); api(`/v1/models/${name}/test`,{method:'POST'}).then(r=>showInline('modelFormResult',{model:name,...r})).catch(e=>showInline('modelFormResult',e.message)); };
    actions.appendChild(edit); actions.appendChild(test);
    if (provider?.type === 'lmstudio') {
      const load=document.createElement('button'); load.textContent='Load'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); loadLmStudioModelByName(name).catch(e=>alert(e.message)); };
      actions.appendChild(load);
    }
    const card = wrap; card.appendChild(actions);
    el.appendChild(wrap);
  }
  // Update "more available" hint next to + button
  updateModelsAvailableHint();
}

function updateModelsAvailableHint() {
  const hint = document.getElementById('modelsMoreAvailable');
  if (!hint) return;
  const unconfCount = getUnconfiguredModelsCount();
  if (unconfCount > 0) {
    hint.textContent = unconfCount + ' more available';
    hint.style.display = '';
  } else {
    hint.style.display = 'none';
  }
}

function getUnconfiguredModelsCount() {
  // Count models returned by providers that are not yet configured
  let count = 0;
  for (const [pname, p] of Object.entries(config.providers || {})) {
    const cached = p.cached_models || [];
    for (const m of cached) {
      const mid = m.id || m.name || '';
      if (!mid) continue;
      const isConfigured = Object.values(config.models || {}).some(cm => cm.provider === pname && (cm.model || '') === mid);
      if (!isConfigured) count++;
    }
  }
  return count;
}

function renderUnconfiguredModels() {
  const el = document.getElementById('unconfiguredModelsList');
  if (!el) return;
  const rows = [];
  for (const [pname, p] of Object.entries(config.providers || {})) {
    const cached = p.cached_models || [];
    for (const m of cached) {
      const mid = m.id || m.name || '';
      if (!mid) continue;
      const isConfigured = Object.values(config.models || {}).some(cm => cm.provider === pname && (cm.model || '') === mid);
      if (isConfigured) continue;
      const summary = modelSummaryLine(m);
      rows.push({provider: pname, model: mid, summary});
    }
  }
  if (!rows.length) {
    el.innerHTML = '<div class="muted small-text">All available models are configured.</div>';
    return;
  }
  const html = rows.map(r => `<div class="unconfig-model-item">
    <div class="unconfig-model-info">
      <code class="unconfig-model-name">${escapeHtml(r.model)}</code>
      <span class="muted small-text">${escapeHtml(r.provider)}</span>
      ${r.summary ? `<span class="muted small-text"> · ${escapeHtml(r.summary)}</span>` : ''}
    </div>
    <button class="ghost-button small-ghost" data-use-unconfig="1" data-provider="${escapeHtml(r.provider)}" data-model="${escapeHtml(r.model)}">Use</button>
  </div>`).join('');
  el.innerHTML = html;
  el.querySelectorAll('button[data-use-unconfig]').forEach(btn => {
    btn.onclick = () => {
      openModelModal();
      modelProvider.value = btn.dataset.provider;
      modelId.value = btn.dataset.model;
      const key = btn.dataset.model.replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
      modelName.value = key;
      modelRunsOn.value = '';
      setModalStatus('modelModalStatus', 'Review and save.');
      closeUnconfigModels();
    };
  });
}

function toggleUnconfiguredModels() {
  const panel = document.getElementById('unconfiguredModelsPanel');
  if (!panel) return;
  if (panel.hidden) {
    renderUnconfiguredModels();
    panel.hidden = false;
  } else {
    panel.hidden = true;
  }
}

function closeUnconfigModels() {
  const panel = document.getElementById('unconfiguredModelsPanel');
  if (panel) panel.hidden = true;
}

function renderActiveModelUsage() {
  const el = document.getElementById('models-active-sessions');
  if (!el) return;
  const sessions = window.__activeSessions || [];
  const byModel = {};
  for (const s of sessions) {
    if (!byModel[s.model]) byModel[s.model] = [];
    byModel[s.model].push(s);
  }
  if (!Object.keys(byModel).length) { el.innerHTML = '<div class="muted small-text">No active sessions.</div>'; return; }
  const rows = Object.entries(byModel).map(([model, sess]) => {
    const names = sess.map(s => s.name || s.id || '?').join(', ');
    const statusBadges = sess.map(s => `<span class="pill ${s.status === 'running' ? 'ok-pill' : ''}">${s.status}</span>`).join(' ');
    return `<tr><td><code>${escapeHtml(model)}</code></td><td>${escapeHtml(names)}</td><td>${statusBadges}</td></tr>`;
  }).join('');
  el.innerHTML = `<table class="compact-table"><thead><tr><th>Model</th><th>Session(s)</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function refreshActiveSessions() {
  try {
    const sessions = await api('/v1/sessions');
    window.__activeSessions = (sessions || []).filter(s => s.status === 'running' || s.status === 'created');
    renderActiveModelUsage();
  } catch(e) { /* ignore */ }
}
async function renderLiveModels() {
  const live = document.getElementById('models-live');
  if (!live) return;
  const providers = Object.keys(config.providers || {});
  if (!providers.length) { live.textContent = 'No providers configured.'; return; }
  const chunks = [];
  for (const name of providers) {
    const result = await fetchProviderModels(name);
    if (!result.ok) { chunks.push(`<div class="remote-provider failed"><b>${name}</b><br><span>${result.error || result.response?.error || 'model listing failed'}</span></div>`); continue; }
    const models = result.models || [];
    const rows = models.map(m => {
      const id = m.id || m.name;
      const key = `${name}-${String(id).replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase()}`.replace(/^-+|-+$/g,'');
      const configured = !!config.models?.[key] || Object.values(config.models || {}).some(x => x.provider === name && (x.model || '') === id);
      return `<li><button class="link-button" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${escapeHtml(id)}</button><button class="ghost-button mini-button" data-add-live-model="1" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${configured ? 'Edit' : 'Configure'}</button><span class="muted">${escapeHtml(modelSummaryLine(m))}</span></li>`;
    }).join('');
    chunks.push(`<div class="remote-provider"><b>${escapeHtml(name)}</b> <span class="pill ${models.length ? 'ok' : ''}">${models.length} models</span><ul>${rows || '<li class="muted">No models returned</li>'}</ul></div>`);
  }
  live.innerHTML = chunks.join('');
  live.querySelectorAll('button[data-model]').forEach(btn => {
    btn.onclick = () => {
      modelProvider.value = btn.dataset.provider;
      modelId.value = btn.dataset.model;
      modelName.value = btn.dataset.key || btn.dataset.model.replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
      modelRunsOn.value = '';
    };
  });
  live.querySelectorAll('button[data-add-live-model]').forEach(btn => {
    btn.onclick = async () => {
      openModelModal();
      modelProvider.value = btn.dataset.provider;
      modelId.value = btn.dataset.model;
      modelName.value = btn.dataset.key || btn.dataset.model.replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
      modelRunsOn.value = '';
      setModalStatus('modelModalStatus', 'Review and save this model.');
    };
  });
  // Also refresh active sessions display
  renderActiveModelUsage();
}
function selectedToolNames() {
  const sel = document.getElementById('profileTools');
  if (!sel) return [];
  if (sel.tagName === 'SELECT') return Array.from(sel.selectedOptions).map(o => o.value).filter(Boolean);
  return csv(sel.value);
}
function setSelectedToolNames(names) {
  const sel = document.getElementById('profileTools');
  if (!sel) return;
  const wanted = new Set(names || []);
  if (sel.tagName === 'SELECT') Array.from(sel.options).forEach(o => { o.selected = wanted.has(o.value); });
  else sel.value = (names || []).join(', ');
}
function renderTools() {
  const pkgEl = document.getElementById('tools-packages');
  if (pkgEl) {
    pkgEl.innerHTML = Object.entries(config.tool_packages || {}).map(([name,p]) => `<div class="row"><div><b>${escapeHtml(name)}</b> <span class="pill ${p.enabled !== false ? 'ok-pill' : ''}">${p.enabled !== false ? 'enabled':'disabled'}</span><br><span class="muted">${escapeHtml(p.description || '')}</span><br><span class="muted">tools: ${escapeHtml((p.tools || []).join(', ') || '-')}</span></div></div>`).join('') || '<div class="muted">No tool packages configured.</div>';
  }
  const pluginEl = document.getElementById('pluginsOverview');
  if (pluginEl) {
    pluginEl.innerHTML = Object.entries(config.plugins || {}).map(([name,p]) => `<div class="row"><div><b>${escapeHtml(name)}</b> <span class="pill">${escapeHtml(p.kind || 'plugin')}</span><br><span class="muted">${escapeHtml(p.description || '')}</span><br><span class="muted">requires: ${escapeHtml((p.requires_tools || []).join(', ') || '-')}</span></div></div>`).join('') || '<div class="muted">No plugins configured.</div>';
  }
  const el = document.getElementById('toolsOverview'); if (!el) return; el.innerHTML = '';
  for (const [name,t] of Object.entries(config.tools || {})) {
    const row=document.createElement('div'); row.className='row clickable-row';
    row.innerHTML = `<div><b>${escapeHtml(name)}</b> <span class="pill ${t.enabled ? 'ok-pill' : ''}">${t.enabled ? 'enabled':'disabled'}</span>${t.package ? ` <span class="pill">${escapeHtml(t.package)}</span>` : ''}<br><span class="muted">${escapeHtml(t.description || '')}</span><br><span class="muted">binaries: ${escapeHtml((t.binaries || []).join(', ') || '-')}</span><br><span class="muted">approval: ${escapeHtml((t.approval_required_patterns || []).join(', ') || '-')}</span></div>`;
    row.onclick=()=>openToolModal(name);
    el.appendChild(row);
  }
}

function endpointName(id) {
  if (!id) return 'PAC/local';
  const r = (window.__pacEndpoints || []).find(x => x.id === id);
  return r ? `${r.name || r.id} (${r.status || 'unknown'})` : id;
}
function selectedRunnerToolNames() {
  const sel = document.getElementById('runnerTools');
  if (!sel) return [];
  return Array.from(sel.selectedOptions || []).map(o => o.value).filter(Boolean);
}
function setSelectedRunnerToolNames(names) {
  const sel = document.getElementById('runnerTools');
  if (!sel) return;
  const wanted = new Set(names || []);
  Array.from(sel.options || []).forEach(o => { o.selected = wanted.has(o.value); });
  updateRunnerToolPackagePreview();
}
function packageNamesForTools(names) {
  const selected = new Set(names || []);
  return Object.entries(config?.tool_packages || {}).filter(([_,pkg]) => (pkg.tools || []).length && (pkg.tools || []).every(t => selected.has(t))).map(([name]) => name);
}
function endpointPiContainer(r) {
  return r.metadata?.agent_runtime?.pi_container || r.capabilities?.pi_container || {};
}

function endpointFeatureChips(r, effectiveTools = []) {
  const caps = r.capabilities || {};
  const tools = caps.tools || {};
  const pi = endpointPiContainer(r) || {};
  const enablement = r.metadata?.agent_enablement || {};
  const chips = [];
  const add = (label, state, required=false, title='') => {
    const cls = state === 'available' ? 'ok-pill' : (required ? 'required-missing-pill' : 'optional-missing-pill');
    const text = state === 'available' ? label : `${label} missing`;
    chips.push(`<span class="pill feature-pill ${cls}" title="${escapeHtml(title || text)}">${escapeHtml(text)}</span>`);
  };
  add('commands', (r.status === 'online' || r.metadata?.local_control_plane) ? 'available' : 'missing', true, 'Endpoint must be reachable for queued commands.');
  add('workspace', r.metadata?.default_workspace ? 'available' : 'missing', true, 'Every endpoint should have a default workspace.');
  add('pi.dev', pi.available ? 'available' : 'missing', true, pi.reason || 'Required for pi.dev container sessions on this endpoint.');
  add('PAC wrapper', (enablement.node_available && enablement.pi_available) ? 'available' : 'missing', !!(enablement.requested || enablement.required), enablement.detail || 'Required when this endpoint runs pi.dev workloads.');
  add('container runtime', (caps.container_runtimes || []).length ? 'available' : 'missing', true, 'Required to build/run the pi.dev and containerized tooling.');
  if (caps.gpu?.available || (caps.gpu?.devices || []).length) add('GPU', 'available', false, 'Detected endpoint hardware.');
  (effectiveTools || []).slice(0, 8).forEach(name => {
    const toolState = tools[name]?.available ? 'available' : 'missing';
    add(name, toolState, true, `Configured endpoint tool: ${name}`);
  });
  if ((effectiveTools || []).length > 8) chips.push(`<span class="pill feature-pill">+${(effectiveTools || []).length - 8} tools</span>`);
  return chips.join('');
}

function endpointRuntimeLines(r) {
  const runtime = r.metadata?.agent_runtime || {};
  const lines = [];
  lines.push(`state: ${runtime.status || r.status || 'unknown'}`);
  if (runtime.kind) lines.push(`kind: ${runtime.kind}`);
  if (runtime.version || r.metadata?.runner_version || r.metadata?.endpoint_version) lines.push(`version: ${runtime.version || r.metadata?.runner_version || r.metadata?.endpoint_version}`);
  if (runtime.detail) lines.push(`detail: ${runtime.detail}`);
  const pi = endpointPiContainer(r);
  if (pi) {
    lines.push(`pi image: ${pi.image || '-'}`);
    lines.push(`pi image available: ${pi.available ? 'yes' : 'no'}`);
    if (pi.runtime) lines.push(`container runtime: ${pi.runtime}`);
    if (pi.reason) lines.push(`reason: ${pi.reason}`);
    if (pi.hint) lines.push(`hint: ${pi.hint}`);
    if (pi.build_command) lines.push(`build: ${pi.build_command}`);
  }
  return lines.join('\n');
}
function updateRunnerToolPackagePreview() {
  const el = document.getElementById('runnerToolPackagePreview');
  if (!el) return;
  const names = selectedRunnerToolNames();
  const packages = packageNamesForTools(names);
  const toolPills = names.map(n => `<span class="pill ok-pill">${escapeHtml(n)}</span>`).join('');
  const packagePills = packages.map(n => `<span class="pill ok-pill">${escapeHtml(n)} package</span>`).join('');
  el.innerHTML = packagePills + toolPills || '<span class="muted">No endpoint tools selected.</span>';
}
function fillModelEndpointOptions(endpoints = window.__pacEndpoints || []) {
  const sel = document.getElementById('modelRunsOn');
  if (!sel || sel.tagName !== 'SELECT') return;
  const current = sel.value;
  sel.innerHTML = '<option value="">PAC/local</option>';
  (endpoints || []).forEach(r => opt(sel, r.id, `${r.name || r.id} (${r.status || 'unknown'})`));
  if (current && !Array.from(sel.options).some(o => o.value === current)) opt(sel, current, current);
  sel.value = current || '';
}
function setModalStatus(id, value='') {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}
function openProviderModal(name='') {
  if (name) fillProviderForm(name); else {
    providerName.value=''; if (document.getElementById('providerPreset')) providerPreset.value='custom-openai'; providerType.value='openai-compatible'; providerBaseUrl.value=''; providerApiKeyEnv.value=''; providerApiKey.value=''; providerTimeout.value=30; fillProviderRuntimeFields({});
  }
  setModalStatus('providerModalStatus');
  const modal = document.getElementById('providerModal');
  if (modal) modal.hidden = false;
  setTimeout(()=>document.getElementById('providerName')?.focus(), 0);
}
function closeProviderModal() { const modal = document.getElementById('providerModal'); if (modal) modal.hidden = true; }
function openModelModal(name='') {
  fillModelEndpointOptions();
  if (name) fillModelForm(name); else {
    modelName.value=''; modelProvider.value=modelProvider.options[0]?.value || ''; modelId.value=''; modelRunsOn.value=''; modelContextWindow.value=4096; modelMaxOutput.value=1024;
    modelSupportsVision.checked=false; modelSupportsJson.checked=false; modelSupportsStreaming.checked=true;
    modelSupportsReasoning.checked=false; modelSupportsToolUse.checked=false;
    modelSupportsAgentic.checked=false; modelSupportsCoding.checked=false; modelSupportsFunctionCalling.checked=false;
    if (document.getElementById('modelArchitecture')) modelArchitecture.value='';
    if (document.getElementById('modelFormat')) modelFormat.value='chat';
    if (document.getElementById('modelParameterCount')) modelParameterCount.value='';
    fillLmStudioRuntimeFields({});
  }
  updateLmStudioModelControls();
  setModalStatus('modelModalStatus');
  const modal = document.getElementById('modelModal');
  if (modal) modal.hidden = false;
  setTimeout(()=>document.getElementById('modelName')?.focus(), 0);
}
function closeModelModal() { const modal = document.getElementById('modelModal'); if (modal) modal.hidden = true; }

function fillProviderForm(name) {
  const p = config.providers?.[name]; if (!p) return;
  if (document.getElementById('providerPreset')) providerPreset.value='';
  providerName.value = name; providerType.value = p.type || 'openai-compatible'; providerBaseUrl.value = p.base_url || '';
  providerApiKeyEnv.value = p.api_key_env || ''; providerApiKey.value = p.api_key || ''; providerTimeout.value = p.timeout_seconds || 30; fillProviderRuntimeFields(p.runtime || {});
}
function fillModelForm(name) {
  const m = config.models?.[name]; if (!m) return;
  modelName.value=name; modelProvider.value=m.provider || ''; modelId.value=m.model || ''; modelRunsOn.value=m.runs_on || '';
  modelContextWindow.value=m.context_window || 4096; modelMaxOutput.value=m.max_output_tokens || 1024;
  modelSupportsVision.checked=!!m.capabilities?.supports_vision; modelSupportsJson.checked=!!m.capabilities?.supports_json;
  modelSupportsStreaming.checked=m.capabilities?.supports_streaming !== false;
  modelSupportsReasoning.checked=!!m.capabilities?.supports_reasoning;
  modelSupportsToolUse.checked=!!m.capabilities?.supports_tool_use;
  modelSupportsAgentic.checked=!!m.capabilities?.supports_agentic;
  modelSupportsCoding.checked=!!m.capabilities?.supports_coding;
  modelSupportsFunctionCalling.checked=!!m.capabilities?.supports_function_calling;
  if (document.getElementById('modelArchitecture')) modelArchitecture.value=m.architecture || '';
  if (document.getElementById('modelFormat')) modelFormat.value=m.format || 'chat';
  if (document.getElementById('modelParameterCount')) modelParameterCount.value=m.parameter_count || '';
  fillLmStudioRuntimeFields(m.extra?.lmstudio_runtime || {});
  updateLmStudioModelControls();
}

function currentModelProvider() {
  return config.providers?.[modelProvider?.value || ''] || null;
}
function updateLmStudioModelControls() {
  const box = document.getElementById('lmStudioModelControls');
  if (!box) return;
  const provider = currentModelProvider();
  box.hidden = !provider || provider.type !== 'lmstudio';
}
function numberOrNull(value) {
  if (value === undefined || value === null || String(value).trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function fillLmStudioRuntimeFields(runtime) {
  const r = runtime || {};
  if (document.getElementById('lmModelContextLength')) lmModelContextLength.value = r.context_length || '';
  if (document.getElementById('lmModelGpuOffload')) lmModelGpuOffload.value = r.gpu_offload ?? '';
  if (document.getElementById('lmModelEvalBatch')) lmModelEvalBatch.value = r.eval_batch_size || '';
  if (document.getElementById('lmModelTemperature')) lmModelTemperature.value = r.temperature ?? '';
  if (document.getElementById('lmModelTopP')) lmModelTopP.value = r.top_p ?? '';
  if (document.getElementById('lmModelSeed')) lmModelSeed.value = r.seed ?? '';
  if (document.getElementById('lmModelFlashAttention')) lmModelFlashAttention.checked = r.flash_attention !== false;
  if (document.getElementById('lmModelKvGpu')) lmModelKvGpu.checked = r.offload_kv_cache_to_gpu !== false;
  if (document.getElementById('lmModelEchoLoadConfig')) lmModelEchoLoadConfig.checked = r.echo_load_config !== false;
}
function collectLmStudioRuntimeFields() {
  const runtime = {
    context_length: numberOrNull(document.getElementById('lmModelContextLength')?.value),
    gpu_offload: numberOrNull(document.getElementById('lmModelGpuOffload')?.value),
    eval_batch_size: numberOrNull(document.getElementById('lmModelEvalBatch')?.value),
    temperature: numberOrNull(document.getElementById('lmModelTemperature')?.value),
    top_p: numberOrNull(document.getElementById('lmModelTopP')?.value),
    seed: numberOrNull(document.getElementById('lmModelSeed')?.value),
    flash_attention: !!document.getElementById('lmModelFlashAttention')?.checked,
    offload_kv_cache_to_gpu: !!document.getElementById('lmModelKvGpu')?.checked,
    echo_load_config: !!document.getElementById('lmModelEchoLoadConfig')?.checked,
  };
  Object.keys(runtime).forEach(k => { if (runtime[k] === null) delete runtime[k]; });
  return runtime;
}
function openToolModal(name='') {
  if(name)fillToolForm(name);
  else{toolName.value='';toolDescription.value='';toolBinaries.value='';toolApprovalPatterns.value='';toolSocket.value='';if(document.getElementById('toolPackage'))document.getElementById('toolPackage').value='';if(document.getElementById('toolInstallHint'))document.getElementById('toolInstallHint').value='';toolEnabled.checked=true;}
  setModalStatus('toolModalStatus','');
  const modal=document.getElementById('toolModal');
  if(modal)modal.hidden=false;
  setTimeout(()=>document.getElementById('toolName')?.focus(),0);
}
function closeToolModal(){

if(document.getElementById('openToolModal'))document.getElementById('openToolModal').onclick=()=>openToolModal();
if(document.getElementById('closeToolModal'))document.getElementById('closeToolModal').onclick=()=>closeToolModal();
  const modal=document.getElementById('toolModal');
  if(modal)modal.hidden=true;
}

function fillToolForm(name) {
  const t = config.tools?.[name]; if (!t) return;
  toolName.value=name; toolDescription.value=t.description || ''; toolBinaries.value=(t.binaries || []).join(', ');
  toolApprovalPatterns.value=(t.approval_required_patterns || []).join(', '); toolSocket.value=t.socket || ''; if (document.getElementById('toolPackage')) toolPackage.value=t.package || ''; if (document.getElementById('toolInstallHint')) toolInstallHint.value=t.install_hint || ''; toolEnabled.checked=t.enabled !== false;
}
async function persistConfigAndReload(messageId, message) {
  await api('/v1/config',{method:'PUT',body:JSON.stringify({config})});
  await loadConfig();
  showInline(messageId, message || 'Saved');
}



function renderFeaturePackPreview(result) {
  const box = document.getElementById('featurePackPreview');
  const apply = document.getElementById('applyFeaturePack');
  if (!box) return;
  if (!result || !result.components) {
    box.innerHTML = '<div class="muted">Upload a PAC patch/full zip or source update zip to preview versions.</div>';
    if (apply) apply.disabled = true;
    return;
  }
  window.pendingFeaturePackUploadId = result.upload_id;
  if (apply) apply.disabled = !result.upload_id || !result.components.length;
  if (result.package_type === 'pac_app_update') {
    const fromVersion = result.current_version || result.components?.[0]?.from_version || '-';
    const toVersion = result.target_version || result.root_version || result.components?.[0]?.to_version || '-';
    const delta = result.changelog?.delta || result.changes || [];
    const changeHtml = delta.length
      ? `<div class="update-delta-list">${delta.map(entry => `<div class="update-delta-version"><div class="update-delta-title">${escapeHtml(entry.title || ('PAC v' + entry.version))}</div><ul>${(entry.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul></div>`).join('')}</div>`
      : '<div class="muted small-text">No version notes were found inside this zip. The update can still be applied.</div>';
    const source = result.changelog?.source ? `<span class="muted small-text">Change notes: ${escapeHtml(result.changelog.source)}</span>` : '';
    box.innerHTML = `<div class="pack-summary strong-summary">PAC application update ready</div><div class="muted small-text">${escapeHtml(result.filename || 'upload')} updates the controller from ${escapeHtml(fromVersion)} to ${escapeHtml(toVersion)}. Apply will install the app patch and restart PAC.</div><table class="compact-table"><thead><tr><th>Update</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody><tr><td><code>PAC app</code></td><td>${escapeHtml(fromVersion)}</td><td>${escapeHtml(toVersion)}</td><td>install + restart</td></tr></tbody></table><div class="update-delta-heading">Changes included</div>${changeHtml}${source}`;
    return;
  }
  const rows = result.components.map(c => `<tr><td><code>${escapeHtml(c.path)}</code></td><td>${escapeHtml(c.kind)}</td><td>${escapeHtml(c.from_version || 'new')}</td><td>${escapeHtml(c.to_version || '-')}</td><td>${escapeHtml(c.status || '')}</td></tr>`).join('');
  box.innerHTML = `<div class="pack-summary">${result.component_count || result.components.length} source folder(s) ready from ${escapeHtml(result.filename || 'upload')}</div><table class="compact-table"><thead><tr><th>Source folder</th><th>Kind</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table>`;
}
async function inspectFeaturePack() {
  const input = document.getElementById('featurePackFile');
  if (!input || !input.files || !input.files[0]) { paneError('Choose a feature update zip first'); return; }
  const fd = new FormData();
  fd.append('file', input.files[0]);
  emitUiEvent('feature_pack_inspect_started', `Feature update inspection started: ${input.files[0].name}`);
  const result = await runWithPaneError(() => api('/v1/sources/feature-pack/inspect', {method:'POST', body: fd}), 'Feature update could not be inspected');
  if (result) { renderFeaturePackPreview(result); emitUiEvent('feature_pack_inspected', result.package_type === 'pac_app_update' ? `PAC app update inspected: ${result.target_version || result.root_version || ''}` : `Feature update inspected: ${(result.components || []).length} source folders`, result); }
}
async function applyFeaturePack() {
  const uploadId = window.pendingFeaturePackUploadId;
  if (!uploadId) { paneError('Inspect a feature update zip first'); return; }
  emitUiEvent('feature_pack_apply_started', 'Feature update apply started', {upload_id: uploadId});
  const result = await runWithPaneError(() => api('/v1/sources/feature-pack/apply', {method:'POST', body: JSON.stringify({upload_id: uploadId})}), 'Feature update could not be applied');
  if (result) {
    renderFeaturePackPreview(null);
    const input = document.getElementById('featurePackFile'); if (input) input.value = '';
    emitUiEvent('feature_pack_applied', result.package_type === 'pac_app_update' ? 'PAC app update applied; restart scheduled' : `Feature update applied: ${(result.components || []).length} source folders`, result);
    if (result.package_type !== 'pac_app_update') await renderSources(selectedSourceFolder || '');
  }
}

function sourceDirForNewEntry() {
  if (selectedSourceEntry && sourceFileState.has(selectedSourceEntry)) return selectedSourceEntry.split('/').slice(0, -1).join('/');
  if (selectedSourceEntry && !sourceFileState.has(selectedSourceEntry)) return selectedSourceEntry;
  if (selectedSourcePath) return selectedSourcePath.split('/').slice(0, -1).join('/');
  return selectedSourceFolder || '';
}
function sourceFileLabel(path) { return (path || '').split('/').pop() || path || 'untitled'; }
function markSourceDirty(path, dirty=true) {
  const state = sourceFileState.get(path);
  if (!state) return;
  state.dirty = !!dirty;
  renderSourceTabs();
  updateSourceDirtyTreeMarkers();
}
function updateSourceDirtyTreeMarkers() {
  const tree = document.getElementById('sourceTree');
  if (!tree) return;
  tree.querySelectorAll('[data-source-path]').forEach(btn => {
    const p = btn.dataset.sourcePath || '';
    btn.classList.toggle('source-dirty', !!sourceFileState.get(p)?.dirty);
  });
}
function renderSourceTabs() {
  const tabs = document.getElementById('sourceTabs');
  if (!tabs) return;
  if (!sourceOpenTabs.length) {
    tabs.innerHTML = '<span class="muted small-text">Open a file from the tree.</span>';
    return;
  }
  tabs.innerHTML = sourceOpenTabs.map(path => {
    const state = sourceFileState.get(path) || {};
    const active = path === selectedSourcePath ? ' active' : '';
    const dirty = state.dirty ? ' dirty' : '';
    return `<button class="source-tab${active}${dirty}" data-source-tab="${escapeHtml(path)}" title="${escapeHtml(path)}"><span>${escapeHtml(sourceFileLabel(path))}</span>${state.dirty ? '<b>•</b>' : ''}<em data-source-close="${escapeHtml(path)}">×</em></button>`;
  }).join('');
  tabs.querySelectorAll('[data-source-tab]').forEach(btn => btn.onclick = (ev) => {
    if (ev.target?.dataset?.sourceClose) return;
    activateSourceTab(btn.dataset.sourceTab || '');
  });
  tabs.querySelectorAll('[data-source-close]').forEach(btn => btn.onclick = (ev) => {
    ev.stopPropagation();
    closeSourceTab(btn.dataset.sourceClose || '');
  });
}
function activateSourceTab(path) {
  const state = sourceFileState.get(path);
  const editor = document.getElementById('sourceEditor');
  if (!state || !editor) return;
  selectedSourcePath = path;
  selectedSourceEntry = path;
  selectedSourceFolder = path.split('/').slice(0, -1).join('/');
  editor.value = state.content || '';
  updateSourceActions();
  renderSourceTabs();
}
function closeSourceTab(path) {
  if (sourceFileState.get(path)?.dirty && !confirm(`${path} has unsaved changes. Close it anyway?`)) return;
  sourceFileState.delete(path);
  sourceOpenTabs = sourceOpenTabs.filter(p => p !== path);
  if (selectedSourcePath === path) {
    selectedSourcePath = sourceOpenTabs[sourceOpenTabs.length - 1] || null;
    if (selectedSourcePath) activateSourceTab(selectedSourcePath);
    else {
      const editor = document.getElementById('sourceEditor');
      if (editor) editor.value = '';
      renderSourceTabs();
    }
  } else renderSourceTabs();
  updateSourceDirtyTreeMarkers();
}
function sourceDepth(path) {
  return (path || '').split('/').filter(Boolean).length;
}
function sourceChildRows(items, depth=0) {
  const rows = [];
  (items || []).forEach(item => {
    const isDir = item.type === 'dir';
    const expanded = isDir && sourceExpandedDirs.has(item.path);
    const iconClass = isDir ? (expanded ? 'tree-icon tree-folder open' : 'tree-icon tree-folder') : 'tree-icon tree-file';
    const versionPill = item.source_version ? `<span class="source-version-pill" title="source version">v${escapeHtml(item.source_version)}</span>` : '';
    const kindLabel = item.component_kind || item.buildable_kind || '';
    const kindPill = kindLabel ? `<span class="source-kind-pill">${escapeHtml(kindLabel)}</span>` : '';
    const componentTitle = item.component_title || item.name;
    const componentHint = item.component_description ? ` title="${escapeHtml(item.component_description)}"` : '';
    const buildTitle = item.buildable_kind === 'container' ? 'Build container image' : 'Build binaries';
    const buildButton = item.buildable_kind ? `<button class="source-build-icon" data-build-kind="${escapeHtml(item.buildable_kind)}" data-build-path="${escapeHtml(item.path)}" title="${buildTitle}" aria-label="${buildTitle}">▶</button>` : '';
    const dirty = sourceFileState.get(item.path)?.dirty ? ' source-dirty' : '';
    const selected = selectedSourceEntry === item.path ? ' selected' : '';
    const indent = Math.max(0, depth) * 22;
    rows.push(`<div class="source-row-wrap ${item.buildable_kind ? 'buildable-source-row' : ''}${selected}" style="--source-depth:${indent}px"><button class="source-row ${isDir ? 'source-dir' : 'source-file'}${dirty}${selected}" data-source-path="${escapeHtml(item.path)}" data-source-type="${item.type}"${componentHint}><span class="source-name"><span class="${iconClass}" aria-hidden="true"></span>${escapeHtml(componentTitle)}${dirty ? '<b class="dirty-dot">•</b>' : ''}</span><span class="source-row-meta">${versionPill}${kindPill}</span></button>${buildButton}</div>`);
    if (isDir && expanded) {
      const cached = sourceTreeCache.get(item.path);
      if (cached?.items?.length) rows.push(...sourceChildRows(cached.items, depth + 1));
      else if (cached) rows.push(`<div class="muted source-empty-folder nested" style="--source-depth:${(depth + 1) * 14}px">No files in this folder.</div>`);
      else rows.push(`<div class="muted source-empty-folder nested" style="--source-depth:${(depth + 1) * 14}px">Loading…</div>`);
    }
  });
  return rows;
}
function bindSourceTreeEvents(tree) {
  tree.querySelectorAll('.source-row').forEach(btn => {
    btn.onclick = async () => {
      const p = btn.dataset.sourcePath || '';
      selectedSourceEntry = p;
      if (btn.dataset.sourceType === 'dir') {
        selectedSourceFolder = p;
        if (sourceExpandedDirs.has(p)) sourceExpandedDirs.delete(p); else sourceExpandedDirs.add(p);
        await renderSources('', {preserveCache:true, focusPath:p});
      } else {
        openSourceFile(p);
      }
      updateSourceActions();
    };
    btn.oncontextmenu = (ev) => openSourceContextMenu(ev, btn.dataset.sourcePath || '', btn.dataset.sourceType || 'file');
  });
  tree.querySelectorAll('.source-build-icon').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      selectedSourceFolder = btn.dataset.buildPath || '';
      selectedSourceEntry = selectedSourceFolder;
      updateSourceActions();
      if (btn.dataset.buildKind === 'container') buildSelectedContainerSource();
      else buildSelectedBinarySource();
    };
  });
}
function normalizeSourceCachePath(path='') {
  const value = String(path || '').trim();
  return (!value || value === '.') ? '' : value.replace(/^\/+/, '');
}
async function ensureSourceDirLoaded(path='') {
  const data = await api(`/v1/sources?path=${encodeURIComponent(path)}`);
  const cachePath = normalizeSourceCachePath(data.path ?? path);
  data.path = cachePath;
  sourceTreeCache.set(cachePath, data);
  return data;
}
async function renderSources(path='', options={}) {
  const tree = document.getElementById('sourceTree');
  if (!tree) return;
  try {
    const targetPath = options.focusPath !== undefined ? options.focusPath : path;
    if (!options.preserveCache || !sourceTreeCache.has('')) await ensureSourceDirLoaded('');
    if (path && !sourceTreeCache.has(path)) await ensureSourceDirLoaded(path);
    const expanded = Array.from(sourceExpandedDirs).filter(Boolean);
    for (const dir of expanded) {
      if (!sourceTreeCache.has(dir)) await ensureSourceDirLoaded(dir);
    }
    const rootData = sourceTreeCache.get('') || {items:[]};
    let rootItems = rootData.items || [];
    if (!rootItems.length && Array.isArray(rootData.top_level) && rootData.top_level.length) {
      rootItems = rootData.top_level.map(name => ({name, path:name, type:'dir'}));
    }
    const rows = sourceChildRows(rootItems, 0);
    tree.classList.remove('muted');
    tree.innerHTML = rows.length ? rows.join('') : '<div class="muted source-empty-folder">No source folders found.</div>';
    selectedSourceFolder = selectedSourceFolder || targetPath || '';
    updateSourceActions();
    renderSourceBuildPanel(sourceTreeCache.get(selectedSourceFolder) || rootData);
    await syncDownloadsWithSourcePath(selectedSourceFolder || '');
    bindSourceTreeEvents(tree);
  } catch (e) {
    tree.classList.add('muted');
    tree.textContent = e.message || String(e);
    paneError('Source list unavailable', e.message || String(e));
  }
}
async function openSourceFile(path) {
  const editor = document.getElementById('sourceEditor');
  if (!editor) return;
  try {
    const data = await api(`/v1/sources/content?path=${encodeURIComponent(path)}`);
    selectedSourcePath = data.path;
    selectedSourceEntry = data.path;
    selectedSourceFolder = data.path.split('/').slice(0, -1).join('/');
    if (!sourceOpenTabs.includes(data.path)) sourceOpenTabs.push(data.path);
    sourceFileState.set(data.path, {content:data.content || '', saved:data.content || '', dirty:false});
    activateSourceTab(data.path);
  } catch (e) {
    paneError('Source file could not be opened', e.message || String(e));
  }
}
async function saveSourceFile(path=selectedSourcePath) {
  const editor = document.getElementById('sourceEditor');
  if (!path || !editor) { paneError('No source file selected'); return; }
  if (path === selectedSourcePath) {
    const state = sourceFileState.get(path) || {};
    state.content = editor.value;
    sourceFileState.set(path, state);
  }
  const state = sourceFileState.get(path);
  const content = state ? state.content : editor.value;
  const result = await runWithPaneError(() => api('/v1/sources/content', {method:'PUT', body: JSON.stringify({path, content})}), 'Source file could not be saved');
  if (result) {
    const current = sourceFileState.get(path) || {};
    current.saved = content; current.content = content; current.dirty = false;
    sourceFileState.set(path, current);
    renderSourceTabs(); updateSourceDirtyTreeMarkers();
    emitUiEvent('source_file_saved', `Source saved: ${result.path}`, result);
  }
}
async function saveAllSourceFiles() {
  for (const path of sourceOpenTabs.slice()) if (sourceFileState.get(path)?.dirty) await saveSourceFile(path);
}
async function createSourceEntry(type) {
  const base = sourceDirForNewEntry();
  const label = type === 'dir' ? 'New folder name' : 'New file name';
  const name = prompt(label, type === 'dir' ? 'new-folder' : 'new-file.txt');
  if (!name) return;
  const path = [base, name].filter(Boolean).join('/');
  const result = await runWithPaneError(() => api('/v1/sources/entry', {method:'POST', body:JSON.stringify({path, type})}), `Source ${type} could not be created`);
  if (result) { sourceTreeCache.clear(); if (type === 'dir') sourceExpandedDirs.add(result.path); await renderSources(base); if (type !== 'dir') await openSourceFile(result.path); }
}
async function renameSelectedSourceEntry(path=selectedSourceEntry) {
  if (!path) return paneError('Select a source entry first');
  const newName = prompt('Rename to', sourceFileLabel(path));
  if (!newName || newName === sourceFileLabel(path)) return;
  const result = await runWithPaneError(() => api('/v1/sources/entry/rename', {method:'POST', body:JSON.stringify({path, new_name:newName})}), 'Source entry could not be renamed');
  if (result) {
    if (sourceFileState.has(path)) {
      const state = sourceFileState.get(path); sourceFileState.delete(path); sourceFileState.set(result.new_path, state);
      sourceOpenTabs = sourceOpenTabs.map(p => p === path ? result.new_path : p);
      if (selectedSourcePath === path) selectedSourcePath = result.new_path;
    }
    selectedSourceEntry = result.new_path;
    sourceTreeCache.clear(); await renderSources(result.new_path.split('/').slice(0,-1).join('/'));
    renderSourceTabs();
  }
}
async function deleteSelectedSourceEntry(path=selectedSourceEntry) {
  if (!path) return paneError('Select a source entry first');
  if (!confirm(`Delete ${path}?`)) return;
  const parent = path.split('/').slice(0,-1).join('/');
  const result = await runWithPaneError(() => api('/v1/sources/entry', {method:'DELETE', body:JSON.stringify({path})}), 'Source entry could not be deleted');
  if (result) {
    if (sourceFileState.has(path)) closeSourceTab(path);
    selectedSourceEntry = parent;
    sourceTreeCache.clear(); await renderSources(parent);
  }
}
function ensureSourceContextMenu() {
  let menu = document.getElementById('sourceContextMenu');
  if (menu) return menu;
  menu = document.createElement('div');
  menu.id = 'sourceContextMenu';
  menu.className = 'source-context-menu';
  document.body.appendChild(menu);
  document.addEventListener('click', () => { menu.hidden = true; });
  return menu;
}
function openSourceContextMenu(ev, path, type) {
  ev.preventDefault(); ev.stopPropagation();
  selectedSourceEntry = path;
  const menu = ensureSourceContextMenu();
  const buildKind = path.startsWith('binaries/') && path.split('/').length === 2 ? 'binary' : (path.startsWith('containers/') && path.split('/').length === 2 ? 'container' : '');
  menu.innerHTML = `<button data-action="rename">Rename</button>${type === 'file' ? '<button data-action="save">Save file</button>' : ''}<button data-action="delete">Delete</button>${buildKind ? '<button data-action="build">Build</button>' : ''}`;
  menu.style.left = `${ev.clientX}px`; menu.style.top = `${ev.clientY}px`; menu.hidden = false;
  menu.querySelectorAll('button').forEach(btn => btn.onclick = async (e) => {
    e.stopPropagation(); menu.hidden = true;
    const action = btn.dataset.action;
    if (action === 'rename') await renameSelectedSourceEntry(path);
    if (action === 'save') await saveSourceFile(path);
    if (action === 'delete') await deleteSelectedSourceEntry(path);
    if (action === 'build') { selectedSourceFolder = path; if (buildKind === 'container') await buildSelectedContainerSource(); else await buildSelectedBinarySource(); }
  });
}


function selectedBuildFolder(kind) {
  const path = selectedSourceFolder || '';
  if (!path) return '';
  const parts = path.split('/').filter(Boolean);
  if (!parts.length) return '';
  if (kind === 'container' && parts[0] !== 'containers') return '';
  if (kind === 'binary' && parts[0] !== 'binaries') return '';
  return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : '';
}
function sourceBuildKindForPath(path) {
  const parts = (path || '').split('/').filter(Boolean);
  if (parts.length < 2) return '';
  if (parts[0] === 'containers') return 'container';
  if (parts[0] === 'binaries') return 'binary';
  return '';
}
function updateSourceActions() {
  const hint = document.getElementById('sourceActionHint');
  const cf = selectedBuildFolder('container');
  const bf = selectedBuildFolder('binary');
  if (hint) hint.textContent = bf ? `Viewing source: ${bf}. Build it from the Source library row.` : (cf ? `Container source: ${cf}. Build it from the Source library row.` : 'Filter by binary source folder.');
  const title = document.getElementById('sourceBuildPanelTitle');
  if (title) title.textContent = 'Downloads';
  updateSourcePanels();
}

async function updateSourcePanels() {
  const cfg = document.getElementById('sourceConfigContent');
  const sec = document.getElementById('sourceSecretsContent');
  if (!cfg || !sec) return;
  const path = selectedSourceEntry || selectedSourceFolder;

  // ── Configuration panel: Variables ──────────────────────────────────
  try {
    const vars = await api('/v1/source-variables');
    if (!vars || !vars.length) {
      cfg.innerHTML = '<div class="var-empty muted">No variables defined yet.</div>';
    } else {
      let html = '<div class="var-list">';
      vars.forEach(function(v) {
        const tags = (v.tags || []).join(', ');
        const tagHtml = tags ? '<span class="var-tags muted">' + escapeHtml(tags) + '</span>' : '';
        html += '<div class="var-item">';
        html += '<div class="var-header"><span class="var-name">' + escapeHtml(v.id) + '</span>' + tagHtml + '</div>';
        html += '<div class="var-value">' + escapeHtml(v.value) + '</div>';
        html += '<div class="var-desc muted small-text">' + escapeHtml(v.description || '') + '</div>';
        html += '</div>';
      });
      html += '</div>';
      cfg.innerHTML = html;
    }
  } catch(e) {
    cfg.innerHTML = '<div class="muted" style="opacity:.5;font-size:.8em;padding:.4rem">Variables unavailable.</div>';
  }

  // ── Secrets panel: Endpoint secrets ─────────────────────────────────
  try {
    const secrets = await api('/v1/secrets');
    if (!secrets || !secrets.length) {
      sec.innerHTML = '<div class="muted" style="opacity:.5;font-size:.8em;padding:.4rem">No secrets configured.</div>';
    } else {
      let html = '<div class="secrets-list">';
      secrets.forEach(function(s) {
        const created = s.created_at ? new Date(s.created_at).toLocaleDateString() : '';
        html += '<div class="secret-item">';
        html += '<div class="secret-name">' + escapeHtml(s.id) + '</div>';
        html += '<div class="secret-meta muted">' + escapeHtml(created) + ' · ' + escapeHtml(s.created_by || 'unknown') + '</div>';
        html += '</div>';
      });
      html += '</div>';
      sec.innerHTML = html;
    }
  } catch(e) {
    sec.innerHTML = '<div class="muted" style="opacity:.5;font-size:.8em;padding:.4rem">Secrets unavailable.</div>';
  }
}

function renderSourceBuildPanel(data={}) {
  const hintBox = document.getElementById('sourceBuildResult');
  if (hintBox && !hintBox.dataset.busy) hintBox.textContent = 'Available downloads are listed by version.';
  updateSourceActions();
}

async function syncDownloadsWithSourcePath(path='') {
  const parts = String(path || '').split('/').filter(Boolean);
  let project = selectedBinaryArtifactFilter || '';
  if (parts[0] === 'binaries') {
    project = parts[1] || '';
  }
  selectedBinaryArtifactFilter = project;
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts(project).catch(e=>paneError('Binary downloads unavailable', e.message));
}

function setBinaryFolderFilterValue(value) {
  const filter = document.getElementById('binaryFolderFilter');
  if (filter && filter.value !== value) filter.value = value || '';
}
async function loadBinaryFolderFilters() {
  const filter = document.getElementById('binaryFolderFilter');
  if (!filter) return;
  try {
    const data = await api('/v1/sources?path=binaries');
    const folders = (data.items || []).filter(i => i.type === 'dir').map(i => i.name).sort((a,b)=>a.localeCompare(b));
    const current = selectedBinaryArtifactFilter || '';
    filter.innerHTML = ['<option value="">All binary folders</option>'].concat(folders.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)).join('');
    filter.value = folders.includes(current) ? current : '';
    selectedBinaryArtifactFilter = filter.value;
  } catch(e) {
    filter.innerHTML = '<option value="">Binary folders unavailable</option>';
  }
}
function binaryVersionFromName(name) {
  const text = String(name || '');
  const match = text.match(/(?:^|[-_])v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)(?=$|[-_])/);
  return match ? match[1] : 'unversioned';
}
function binaryPlatformFromName(name, project) {
  let text = String(name || '');
  if (project && text.startsWith(project + '-')) text = text.slice(project.length + 1);
  text = text.replace(/^[0-9]+\.[0-9]+\.[0-9]+[-_]?/, '');
  const match = text.match(/(linux|darwin|windows|freebsd|openbsd|netbsd)[-_](amd64|arm64|arm|386|ppc64le|s390x)/i);
  return match ? match[0].replace('_', '/') : text;
}
function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (!n) return '0 bytes';
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function renderBinaryDownloads(projects) {
  const el = document.getElementById('sourceBinaryArtifacts');
  if (!el) return;
  const grouped = new Map();
  (projects || []).forEach(project => {
    (project.artifacts || []).forEach(a => {
      const version = a.version || (binaryVersionFromName(a.name) === 'unversioned' ? (project.source_version || 'unversioned') : binaryVersionFromName(a.name));
      const key = `${project.project}::${version}`;
      if (!grouped.has(key)) grouped.set(key, {project: project.project, version, artifacts: [], sourceVersion: project.source_version || ''});
      grouped.get(key).artifacts.push(a);
    });
  });
  const groups = Array.from(grouped.values()).sort((a,b) => {
    const projectCmp = a.project.localeCompare(b.project);
    if (projectCmp) return projectCmp;
    return b.version.localeCompare(a.version, undefined, {numeric:true});
  });
  if (!groups.length) {
    el.innerHTML = '<span class="muted">No downloads available yet for this category. Build binaries from the Source library row.</span>';
    return;
  }
  el.innerHTML = groups.map(group => {
    const links = group.artifacts
      .sort((a,b)=>String(a.name).localeCompare(String(b.name), undefined, {numeric:true}))
      .map(a => `<span class="download-artifact"><a class="download-pill" href="${a.download_url}" download title="${escapeHtml(a.name)}"><span>${escapeHtml(binaryPlatformFromName(a.name, group.project))}</span><small>${escapeHtml(formatBytes(a.size))}</small></a><button class="icon-button delete-artifact" data-project="${escapeHtml(group.project)}" data-filename="${escapeHtml(a.name)}" title="Delete this binary">×</button></span>`)
      .join('');
    return `<div class="download-version-group"><div class="download-version-title"><b>${escapeHtml(group.project)}</b><span>binary v${escapeHtml(group.version)}</span></div><div class="download-pill-list">${links}</div></div>`;
  }).join('');
  el.querySelectorAll('.delete-artifact').forEach(btn => {
    btn.onclick = () => deleteBinaryArtifact(btn.dataset.project || '', btn.dataset.filename || '').catch(e => paneError('Delete binary failed', e.message));
  });
}

async function deleteBinaryArtifact(project, filename) {
  if (!project || !filename) return;
  if (!confirm(`Delete binary ${filename}?`)) return;
  const result = await api(`/v1/sources/binary-artifacts/${encodeURIComponent(project)}/${encodeURIComponent(filename)}`, {method:'DELETE'});
  setSourceBuildHint(`Deleted ${result.deleted || filename}.`, false);
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter || '').catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}

async function pruneBinaryArtifacts(dryRun=false) {
  const project = selectedBinaryArtifactFilter || '';
  const label = project ? project : 'all binary folders';
  if (!dryRun && !confirm(`Keep only the newest binary version for ${label} and delete older versions?`)) return;
  const result = await api('/v1/sources/binary-artifacts/prune', {method:'POST', body:JSON.stringify({project, keep_versions:1, dry_run:dryRun})});
  const bytes = formatBytes(result.deleted_bytes || 0);
  setSourceBuildHint(dryRun ? `Prune preview: ${result.deleted_count || 0} old file(s), ${bytes}.` : `Pruned ${result.deleted_count || 0} old file(s), ${bytes}.`, false);
  await loadSourceBinaryArtifacts(project).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}
async function loadSourceBinaryArtifacts(project='') {
  const el = document.getElementById('sourceBinaryArtifacts');
  if (!el) return;
  try {
    const effectiveProject = project !== undefined && project !== null ? project : selectedBinaryArtifactFilter;
    setBinaryFolderFilterValue(effectiveProject || '');
    const qs = effectiveProject ? `?project=${encodeURIComponent(effectiveProject)}` : '';
    const data = await api(`/v1/sources/binary-artifacts${qs}`);
    renderBinaryDownloads(data.projects || []);
  } catch(e) { el.textContent = `Could not load downloads: ${e.message}`; }
}
function formatBuildCommand(command) {
  return Array.isArray(command) ? command.join(' ') : String(command || '');
}
function setSourceBuildHint(text, busy=false) {
  const box = document.getElementById('sourceBuildResult');
  if (!box) return;
  box.dataset.busy = busy ? '1' : '';
  box.textContent = text || 'Available downloads are listed by version.';
}
function renderSourceBuildResult(result) {
  if (!result) { setSourceBuildHint(); return; }
  if (result.kind === 'binary') {
    const count = (result.artifacts || []).length;
    setSourceBuildHint(result.ok ? `${count} file${count === 1 ? '' : 's'} ready to download.` : 'Build failed. Open Events for details.', false);
  } else if (result.kind === 'container') {
    setSourceBuildHint(result.ok ? `Container image built: ${result.image || result.folder || ''}` : 'Container build failed. Open Events for details.', false);
  } else {
    setSourceBuildHint('Build finished. Open Events for details.', false);
  }
}
async function buildSelectedContainerSource() {
  const folder = selectedBuildFolder('container');
  if (!folder) return paneError('Select a buildable folder under containers first');
  setSourceBuildHint(`Building ${folder} from the folder root…`, true);
  emitUiEvent('source_container_build_started', `Container build started: ${folder}`, {path: folder});
  const result = await runWithPaneError(() => api('/v1/sources/build-container', {method:'POST', body:JSON.stringify({path:folder})}), 'Container build failed');
  if (result) { renderSourceBuildResult(result); emitUiEvent(result.ok ? 'source_container_built' : 'source_container_build_failed', result.ok ? `Container build completed: ${result.image || folder}` : `Container build failed: ${folder}`, result); }
  await loadGlobalEvents(true).catch(()=>{});
}
async function buildSelectedBinarySource() {
  const folder = selectedBuildFolder('binary');
  if (!folder) return paneError('Select a buildable folder under binaries first');
  setSourceBuildHint(`Building ${folder} for supported OS/architecture targets…`, true);
  emitUiEvent('source_binary_build_started', `Binary build started: ${folder}`, {path: folder});
  const result = await runWithPaneError(() => api('/v1/sources/build-binary', {method:'POST', body:JSON.stringify({path:folder, server_url:(config.server?.public_url || '').replace(/\/$/, '')})}), 'Binary build failed');
  if (result) { renderSourceBuildResult(result); emitUiEvent(result.ok ? 'source_binary_built' : 'source_binary_build_failed', result.ok ? `Binary build completed: ${folder}` : `Binary build failed: ${folder}`, result); }
  if (folder === 'binaries/zed-binary') await loadMcpBuildStatus().catch(()=>{});
  selectedBinaryArtifactFilter = folder.split('/')[1] || '';
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter).catch(()=>{});
  await loadGlobalEvents(true).catch(()=>{});
}

function workspaceValue(id) { return document.getElementById(id)?.value?.trim() || ''; }
function workspaceChecked(id) { return !!document.getElementById(id)?.checked; }
function renderWorkspaces() {
  const el = document.getElementById('workspaces');
  if (!el) return;
  el.innerHTML = '';
  for (const [name,w] of Object.entries(config.workspaces || {})) {
    const lifecycle = w.ephemeral ? `ephemeral${w.ttl_hours ? `, ${w.ttl_hours}h TTL` : ''}` : 'persistent';
    const placement = w.endpoint_id || w.endpoint_selector || 'select at runtime';
    const data = w.data_bundle_url || w.data_bundle_path || 'none';
    const row = document.createElement('div'); row.className = 'workspace-card clickable-row';
    row.innerHTML = `<div class="workspace-card-title"><b>${escapeHtml(name)}</b><span>${escapeHtml(lifecycle)}</span></div>
      <div class="workspace-card-grid">
        <div><small>type</small><b>${escapeHtml(w.type || 'local')}</b></div>
        <div><small>runtime</small><b>${escapeHtml(w.runtime || 'any')}</b></div>
        <div><small>placement</small><b>${escapeHtml(placement)}</b></div>
        <div><small>profile</small><b>${escapeHtml(w.default_agent_profile || '-')}</b></div>
      </div>
      <code>${escapeHtml(w.description || '')}${w.description ? '\n' : ''}path: ${escapeHtml(w.path || '-')}
url: ${escapeHtml(w.url || '-')}
branch: ${escapeHtml(w.branch || '-')}
container: ${escapeHtml(w.container_image || '-')}
data zip: ${escapeHtml(data)}
data path: ${escapeHtml(w.data_mount_path || '-')}
default: ${w.is_default ? 'yes' : 'no'}
protected: ${escapeHtml((w.protected_paths || []).join(', ') || '-')}
human_write: ${escapeHtml(w.human_write_policy || 'deny')}</code>`;
    row.onclick = () => openWorkspaceModal(name);
    el.appendChild(row);
  }
}
function openWorkspaceModal(name='') {
  if (name) fillWorkspaceForm(name);
  else { workspaceName.value=''; workspaceType.value='local'; workspaceRuntime.value='any'; workspacePath.value=''; workspaceUrl.value=''; workspaceBranch.value=''; if(document.getElementById('workspaceContainerImage'))workspaceContainerImage.value=''; workspaceDefaultProfile.value=''; if(document.getElementById('workspaceEndpoint'))workspaceEndpoint.value=''; if(document.getElementById('workspaceEndpointSelector'))workspaceEndpointSelector.value=''; if(document.getElementById('workspaceDataUrl'))workspaceDataUrl.value=''; if(document.getElementById('workspaceDataPath'))workspaceDataPath.value=''; if(document.getElementById('workspaceDataMount'))workspaceDataMount.value=''; if(document.getElementById('workspaceTtlHours'))workspaceTtlHours.value=''; workspaceEphemeral.checked=false; if(document.getElementById('workspaceDeleteOnExpire'))workspaceDeleteOnExpire.checked=true; if(document.getElementById('workspaceIsDefault'))workspaceIsDefault.checked=false; if(document.getElementById('workspaceProtectedPaths'))workspaceProtectedPaths.value=''; if(document.getElementById('workspaceHumanWritePolicy'))workspaceHumanWritePolicy.value='deny'; }
  setModalStatus('workspaceModalStatus','');
  const modal=document.getElementById('workspaceModal');
  if(modal)modal.hidden=false;
  setTimeout(()=>document.getElementById('workspaceName')?.focus(),0);
}
function closeWorkspaceModal(){
  const modal=document.getElementById('workspaceModal');
  if(modal)modal.hidden=true;
}

function fillWorkspaceForm(name) {
  const w = config.workspaces?.[name]; if (!w) return;
  workspaceName.value = name;
  if (document.getElementById('workspaceDescription')) workspaceDescription.value = w.description || '';
  workspaceType.value = w.type || 'local';
  if (document.getElementById('workspaceRuntime')) workspaceRuntime.value = w.runtime || 'any';
  workspacePath.value = w.path || ''; workspaceUrl.value = w.url || ''; workspaceBranch.value = w.branch || '';
  if (document.getElementById('workspaceContainerImage')) workspaceContainerImage.value = w.container_image || '';
  workspaceDefaultProfile.value = w.default_agent_profile || '';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.value = w.endpoint_id || '';
  if (document.getElementById('workspaceEndpointSelector')) workspaceEndpointSelector.value = w.endpoint_selector || '';
  if (document.getElementById('workspaceDataUrl')) workspaceDataUrl.value = w.data_bundle_url || '';
  if (document.getElementById('workspaceDataPath')) workspaceDataPath.value = w.data_bundle_path || '';
  if (document.getElementById('workspaceDataMount')) workspaceDataMount.value = w.data_mount_path || '';
  if (document.getElementById('workspaceTtlHours')) workspaceTtlHours.value = w.ttl_hours || '';
  if (document.getElementById('workspaceEphemeral')) workspaceEphemeral.checked = !!w.ephemeral;
  if (document.getElementById('workspaceDeleteOnExpire')) workspaceDeleteOnExpire.checked = w.delete_on_expire !== false;
  if (document.getElementById('workspaceIsDefault')) workspaceIsDefault.checked = !!w.is_default;
  if (document.getElementById('workspaceProtectedPaths')) workspaceProtectedPaths.value = (w.protected_paths || []).join(', ');
  if (document.getElementById('workspaceHumanWritePolicy')) workspaceHumanWritePolicy.value = w.human_write_policy || 'deny';
}
async function saveWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name) return alert('Workspace name is required');
  const body = {
    description: workspaceValue('workspaceDescription') || null,
    type: workspaceType.value || 'local',
    runtime: workspaceValue('workspaceRuntime') || 'any',
    path: workspacePath.value.trim() || null,
    url: workspaceUrl.value.trim() || null,
    branch: workspaceBranch.value.trim() || null,
    container_image: workspaceValue('workspaceContainerImage') || null,
    default_agent_profile: workspaceDefaultProfile.value || null,
    endpoint_id: document.getElementById('workspaceEndpoint')?.value || null,
    endpoint_selector: workspaceValue('workspaceEndpointSelector') || null,
    data_bundle_url: workspaceValue('workspaceDataUrl') || null,
    data_bundle_path: workspaceValue('workspaceDataPath') || null,
    data_mount_path: workspaceValue('workspaceDataMount') || null,
    ephemeral: workspaceChecked('workspaceEphemeral'),
    ttl_hours: workspaceValue('workspaceTtlHours') || null,
    delete_on_expire: workspaceChecked('workspaceDeleteOnExpire'),
    is_default: !!document.getElementById('workspaceIsDefault')?.checked,
    protected_paths: (document.getElementById('workspaceProtectedPaths')?.value || '').split(',').map(p => p.trim()).filter(Boolean),
    human_write_policy: document.getElementById('workspaceHumanWritePolicy')?.value || 'deny',
  };
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'PUT', body:JSON.stringify(body)});
  await loadConfig();
  showInline('workspaceFormResult', `Saved workspace ${name}`);
}
async function deleteWorkspaceFromForm() {
  const name = workspaceName.value.trim();
  if (!name || !config.workspaces?.[name]) return alert('Select an existing workspace first');
  if (!confirm(`Delete workspace ${name}?`)) return;
  await api(`/v1/workspaces/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadConfig();
  showInline('workspaceFormResult', `Deleted workspace ${name}`);
}

function renderProfiles() {
  const el = document.getElementById('profiles'); el.innerHTML = '';
  for (const [name,p] of Object.entries(config.agent_profiles || {})) {
    const av = p.model ? modelAvailability(p.model) : {ok:false, reason:'no model'};
    const valid = av.ok;
    const row = document.createElement('div'); row.className = 'model-card clickable-row';
    const ws = p.workspace ? `<span class="model-meta-item"><span class="muted">Workspace</span> <span>${escapeHtml(p.workspace)}</span></span>` : '';
    row.innerHTML = `<div class="profile-card-header"><code class="profile-name">${escapeHtml(name)}</code>${valid ? '' : '<span class="warn-text small-text"> [not selectable]</span>'}</div>
    <div class="profile-card-body">
      <div class="profile-card-meta">
        <span class="model-meta-item"><span class="muted">Model</span> <span>${escapeHtml(p.model)}</span></span>
        <span class="model-meta-item"><span class="muted">Context</span> <span>${escapeHtml(p.context_profile || p.context_mode)}</span></span>
        ${ws}
        <span class="model-meta-item"><span class="muted">Permissions</span> <span>${escapeHtml(p.permission_profile)}</span></span>
      </div>
      <div class="profile-card-tools">${(p.tools||[]).join(', ') || '<span class="muted small-text">no tools</span>'}</div>
      ${valid ? '' : `<div class="warn-text small-text" style="margin-top:.3rem">${escapeHtml(av.reason)}</div>`}
    </div>`;
    row.onclick = () => openProfileModal(name);
    el.appendChild(row);
  }
}
function fillProfileForm(name) {
  const p = config.agent_profiles?.[name]; if (!p) return;
  profileName.value = name;
  profileModel.value = p.model || '';
  profileContextProfile.value = p.context_profile || 'medium';
  profileContextMode.value = p.context_mode || 'medium';
  profileWorkspace.value = p.workspace || '';
  profilePermission.value = p.permission_profile || 'ask-first';
  profileMaxRuntime.value = p.max_runtime_minutes || 60;
  setSelectedToolNames(p.tools || []);
  profileSystemPrompt.value = p.system_prompt || 'You are a careful remote coding and infrastructure agent.';
}
function openProfileModal(name='') {
  if (name) fillProfileForm(name); else {
    profileName.value=''; profileModel.value=''; profileContextProfile.value='medium'; profileContextMode.value='medium';
    profileWorkspace.value=''; profilePermission.value='ask-first'; profileMaxRuntime.value='60';
    setSelectedToolNames([]); profileSystemPrompt.value='You are a careful remote coding and infrastructure agent.';
  }
  setModalStatus('profileModalStatus', '');
  const modal = document.getElementById('profileModal');
  if (modal) modal.hidden = false;
  setTimeout(()=>document.getElementById('profileName')?.focus(), 0);
}
function closeProfileModal() { const modal = document.getElementById('profileModal'); if (modal) modal.hidden = true; }

function formatBytes(value) {
  const n = Number(value || 0);
  if (!n) return '-';
  const units = ['B','KB','MB','GB','TB','PB'];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}
function firstValue(...values) { return values.find(v => v !== undefined && v !== null && String(v) !== '') ?? '-'; }
function endpointHardware(r) {
  const c = r.capabilities || {};
  const hw = c.hardware || {};
  const cpu = firstValue(hw.cpu?.model, c.cpu?.model, hw.cpu_model);
  const cores = firstValue(hw.cpu?.logical_cores, c.cpu?.logical_cores, c.cpu?.cores);
  const ram = firstValue(hw.memory?.total_bytes ? formatBytes(hw.memory.total_bytes) : null, c.memory?.total_bytes ? formatBytes(c.memory.total_bytes) : null, hw.ram);
  const disk = firstValue(hw.disk?.total_bytes ? formatBytes(hw.disk.total_bytes) : null, c.disk?.total_bytes ? formatBytes(c.disk.total_bytes) : null, hw.disk);
  const gpuRaw = c.gpu?.devices?.length ? c.gpu.devices.map(g => g.name || g.raw || 'GPU').join(', ') : (c.gpu?.raw || (c.gpu?.available ? 'available' : '-'));
  return {cpu, cores, ram, disk, gpu: gpuRaw};
}
function compactContainerLine(c) {
  const names = Array.isArray(c.Names) ? c.Names.join(', ') : (c.Names || c.names || c.Name || c.name || '-');
  const image = c.Image || c.image || '-';
  const state = c.State || c.state || c.Status || c.status || '';
  return `${names} · ${image}${state ? ` · ${state}` : ''}`;
}
async function loadRunners() {
  const endpoints = await api('/v1/endpoints');
  window.__pacEndpoints = endpoints;
  fillModelEndpointOptions(endpoints);
  if (document.getElementById('workspaceEndpoint')) { workspaceEndpoint.innerHTML = '<option value="">none</option>'; endpoints.forEach(r => opt(workspaceEndpoint, r.id, `${r.name || r.id} (${r.status || 'unknown'})`)); }
  if (document.getElementById('taskRunner')) { taskRunner.innerHTML = '<option value="">PAC/local</option>'; endpoints.forEach(r => opt(taskRunner, r.id, `${r.name} (${r.status})`)); }
  if (document.getElementById('sessionEndpoint')) { sessionEndpoint.innerHTML = '<option value="">select endpoint</option>'; endpoints.forEach(r => opt(sessionEndpoint, r.id, `${r.name} (${r.status})`)); }
  const summaries = [document.getElementById('runnerSummary'), document.getElementById('runnerSummaryEndpoints')].filter(Boolean);
  if (summaries.length) {
    const online = endpoints.filter(r => r.status === 'online').length;
    const gpu = endpoints.filter(r => r.capabilities?.gpu?.available || r.capabilities?.gpu?.devices?.length).length;
    const html = `<div class="metric"><b>${endpoints.length}</b><span>endpoints</span></div><div class="metric"><b>${online}</b><span>online</span></div><div class="metric"><b>${gpu}</b><span>GPU hosts</span></div>`;
    summaries.forEach(summary => summary.innerHTML = html);
  }
  const el = document.getElementById('runners'); if (!el) return;
  el.innerHTML = endpoints.length ? '' : '<div class="muted">No endpoints yet. Add the local host or register a remote endpoint.</div>';
  endpoints.forEach(r => {
    const hw = endpointHardware(r);
    const configuredTools = r.metadata?.agent_tools || [];
    const discoveredTools = r.capabilities?.tools ? Object.entries(r.capabilities.tools).filter(([_,v])=>v.available).map(([k])=>k) : [];
    const effectiveTools = configuredTools.length ? configuredTools : discoveredTools;
    const tools = effectiveTools.length ? effectiveTools.join(', ') : '-';
    const packages = (r.metadata?.tool_packages || packageNamesForTools(effectiveTools)).join(', ') || '-';
    const defaultWorkspace = r.metadata?.default_workspace || Object.entries(config.workspaces || {}).find(([_,w]) => w.endpoint_id === r.id && w.is_default)?.[0] || '-';
    const modelLinks = Object.entries(config.models || {}).filter(([_,m]) => m.runs_on === r.id).map(([k])=>k).join(', ');
    const containers = (r.containers || []).slice(0,4).map(compactContainerLine).join('\n');
    const card=document.createElement('article'); card.className='endpoint-card';
    const localBadge = r.metadata?.local_control_plane ? ' <span class="pill">local</span>' : '';
    const version = r.metadata?.runner_version || r.metadata?.endpoint_version || r.metadata?.agent_runtime?.version || '-';
    const runtimeLines = endpointRuntimeLines(r);
    const lastSeen = r.last_seen_at ? new Date(r.last_seen_at).toLocaleString() : 'never';
    const updateStatus = r.metadata?.update_status ? `<span class="pill">update ${escapeHtml(r.metadata.update_status)}</span>` : '';
    const maintenanceStatus = r.metadata?.maintenance_status ? `<span class="pill">maint ${escapeHtml(r.metadata.maintenance_status)}</span>` : '';
    const enablement = r.metadata?.agent_enablement || {};
    const nodeText = enablement.node_available ? (enablement.node_version || 'available') : 'missing';
    const wrapperText = enablement.pac_wrapper_available ? 'installed' : 'missing';
    const agentClass = enablement.status === 'ready' ? 'ok-pill' : (enablement.status === 'blocked' ? 'warn-pill' : '');
    const piContainer = endpointPiContainer(r);
    const piMissing = piContainer && piContainer.available === false;
    const featureChips = endpointFeatureChips(r, effectiveTools);
    const os = r.capabilities?.os?.name || r.capabilities?.system?.os || r.capabilities?.platform || '-';
    const arch = r.capabilities?.cpu?.architecture || r.capabilities?.os?.arch || r.capabilities?.platform_arch || '-';
    const containerRuntime = r.capabilities?.container_runtimes?.length ? r.capabilities.container_runtimes.join(', ') : '-';
    const gpuText = r.capabilities?.gpu?.available ? (r.capabilities.gpu.devices?.length ? r.capabilities.gpu.devices.map(g=>g.name||'GPU').join(', ') : 'available') : '-';
    const pi = endpointPiContainer(r);
    const wsBadge = r.metadata?.default_workspace ? `<span class="pill ok-pill">ws: ${escapeHtml(r.metadata.default_workspace)}</span>` : '<span class="pill optional-missing-pill">no default workspace</span>';
    const piContainerBadge = pi?.available ? `<span class="pill ok-pill">pi.dev image</span>` : (pi ? `<span class="pill warn-pill">pi.dev ${pi.reason || 'missing'}</span>` : '');
    card.innerHTML = `<div class="endpoint-card-grid">
      <div class="ecard-head">
        <div class="ecard-name-block">
          <h3 class="ecard-name">${escapeHtml(r.name)}</h3>
          <code class="ecard-id">${escapeHtml(r.id)}</code>
        </div>
        <div class="ecard-status-block">
          <span class="pill ${r.status === 'online' ? 'ok-pill' : ''}">${escapeHtml(r.status)}</span>${localBadge}
        </div>
      </div>
      <div class="ecard-row">
        <div class="ecard-capabilities">
          <span class="ecard-cap-label">Capabilities</span>
          <div class="ecard-cap-chips">${featureChips}</div>
        </div>
        <div class="ecard-meta-block">
          <div class="ecard-meta-row"><span class="muted">Version</span><code>${escapeHtml(version || '-')}</code></div>
          <div class="ecard-meta-row"><span class="muted">OS</span><span>${escapeHtml(os)} ${escapeHtml(arch)}</span></div>
          <div class="ecard-meta-row"><span class="muted">Container</span><span>${escapeHtml(containerRuntime)}</span></div>
          <div class="ecard-meta-row"><span class="muted">GPU</span><span>${escapeHtml(gpuText)}</span></div>
        </div>
      </div>
      <div class="ecard-row">
        <div class="ecard-hardware">
          <div class="ecard-hw-item"><b>CPU</b><span>${escapeHtml(hw.cpu || '-')}</span><small>${escapeHtml(hw.cores ? hw.cores+' threads' : '-')}</small></div>
          <div class="ecard-hw-item"><b>RAM</b><span>${escapeHtml(hw.ram || '-')}</span></div>
          <div class="ecard-hw-item"><b>Disk</b><span>${escapeHtml(hw.disk || '-')}</span></div>
          <div class="ecard-hw-item"><b>Last seen</b><span>${escapeHtml(lastSeen)}</span></div>
        </div>
        <div class="ecard-workspace-block">
          ${wsBadge}
          ${piContainerBadge}
          ${updateStatus}${maintenanceStatus}
        </div>
      </div>
      <details class="ecard-details"><summary>Details</summary>
        <div class="ecard-detail-grid">
          <div class="ecard-detail-section"><h4>pi.dev runtime</h4><pre>${escapeHtml(runtimeLines)}</pre><div class="muted small-text">${escapeHtml(enablement.detail || 'disabled')}</div></div>
          <div class="ecard-detail-section"><h4>Workspace</h4><div class="muted small-text">${escapeHtml(defaultWorkspace)}</div></div>
          <div class="ecard-detail-section"><h4>Tools (${effectiveTools.length})</h4><div class="muted small-text">${escapeHtml(tools)}</div><div class="muted small-text">packages: ${escapeHtml(packages)}</div></div>
          <div class="ecard-detail-section"><h4>Models (${modelLinks ? modelLinks.split(', ').length : 0})</h4><div class="muted small-text">${escapeHtml(modelLinks || '-')}</div></div>
          <div class="ecard-detail-section"><h4>Containers</h4><pre>${escapeHtml(containers || 'No running containers.')}</pre></div>
        </div>
      </details>`;
    const actions = document.createElement('div'); actions.className = 'button-row endpoint-actions';
    const edit=document.createElement('button'); edit.textContent='Edit endpoint'; edit.className='ghost-button'; edit.onclick=()=>openEndpointModal(r.id); actions.appendChild(edit);
    const cmd=document.createElement('button'); cmd.textContent='Command'; cmd.className='ghost-button'; cmd.disabled = r.status !== 'online' && !r.metadata?.local_control_plane; cmd.onclick=()=>openEndpointCommandModal(r.id); actions.appendChild(cmd);
    const nodeBtn=document.createElement('button'); nodeBtn.textContent='Install Node.js'; nodeBtn.className='ghost-button'; nodeBtn.disabled = enablement.node_available || (r.status !== 'online' && !r.metadata?.local_control_plane); nodeBtn.onclick=async()=>{ if(confirm(`Install Node.js on ${r.name}?`)){ const res=await api(`/v1/endpoints/${r.id}/install-node`,{method:'POST', body:JSON.stringify({method:'auto'})}); if(localDiscovery) localDiscovery.textContent='Node.js install requested. Details are in Events.'; emitUiEvent('endpoint_node_install_requested', `Node.js install requested: ${r.name}`, res); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); } }; actions.appendChild(nodeBtn);
    if (r.metadata?.local_control_plane) { const boot=document.createElement('button'); boot.textContent='Build/install controller pi.dev'; boot.className='ghost-button'; boot.onclick=async()=>{ boot.disabled=true; boot.textContent='Starting…'; const res=await api('/v1/controller-harness/bootstrap',{method:'POST'}); emitUiEvent('controller_pi_dev_bootstrap_requested', 'Controller pi.dev bootstrap started', res); await loadGlobalEvents(true).catch(()=>{}); await loadRunners(); }; actions.appendChild(boot); }
    const piBtn=document.createElement('button'); piBtn.textContent='Install pi.dev'; piBtn.className='ghost-button'; piBtn.disabled = !piMissing || (r.status !== 'online' && !r.metadata?.local_control_plane); piBtn.onclick=async()=>{ const image = piContainer.image || 'localhost/pi-agent-harness:stage11'; piBtn.disabled=true; piBtn.textContent='Installing pi.dev…'; const res=await api(`/v1/endpoints/${r.id}/install-pi-harness`,{method:'POST', body:JSON.stringify({image, runtime:'auto'})}); if(localDiscovery) localDiscovery.textContent='pi.dev install started. Watch Events for completion or failure.'; emitUiEvent('endpoint_pi_harness_install_requested', `pi.dev install started: ${r.name}`, res); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); }; actions.appendChild(piBtn);
    const upd=document.createElement('button'); upd.textContent='Update'; upd.disabled = r.status !== 'online' || !!r.metadata?.local_control_plane;
    upd.onclick=async()=>{ if(confirm(`Queue software update for ${r.name}?`)){ await api(`/v1/endpoints/${r.id}/update`,{method:'POST', body:JSON.stringify({restart:true})}); await loadRunners(); } };
    actions.appendChild(upd);
    const maint=document.createElement('button'); maint.textContent='Maintenance'; maint.disabled = r.status !== 'online'; maint.className='ghost-button';
    maint.onclick=async()=>{ if(confirm(`Run safe PAC maintenance cleanup on ${r.name}?`)){ await api(`/v1/endpoints/${r.id}/maintenance`,{method:'POST', body:JSON.stringify({max_age_hours:24,dry_run:false,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false})}); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); } };
    actions.appendChild(maint);
    const dry=document.createElement('button'); dry.textContent='Dry run'; dry.disabled = r.status !== 'online'; dry.className='ghost-button';
    dry.onclick=async()=>{ await api(`/v1/endpoints/${r.id}/maintenance`,{method:'POST', body:JSON.stringify({max_age_hours:24,dry_run:true,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false})}); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); };
    actions.appendChild(dry);
    const del=document.createElement('button'); del.textContent='Delete'; del.className='danger-button';
    del.onclick=async()=>{ if(confirm(`Delete endpoint ${r.name}?`)){ await api(`/v1/endpoints/${r.id}`,{method:'DELETE'}); await loadRunners(); } };
    actions.appendChild(del);
    card.appendChild(actions);
    el.appendChild(card);
  });
}



function renderStatCards(metrics) {
  const el = document.getElementById('dashboardStats');
  if (!el) return;
  const stats = [
    ['Sessions', metrics.sessions_total, `${metrics.sessions_active || 0} active`],
    ['Tasks', metrics.tasks_total, `${metrics.tasks_running || 0} running/queued`],
    ['Completed', metrics.tasks_completed, 'tasks done'],
    ['Failed', metrics.tasks_failed, 'tasks failed'],
    ['Approvals', metrics.approvals_pending, 'pending'],
    ['Endpoints', metrics.endpoints_total, `${metrics.endpoints_online || 0} online`],
  ];
  el.innerHTML = stats.map(([label,value,hint]) => `<div class="metric"><b>${value ?? 0}</b><span>${label}</span><small>${hint}</small></div>`).join('');
}
function renderBarChart(id, rows, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  const entries = Object.entries(rows || {}).filter(([_,v]) => Number(v) > 0);
  if (!entries.length) { el.textContent = emptyText || 'No data yet.'; return; }
  const max = Math.max(...entries.map(([_,v]) => Number(v) || 0), 1);
  el.innerHTML = entries.map(([label,value]) => `<div class="bar-row"><span>${escapeHtml(label)}</span><div class="bar-track"><i style="width:${Math.max(6, Math.round((Number(value)/max)*100))}%"></i></div><b>${value}</b></div>`).join('');
}
function renderEventActivity(points) {
  const el = document.getElementById('eventActivityChart');
  if (!el) return;
  const rows = points || [];
  const max = Math.max(...rows.map(p => Number(p.count) || 0), 1);
  el.innerHTML = `<div class="spark-bars">${rows.map(p => `<div class="spark-col" title="${escapeHtml(p.date)}: ${p.count}"><i style="height:${Math.max(8, Math.round((Number(p.count || 0)/max)*100))}%"></i><span>${escapeHtml(String(p.date || '').slice(5))}</span></div>`).join('')}</div>`;
}
async function loadDashboardMetrics() {
  try {
    const metrics = await api('/v1/metrics/summary');
    renderStatCards(metrics);
    renderBarChart('taskStatusChart', metrics.task_status, 'No tasks have run yet.');
    renderEventActivity(metrics.events_by_day);
  } catch (e) {
    const el = document.getElementById('dashboardStats');
    if (el) el.innerHTML = `<div class="muted">Could not load metrics: ${escapeHtml(e.message)}</div>`;
  }
}

function openEndpointModal(id='') {
  editingEndpointId = id || null;
  const modal = document.getElementById('endpointModal');
  const status = document.getElementById('endpointModalStatus');
  const title = document.getElementById('endpointModalTitle');
  if (status) status.textContent = '';
  if (title) title.textContent = editingEndpointId ? 'Edit endpoint' : 'Add remote endpoint';
  const endpoint = editingEndpointId ? (window.__pacEndpoints || []).find(r => r.id === editingEndpointId) : null;
  if (endpoint) {
    runnerName.value = endpoint.name || '';
    runnerLabels.value = (endpoint.labels || []).join(',');
    runnerEndpoint.value = endpoint.endpoint || '';
    setSelectedRunnerToolNames(endpoint.metadata?.agent_tools || []);
    if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.value = endpoint.metadata?.default_workspace || '';
    if (document.getElementById('runnerAgentEnabled')) runnerAgentEnabled.checked = !!(endpoint.metadata?.agent_requested || endpoint.metadata?.agent_enabled);
  } else {
    runnerName.value = 'gpu-workstation-01';
    runnerLabels.value = 'linux,gpu,endpoint';
    runnerEndpoint.value = '';
    setSelectedRunnerToolNames([]);
    if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.value = '';
    if (document.getElementById('runnerAgentEnabled')) runnerAgentEnabled.checked = false;
  }
  if (modal) { modal.hidden = false; setTimeout(() => document.getElementById('runnerName')?.focus(), 0); }
}
function closeEndpointModal() {
  const modal = document.getElementById('endpointModal');
  if (modal) modal.hidden = true;
}
function openSessionModal() {
  const modal = document.getElementById('sessionModal');
  if (modal) { modal.hidden = false; setTimeout(() => document.getElementById('sessionName')?.focus(), 0); }
}
function closeSessionModal() {
  const modal = document.getElementById('sessionModal');
  if (modal) modal.hidden = true;
}
function switchToTab(tabId) {
  const btn = document.querySelector(`.tab[data-tab="${tabId}"]`);
  if (btn) btn.click();
}


// Settings subnav
function switchSettingsPanel(name) {
  document.querySelectorAll('.settings-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.settings-sub-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById('settings-' + name);
  if (panel) { panel.style.display = 'block'; panel.classList.add('active'); }
  const btn = document.querySelector('.settings-sub-btn[data-settings-panel="' + name + '"]');
  if (btn) btn.classList.add('active');
  // Lazy init per panel
  if (name === 'users') loadUsersList();
  if (name === 'registry') loadRegistryImages();
  if (name === 'pi-dev') { renderControllerHarnessSettings(); }
  if (name === 'endpoint') renderEndpointConnectionSettings();
  if (name === 'service') renderServiceMode();
  if (name === 'tls') renderTlsInfo();
  if (name === 'config') { document.getElementById('configEditor').value = JSON.stringify(config, null, 2); renderSystemInfo(); }
}

document.querySelectorAll('.settings-sub-btn').forEach(btn => {
  btn.addEventListener('click', () => switchSettingsPanel(btn.dataset.settingsPanel));
});

// ============================================================
// 2. Users management
// ============================================================
async function loadUsersList() {
  const el = document.getElementById('usersList');
  if (!el) return;
  try {
    const users = await api('/v1/users');
    if (!users || !users.length) { el.innerHTML = '<p class="muted small-text">No users yet.</p>'; return; }
    el.innerHTML = users.map(u => `
      <div class="user-row">
        <div class="user-row-info">
          <span class="user-row-name">${escapeHtml(u.username)}</span>
          <span class="user-row-meta">${escapeHtml(u.display_name || '')} <span class="role-badge ${u.role}">${u.role}</span></span>
        </div>
        <div class="user-row-actions">
          <button class="ghost-button small-ghost" onclick="deleteUser('${escapeHtml(u.username)}')" title="Delete user">✕</button>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = '<p class="muted small-text">Could not load users: ' + escapeHtml(e.message) + '</p>'; }
}

async function deleteUser(username) {
  if (!confirm('Delete user ' + username + '?')) return;
  try {
    await api('/v1/users/' + username, {method: 'DELETE'});
    loadUsersList();
  } catch(e) { alert('Delete failed: ' + e.message); }
}

document.getElementById('addUserBtn')?.addEventListener('click', () => {
  document.getElementById('addUserForm').style.display = 'block';
  document.getElementById('newUserUsername').focus();
});
document.getElementById('cancelNewUserBtn')?.addEventListener('click', () => {
  document.getElementById('addUserForm').style.display = 'none';
  document.getElementById('newUserUsername').value = '';
  document.getElementById('newUserDisplayName').value = '';
  document.getElementById('newUserPassword').value = '';
});
document.getElementById('saveNewUserBtn')?.addEventListener('click', async () => {
  const username = document.getElementById('newUserUsername').value.trim();
  const display_name = document.getElementById('newUserDisplayName').value.trim() || username;
  const password = document.getElementById('newUserPassword').value;
  const role = document.getElementById('newUserRole').value;
  const resultEl = document.getElementById('addUserResult');
  if (!username || !password) { resultEl.textContent = 'username and password required'; return; }
  try {
    const r = await api('/v1/users', {method:'POST', body: JSON.stringify({username, display_name, password, role})});
    resultEl.textContent = 'User created: ' + username;
    document.getElementById('cancelNewUserBtn').click();
    loadUsersList();
  } catch(e) { resultEl.textContent = e.message; }
});

// ============================================================
// 3. Profile memory management
// ============================================================
async function loadProfileMemoryList() {
  const el = document.getElementById('profileMemoryList');
  if (!el) return;
  try {
    // Load all profiles and check memory status for each
    const profiles = await api('/v1/profiles');
    if (!profiles || !profiles.length) { el.innerHTML = '<p class="muted small-text">No profiles yet.</p>'; return; }
    const rows = await Promise.all(profiles.map(async p => {
      try {
        const mem = await api('/v1/profiles/' + p.name + '/memory');
        return { profile: p.name, ...mem };
      } catch { return { profile: p.name, ok: false, exists: false }; }
    }));
    el.innerHTML = rows.map(r => `
      <div class="memory-row">
        <div>
          <div class="memory-row-name">${escapeHtml(r.profile)}</div>
          <div class="memory-row-meta">${r.exists ? (r.commits?.length ? r.commits.length + ' commits' : 'empty') : 'no memory repo'}</div>
        </div>
        <div class="memory-row-actions">
          ${r.exists ? '<button class="ghost-button small-ghost" onclick="commitProfileMemory(\'' + r.profile + '\')" title="Commit pending changes">Commit</button>' : ''}
          <button class="ghost-button small-ghost" onclick="initProfileMemory('\'' + r.profile + '\')" title="${r.exists ? 'Re-init (noop)' : 'Initialize'}">${r.exists ? 'Status' : 'Init'}</button>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = '<p class="muted small-text">Could not load: ' + escapeHtml(e.message) + '</p>'; }
}

async function initProfileMemory(profile) {
  const resultEl = document.getElementById('profileMemoryResult');
  try {
    const r = await api('/v1/profiles/' + profile + '/memory', {method:'POST'});
    resultEl.textContent = (r.action === 'created' ? 'Created' : 'Found') + ' memory repo at ' + r.path;
    loadProfileMemoryList();
  } catch(e) { resultEl.textContent = e.message; }
}

async function commitProfileMemory(profile) {
  const resultEl = document.getElementById('profileMemoryResult');
  try {
    const r = await api('/v1/profiles/' + profile + '/memory/commit', {method:'POST', body: JSON.stringify({message: 'Manual commit'})});
    resultEl.textContent = r.ok ? 'Committed: ' + (r.message || profile) : r.error;
    loadProfileMemoryList();
  } catch(e) { resultEl.textContent = e.message; }
}

document.getElementById('initProfileMemoryBtn')?.addEventListener('click', () => {
  document.getElementById('initProfileMemoryForm').style.display = 'block';
  document.getElementById('initMemoryProfile').focus();
});
document.getElementById('cancelInitProfileMemoryBtn')?.addEventListener('click', () => {
  document.getElementById('initProfileMemoryForm').style.display = 'none';
  document.getElementById('initMemoryProfile').value = '';
});
document.getElementById('doInitProfileMemoryBtn')?.addEventListener('click', async () => {
  const profile = document.getElementById('initMemoryProfile').value.trim();
  if (!profile) return;
  await initProfileMemory(profile);
  document.getElementById('cancelInitProfileMemoryBtn').click();
  loadProfileMemoryList();
});

// Load on users panel open
const _origSwitchSettingsPanel = switchSettingsPanel;
switchSettingsPanel = function(name) {
  if (name === 'users') loadUsersList().then(loadProfileMemoryList);
  _origSwitchSettingsPanel(name);
};

// ============================================================
// 4. Container registry
// ============================================================
let _registryImages = [];
let _selectedImage = null;

async function loadRegistryImages() {
  const el = document.getElementById('registryImages');
  if (!el) return;
  try {
    const images = await api('/v1/registry/images');
    _registryImages = images || [];
    if (!_registryImages.length) {
      el.innerHTML = '<p class="muted small-text">No images in registry. Pull or build one to get started.</p>';
      document.getElementById('registryImageDetail').innerHTML = 'Select an image to see its details.';
      return;
    }
    el.innerHTML = _registryImages.map(img => `
      <div class="registry-image-row${_selectedImage === img.tag ? ' selected' : ''}" onclick="selectRegistryImage('${escapeHtml(img.tag.replace(/'/g, '\\\''))}')">
        <div class="registry-image-info">
          <span class="registry-image-name">${escapeHtml(img.tag)}</span>
          <span class="registry-image-meta">${img.size || '?'} · ${img.created || '?'}</span>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = '<p class="muted small-text">Could not load registry: ' + escapeHtml(e.message) + '</p>'; }
}

function selectRegistryImage(tag) {
  _selectedImage = tag;
  loadRegistryImages();
  showRegistryImageDetail(tag);
}

async function showRegistryImageDetail(tag) {
  const el = document.getElementById('registryImageDetail');
  if (!el || !tag) return;
  try {
    const detail = await api('/v1/registry/images/' + encodeURIComponent(tag));
    el.innerHTML = `<pre style="white-space:pre-wrap;word-break:break-all;font-size:.75rem;margin:0">${escapeHtml(JSON.stringify(detail, null, 2))}</pre>`;
  } catch(e) { el.innerHTML = '<p class="muted small-text">Could not load detail: ' + escapeHtml(e.message) + '</p>'; }
}

// Pull image
document.getElementById('pullRegistryImageBtn')?.addEventListener('click', () => {
  document.getElementById('pullImageForm').style.display = 'block';
  document.getElementById('buildImageForm').style.display = 'none';
  document.getElementById('pullImageSource').focus();
});
document.getElementById('cancelPullImageBtn')?.addEventListener('click', () => {
  document.getElementById('pullImageForm').style.display = 'none';
  document.getElementById('pullImageSource').value = '';
});
document.getElementById('doPullImageBtn')?.addEventListener('click', async () => {
  const source = document.getElementById('pullImageSource').value.trim();
  const tag = document.getElementById('pullImageTag').value.trim();
  const resultEl = document.getElementById('registryResult');
  if (!source || !tag) { resultEl.textContent = 'Source and local tag required'; return; }
  resultEl.textContent = 'Pulling...';
  try {
    const r = await api('/v1/registry/pull', {method:'POST', body: JSON.stringify({source, tag})});
    resultEl.textContent = 'Pulled: ' + tag + (r.size ? ' (' + r.size + ')' : '');
    document.getElementById('cancelPullImageBtn').click();
    loadRegistryImages();
  } catch(e) { resultEl.textContent = 'Error: ' + e.message; }
});

// Build image
document.getElementById('buildRegistryImageBtn')?.addEventListener('click', () => {
  document.getElementById('buildImageForm').style.display = 'block';
  document.getElementById('pullImageForm').style.display = 'none';
  document.getElementById('buildDockerfile').focus();
});
document.getElementById('cancelBuildImageBtn')?.addEventListener('click', () => {
  document.getElementById('buildImageForm').style.display = 'none';
  document.getElementById('buildDockerfile').value = '';
  document.getElementById('buildImageTag').value = '';
  document.getElementById('buildContext').value = '';
});
document.getElementById('doBuildImageBtn')?.addEventListener('click', async () => {
  const dockerfile = document.getElementById('buildDockerfile').value.trim();
  const tag = document.getElementById('buildImageTag').value.trim();
  const context = document.getElementById('buildContext').value.trim();
  const resultEl = document.getElementById('registryResult');
  if (!dockerfile || !tag) { resultEl.textContent = 'Dockerfile and tag required'; return; }
  resultEl.textContent = 'Building...';
  try {
    const r = await api('/v1/registry/build', {method:'POST', body: JSON.stringify({dockerfile, tag, context})});
    resultEl.textContent = r.ok ? 'Built: ' + tag + (r.size ? ' (' + r.size + ')' : '') : (r.error || 'Build failed');
    document.getElementById('cancelBuildImageBtn').click();
    loadRegistryImages();
  } catch(e) { resultEl.textContent = 'Error: ' + e.message; }
});


function renderZedConfigExamples() {
  const publicUrl = (config.server?.public_url || 'https://localhost').replace(/\/$/, '');
  const local = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'C:/tools/pac.exe',
        args: ['--base-url', publicUrl],
        env: {}
      }
    }
  };
  const remote = {
    context_servers: {
      pac: {
        source: 'custom',
        command: 'npx',
        args: ['-y', 'mcp-remote', `${publicUrl}/mcp`, '--insecure'],
        env: {}
      }
    }
  };
  const localEl = document.getElementById('zedMcpConfigLocal');
  const remoteEl = document.getElementById('zedMcpConfigRemote');
  if (localEl) localEl.textContent = JSON.stringify(local, null, 2);
  if (remoteEl) remoteEl.textContent = JSON.stringify(remote, null, 2);
}


async function loadServiceModeStatus() {
  const info = document.getElementById('serviceModeInfo');
  if (!info) return;
  try {
    const svc = await api('/v1/admin/service/status');
    const rows = {
      'Configured mode': svc.configured_mode || '-',
      'System service': svc.system_unit_exists ? `present / ${svc.system_active || '-'}` : `missing / ${svc.system_active || '-'}`,
      'User service': svc.user_unit_exists ? `present / ${svc.user_active || '-'}` : `missing / ${svc.user_active || '-'}`,
      'Port': svc.port || '-',
      'Host switch allowed now': svc.can_manage_host_now ? 'yes' : 'needs sudo/manual command',
      'System unit': svc.system_unit || '-',
      'User unit': svc.user_unit || '-',
    };
    info.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('');
    const result = document.getElementById('serviceModeResult');
    if (result && svc.manual_host_command) result.textContent = `Host service manual command if sudo is needed:\n${svc.manual_host_command}`;
  } catch (e) {
    info.innerHTML = `<div><span>Status</span><code>Could not load service status: ${escapeHtml(e.message)}</code></div>`;
  }
}

async function setServiceMode(mode) {
  const result = document.getElementById('serviceModeResult');
  if (mode === 'host' && !confirm('Switch PAC to host/system service? This requires sudo/root or passwordless sudo, uses port 443, and will restart PAC.')) return;
  if (mode === 'user' && !confirm('Switch PAC to user service? This will move PAC back to the user systemd service, use 8443, and restart PAC.')) return;
  if (result) result.textContent = `Switching PAC to ${mode} service mode…`;
  const payload = await api('/v1/admin/service/mode', {method:'POST', body:JSON.stringify({mode})});
  if (result) result.textContent = payload?.message || payload?.status || `Service mode ${mode} requested. Details are in Events.`; emitUiEvent('service_mode_changed', result ? result.textContent : 'Service mode changed', payload);
  if (payload.restart_scheduled) scheduleHiddenReloadAfterRestart(18);
  await loadServiceModeStatus();
  await loadControllerHarnessStatus();
}

async function loadTlsStatus() {
  const el = document.getElementById('tlsInfo');
  if (!el) return;
  try {
    const tls = await api('/v1/tls/status');
    const rows = {
      'CA': tls.ca_exists ? 'present' : 'missing',
      'CA valid until': tls.ca_valid_until || '-',
      'Server cert': tls.server_cert_exists ? 'present' : 'missing',
      'Server valid until': tls.server_valid_until || '-',
      'mDNS name': tls.mdns_hostname || 'admin.pac.local',
      'mDNS URL': tls.mdns_url || '-',
      'mDNS enabled': tls.mdns?.enabled === false ? 'no' : 'yes',
      'mDNS state': tls.mdns_status?.state || '-',
      'mDNS message': tls.mdns_status?.message || '-',
      'Port 443': tls.port_443?.configured ? 'configured' : 'not configured',
      'CA file': tls.ca_cert_file || '-',
      'Server cert file': tls.server_cert_file || '-',
      'Details': tls.details_file || '-',
    };
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(v)}</code></div>`).join('');
  } catch (e) {
    el.innerHTML = `<div><span>Status</span><code>Could not load TLS status: ${escapeHtml(e.message)}</code></div>`;
  }
}

function renderSystemInfo() {
  const pacp = config.pacp || {};
  const rows = {
    'PAC home': pacp.home || '-',
    'Config': pacp.config_path || '-',
    'Single-instance lock': pacp.single_instance_lock || '-',
    'Public URL': config.server?.public_url || '-',
    'Workspace root': config.server?.default_workspace_root || '-',
  };
  for (const id of ['systemInfo','pacpInfo']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${v}</code></div>`).join('');
  }
}


function fillHarnessSelects() {
  const profileSel = document.getElementById('harnessAgentProfile');
  const modelSel = document.getElementById('harnessModel');
  const permSel = document.getElementById('harnessPermission');
  if (profileSel) { profileSel.innerHTML = '<option value="">none</option>'; Object.keys(config.agent_profiles || {}).forEach(name => opt(profileSel, name, name)); }
  if (modelSel) { modelSel.innerHTML = '<option value="">profile default</option>'; Object.keys(config.models || {}).forEach(name => opt(modelSel, name, name)); }
  if (permSel) { permSel.innerHTML = ''; Object.keys(config.permission_profiles || {'ask-first':{}}).forEach(name => opt(permSel, name, name)); }
}

function renderControllerHarnessSettings(status=null) {
  fillHarnessSelects();
  const h = config.controller_harness || {};
  const setVal = (id, value) => { const el = document.getElementById(id); if (el) el.value = value ?? ''; };
  const setChecked = (id, value) => { const el = document.getElementById(id); if (el) el.checked = !!value; };
  setChecked('harnessEnabled', h.enabled !== false);
  setChecked('harnessAutoBootstrap', h.auto_bootstrap !== false);
  setChecked('harnessAutoBuildWrapper', h.auto_build_wrapper !== false);
  setChecked('harnessAutoInstallPiDev', h.auto_install_pi_dev !== false);
  setChecked('harnessAutoSession', h.auto_create_session !== false);
  setChecked('harnessExposeTools', h.expose_platform_tools !== false);
  setVal('harnessSessionName', h.session_name || 'PAC controller pi.dev');
  setVal('harnessWorkspaceProfile', h.workspace_profile || 'agent-control');
  setVal('harnessAgentProfile', h.agent_profile || 'main-pi-dev');
  setVal('harnessModel', h.model || '');
  setVal('harnessPermission', h.permission_profile || 'ask-first');
  setVal('harnessContextMode', h.context_mode || 'medium');
  setVal('harnessRunnerId', h.runner_id || 'local-PAC');
  const box = document.getElementById('controllerHarnessStatus');
  if (box) {
    const session = status?.session;
    const runner = status?.runner;
    const rows = {
      'State': status ? (status.ok ? 'ready' : 'needs setup') : 'not checked',
      'Message': status?.message || 'Saved settings are shown below.',
      'Runner': runner?.name || h.runner_id || '-',
      'Session': session?.name || '-',
      'Model': session?.model || h.model || 'profile default',
      'Workspace': session?.workspace_path || '-',
      'PAC wrapper': runner?.capabilities?.pac_wrapper?.available ? (runner.capabilities.pac_wrapper.path || 'available') : (runner?.capabilities?.pac_wrapper?.reason || 'missing'),
      'pi.dev image': runner?.capabilities?.pi_container?.available ? (runner.capabilities.pi_container.image || 'available') : (runner?.capabilities?.pi_container?.reason || 'missing'),
    };
    box.innerHTML = Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('');
  }
}

async function loadControllerHarnessStatus() {
  try {
    const status = await api('/v1/controller-harness');
    renderControllerHarnessSettings(status);
    return status;
  } catch (e) {
    renderControllerHarnessSettings({ok:false, message:e.message});
    return null;
  }
}

async function saveControllerHarnessSettings() {
  const result = document.getElementById('controllerHarnessResult');
  const payload = {
    enabled: !!document.getElementById('harnessEnabled')?.checked,
    auto_bootstrap: !!document.getElementById('harnessAutoBootstrap')?.checked,
    auto_build_wrapper: !!document.getElementById('harnessAutoBuildWrapper')?.checked,
    auto_install_pi_dev: !!document.getElementById('harnessAutoInstallPiDev')?.checked,
    auto_create_session: !!document.getElementById('harnessAutoSession')?.checked,
    expose_platform_tools: !!document.getElementById('harnessExposeTools')?.checked,
    session_name: document.getElementById('harnessSessionName')?.value?.trim() || 'PAC controller pi.dev',
    workspace_profile: document.getElementById('harnessWorkspaceProfile')?.value?.trim() || 'agent-control',
    agent_profile: document.getElementById('harnessAgentProfile')?.value || 'main-pi-dev',
    model: document.getElementById('harnessModel')?.value || null,
    permission_profile: document.getElementById('harnessPermission')?.value || 'ask-first',
    context_mode: document.getElementById('harnessContextMode')?.value || 'medium',
    runner_id: document.getElementById('harnessRunnerId')?.value?.trim() || 'local-PAC',
  };
  const status = await api('/v1/controller-harness/settings', {method:'POST', body:JSON.stringify(payload)});
  if (result) result.textContent = status.message || 'Controller pi.dev settings saved.';
  await loadConfig();
  await loadSessions();
  if (status?.session?.id) { selectedSession = status.session; }
  await loadGlobalEvents(true).catch(()=>{});
}


async function bootstrapControllerHarness() {
  const result = document.getElementById('controllerHarnessResult');
  if (result) result.textContent = 'Starting controller pi.dev bootstrap…';
  const status = await api('/v1/controller-harness/bootstrap', {method:'POST'});
  if (result) result.textContent = status.message || 'Controller pi.dev bootstrap started.';
  await loadGlobalEvents(true).catch(()=>{});
  await loadRunners().catch(()=>{});
}

async function openControllerHarnessSession() {
  const status = await loadControllerHarnessStatus();
  if (status?.session?.id) { switchToTab('sessions-tab'); await selectSession(status.session.id); }
  else showInline('controllerHarnessResult', status?.message || 'pi.dev session is not available yet. Select a model/profile first.');
}

function renderEndpointConnectionSettings() {
  const urlInput = document.getElementById('endpointPublicUrl');
  const mdnsInput = document.getElementById('endpointMdnsEnabled');
  if (urlInput) urlInput.value = config.server?.public_url || '';
  if (mdnsInput) mdnsInput.checked = config.mdns?.enabled !== false;
}

async function saveEndpointConnectionSettings() {
  const result = document.getElementById('endpointConnectionResult');
  const publicUrl = (document.getElementById('endpointPublicUrl')?.value || '').trim();
  const mdnsEnabled = !!document.getElementById('endpointMdnsEnabled')?.checked;
  if (!publicUrl) return paneError('Enter the controller URL endpoints should use');
  const payload = await api('/v1/server/connection', {method:'POST', body:JSON.stringify({public_url: publicUrl, mdns_enabled: mdnsEnabled})});
  if (result) result.textContent = payload.message || 'Endpoint connection settings saved.';
  await loadConfig();
  await loadGlobalEvents(true).catch(()=>{});
}

async function loadConfig() {
  config = await api('/v1/config');
  fillSelects(); renderWorkspaces(); renderProfiles(); renderProviders(); renderModels(); renderTools();
  refreshActiveSessions().catch(()=>{});
  startModelScorePolling();
  document.getElementById('configEditor').value = JSON.stringify(config, null, 2);
  renderSystemInfo();
  renderControllerHarnessSettings();
  renderEndpointConnectionSettings();
  renderZedConfigExamples();
  renderSources();
  await loadTlsStatus();
  await loadServiceModeStatus();
  await loadControllerHarnessStatus();
}
async function loadSessions() {
  const sessions = await api('/v1/sessions');
  const dashboard = document.getElementById('sessions');
  const picker = document.getElementById('sessionTopSelect');
  if (dashboard) dashboard.innerHTML = '';
  if (picker) picker.innerHTML = '<option value="">Select session</option>';
  if (!sessions.length) {
    if (dashboard) dashboard.innerHTML = '<div class="muted">No sessions yet. Create one from the Sessions page.</div>';
    if (picker) picker.innerHTML = '<option value="">No sessions yet</option>';
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
}
async function selectSession(id) {
  selectedSession = await api(`/v1/sessions/${id}`);
  const preferredEndpoint = selectedSession.metadata?.preferred_endpoint || '';
  const endpointName = (window.__pacEndpoints || []).find(e => e.id === preferredEndpoint)?.name || preferredEndpoint || 'PAC/local';
  document.getElementById('selectedSession').innerHTML = `<span class="session-lock-dot"></span><span>Profile: ${escapeHtml(selectedSession.agent_profile || 'default')}</span><span>Endpoint: ${escapeHtml(endpointName)}</span><span>Mode: ${escapeHtml(selectedSession.metadata?.execution_mode || (selectedSession.metadata?.agent_enabled === false ? 'direct model' : 'pi.dev'))}</span><span>Model: ${escapeHtml(selectedSession.model || '')}</span><span>${escapeHtml(selectedSession.workspace_path || '')}</span>`;
  if (document.getElementById('sessionTopSelect')) sessionTopSelect.value = selectedSession.id;
  if (document.getElementById('taskRunner')) taskRunner.value = preferredEndpoint || '';
  if (document.getElementById('sessionEndpointLock')) sessionEndpointLock.textContent = `Profile: ${selectedSession.agent_profile || 'default'} · endpoint: ${endpointName} · model: ${selectedSession.model || 'session default'}`;
  const timeline = document.getElementById('events');
  if (timeline) timeline.innerHTML = '<div class="empty-timeline">Waiting for session events.</div>';
  sessionThinkingGroup = null;
  sessionEventSeen = new Set();
  sessionMessageSeen = new Set();
  sessionPendingRows = new Map();
  try {
    const snapshot = await api(`/v1/sessions/${id}/events/snapshot?limit=120`);
    if (timeline) timeline.innerHTML = snapshot.length ? '' : '<div class="empty-timeline">No session events yet.</div>';
    // Mark the thinking group as already-closed before loading historical events
    // so agent_thinking events render WITHOUT spinners (historical = already done)
    sessionThinkingGroup = {events: [], startedAt: new Date(), endedAt: new Date(), row: null, closed: true, isHistorical: true};
    snapshot.forEach(ev => renderSessionTimelineEvent(ev));
    // Keep a dormant historical marker so live agent_thinking events know to skip rendering
    // (live events will reopen the group properly when they arrive)
    sessionThinkingGroup = {events: [], startedAt: new Date(), endedAt: new Date(), closed: false, isHistorical: true};
    // Small delay then switch to fully open so any race-condition live events don't leak spinners
    setTimeout(() => { sessionThinkingGroup = null; }, 2000);
    // Safety: remove any thinking-live rows that were rendered during snapshot load
    setTimeout(() => {
      const tl = document.getElementById('events');
      if (tl) tl.querySelectorAll('.thinking-live').forEach(r => r.remove());
    }, 100);
  } catch (_) {}
  if (source) source.close();
  // EventSource cannot set auth headers, so auth-enabled deployments should use the snapshot refresh path or put UI/API behind same auth proxy.
  source = new EventSource(`/v1/sessions/${id}/events`);
  source.onmessage = e => { try { appendEvent('message', JSON.parse(e.data)); } catch { appendEvent('message', e.data); } };
  ['user_message','agent_routing','task_queued','stdout','stderr','task_started','task_completed','task_failed','approval_required','task_approved','task_rejected','session_created','agent_loop_started','agent_thinking','model_response','tool_call','tool_result','tool_approval_required','tool_approval_responded','result','full_control_enabled'].forEach(t => source.addEventListener(t, e => { try { appendEvent(t, JSON.parse(e.data)); } catch { appendEvent(t, e.data); } }));
}
function appendEvent(type, payload) {
  const event = normalizeEvent(type, payload);
  renderSessionTimelineEvent(event);
  renderGlobalEvent(event);
  loadApprovals().catch(()=>{});
}
async function loadApprovals() {
  const tasks = await api('/v1/tasks/pending-approvals');
  const el = document.getElementById('approvals'); el.innerHTML = '';
  tasks.forEach(t => {
    const row=document.createElement('div'); row.className='row';
    row.innerHTML=`<div><b>${t.command || t.prompt}</b><br><span class="muted">${t.session_id}</span></div>`;
    const a=document.createElement('button'); a.textContent='Approve'; a.onclick=async()=>{await api(`/v1/tasks/${t.id}/approve`,{method:'POST'}); await loadApprovals();};
    const r=document.createElement('button'); r.textContent='Reject'; r.onclick=async()=>{await api(`/v1/tasks/${t.id}/reject?reason=Rejected`,{method:'POST'}); await loadApprovals();};
    row.append(a,r); el.appendChild(row);
  });
}
document.getElementById('refresh').onclick=()=>init();
document.getElementById('createSession').onclick=async()=>{
  const btn = document.getElementById('createSession');
  const status = document.getElementById('sessionCreateStatus');
  try {
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Creating…';
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
  if(!selectedSession) return alert('select a session first');
  const rawPrompt = (taskPrompt.value || '').trim();
  if(!rawPrompt) return;
  const parsedSlash = parseSessionSlashCommand(rawPrompt);
  if (parsedSlash?.error) return alert(parsedSlash.error);
  if (parsedSlash?.kind === 'help') {
    alert(slashCommandHelpText());
    return;
  }
  let prompt = parsedSlash?.prompt || rawPrompt;
  let command = '';
  const metadata={};
  if (parsedSlash?.metadata) Object.assign(metadata, parsedSlash.metadata);
  const runnerChoice = selectedSession.metadata?.preferred_endpoint || taskRunner.value || '';
  if(runnerChoice){
    metadata.runner_id=runnerChoice;
    const isToolInvocation = Boolean(metadata.tool_name);
    metadata.execution_mode = isToolInvocation ? 'host' : ((taskExecution.value === 'container' || taskExecution.value === 'pi_container') ? taskExecution.value : 'pi_container');
    if(taskImage.value) metadata.container_image=taskImage.value;
    if (isToolInvocation) command = `tool:${metadata.tool_name}`;
  }
  if (parsedSlash?.kind === 'compact') {
    metadata.execution_mode = 'pi_container';
  }
  if (parsedSlash?.kind === 'subagent') {
    metadata.execution_mode = 'pi_container';
    metadata.agent_profile = selectedSession.agent_profile || selectedSession.metadata?.agent_profile || null;
  }
  if (document.getElementById('taskModel')?.value) metadata.model = taskModel.value;
  taskPrompt.value='';
  taskCommand.value='';
  autosizeSessionPrompt();
  const created = await api(`/v1/sessions/${selectedSession.id}/tasks`,{method:'POST',body:JSON.stringify({prompt:prompt || rawPrompt,command,metadata})});
  if (created && created.id) {
    const localEvent = {
      id: `local_user_${created.id}`,
      session_id: selectedSession.id,
      task_id: created.id,
      type: 'user_message',
      message: rawPrompt,
      created_at: created.created_at || new Date().toISOString(),
      data: {role:'user', model: metadata.model || selectedSession.model, endpoint_id: metadata.runner_id || selectedSession.metadata?.preferred_endpoint, command, execution_mode: metadata.execution_mode, slash_command: metadata.slash_command, tool_name: metadata.tool_name, args: metadata.args, stored:true, pi_dev_enabled:selectedSession.metadata?.agent_enabled !== false, routing:'pi.dev'}
    };
    renderSessionTimelineEvent(localEvent);
  }
}

const composerAddContextBtn = document.getElementById('composerAddContext');
const composerContextMenu = document.getElementById('composerContextMenu');
if (composerAddContextBtn && composerContextMenu) {
  composerAddContextBtn.onclick = (ev) => { ev.stopPropagation(); composerContextMenu.hidden = !composerContextMenu.hidden; };
  composerContextMenu.onclick = (ev) => ev.stopPropagation();
  document.addEventListener('click', () => { composerContextMenu.hidden = true; });
}

const sessionTopSelect = document.getElementById('sessionTopSelect');
if (sessionTopSelect) sessionTopSelect.onchange = () => { if (sessionTopSelect.value) { switchToTab('sessions-tab'); selectSession(sessionTopSelect.value); } };

function openContainerDestinationModal() {
  const modal = document.getElementById('containerDestinationModal');
  const input = document.getElementById('containerDestinationImage');
  if (input) input.value = document.getElementById('taskImage')?.value || '';
  if (modal) modal.hidden = false;
  setTimeout(() => input?.focus(), 20);
}
function closeContainerDestinationModal() { const modal = document.getElementById('containerDestinationModal'); if (modal) modal.hidden = true; }
const taskExecutionSelect = document.getElementById('taskExecution');
if (taskExecutionSelect) taskExecutionSelect.onchange = () => { if (taskExecutionSelect.value === 'container') openContainerDestinationModal(); };
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
  closeContainerDestinationModal();
};
const clearContainerDestinationBtn = document.getElementById('clearContainerDestination');
if (clearContainerDestinationBtn) clearContainerDestinationBtn.onclick = () => {
  if (document.getElementById('taskImage')) taskImage.value = '';
  if (document.getElementById('taskExecution')) taskExecution.value = 'host';
  closeContainerDestinationModal();
};
const runTaskBtn = document.getElementById('runTask');

function autosizeSessionPrompt() {
  const el = document.getElementById('taskPrompt');
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(160, Math.max(28, el.scrollHeight)) + 'px';
}

if (runTaskBtn) runTaskBtn.onclick=()=>sendSessionComposer().catch(e=>alert(e.message));
const taskPromptInput = document.getElementById('taskPrompt');
if (taskPromptInput) { taskPromptInput.addEventListener('input', autosizeSessionPrompt); taskPromptInput.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); sendSessionComposer().catch(e=>alert(e.message)); } }); autosizeSessionPrompt(); }
const taskCommandInput = document.getElementById('taskCommand');
if (taskCommandInput) taskCommandInput.addEventListener('keydown', (ev) => { if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { ev.preventDefault(); sendSessionComposer().catch(e=>alert(e.message)); } });
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
const loadDiffBtn = document.getElementById('loadDiff');
if (loadDiffBtn) loadDiffBtn.onclick=()=>openGitDiffModal();
document.getElementById('saveConfig').onclick=async()=>{ const body={config:JSON.parse(configEditor.value)}; await api('/v1/config',{method:'PUT',body:JSON.stringify(body)}); await init(); };
if (document.getElementById('saveEndpointConnection')) document.getElementById('saveEndpointConnection').onclick=()=>saveEndpointConnectionSettings().catch(e=>paneError('Saving endpoint URL failed', e.message));
if (document.getElementById('saveControllerHarness')) document.getElementById('saveControllerHarness').onclick=()=>saveControllerHarnessSettings().catch(e=>paneError('Saving controller pi.dev failed', e.message));
if (document.getElementById('bootstrapControllerHarness')) document.getElementById('bootstrapControllerHarness').onclick=()=>bootstrapControllerHarness().catch(e=>paneError('Starting controller pi.dev bootstrap failed', e.message));
if (document.getElementById('openControllerHarnessSession')) document.getElementById('openControllerHarnessSession').onclick=()=>openControllerHarnessSession().catch(e=>paneError('Opening controller pi.dev failed', e.message));
if (document.getElementById('providerPreset')) providerPreset.onchange=()=>applyProviderPreset(providerPreset.value);
if (document.getElementById('saveProvider')) saveProvider.onclick=()=>saveProviderFromForm().catch(e=>paneError('Provider save failed', e.message));
if (document.getElementById('connectProviderForm')) connectProviderForm.onclick=()=>connectProviderFromForm().catch(e=>paneError('Provider connect failed', e.message));
if (document.getElementById('saveModel')) saveModel.onclick=()=>saveModelFromForm().catch(e=>paneError('Model save failed', e.message));
if (document.getElementById('testModelForm')) testModelForm.onclick=()=>testModelFromForm().catch(e=>paneError('Model test failed', e.message));
if (document.getElementById('modelProvider')) modelProvider.onchange=()=>updateLmStudioModelControls();
const checkSourceUpdatesBtn = document.getElementById('checkSourceUpdates');
if (checkSourceUpdatesBtn) checkSourceUpdatesBtn.onclick = checkSourceOnlineUpdates;

// PAC update buttons
const checkPacBtn = document.getElementById('checkPacUpdatesBtn');
if (checkPacBtn) checkPacBtn.onclick = () => { checkPacUpdateStatus(); };
const applyPacBtn = document.getElementById('applyPacUpdateBtn');
if (applyPacBtn) applyPacBtn.onclick = applyPacUpdate;
const dismissPacBtn = document.getElementById('dismissPacUpdateBtn');
if (dismissPacBtn) dismissPacBtn.onclick = () => {
  const statusLine = document.getElementById('pacUpdateStatusLine');
  if (statusLine) statusLine.style.display = 'none';
};

async function generateLocalDiff() {
  const versionInput = document.getElementById('diffVersionInput');
  const statusEl = document.getElementById('diffGenStatus');
  const resultEl = document.getElementById('diffGenResult');
  const btn = document.getElementById('generateDiffBtn');
  const version = (versionInput?.value || '').trim();
  if (!version) { alert('Please enter a version number, e.g. 1.0.107'); return; }
  if (!confirm(`Generate .pac/diffs/v${version}.diff from your local changes?`)) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = 'Generating diff…'; }
  if (resultEl) resultEl.style.display = 'none';
  try {
    const r = await api(`/v1/updates/generate-local-diff?version=${encodeURIComponent(version)}`, {
      method: 'POST',
    });
    const d = await r;
    if (d.ok && d.status === 'written') {
      if (statusEl) statusEl.textContent = 'Done!';
      if (resultEl) {
        _lastDiffVersion = version;
        resultEl.style.display = 'block';
        resultEl.innerHTML = `<div style="margin-top:4px">Diff written: <code>${d.diff_path}</code> (${d.size?.toLocaleString()} bytes) — <a href="/v1/updates/diff/${version}" target="_blank" style="color:#9966ff;text-decoration:underline">Download</a></div>`;
      }
      renderUpdateDetail(null);
    } else if (d.ok && d.status === 'no_diff') {
      if (statusEl) statusEl.textContent = 'No differences found — nothing to release.';
    } else {
      if (statusEl) statusEl.textContent = 'Error: ' + (d.error || JSON.stringify(d));
    }
  } catch(e) {
    if (statusEl) statusEl.textContent = 'Request failed: ' + e;
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Generate diff'; }
}

const generateDiffBtn = document.getElementById('generateDiffBtn');
if (generateDiffBtn) generateDiffBtn.onclick = generateLocalDiff;

// Run PAC update check on load
checkPacUpdateStatus();

// Archive & change tracking UI
const archiveNowBtn = document.getElementById('archiveNowBtn');
if (archiveNowBtn) archiveNowBtn.onclick = () => { runArchiveCurrent(); };
const detectChangesBtn = document.getElementById('detectChangesBtn');
if (detectChangesBtn) detectChangesBtn.onclick = () => { runDetectChanges(); };
const viewChangeDiffBtn = document.getElementById('viewChangeDiffBtn');
if (viewChangeDiffBtn) viewChangeDiffBtn.onclick = () => { showChangeDiff(); };
const clearChangesBtn = document.getElementById('clearChangesBtn');
if (clearChangesBtn) clearChangesBtn.onclick = () => { discardChanges(); };
const diffToLatestBtn = document.getElementById('diffToLatestBtn');
if (diffToLatestBtn) diffToLatestBtn.onclick = () => { runDiffToLatest(); };

async function runArchiveCurrent() {
  const btn = document.getElementById('archiveNowBtn');
  const msg = document.getElementById('archiveStatusMsg');
  if (btn) { btn.disabled = true; btn.textContent = 'Archiving…'; }
  if (msg) { msg.style.display = 'block'; msg.textContent = 'Creating archive…'; }
  try {
    const r = await fetch('/v1/updates/archive-current', {method:'POST'});
    const d = await r.json();
    if (d.status === 'archived') {
      if (msg) msg.textContent = 'Archived v' + d.version + ' — ' + d.meta.file_count + ' files, ' + Math.round(d.meta.total_bytes/1024) + ' KB';
      refreshArchiveStatus();
    } else if (d.status === 'exists') {
      if (msg) msg.textContent = 'Archive already exists for v' + d.version;
      refreshArchiveStatus();
    } else {
      if (msg) msg.textContent = 'Error: ' + (d.detail || JSON.stringify(d));
    }
  } catch(e) {
    if (msg) msg.textContent = 'Failed: ' + e;
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Archive current version'; }
}

async function runDetectChanges() {
  const btn = document.getElementById('detectChangesBtn');
  const msg = document.getElementById('archiveStatusMsg');
  if (btn) { btn.disabled = true; btn.textContent = 'Detecting…'; }
  if (msg) { msg.style.display = 'block'; msg.textContent = 'Comparing files…'; }
  try {
    const r = await fetch('/v1/updates/detect-changes', {method:'POST'});
    const d = await r.json();
    if (d.has_changes) {
      const s = d.summary;
      if (msg) msg.textContent = 'Diverged: ' + s.added + ' added, ' + s.removed + ' removed, ' + s.modified + ' modified';
      if (document.getElementById('archiveChangeLine')) document.getElementById('archiveChangeLine').style.display = 'flex';
      if (document.getElementById('archiveChangeBadge')) { document.getElementById('archiveChangeBadge').textContent = 'Diverged'; document.getElementById('archiveChangeBadge').className = 'archive-status-badge change-badge'; }
      if (document.getElementById('archiveChangeSummary')) document.getElementById('archiveChangeSummary').textContent = s.added + 'A / ' + s.removed + 'R / ' + s.modified + 'M';
      if (document.getElementById('archiveDiffActions')) document.getElementById('archiveDiffActions').style.display = 'flex';
      if (document.getElementById('archiveDetailPanel')) document.getElementById('archiveDetailPanel').style.display = 'block';
    } else {
      if (msg) msg.textContent = 'No changes detected — system matches archive';
      if (document.getElementById('archiveChangeLine')) document.getElementById('archiveChangeLine').style.display = 'none';
    }
    refreshArchiveStatus();
  } catch(e) {
    if (msg) msg.textContent = 'Failed: ' + e;
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Detect changes'; }
}

async function showChangeDiff() {
  const body = document.getElementById('diffViewerBody');
  const title = document.getElementById('diffViewerTitle');
  if (title) title.textContent = 'Local changes';
  if (body) { body.style.display = 'block'; body.textContent = 'Loading…'; }
  try {
    const r = await fetch('/v1/updates/change-diff');
    const d = await r.json();
    if (d.has_diff && d.content) {
      if (body) body.textContent = d.content;
    } else {
      if (body) body.textContent = 'No diff available';
    }
  } catch(e) {
    if (body) body.textContent = 'Error: ' + e;
  }
}

async function discardChanges() {
  if (!confirm('Discard change tracking? Your files are not affected.')) return;
  try {
    const r = await fetch('/v1/updates/clear-change-state', {method:'POST'});
    const d = await r.json();
    if (d.ok) {
      if (document.getElementById('archiveChangeLine')) document.getElementById('archiveChangeLine').style.display = 'none';
      if (document.getElementById('archiveDiffActions')) document.getElementById('archiveDiffActions').style.display = 'none';
      if (document.getElementById('archiveDetailPanel')) document.getElementById('archiveDetailPanel').style.display = 'none';
      const msg = document.getElementById('archiveStatusMsg');
      if (msg) msg.textContent = 'Change tracking cleared.';
      refreshArchiveStatus();
    }
  } catch(e) { alert('Failed: ' + e); }
}

async function runDiffToLatest() {
  const btn = document.getElementById('diffToLatestBtn');
  const statusEl = document.getElementById('diffToLatestStatus');
  const resultEl = document.getElementById('diffToLatestResult');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  if (statusEl) { statusEl.style.display = 'inline'; statusEl.textContent = 'Fetching diff…'; }
  if (resultEl) resultEl.style.display = 'none';
  try {
    const r = await fetch('/v1/updates/diff-to-latest');
    const d = await r.json();
    if (d.has_diff) {
      if (statusEl) statusEl.textContent = 'v' + d.from_version + ' → v' + d.to_version + ' — ' + d.diff_line_count + ' lines';
      if (resultEl) {
        resultEl.style.display = 'block';
        const firstFew = (d.diff || '').split('\n').slice(0, 10).join('\n');
        resultEl.innerHTML = '<div style="background:#111;border-radius:4px;padding:8px;max-height:180px;overflow-y:auto;font-family:monospace;font-size:0.8em;white-space:pre">' + escapeHtml(firstFew) + '\n[...]</div><div style="margin-top:6px"><a href="/v1/updates/diff-to-latest" target="_blank" style="color:#9966ff;font-size:0.85em">View full diff</a></div>';
      }
    } else {
      if (statusEl) statusEl.textContent = 'No diff available';
    }
  } catch(e) {
    if (statusEl) statusEl.textContent = 'Error: ' + e;
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Preview update diff'; }
}

async function refreshArchiveStatus() {
  try {
    const r = await fetch('/v1/updates/status');
    const d = await r.json();
    const badge = document.getElementById('archiveStatusBadge');
    const verLabel = document.getElementById('archiveVersionLabel');
    const archiveActions = document.getElementById('archiveNowBtn');
    if (d.has_archive) {
      if (badge) { badge.textContent = 'v' + d.current_version + ' archived'; badge.className = 'archive-status-badge archived-badge'; }
      if (verLabel) { verLabel.style.display = 'inline'; verLabel.textContent = '(' + d.current_archive + ')'; }
      if (archiveActions) archiveActions.style.display = 'none';
    } else {
      if (badge) { badge.textContent = 'Not archived'; badge.className = 'archive-status-badge muted'; }
      if (verLabel) verLabel.style.display = 'none';
      if (archiveActions) archiveActions.style.display = 'inline-block';
    }
    if (d.has_local_changes) {
      if (document.getElementById('archiveChangeLine')) document.getElementById('archiveChangeLine').style.display = 'flex';
      if (document.getElementById('archiveChangeBadge')) { document.getElementById('archiveChangeBadge').textContent = 'Diverged'; document.getElementById('archiveChangeBadge').className = 'archive-status-badge change-badge'; }
      if (document.getElementById('archiveDiffActions')) document.getElementById('archiveDiffActions').style.display = 'flex';
      if (document.getElementById('archiveDetailPanel')) document.getElementById('archiveDetailPanel').style.display = 'block';
    }
  } catch(e) { console.error('refreshArchiveStatus failed', e); }
}

// Run archive status check on load
refreshArchiveStatus();



let _cachedUpdateMeta = null;
let _lastDiffVersion = null;

function renderUpdateDetail(meta) {
  const panel = document.getElementById('updatesDetailPanel');
  const title = document.getElementById('updatesDetailTitle');
  const ver = document.getElementById('updatesDetailVersion');
  const body = document.getElementById('updatesDetailBody');
  if (!panel) return;
  if (!meta || !meta.ok) {
    if (title) title.textContent = 'Release details';
    if (ver) ver.textContent = '';
    if (body) body.innerHTML = '<div class="muted small-text">Check for updates to see release details here.</div>';
    return;
  }
  if (title) title.textContent = meta.has_update ? 'Changes in' : 'Current release';
  if (ver) ver.textContent = 'v' + (meta.latest_version || meta.current_version);
  const changes = meta.changes || [];
  if (body) {
    if (changes.length) {
      body.innerHTML = '<ul class="updates-changes-list">' + changes.map(c => '<li>' + escapeHtml(c) + '</li>').join('') + '</ul>'
        + (meta.body ? '<details style="margin-top:10px"><summary class="muted small-text" style="cursor:pointer">Full notes</summary><div class="muted small-text" style="white-space:pre-wrap;margin-top:4px;font-size:0.9em">' + escapeHtml(meta.body || '') + '</div></details>' : '');
    } else {
      body.innerHTML = '<div class="muted small-text">No change notes available for this release.</div>';
    }
  }
}

async function checkPacUpdateStatus() {
  const currentSpan = document.getElementById('pacCurrentVersion');
  const statusLine = document.getElementById('pacUpdateStatusLine');
  const statusBadge = document.getElementById('pacStatusBadge');
  const updateLink = document.getElementById('pacUpdateVersionLink');
  const applyBtn = document.getElementById('applyPacUpdateBtn');
  const dismissBtn = document.getElementById('dismissPacUpdateBtn');
  try {
    const r = await fetch('/v1/updates/check');
    const d = await r;
    _cachedUpdateMeta = d;
    if (currentSpan) currentSpan.textContent = 'v' + (d.current_version || '?');
    if (d.ok && d.has_update) {
      statusLine.style.display = 'flex';
      if (statusBadge) { statusBadge.textContent = 'Update available'; statusBadge.className = 'pac-status-badge update-badge'; }
      if (updateLink) { updateLink.textContent = 'v' + d.latest_version; updateLink.href = d.release_url || '#'; }
      if (applyBtn) applyBtn.style.display = 'inline-block';
      if (dismissBtn) dismissBtn.style.display = 'inline-block';
      renderUpdateDetail(d);
    } else if (d.ok) {
      statusLine.style.display = 'flex';
      if (statusBadge) { statusBadge.textContent = 'Up to date'; statusBadge.className = 'pac-status-badge current-badge'; }
      if (updateLink) { updateLink.textContent = 'v' + d.current_version; updateLink.href = d.release_url || '#'; }
      if (applyBtn) applyBtn.style.display = 'none';
      if (dismissBtn) dismissBtn.style.display = 'none';
      renderUpdateDetail(d);
    } else {
      statusLine.style.display = 'none';
      renderUpdateDetail(null);
    }
  } catch(e) {
    console.error('checkPacUpdateStatus failed', e);
    renderUpdateDetail(null);
  }
}



async function applyPacUpdate() {
  if (!confirm('Download and apply the latest PAC release? PAC will restart.')) return;
  const btn = document.getElementById('applyPacUpdateBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  try {
    const r = await fetch('/v1/updates/apply?restart_after_update=true', {method:'POST'});
    const d = await r;
    if (d.ok) {
      const diffInfo = d.local_diff;
      const diffApplied = d.diff_applied;
      let msg = 'Update applied. PAC will restart shortly.';
      if (diffInfo && !diffInfo.skipped && diffInfo.ok && diffApplied && diffApplied.ok) {
        msg = 'Update applied. PAC will restart shortly.\n\nLocal modifications were preserved and reapplied automatically (' + (diffApplied.applied_count || 0) + ' file(s) patched).';
      } else if (diffInfo && !diffInfo.skipped && diffInfo.ok && diffApplied && !diffApplied.ok) {
        const failed = (diffApplied.failed_files || []).slice(0, 5);
        msg = 'Update applied, but local modifications could not be fully reapplied:\n\n' + failed.map(function(f) { return '  - ' + f; }).join('\n') + '\n\nYour local changes are preserved in updates/local-patches/. You can manually resolve the conflicts or contact support.';
        alert(msg);
        return;
      } else if (diffInfo && !diffInfo.skipped && !diffInfo.ok) {
        msg = 'Update applied. PAC will restart shortly.\n\nWarning: local diff generation failed: ' + (diffInfo.error || 'unknown error') + '. Your local modifications were not saved.';
      }
      alert(msg);
    } else {
      alert('Update failed: ' + (d.error || 'unknown error'));
      if (btn) { btn.disabled = false; btn.textContent = 'Update & restart'; }
    }
  } catch(e) { alert('Update request failed: ' + e); if (btn) { btn.disabled = false; btn.textContent = 'Update & restart'; } }
}

if (document.getElementById('loadLmStudioModel')) loadLmStudioModel.onclick=()=>loadLmStudioModelFromForm().catch(e=>paneError('LM Studio load failed', e.message));
if (document.getElementById('unloadLmStudioModel')) unloadLmStudioModel.onclick=()=>unloadLmStudioModelFromForm().catch(e=>paneError('LM Studio unload failed', e.message));
if (document.getElementById('inspectLmStudioModel')) inspectLmStudioModel.onclick=()=>inspectLmStudioModelFromForm().catch(e=>paneError('LM Studio inspect failed', e.message));
if (document.getElementById('runnerTools')) runnerTools.addEventListener('change', updateRunnerToolPackagePreview);
document.querySelectorAll('[data-source-root]').forEach(btn => btn.addEventListener('click', () => renderSources(btn.dataset.sourceRoot || '')));
const inspectFeaturePackBtn = document.getElementById('inspectFeaturePack'); if (inspectFeaturePackBtn) inspectFeaturePackBtn.addEventListener('click', inspectFeaturePack);
const applyFeaturePackBtn = document.getElementById('applyFeaturePack'); if (applyFeaturePackBtn) applyFeaturePackBtn.addEventListener('click', applyFeaturePack);
document.querySelectorAll('[data-source-open]').forEach(btn => btn.addEventListener('click', () => { switchToTab('sources-tab'); openSourceFile(btn.dataset.sourceOpen || ''); renderSources((btn.dataset.sourceOpen || '').split('/').slice(0,-1).join('/')); }));
const saveSourceBtn = document.getElementById('saveSourceFile');
if (saveSourceBtn) saveSourceBtn.onclick = () => saveSourceFile();
const sourceEditorInput = document.getElementById('sourceEditor');
if (sourceEditorInput) {
  sourceEditorInput.addEventListener('input', () => {
    if (!selectedSourcePath) return;
    const state = sourceFileState.get(selectedSourcePath) || {saved:'', content:''};
    state.content = sourceEditorInput.value;
    state.dirty = state.content !== (state.saved || '');
    sourceFileState.set(selectedSourcePath, state);
    renderSourceTabs();
    updateSourceDirtyTreeMarkers();
  });
  sourceEditorInput.addEventListener('keydown', (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 's') { ev.preventDefault(); saveSourceFile().catch(e=>paneError('Source file could not be saved', e.message)); }
  });
}

/* === Model Balancer Skill === */
window.__modelScores = {};

function computeSpeedScore(modelName) {
  // Returns null if no data, or 0-100 score
  const sessions = window.__activeSessions || [];
  const used = sessions.filter(s => s.model === modelName);
  if (!used.length) return null;
  // Use average session duration as proxy for performance
  // For now, use endpoint responsiveness as a proxy
  const m = (config.models || {})[modelName];
  if (!m) return null;
  const p = (config.providers || {})[m.provider];
  if (!p) return null;
  // If provider is LM Studio and it's loaded, we consider it optimal
  if (p.type === 'lmstudio') {
    return p.status === 'connected' ? 85 : 40;
  }
  // For API providers, assume reasonable performance
  return 75;
}

function computeConfigScore(modelName) {
  const m = (config.models || {})[modelName];
  if (!m) return null;
  let score = 100;
  const issues = [];

  // Context window check
  const ctx = m.context_window || 4096;
  if (ctx > 128000) score -= 10; // unrealistically high

  // Check LM Studio settings if applicable
  const lm = (m.extra || {}).lmstudio_runtime || m;
  const p = (config.providers || {})[m.provider];
  if (p?.type === 'lmstudio') {
    // GPU offload is critical for performance
    if (lm.gpu_offload == null || lm.gpu_offload === 0) {
      score -= 25;
      issues.push('GPU offload not set');
    }
    // Flash attention recommendation
    if (!lm.flash_attention) {
      score -= 15;
      issues.push('Flash attention disabled');
    }
    // Batch size
    if (lm.eval_batch_size && lm.eval_batch_size > 1024) {
      score -= 5; // potentially too high for consumer GPU
    }
    // Context length alignment
    if (lm.context_length && ctx && lm.context_length < ctx) {
      score -= 10;
      issues.push('Load context shorter than configured window');
    }
  }

  // Capabilities check - missing important capabilities isn't an issue but
  // the presence of them is good
  const caps = m.capabilities || {};
  if (!caps.supports_streaming) { score -= 5; }

  return Math.max(0, score);
}

function refreshModelScores() {
  const models = Object.keys(config.models || {});
  const scores = {};
  let hasRecommendation = false;
  for (const name of models) {
    const ss = computeSpeedScore(name);
    const cs = computeConfigScore(name);
    scores[name] = { speed_score: ss, config_score: cs };
    if (cs !== null && cs < 70) hasRecommendation = true;
  }
  window.__modelScores = scores;

  // Update recommendations panel
  const panel = document.getElementById('models-recommendations-panel');
  const body = document.getElementById('models-recommendations-body');
  if (panel && body) {
    const recs = Object.entries(scores).filter(([name, s]) => s.config_score !== null && s.config_score < 70);
    if (recs.length && hasRecommendation) {
      const html = recs.map(([name, s]) => {
        const m = (config.models || {})[name] || {};
        const p = (config.providers || {})[m.provider] || {};
        const lm = (m.extra || {}).lmstudio_runtime || m;
        const issues = [];
        if (p?.type === 'lmstudio') {
          if (!lm.gpu_offload) issues.push('Enable GPU offload');
          if (!lm.flash_attention) issues.push('Enable flash attention');
          if (lm.context_length && m.context_window && lm.context_length < m.context_window) issues.push('Load context shorter than configured context window');
        }
        return `<div class="models-recommendation-item">
          <span class="recommendation-icon">&#9888;</span>
          <div class="recommendation-text">
            <strong>${escapeHtml(name)}</strong> — config score ${s.config_score}/100
            ${issues.length ? '<p>' + issues.map(i => escapeHtml(i)).join(', ') + '</p>' : '<p>Review LM Studio load settings for this model.</p>'}
          </div>
        </div>`;
      }).join('');
      body.innerHTML = html;
      panel.hidden = false;
    } else {
      panel.hidden = true;
    }
  }

  // Re-render model cards to show updated score dots
  if (document.getElementById('models-configured')) renderModels();
}

// Poll model scores every 60 seconds
window.__modelScoreTimer = null;
function startModelScorePolling() {
  if (window.__modelScoreTimer) clearInterval(window.__modelScoreTimer);
  refreshModelScores();
  window.__modelScoreTimer = setInterval(refreshModelScores, 60000);
}

/* === End Model Balancer Skill === */

const sourceMenuBtn = document.getElementById('sourceFileMenuButton');
const sourceMenu = document.getElementById('sourceFileMenu');
if (sourceMenuBtn && sourceMenu) {
  sourceMenuBtn.onclick = (ev) => { ev.stopPropagation(); sourceMenu.hidden = !sourceMenu.hidden; };
  sourceMenu.onclick = ev => ev.stopPropagation();
  document.addEventListener('click', () => { sourceMenu.hidden = true; });
}
const sourceMenuSave = document.getElementById('sourceMenuSave');
if (sourceMenuSave) sourceMenuSave.onclick = () => saveSourceFile().catch(e=>paneError('Source file could not be saved', e.message));
const sourceMenuSaveAll = document.getElementById('sourceMenuSaveAll');
if (sourceMenuSaveAll) sourceMenuSaveAll.onclick = () => saveAllSourceFiles().catch(e=>paneError('Source files could not be saved', e.message));
const newSourceFileBtn = document.getElementById('newSourceFile');
if (newSourceFileBtn) newSourceFileBtn.onclick = () => createSourceEntry('file').catch(e=>paneError('Source file could not be created', e.message));
const newSourceFolderBtn = document.getElementById('newSourceFolder');
if (newSourceFolderBtn) newSourceFolderBtn.onclick = () => createSourceEntry('dir').catch(e=>paneError('Source folder could not be created', e.message));
const renameSourceBtn = document.getElementById('renameSourceEntry');
if (renameSourceBtn) renameSourceBtn.onclick = () => renameSelectedSourceEntry().catch(e=>paneError('Source entry could not be renamed', e.message));
const deleteSourceBtn = document.getElementById('deleteSourceEntry');
if (deleteSourceBtn) deleteSourceBtn.onclick = () => deleteSelectedSourceEntry().catch(e=>paneError('Source entry could not be deleted', e.message));
if (document.getElementById('saveTool')) saveTool.onclick=()=>saveToolFromForm().catch(e=>paneError('Tool save failed', e.message));
if (document.getElementById('saveProfile')) saveProfile.onclick=()=>saveProfileFromForm().catch(e=>paneError('Profile save failed', e.message));
if (document.getElementById('deleteProfile')) document.getElementById('deleteProfile').onclick=()=>deleteProfileFromForm().catch(e=>paneError('Profile delete failed', e.message));
if (document.getElementById('openProfileModal')) openProfileModal.onclick=()=>openProfileModal();
if (document.getElementById('closeProfileModal')) { const btn = document.getElementById('closeProfileModal'); btn.addEventListener('click', () => closeProfileModal()); }
const profileModalEl = document.getElementById('profileModal');
if (profileModalEl) profileModalEl.onclick = (ev) => { if (ev.target === profileModalEl) closeProfileModal(); };

if(document.getElementById('openWorkspaceModal'))document.getElementById('openWorkspaceModal').onclick=()=>openWorkspaceModal();
if(document.getElementById('closeWorkspaceModal'))document.getElementById('closeWorkspaceModal').onclick=()=>closeWorkspaceModal();
if(document.getElementById('saveWorkspace'))document.getElementById('saveWorkspace').onclick=saveWorkspaceFromForm;
if(document.getElementById('deleteWorkspace'))document.getElementById('deleteWorkspace').onclick=deleteWorkspaceFromForm;
if (document.getElementById('saveWorkspace')) saveWorkspace.onclick=()=>saveWorkspaceFromForm().catch(e=>paneError('Workspace save failed', e.message));
if (document.getElementById('deleteProfile')) deleteProfile.onclick=()=>deleteProfileFromForm().catch(e=>paneError('Profile delete failed', e.message));
if (document.getElementById('deleteWorkspace')) deleteWorkspace.onclick=()=>deleteWorkspaceFromForm().catch(e=>paneError('Workspace delete failed', e.message));
if (document.getElementById('deleteTool')) deleteTool.onclick=()=>deleteToolFromForm().catch(e=>paneError('Tool delete failed', e.message));
if (document.getElementById('uploadStagePackage')) uploadStagePackage.onclick=()=>uploadStagePackageFromForm().catch(e=>{ showInline('stagePackageResult', `Failed: ${e.message}`); paneError('Package upload failed', e.message); });
if (document.getElementById('restartPac')) restartPac.onclick=()=>restartPacFromForm().catch(e=>{ showInline('stagePackageResult', `Failed: ${e.message}`); paneError('Restart request failed', e.message); });
if (document.getElementById('refreshTlsStatus')) refreshTlsStatus.onclick=()=>loadTlsStatus().catch(e=>paneError('TLS status failed', e.message));
if (document.getElementById('setHostService')) setHostService.onclick=()=>setServiceMode('host').catch(e=>paneError('Service mode change failed', e.message));
if (document.getElementById('setUserService')) setUserService.onclick=()=>setServiceMode('user').catch(e=>paneError('Service mode change failed', e.message));

async function saveProviderFromForm() {
  if (!providerName.value.trim()) return alert('Provider name is required');
  config.providers = config.providers || {};
  let providerBase = providerBaseUrl.value.trim();
  if ((providerType.value === 'lmstudio' || providerType.value === 'vllm') && providerBase && !providerBase.replace(/\/$/, '').endsWith('/v1')) providerBase = providerBase.replace(/\/$/, '') + '/v1';
  if ((providerType.value === 'anthropic-compatible' || providerType.value === 'minimax') && providerBase && !providerBase.replace(/\/$/, '').endsWith('/v1')) providerBase = providerBase.replace(/\/$/, '') + '/v1';
  const pname = providerName.value.trim();
  const existing = config.providers?.[pname] || {};
  config.providers[pname] = {
    ...existing,
    type: providerType.value,
    base_url: providerBase || null,
    api_key_env: providerApiKeyEnv.value.trim() || null,
    api_key: providerApiKey.value.trim() || null,
    timeout_seconds: Number(providerTimeout.value || 30),
    default_headers: existing.default_headers || {},
    enabled: existing.enabled ?? false,
    status: existing.status || 'disabled',
    runtime: collectProviderRuntimeFields(existing.runtime || {}),
  };
  await persistConfigAndReload('providerFormResult', `Saved provider ${providerName.value.trim()}`);
  setModalStatus('providerModalStatus', 'Saved');
}
async function saveModelFromForm() {
  if (!modelName.value.trim()) return alert('Model name is required');
  if (!modelProvider.value) return alert('Provider is required');
  config.models = config.models || {};
  config.models[modelName.value.trim()] = {
    provider: modelProvider.value,
    model: modelId.value.trim() || null,
    runs_on: modelRunsOn.value.trim() || null,
    context_window: Number(modelContextWindow.value || 4096),
    max_output_tokens: Number(modelMaxOutput.value || 1024),
    format: document.getElementById('modelFormat')?.value || 'chat',
    architecture: document.getElementById('modelArchitecture')?.value.trim() || null,
    parameter_count: document.getElementById('modelParameterCount')?.value.trim() || null,
    capabilities: {
      supports_chat: true,
      supports_tools: false,
      supports_vision: !!modelSupportsVision.checked,
      supports_json: !!modelSupportsJson.checked,
      supports_streaming: !!modelSupportsStreaming.checked,
      supports_reasoning: !!document.getElementById('modelSupportsReasoning')?.checked,
      supports_tool_use: !!document.getElementById('modelSupportsToolUse')?.checked,
      supports_agentic: !!document.getElementById('modelSupportsAgentic')?.checked,
      supports_coding: !!document.getElementById('modelSupportsCoding')?.checked,
      supports_function_calling: !!document.getElementById('modelSupportsFunctionCalling')?.checked,
      reasoning: document.getElementById('modelSupportsReasoning')?.checked ? 'chain_of_thought' : 'none'
    },
    extra: currentModelProvider()?.type === 'lmstudio' ? {lmstudio_runtime: collectLmStudioRuntimeFields()} : {},
  };
  const savedName = modelName.value.trim();
  await persistConfigAndReload(null, null);
  showInline('modelFormResult', {model: savedName, provider: modelProvider.value, model_id: modelId.value.trim() || null, preferred_endpoint: modelRunsOn.value.trim() || null});
  setModalStatus('modelModalStatus', 'Saved');
}
async function saveProfileFromForm() {
  const name = profileName.value.trim();
  if (!name) return alert('Profile name is required');
  if (!profileModel.value || !config.models?.[profileModel.value]) return alert('Choose an existing configured model first');
  const body = {
    description: `Session preset for ${profileModel.value}`,
    model: profileModel.value,
    context_profile: profileContextProfile.value || null,
    context_mode: profileContextMode.value || 'medium',
    permission_profile: profilePermission.value || 'ask-first',
    tools: selectedToolNames(),
    system_prompt: profileSystemPrompt.value.trim() || 'You are a careful remote coding and infrastructure agent.',
    workspace: profileWorkspace.value || null,
    max_runtime_minutes: parseInt(profileMaxRuntime.value) || 60,
  };
  const r = await api(`/v1/agent-profiles/${encodeURIComponent(name)}`,{method:'PUT',body:JSON.stringify(body)});
  config.agent_profiles = config.agent_profiles || {}; config.agent_profiles[name] = r;
  await loadConfig();
  showInline('profileFormResult', `Saved profile ${name}`);
  closeProfileModal();
}
async function deleteProfileFromForm() {
  const name = profileName.value.trim();
  if (!name || !config.agent_profiles?.[name]) return alert('Select an existing profile first');
  if (!confirm(`Delete profile ${name}?`)) return;
  await api(`/v1/agent-profiles/${encodeURIComponent(name)}`,{method:'DELETE'});
  await loadConfig();
  showInline('profileFormResult', `Deleted profile ${name}`);
  closeProfileModal();
}
async function saveToolFromForm() {
  if (!toolName.value.trim()) return alert('Tool name is required');
  config.tools = config.tools || {};
  config.tools[toolName.value.trim()] = {
    enabled: !!toolEnabled.checked,
    description: toolDescription.value.trim() || null,
    approval_required_patterns: csv(toolApprovalPatterns.value),
    binaries: csv(toolBinaries.value),
    socket: toolSocket.value.trim() || null,
    package: document.getElementById('toolPackage')?.value || null,
    install_hint: document.getElementById('toolInstallHint')?.value.trim() || null,
  };
  await persistConfigAndReload('toolFormResult', `Saved tool ${toolName.value.trim()}`);
}
async function deleteToolFromForm() {
  const name = toolName.value.trim();
  if (!name || !config.tools?.[name]) return alert('Select an existing tool first');
  if (!confirm(`Delete tool ${name}? Profiles using it may need updates.`)) return;
  delete config.tools[name];
  await persistConfigAndReload('toolFormResult', `Deleted tool ${name}`);
}
async function connectProviderFromForm() {
  await saveProviderFromForm();
  const name = providerName.value.trim();
  const r = await api(`/v1/providers/${name}/toggle`,{method:'POST', body:JSON.stringify({enabled:true})});
  await loadConfig();
  showInline('providerFormResult', r);
  if (r.synced_models?.length) showInline('modelFormResult', {provider:name, synced_models:r.synced_models, count:r.synced_models.length});
}

async function ensureModelSavedForLmStudio() {
  await saveModelFromForm();
  const name = modelName.value.trim();
  const provider = config.providers?.[modelProvider.value];
  if (!provider || provider.type !== 'lmstudio') throw new Error('This model is not backed by an LM Studio provider.');
  return name;
}
async function loadLmStudioModelByName(name) {
  const m = config.models?.[name];
  if (!m) throw new Error('Model not found');
  const runtime = m.extra?.lmstudio_runtime || {};
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/load`, {method:'POST', body:JSON.stringify({model:m.model, ...runtime})});
  showInline('modelFormResult', {model:name, lmstudio_load:r});
  await loadGlobalEvents(true).catch(()=>{});
  return r;
}
async function loadLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const runtime = collectLmStudioRuntimeFields();
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/load`, {method:'POST', body:JSON.stringify({model:modelId.value.trim(), ...runtime})});
  showInline('modelFormResult', {model:name, lmstudio_load:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio load requested' : 'LM Studio load failed');
  await loadGlobalEvents(true).catch(()=>{});
}
async function unloadLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const instance_id = prompt('Instance id / loaded model id to unload', modelId.value.trim() || name);
  if (!instance_id) return;
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id})});
  showInline('modelFormResult', {model:name, lmstudio_unload:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio unload requested' : 'LM Studio unload failed');
  await loadGlobalEvents(true).catch(()=>{});
}
async function inspectLmStudioModelFromForm() {
  const name = await ensureModelSavedForLmStudio();
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/inspect`);
  showInline('modelFormResult', {model:name, lmstudio:r});
  setModalStatus('modelModalStatus', r.ok ? 'LM Studio server reachable' : 'LM Studio inspect failed');
}

async function testModelFromForm() {
  await saveModelFromForm();
  const name = modelName.value.trim();
  const r = await api(`/v1/models/${name}/test`,{method:'POST'});
  showInline('modelFormResult', {model:name, ...r});
}


function scheduleHiddenReloadAfterRestart(seconds = 18) {
  window.__pacRestartReloadTimer = window.__pacRestartReloadTimer || null;
  if (window.__pacRestartReloadTimer) clearTimeout(window.__pacRestartReloadTimer);
  const result = document.getElementById('stagePackageResult');
  if (result) result.textContent += `

PAC is restarting. This page will refresh automatically in ${seconds} seconds.`;
  window.__pacRestartReloadTimer = setTimeout(() => window.location.reload(), seconds * 1000);
}

async function uploadStagePackageFromForm() {
  const input = document.getElementById('stagePackageFile');
  const result = document.getElementById('stagePackageResult');
  if (!input || !input.files || !input.files[0]) return alert('Choose a PAC package (.pac or .zip) first');
  const fd = new FormData();
  fd.append('file', input.files[0]);
  const apply = document.getElementById('stageApplyNow')?.checked !== false;
  const restartAfterUpdate = true;
  result.textContent = 'Uploading package...';
  const _token = localStorage.getItem('pac_auth_token') || '';
  let r = await fetch(`/v1/admin/stage-package?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
    method: 'POST',
    headers: { ...(_token ? {'Authorization': `Bearer ${_token}`} : {}) },
    body: fd,
  });
  if (r.status === 404) {
    result.textContent = 'Primary upload endpoint returned 404; retrying compatibility endpoint...';
    r = await fetch(`/v1/update/upload?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
      method: 'POST',
      headers: { ...(_token ? {'Authorization': `Bearer ${_token}`} : {}) },
      body: fd,
    });
  }
  const text = await r.text();
  if (!r.ok) throw new Error(`${r.status}: ${text}`);
  let payload;
  try { payload = JSON.parse(text); } catch { payload = text; }
  let diffMsg = '';
  if (typeof payload === 'object' && payload.local_diff && !payload.local_diff.skipped && payload.diff_applied) {
    const di = payload.local_diff;
    const da = payload.diff_applied;
    if (di.ok && da.ok) {
      diffMsg = `  Local modifications preserved and reapplied (${da.applied_count || 0} file(s) patched).`;
    } else if (di.ok && !da.ok) {
      diffMsg = `  Warning: local modifications could not be reapplied: ${(da.failed_files || []).slice(0,3).join(', ')}. Your changes are saved in updates/local-patches/.`;
    } else if (!di.ok) {
      diffMsg = `  Warning: local diff could not be saved: ${di.error || 'unknown'}. Your modifications may be overwritten.`;
    }
  }
  const baseMsg = typeof payload === 'string' ? payload : (payload.message || payload.status || 'Package uploaded. Details are in Events.');
  result.textContent = diffMsg ? baseMsg + '\n' + diffMsg : baseMsg;
  if (typeof payload !== 'string') emitUiEvent('package_upload_completed', result.textContent, payload);
  if (apply && payload && typeof payload === 'object' && payload.restart_scheduled) scheduleHiddenReloadAfterRestart(18);
  await loadGlobalEvents(true).catch(()=>{});
}
async function restartPacFromForm() {
  if (!confirm('Restart PAC now? If this was started manually, it will exit and you must start it again.')) return;
  const result = document.getElementById('stagePackageResult');
  result.textContent = 'Restart requested...';
  const r = await api('/v1/admin/restart', {method:'POST'});
  result.textContent = r.message || r.status || 'Restart requested. Details are in Events.'; emitUiEvent('pac_restart_requested', result.textContent, r);
  scheduleHiddenReloadAfterRestart(18);
}



async function loadMcpBuildStatus() {
  const box = document.getElementById('mcpBuildStatus');
  if (!box) return;
  try {
    const status = await api('/v1/mcp/build/status');
    const artifacts = status.artifacts || [];
    const links = artifacts.map(a => `<li><a href="${a.download_url}" download>${a.name}</a> <span class="muted">(${a.size || 0} bytes)</span></li>`).join('');
    box.innerHTML = `<b>Status:</b> ${status.status || 'unknown'}<br><b>Message:</b> ${escapeHtml(status.message || '')}<br><b>Version:</b> ${status.version || ''}${artifacts.length ? `<br><b>Downloads:</b><ul>${links}</ul>` : '<br><span class="muted">No binaries available yet.</span>'}<br><span class="muted">Build details are recorded in Events.</span>`;
  } catch (e) {
    box.textContent = 'Could not load Zed binary status: ' + e.message;
  }
}
async function buildMcpBridgeFromUi() {
  switchToTab('sources-tab');
  await renderSources('binaries/zed-binary');
  selectedSourceFolder = 'binaries/zed-binary';
  updateSourceActions();
  await buildSelectedBinarySource();
}




const binaryFolderFilter = document.getElementById('binaryFolderFilter');
if (binaryFolderFilter) binaryFolderFilter.onchange = () => {
  selectedBinaryArtifactFilter = binaryFolderFilter.value || '';
  loadSourceBinaryArtifacts(selectedBinaryArtifactFilter).catch(e=>paneError('Binary downloads unavailable', e.message));
};

const openDownloadsModalBtn = document.getElementById('openDownloadsModal');
const downloadsModal = document.getElementById('downloadsModal');
const closeDownloadsModalBtn = document.getElementById('closeDownloadsModal');
if (openDownloadsModalBtn && downloadsModal) openDownloadsModalBtn.onclick = async () => { downloadsModal.hidden = false; await loadSourceBinaryArtifacts(selectedBinaryArtifactFilter || '').catch(e=>paneError('Downloads unavailable', e.message)); };
if (closeDownloadsModalBtn && downloadsModal) closeDownloadsModalBtn.onclick = () => { downloadsModal.hidden = true; };
if (downloadsModal) downloadsModal.onclick = (ev) => { if (ev.target === downloadsModal) downloadsModal.hidden = true; };

const openProviderBtn = document.getElementById('openProviderModal');
if (openProviderBtn) openProviderBtn.onclick = () => openProviderModal();
const closeProviderBtn = document.getElementById('closeProviderModal');
if (closeProviderBtn) closeProviderBtn.onclick = closeProviderModal;
const openModelBtn = document.getElementById('openModelModal');
if (openModelBtn) openModelBtn.onclick = () => openModelModal();
const closeModelBtn = document.getElementById('closeModelModal');
if (closeModelBtn) closeModelBtn.onclick = closeModelModal;
const showUnconfigBtn = document.getElementById('showUnconfigModels');
if (showUnconfigBtn) showUnconfigBtn.onclick = () => toggleUnconfiguredModels();
const closeUnconfigBtn = document.getElementById('closeUnconfigModels');
if (closeUnconfigBtn) closeUnconfigBtn.onclick = () => closeUnconfigModels();

const openSessionBtn = document.getElementById('openSessionModal');
if (openSessionBtn) openSessionBtn.onclick = openSessionModal;
const dashboardNewSessionBtn = document.getElementById('dashboardNewSession');
if (dashboardNewSessionBtn) dashboardNewSessionBtn.onclick = () => { switchToTab('sessions-tab'); openSessionModal(); };
const closeSessionBtn = document.getElementById('closeSessionModal');
if (closeSessionBtn) closeSessionBtn.onclick = closeSessionModal;
const sessionModal = document.getElementById('sessionModal');
if (sessionModal) sessionModal.onclick = (ev) => { if (ev.target === sessionModal) closeSessionModal(); };
const dashboardRefreshBtn = document.getElementById('dashboardRefreshMetrics');
if (dashboardRefreshBtn) dashboardRefreshBtn.onclick = () => loadDashboardMetrics();

async function refreshDashboardMetricsOnStartup() {
  for (const delay of [0, 300, 900, 1800, 3500]) {
    setTimeout(() => loadDashboardMetrics().catch(e => { if (delay === 0) paneError('Dashboard metrics could not load', e.message || String(e)); }), delay);
  }
}
async function checkSourceOnlineUpdates(){
  const status = document.getElementById('sourceUpdateStatus');
  const box = document.getElementById('sourceOnlineUpdates');
  if (status) status.textContent = 'Checking pac-labs/packages…';
  if (box) box.innerHTML = '<div class="muted">Checking online source module repository…</div>';
  const result = await runWithPaneError(() => api('/v1/sources/online-updates'), 'Source module update check failed');
  if (!result) return;
  if (status) status.textContent = result.ok ? `${result.update_count || 0} update(s) available` : 'check failed';
  renderSourceOnlineUpdates(result);
  emitUiEvent(result.ok ? 'source_online_updates_checked' : 'source_online_updates_failed', result.ok ? `Source module updates checked: ${result.update_count || 0} available` : 'Source module update check failed', result);
}

function renderSourceOnlineUpdates(result){
  const box = document.getElementById('sourceOnlineUpdates');
  if (!box) return;
  if (!result.ok) {
    box.innerHTML = `<div class="pack-summary warn-summary">Could not check source modules</div><div class="muted small-text">${escapeHtml(result.error || 'Unknown error')}</div>`;
    return;
  }
  const updates = result.updates || [];
  const repo = result.repository || 'pac-labs/packages';
  const checked = result.checked_at ? new Date(result.checked_at).toLocaleString() : 'now';
  if (!updates.length) {
    box.innerHTML = `<div class="pack-summary strong-summary">Source modules are current</div><div class="muted small-text">Checked ${escapeHtml(repo)} at ${escapeHtml(checked)}.</div>`;
    return;
  }
  const rows = updates.map(u => `<tr><td><code>${escapeHtml(u.source_path || u.id || '-')}</code><div class="muted small-text">${escapeHtml(u.description || '')}</div></td><td>${escapeHtml(u.local_version || 'not installed')}</td><td>${escapeHtml(u.remote_version || result.packages_version || 'latest')}</td><td><span class="pill ${u.status === 'new' ? 'ok-pill' : 'warn-pill'}">${escapeHtml(u.status || 'update')}</span></td></tr>`).join('');
  box.innerHTML = `<div class="pack-summary strong-summary">${updates.length} source module update(s) available</div><div class="muted small-text">Checked ${escapeHtml(repo)} at ${escapeHtml(checked)}. Apply by downloading/importing the packages release or seed zip.</div><table class="compact-table"><thead><tr><th>Module</th><th>Local</th><th>Online</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}


async function showSetupModal() {
  return new Promise(async (resolve) => {
    const existing = document.getElementById('setupModal');
    if (existing) existing.remove();
    const appShell = document.querySelector('.app-shell');
    if (appShell) appShell.style.display = 'none';

    const overlay = document.createElement('div');
    overlay.id = 'setupModal';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:#050508;backdrop-filter:blur(6px)';

    const card = document.createElement('div');
    card.style.cssText = 'background:#0f1526;border:1px solid rgba(139,92,246,.4);border-radius:16px;padding:2.5rem;max-width:400px;width:90%;box-shadow:0 24px 64px rgba(0,0,0,.6)';
    card.innerHTML = '<div style=text-align:center;margin-bottom:2rem><div style=font-size:1.6rem;font-weight:800;color:#fff;letter-spacing:.05em;margin-bottom:.4rem>PAC Control</div><div style=font-size:.82rem;color:#8b7fc4;text-transform:uppercase;letter-spacing:.12em>Initial Setup</div></div><div style=color:#c4b8e8;font-size:.88rem;margin-bottom:1.5rem;text-align:center>No users found. Create your admin account to get started.</div><div id=setupError style=color:#f87171;font-size:.8rem;margin-bottom:.6rem;text-align:center;min-height:1.2em></div><div class=form-grid style=gap:.7rem><label style=color:#a89ed4;font-size:.78rem>Username<input id=setupUsername placeholder=admin style=background:rgba(10,8,22,.7);border:1px solid rgba(139,92,246,.3);border-radius:8px;padding:.5rem .65rem;color:#fff;font-size:.9rem;width:100%;box-sizing:border-box /></label><label style=color:#a89ed4;font-size:.78rem>Display name<input id=setupDisplayName placeholder="Admin User" style=background:rgba(10,8,22,.7);border:1px solid rgba(139,92,246,.3);border-radius:8px;padding:.5rem .65rem;color:#fff;font-size:.9rem;width:100%;box-sizing:border-box /></label><label style=color:#a89ed4;font-size:.78rem>Password<input id=setupPassword type=password placeholder="min 8 characters" style=background:rgba(10,8,22,.7);border:1px solid rgba(139,92,246,.3);border-radius:8px;padding:.5rem .65rem;color:#fff;font-size:.9rem;width:100%;box-sizing:border-box /></label><label style=color:#a89ed4;font-size:.78rem>Confirm password<input id=setupPassword2 type=password placeholder=repeat style=background:rgba(10,8,22,.7);border:1px solid rgba(139,92,246,.3);border-radius:8px;padding:.5rem .65rem;color:#fff;font-size:.9rem;width:100%;box-sizing:border-box /></label></div><button id=doSetupBtn style=margin-top:1.2rem;width:100%;padding:.65rem;background:rgba(109,69,214,.8);border:1px solid rgba(139,92,246,.6);border-radius:8px;color:#fff;font-weight:700;font-size:.9rem;cursor:pointer>Create admin account</button>';

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    async function doSetup() {
      const username = document.getElementById('setupUsername').value.trim();
      const display_name = document.getElementById('setupDisplayName').value.trim() || username;
      const password = document.getElementById('setupPassword').value;
      const password2 = document.getElementById('setupPassword2').value;
      const errorEl = document.getElementById('setupError');
      if (!username || !password) { errorEl.textContent = 'username and password required'; return; }
      if (password !== password2) { errorEl.textContent = 'Passwords do not match'; return; }
      if (password.length < 8) { errorEl.textContent = 'Password must be at least 8 characters'; return; }
      try {
        const r = await fetch('/v1/auth/setup', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username, password, display_name})});
        const data = await r.json();
        if (!r.ok) { errorEl.textContent = data.detail || 'Setup failed'; return; }
        setStoredToken(data.token);
        showUserChip(data.user);
        overlay.remove();
        await loadConfig();
        await updateUserChip();
        await loadSessions(); await loadApprovals(); await loadRunners();
    // Auto-select pi.dev session on startup
    setTimeout(async () => {
      const sessions = await api('/v1/sessions');
      const piDev = sessions.find(s => (s.metadata && s.metadata.agent_profile === 'main-pi-dev') || (s.agent_profile || '').includes('main-pi-dev'));
      if (piDev && !selectedSession) selectSession(piDev.id);
    }, 300);
        refreshDashboardMetricsOnStartup();
        await loadGlobalEvents(true);
        loadMcpBuildStatus().catch(()=>{});
        await loadBinaryFolderFilters().catch(()=>{});
        await loadSourceBinaryArtifacts().catch(()=>{});
        updateSourceActions();
        resolve();
      } catch(e) { errorEl.textContent = e.message || String(e); }
    }

    document.getElementById('doSetupBtn').addEventListener('click', doSetup);
    document.getElementById('setupPassword2').addEventListener('keydown', e => { if (e.key === 'Enter') doSetup(); });
    document.getElementById('setupUsername').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('setupPassword').focus(); });
  });
}


async function showLoginModal() {
  const appShell = document.querySelector('.app-shell');
  if (appShell) appShell.style.display = 'none';
  const existing = document.getElementById('loginModal');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'loginModal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:#050508;';
  const card = document.createElement('div');
  card.style.cssText = 'background:#0a0a14;border:1px solid #1a1a2e;border-radius:12px;padding:2.5rem;max-width:380px;width:90%;box-shadow:0 16px 48px rgba(0,0,0,.7)';
  card.innerHTML = '<div style=text-align:center;margin-bottom:2rem><div style=font-size:1.4rem;font-weight:700;color:#e8e6f0;letter-spacing:.03em;margin-bottom:.3rem>PAC Control</div><div style=font-size:.78rem;color:#5a5478;text-transform:uppercase;letter-spacing:.1em>Sign in</div></div><div id=loginError style=color:#e06060;font-size:.82rem;margin-bottom:.8rem;text-align:center;min-height:1.2em></div><div class=form-grid style=gap:.6rem><label style=color:#8880a0;font-size:.8rem>Username<input id=loginUsername autocomplete=username style=background:rgba(10,10,20,.8);border:1px solid #2a2a4e;border-radius:6px;padding:.55rem .7rem;color:#e8e6f0;font-size:.9rem;width:100%;box-sizing:border-box /></label><label style=color:#8880a0;font-size:.8rem>Password<input id=loginPassword type=password autocomplete=current-password style=background:rgba(10,10,20,.8);border:1px solid #2a2a4e;border-radius:6px;padding:.55rem .7rem;color:#e8e6f0;font-size:.9rem;width:100%;box-sizing:border-box /></label></div><button id=doLoginBtn style=margin-top:1.3rem;width:100%;padding:.65rem;background:#3a2f7a;border:1px solid #4a3f8a;border-radius:6px;color:#c4b8ff;font-weight:600;font-size:.9rem;cursor:pointer>Sign in</button>';
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  const btn = document.getElementById('doLoginBtn');
  btn.onclick = async function() {
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errorEl = document.getElementById('loginError');
    btn.disabled = true; btn.textContent = 'Signing in…';
    try {
      const r = await fetch('/v1/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username, password})});
      const data = await r.json();
      if (!r.ok || !data.ok) { throw new Error(data.error || 'Login failed'); }
      setStoredToken(data.token);
      localStorage.setItem('pac_user', JSON.stringify(data.user));
      const modal = document.getElementById('loginModal');
      if (modal) modal.remove();
      const shell = document.querySelector('.app-shell');
      if (shell) shell.style.display = '';
      showUserChip(data.user);
      await loadConfig();
      await loadSessions(); await loadApprovals(); await loadRunners();
    // Auto-select pi.dev session on startup
    setTimeout(async () => {
      const sessions = await api('/v1/sessions');
      const piDev = sessions.find(s => (s.metadata && s.metadata.agent_profile === 'main-pi-dev') || (s.agent_profile || '').includes('main-pi-dev'));
      if (piDev && !selectedSession) selectSession(piDev.id);
    }, 300);
      refreshDashboardMetricsOnStartup();
      await loadGlobalEvents(true);
      loadMcpBuildStatus().catch(()=>{});
      await loadBinaryFolderFilters().catch(()=>{});
      await loadSourceBinaryArtifacts().catch(()=>{});
      updateSourceActions();
    } catch(e) {
      errorEl.textContent = e.message || 'Login failed';
      btn.disabled = false; btn.textContent = 'Sign in';
    }
  };
  document.getElementById('loginPassword').addEventListener('keydown', e => { if (e.key === 'Enter') btn.onclick(); });
  document.getElementById('loginUsername').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('loginPassword').focus(); });
}

async function init(){
  // Check authentication first — if not logged in, show login and return
  try {
    // Support legacy pac_token key for backwards compatibility
    const legacy = localStorage.getItem('pac_token');
    if (legacy && !getStoredToken()) { setStoredToken(legacy); }
    
    const token = getStoredToken();
    if (!token) {
      await showLoginModal();
      return;
    }
    // Verify token by calling auth/me
    const me = await fetch('/v1/auth/me', {headers:{'Accept':'application/json', 'Authorization': 'Bearer ' + token}}).then(r => r.json()).catch(() => null);
    if (!me || !me.id) {
      setStoredToken('');
      await showLoginModal();
      return;
    }
  } catch(e) {
    console.warn('auth check failed', e);
    setStoredToken('');
    await showLoginModal();
    return;
  }
  setupTabs(); setupEventsRail();
  await loadConfig();
  await updateUserChip();
  await loadSessions(); await loadApprovals(); await loadRunners();
  refreshDashboardMetricsOnStartup();
  await loadGlobalEvents(true);
  loadMcpBuildStatus().catch(()=>{});
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts().catch(()=>{});
  updateSourceActions();
}
init().catch(e=>paneError('PAC UI could not load', e.message || String(e)));

const openEndpointBtn = document.getElementById('openEndpointModal');
if (openEndpointBtn) openEndpointBtn.onclick = openEndpointModal;

function openEndpointCommandModal(id) {
  commandEndpointId = id;
  const r = (window.__pacEndpoints || []).find(x => x.id === id);
  const modal = document.getElementById('endpointCommandModal');
  if (document.getElementById('endpointCommandTarget')) endpointCommandTarget.value = r ? `${r.name} (${r.id})` : id;
  if (document.getElementById('endpointCommandMode')) endpointCommandMode.value = 'host';
  if (document.getElementById('endpointCommandImage')) endpointCommandImage.value = '';
  if (document.getElementById('endpointCommandWorkspace')) endpointCommandWorkspace.value = '';
  if (document.getElementById('endpointCommandText')) endpointCommandText.value = 'pwd && ls -la';
  if (document.getElementById('endpointCommandStatus')) endpointCommandStatus.textContent = '';
  if (modal) modal.hidden = false;
}
function closeEndpointCommandModal() {
  const modal = document.getElementById('endpointCommandModal');
  if (modal) modal.hidden = true;
}

const closeEndpointBtn = document.getElementById('closeEndpointModal');
if (closeEndpointBtn) closeEndpointBtn.onclick = closeEndpointModal;
const endpointModal = document.getElementById('endpointModal');
if (endpointModal) endpointModal.onclick = (ev) => { if (ev.target === endpointModal) closeEndpointModal(); };
const closeEndpointCommandBtn = document.getElementById('closeEndpointCommandModal');
if (closeEndpointCommandBtn) closeEndpointCommandBtn.onclick = closeEndpointCommandModal;
const endpointCommandModal = document.getElementById('endpointCommandModal');
if (endpointCommandModal) endpointCommandModal.onclick = (ev) => { if (ev.target === endpointCommandModal) closeEndpointCommandModal(); };
const queueEndpointCommandBtn = document.getElementById('queueEndpointCommand');
if (queueEndpointCommandBtn) queueEndpointCommandBtn.onclick = async()=>{
  const status = document.getElementById('endpointCommandStatus');
  try {
    queueEndpointCommandBtn.disabled = true;
    if (status) status.textContent = 'Queued…';
    const mode = document.getElementById('endpointCommandMode')?.value || 'host';
    const body = {prompt:'Endpoint command', command:document.getElementById('endpointCommandText')?.value || 'pwd', execution_mode:mode, container_image:document.getElementById('endpointCommandImage')?.value || null, workspace_path:document.getElementById('endpointCommandWorkspace')?.value || null, metadata:{source_endpoint_id:'controller'}};
    await api(`/v1/endpoints/${encodeURIComponent(commandEndpointId)}/commands`, {method:'POST', body:JSON.stringify(body)});
    if (status) status.textContent = 'Queued.';
    closeEndpointCommandModal();
    await loadGlobalEvents(true).catch(()=>{});
  } catch(e) { if (status) status.textContent = `Failed: ${e.message}`; } finally { queueEndpointCommandBtn.disabled = false; }
};
const addRunnerBtn = document.getElementById('addRunner');
if (addRunnerBtn) addRunnerBtn.onclick = async()=>{
  const status = document.getElementById('endpointModalStatus');
  try {
    addRunnerBtn.disabled = true;
    if (status) status.textContent = 'Adding…';
    const chosenTools = selectedRunnerToolNames(); const body={name:runnerName.value || 'remote-endpoint', labels:runnerLabels.value.split(',').map(x=>x.trim()).filter(Boolean), endpoint:runnerEndpoint.value || null, allow_host_execution:true, allow_container_execution:true, agent_enabled:!!document.getElementById('runnerAgentEnabled')?.checked, metadata:{agent_tools:chosenTools, tool_packages:packageNamesForTools(chosenTools), default_workspace:document.getElementById('runnerDefaultWorkspace')?.value || null}};
    const path = editingEndpointId ? `/v1/endpoints/${editingEndpointId}` : '/v1/endpoints';
    const method = editingEndpointId ? 'PUT' : 'POST';
    await api(path,{method, body:JSON.stringify(body)});
    if (status) status.textContent = editingEndpointId ? 'Saved.' : 'Added.';
    closeEndpointModal();
    await loadRunners(); await loadGlobalEvents(true).catch(()=>{});
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message}`;
  } finally {
    addRunnerBtn.disabled = false;
  }
};
const discoverBtn = document.getElementById('discoverLocal');
if (discoverBtn) discoverBtn.onclick = async()=>{ const r=await api('/v1/endpoints/local/discover'); if(localDiscovery) localDiscovery.textContent='Local host discovery completed. Details are in Events.'; emitUiEvent('local_endpoint_discovered', 'Local host discovery completed', r); };
const addLocalBtn = document.getElementById('addLocalRunner');
if (addLocalBtn) addLocalBtn.onclick = async()=>{ const box=document.getElementById('localDiscovery'); try { if(box) box.textContent='Adding local endpoint…'; const r=await api('/v1/endpoints/local',{method:'POST'}); if(box) box.textContent='Local endpoint added. Details are in Events.'; emitUiEvent('local_endpoint_added', 'Local endpoint added', r); await loadRunners(); await loadGlobalEvents(true).catch(()=>{}); } catch(e){ if(box) box.textContent='Local endpoint could not be added. Details are in Events.'; paneError('Local endpoint could not be added', e.message); } };

const updateAllBtn = document.getElementById('updateAllEndpoints');
if (updateAllBtn) updateAllBtn.onclick = async()=>{
  if(!confirm('Queue software update for all online remote endpoints?')) return;
  const result = await api('/v1/endpoints/update-all',{method:'POST'});
  if(localDiscovery) localDiscovery.textContent = 'Endpoint update requested. Details are in Events.'; emitUiEvent('endpoint_update_all_requested', 'Endpoint update requested', result);
  await loadRunners();
};

const maintenanceAllBtn = document.getElementById('maintenanceAllEndpoints');
if (maintenanceAllBtn) maintenanceAllBtn.onclick = async()=>{
  if(!confirm('Run safe PAC maintenance cleanup on all online endpoints? This removes only PAC-created stopped containers, stale PAC workspaces, and temporary artifact bundles older than 24 hours.')) return;
  const result = await api('/v1/endpoints/maintenance-all',{method:'POST', body:JSON.stringify({max_age_hours:24,dry_run:false,remove_containers:true,remove_workspaces:true,remove_temp_artifacts:true,prune_images:false})});
  if(localDiscovery) localDiscovery.textContent = 'Endpoint maintenance requested. Details are in Events.'; emitUiEvent('endpoint_maintenance_all_requested', 'Endpoint maintenance requested', result);
  await loadRunners();
  await loadGlobalEvents(true).catch(()=>{});
};

const buildMcpBtn = document.getElementById('buildMcpBridge');
if (buildMcpBtn) buildMcpBtn.onclick = () => buildMcpBridgeFromUi().catch(e=>paneError('Zed binary build failed', e.message));
const refreshMcpBtn = document.getElementById('refreshMcpBridge');
if (refreshMcpBtn) refreshMcpBtn.onclick = () => loadMcpBuildStatus();

const closeSessionEventBtn = document.getElementById('closeSessionEventModal');
if (closeSessionEventBtn) closeSessionEventBtn.onclick = closeSessionEventModal;
const sessionEventModal = document.getElementById('sessionEventModal');
if (sessionEventModal) sessionEventModal.onclick = (ev) => { if (ev.target === sessionEventModal) closeSessionEventModal(); };
const closeGitDiffBtn = document.getElementById('closeGitDiffModal');
if (closeGitDiffBtn) closeGitDiffBtn.onclick = closeGitDiffModal;
const gitDiffModal = document.getElementById('gitDiffModal');
if (gitDiffModal) gitDiffModal.onclick = (ev) => { if (ev.target === gitDiffModal) closeGitDiffModal(); };

// ─── Marketplace ──────────────────────────────────────────────────────────────

let mpCache = {};

function openMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (!modal) return;
  modal.hidden = false;
  document.getElementById('mpResultsList').innerHTML = '<div class="muted small-text" style="padding:1rem;text-align:center">Enter a search term and press Search</div>';
  document.getElementById('mpDetailPanel').innerHTML = '<div class="muted small-text" style="padding:2rem;text-align:center">Select a model from the list to see details</div>';
  document.getElementById('mpSearchInput').focus();
}

function closeMarketplaceModal() {
  document.getElementById('marketplaceModal').hidden = true;
}

async function mpSearch() {
  const q = document.getElementById('mpSearchInput').value.trim();
  const cap = document.getElementById('mpCapabilityFilter').value;
  const sort = document.getElementById('mpSortBy').value;
  const statusEl = document.getElementById('mpStatus');
  const listEl = document.getElementById('mpResultsList');
  if (!q) { showInline('mpStatus', {error: 'Enter a search term'}); return; }
  showInline('mpStatus', {loading: 'Searching HuggingFace...'}, statusEl);
  listEl.innerHTML = '<div class="muted small-text" style="padding:1rem;text-align:center">Loading...</div>';
  try {
    const params = new URLSearchParams({q, limit: 20, sort});
    if (cap) params.set('capability', cap);
    const data = await api('/v1/models/marketplace/search?' + params);
    mpCache.results = data.results || [];
    renderMpResults(mpCache.results);
    showInline('mpStatus', {ok: data.total + ' models found'}, statusEl);
  } catch (e) {
    listEl.innerHTML = '<div class="muted small-text" style="padding:1rem;color:#f87171">Error: ' + e.message + '</div>';
    showInline('mpStatus', {error: e.message}, statusEl);
  }
}

function renderMpResults(results) {
  const listEl = document.getElementById('mpResultsList');
  if (!results.length) { listEl.innerHTML = '<div class="muted small-text" style="padding:1rem;text-align:center">No results</div>'; return; }
  listEl.innerHTML = results.map(r => {
    const caps = Object.entries(r.capabilities || {}).filter(([k,v]) => v).map(([k]) => capabilityTag(k)).join(' ') || '<span class="muted">general</span>';
    const params = r.params_b ? r.params_b + 'B' : '?B';
    const vram = r.vram_q4_k_m_gb ? r.vram_q4_k_m_gb.toFixed(0) + 'GB' : '';
    const quants = (r.available_quants || []).slice(0,4).join(', ') || 'unknown';
    return '<div class="mp-model-card" data-model-id="'+escapeHtml(r.model_id)+'" onclick="mpSelectModel(\''+escapeHtml(r.model_id.replace(/'/g,'\\' ))+'\')">'
      + '<div class="mp-model-name">'+escapeHtml(r.model_id.split('/').pop())+'</div>'
      + '<div class="mp-model-author muted small-text">by '+escapeHtml(r.author)+'</div>'
      + '<div class="mp-model-caps">'+caps+'</div>'
      + '<div class="mp-model-meta muted small-text">'+params+' · '+vram+' · '+quants+'</div>'
      + '<div class="mp-model-stats muted small-text">⬇ '+r.downloads.toLocaleString()+' · ♥ '+r.likes.toLocaleString()+'</div>'
      + '</div>';
  }).join('');
}

async function mpSelectModel(modelId) {
  const detailEl = document.getElementById('mpDetailPanel');
  detailEl.innerHTML = '<div class="muted small-text" style="padding:2rem;text-align:center">Loading...</div>';
  // Highlight selected
  document.querySelectorAll('.mp-model-card').forEach(c => c.classList.remove('selected'));
  document.querySelector('.mp-model-card[data-model-id="'+modelId+'"]')?.classList.add('selected');
  try {
    const data = await api('/v1/models/marketplace/model/' + encodeURIComponent(modelId));
    renderMpDetail(data);
  } catch (e) {
    detailEl.innerHTML = '<div class="muted small-text" style="padding:2rem;color:#f87171">Error loading details: '+e.message+'</div>';
  }
}

function renderMpDetail(d) {
  const detailEl = document.getElementById('mpDetailPanel');
  const caps = Object.entries(d.capabilities || {}).filter(([k,v]) => v).map(([k]) => capabilityTag(k)).join(' ') || 'general purpose';
  const params = d.params_b ? d.params_b + 'B params' : '';
  const vram = d.vram_q4_k_m_gb ? '~'+d.vram_q4_k_m_gb.toFixed(0)+'GB VRAM (Q4_K_M)' : '';
  const quants = (d.available_quants || []).join(', ') || 'unknown';
  const readme = d.readme_preview ? '<div class="mp-readme">'+escapeHtml(d.readme_preview)+'</div>' : '';
  const scoreColors = {fast:'#4ade80', medium:'#facc15', slow:'#f97316', impossible:'#f87171', unknown:'#94a3b8'};
  const providerScores = (d.provider_scores || []).map(s => {
    const color = scoreColors[s.speed_category] || '#94a3b8';
    const badge = s.can_run
      ? '<span class="mp-badge ok">✅ '+escapeHtml(s.provider_name)+'</span>'
      : '<span class="mp-badge warn">⚠️ '+escapeHtml(s.provider_name)+'</span>';
    return '<div class="mp-provider-score">'+badge+'<span class="muted small-text">'+escapeHtml(s.reason)+'</span>'
      + (s.quant_recommended ? '<span class="muted small-text"> · recommended: '+s.quant_recommended+'</span>' : '')
      + '</div>';
  }).join('');
  detailEl.innerHTML = '<div style="padding:0 0.5rem">'
    + '<div style="font-size:1.1em;font-weight:600;margin-bottom:4px">'+escapeHtml(d.model_id)+'</div>'
    + '<div class="muted small-text" style="margin-bottom:12px">by '+escapeHtml(d.author)+' · ⬇ '+d.downloads.toLocaleString()+' downloads · ♥ '+d.likes.toLocaleString()+'</div>'
    + '<div style="margin-bottom:12px">'+caps+'</div>'
    + '<div class="muted small-text" style="margin-bottom:8px">'+params+' · '+vram+'</div>'
    + '<div class="muted small-text" style="margin-bottom:8px">Available quants: '+escapeHtml(quants)+'</div>'
    + '<div style="margin:12px 0"><b>Provider compatibility:</b></div>'
    + '<div id="mpProviderScores">'+providerScores+'</div>'
    + '<div style="margin-top:12px"><button id="mpConfigureBtn" class="ghost-button">Configure in PAC</button></div>'
    + readme
    + '</div>';
  document.getElementById('mpConfigureBtn').onclick = () => {
    closeMarketplaceModal();
    openModelModal();
    modelName.value = d.model_id.replace(/[^a-zA-Z0-9_.-]+/g, '-').toLowerCase();
    modelId.value = d.model_id;
    modelProvider.value = (d.provider_scores || []).find(s => s.can_run)?.endpoint_id || 'local-PAC';
    modelRunsOn.value = '';
    setModalStatus('modelModalStatus', 'Review and save. Quantization: ' + ((d.provider_scores || [])[0]?.quant_recommended || 'Q4_K_M'));
  };
}

// Event listeners
document.getElementById('openMarketplaceModal')?.addEventListener('click', openMarketplaceModal);
document.getElementById('closeMarketplaceModal')?.addEventListener('click', closeMarketplaceModal);
document.getElementById('mpSearchBtn')?.addEventListener('click', mpSearch);
document.getElementById('mpSearchInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') mpSearch(); });


// ── README Modal ─────────────────────────────────────────────────────────────
const PAC_README = `<p style="margin:0 0 1rem"><strong>PAC — Pi Agent Controller</strong> — a lightweight agent control system. Manage sessions, route to local or remote models, execute tasks on endpoints, and monitor everything from a single Web UI.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Sessions</h3>
<p style="margin:0 0 .75rem">A session is a conversation with a selected model. Each session has:</p>
<ul style="margin:0 0 1rem;padding-left:1.2rem">
  <li><strong>Context profile</strong> — budget for history, output, file context</li>
  <li><strong>Permission profile</strong> — network access, tool permissions</li>
  <li><strong>Workspace</strong> — local directory or endpoint workspace</li>
  <li><strong>Agent loop</strong> — pi.dev (Node.js) or direct model</li>
</ul>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Models and providers</h3>
<p style="margin:0 0 .75rem">PAC does not run models — it routes requests to your provider. Connect LM Studio, Ollama, vLLM, or OpenAI-compatible endpoints. Models are configured in <code>config/config.yaml</code> with a provider reference and context settings.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">pi.dev runtime</h3>
<p style="margin:0 0 .75rem">pi.dev is a Node.js-based agent that runs in a <code>pi-agent-harness</code> container on endpoints. It supports code execution, file operations, git, and tool use via a defined tool schema. pi.dev sessions can be created from the Sessions tab.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Endpoints</h3>
<p style="margin:0 0 .75rem">Remote hosts running <code>pac-endpoint</code> binary. Register endpoints in the Endpoints tab. Each endpoint can run host or container jobs. pi.dev wrapper workloads require Node.js on the endpoint.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Local model marketplace</h3>
<p style="margin:0 0 .75rem">Browse HuggingFace GGUF models from the Models tab. Compatible models are shown with provider compatibility scores. Download to your LM Studio provider directly from the UI.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Permissions and security</h3>
<p style="margin:0 0 .75rem">Permission profiles control what tools a session can use. <code>full-control</code> bypasses approval prompts. <code>standard</code> requires approval for shell and write operations. Network access and file read/write can be individually restricted.</p>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Install</h3>
<pre style="background:rgba(0,0,0,.3);padding:.75rem;border-radius:6px;font-size:.78rem;overflow-x:auto">./install.sh
PACP_HOME=/data/pacp ./install.sh  # override home directory</pre>

<h3 style="font-size:.9rem;margin:1rem 0 .5rem;color:var(--accent)">Configuration</h3>
<p style="margin:0 0 .5rem">All config is in <code>~/.pacp/config/config.yaml</code>. Providers, models, profiles, and endpoints are defined there. Restart the service after editing: <code>systemctl --user restart pacp</code></p>`;

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('closeReadmeModal')?.addEventListener('click', () => {
    document.getElementById('readmeModal').hidden = true;
  });
  document.getElementById('openReadmeModal')?.addEventListener('click', () => {
    document.getElementById('readmeContent').innerHTML = PAC_README;
    document.getElementById('readmeModal').hidden = false;
  });
  document.getElementById('readmeModal')?.addEventListener('click', (ev) => {
    if (ev.target === document.getElementById('readmeModal')) {
      document.getElementById('readmeModal').hidden = true;
    }
  });
});
