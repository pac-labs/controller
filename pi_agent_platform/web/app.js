
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
let sessionThinkingGroups = new Map();
let sessionEventSeen = new Set();
let sessionMessageSeen = new Set();
let sessionPendingRows = new Map();
let sessionApprovalRows = new Map();
let sessionLatestEventId = null;
let sessionPoll = null;
let activeSessionTaskId = null;
let setupStatus = null;
let sessionSlashCommands = [];
let pacThemeMode = 'system';
let marketplaceResultCache = [];
let currentVersionInfo = null;
let approvalsRequest = null;
let sessionRunButtonRequest = null;
let sessionPollRequest = null;
let sessionPollingActiveFor = null;
let currentUser = null;
let authStatus = null;
let suppressSessionAutoScroll = false;
let sessionHydrationToken = 0;
let sessionHydrationActiveFor = null;
let sessionHydrationBufferedEvents = [];
let providerHealthCache = new Map();
let controllerHarnessStatusCache = null;

const AUTH_TOKEN_KEY = 'pac_auth_token';

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
    currentVersionInfo = v || null;
    const backend = v?.version || 'unknown';
    const ui = v?.ui_build || 'unknown';
    document.querySelectorAll('.app-version').forEach(el => el.textContent = 'v' + backend);
    const stamp = document.getElementById('buildStamp');
    if (stamp) {
      stamp.textContent = `backend v${backend} • ui ${ui}`;
      const when = v?.ui_updated_at ? `\nUI updated: ${v.ui_updated_at}` : '';
      stamp.title = `Backend version: ${backend}\nUI build: ${ui}${when}`;
    }
    if (v?.version) document.title = `PAC - Pi Agent Control v${v.version}`;
  } catch (_) {}
}
function slashCommandHelpText() {
  const commands = (sessionSlashCommands && sessionSlashCommands.length) ? sessionSlashCommands : Object.values(SESSION_SLASH_COMMANDS);
  return commands.map(c => `${c.label} - ${c.description}`).join('\n');
}
function isHelpSlashCommand(raw) {
  return String(raw || '').trim().toLowerCase() === '/help';
}
function applyThemeMode(mode = 'system') {
  pacThemeMode = ['system', 'dark', 'light'].includes(String(mode)) ? String(mode) : 'system';
  const root = document.documentElement;
  const body = document.body;
  if (pacThemeMode === 'system') {
    root.removeAttribute('data-theme');
    if (body) body.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', pacThemeMode);
    if (body) body.setAttribute('data-theme', pacThemeMode);
  }
  try { localStorage.setItem('pac-theme', pacThemeMode); } catch (_) {}
  const select = document.getElementById('themeMode');
  if (select) select.value = pacThemeMode;
}
function loadThemeMode() {
  let saved = 'system';
  try { saved = localStorage.getItem('pac-theme') || 'system'; } catch (_) {}
  applyThemeMode(saved);
}

function hideSetupWizard() {
  const modal = document.getElementById('setupWizard');
  if (modal) modal.hidden = true;
}
function openSetupWizard() {
  const modal = document.getElementById('setupWizard');
  if (modal) modal.hidden = false;
}
function renderSetupWizard() {
  setupStatus = config?.setup_status || null;
  const body = document.getElementById('setupWizardBody');
  const modal = document.getElementById('setupWizard');
  if (!body || !modal) return;
  const issues = setupStatus?.required_issues || [];
  const warnings = setupStatus?.warnings || [];
  if (!issues.length) {
    body.innerHTML = '';
    hideSetupWizard();
    return;
  }
  const issueRows = issues.map(issue => {
    const actionTab = issue.action_tab || 'settings-tab';
    const actionLabel = issue.action_label || 'Open';
    return `<div class="pack-summary warn-summary"><b>${escapeHtml(issue.title || 'Configuration required')}</b><div class="muted small-text">${escapeHtml(issue.detail || '')}</div><div class="button-row"><button type="button" class="ghost-button setup-nav-button" data-tab="${escapeHtml(actionTab)}">${escapeHtml(actionLabel)}</button></div></div>`;
  }).join('');
  const warningRows = warnings.length ? `<div class="muted small-text"><b>Warnings</b></div>${warnings.map(issue => `<div class="pack-summary"><b>${escapeHtml(issue.title || 'Warning')}</b><div class="muted small-text">${escapeHtml(issue.detail || '')}</div></div>`).join('')}` : '';
  body.innerHTML = `<div class="pack-summary strong-summary">Required setup items: ${issues.length}</div>${issueRows}${warningRows}`;
  body.querySelectorAll('.setup-nav-button').forEach(btn => {
    btn.onclick = () => {
      const tab = btn.dataset.tab || 'settings-tab';
      if (tab.startsWith('settings:')) {
        switchToTab('settings-tab');
        switchSettingsPanel(tab.split(':')[1] || 'updates');
      } else {
        switchToTab(tab);
      }
      if (tab === 'providers-tab') openProviderModal();
      if (tab === 'models-tab') openModelModal();
      hideSetupWizard();
    };
  });
  openSetupWizard();
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
function appendText(parent, tag, className, text) {
  if (text == null || text === '') return null;
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = String(text);
  parent.appendChild(el);
  return el;
}
function appendChatText(parent, role, text) {
  if (text == null || text === '') return null;
  if (typeof marked !== 'undefined' && (role === 'assistant' || role === 'system' || role === 'error')) {
    const el = document.createElement('div');
    el.className = 'chat-bubble-text markdown-body';
    el.innerHTML = marked.parse(String(text));
    parent.appendChild(el);
    return el;
  }
  return appendText(parent, 'div', 'chat-bubble-text', text);
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
  if (t.includes('result') || t.includes('assistant_message') || t === 'final') return false;
  return t.includes('tool') || t.includes('command') || t.includes('runner') ||
    t.includes('stdout') || t.includes('stderr') || t.includes('approval') ||
    t.includes('thinking') || t.includes('intent') || t.includes('routing') || t.includes('task_queued') || t.includes('task_started') ||
    t.includes('task_completed') || t.includes('task_failed') || t.includes('task_approved') ||
    t.includes('task_rejected') || t.includes('subagent_started') || t.includes('context_compacted') ||
    t.includes('model_response') ||
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
    t === 'task_completed' || t === 'context_compacted' || t === 'full_control_enabled' ||
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
  if (type.includes('task_completed')) return 'Finished thinking';
  if (type.includes('agent_thinking')) return event?.message || 'Thinking';
  if (type.includes('agent_intent')) {
    if (data.tool) return `Preparing ${data.tool}`;
    if (data.command) return `Preparing command ${data.command}`;
    if (data.action_type === 'final') return 'Preparing final response';
    return event?.message || 'Choosing next step';
  }
  if (type.includes('agent_routing')) return event?.message || 'Routing task';
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
  if (title) title.textContent = 'Thought details';
  if (body) {
    body.className = 'modal-scroll-output tool-activity-modal';
    const duration = formatDurationMs(((group.endedAt || new Date()).getTime()) - (group.startedAt || new Date()).getTime());
    const planSteps = deriveThinkingPlanSteps(group);
    const summary = escapeHtml(group.summary || 'Thinking');
    body.innerHTML = `
      <div class="thought-modal-summary">
        <div class="thought-modal-kicker">${escapeHtml(group.closed ? 'Thought completed' : 'Currently thinking')}</div>
        <div class="thought-modal-title">${summary}</div>
        <div class="thought-modal-meta">
          <span>${escapeHtml(group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`)}</span>
          <span>${thinkingGroupToolCount(group)} ${thinkingGroupToolCount(group) === 1 ? 'tool' : 'tools'}</span>
          <span>${escapeHtml(thinkingGroupNeedsApproval(group) ? 'Awaiting approval' : group.closed ? 'Completed' : 'Active')}</span>
        </div>
      </div>
      ${planSteps.length ? `<div class="thought-modal-plan">${planSteps.map((step, index) => `<div class="thought-modal-plan-item ${escapeHtml(step.status)}"><span class="thought-modal-plan-index">${index + 1}</span><span class="thought-modal-plan-label">${escapeHtml(step.label)}</span><span class="thought-modal-plan-state">${escapeHtml(step.status === 'running' ? 'Active' : step.status === 'attention' ? 'Needs approval' : step.status === 'failed' ? 'Failed' : 'Done')}</span></div>`).join('')}</div>` : ''}
      ${sessionThinkingDetailsHtml(group.events || [])}`;
  }
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
function deriveThinkingPlanSteps(group) {
  const rows = Array.isArray(group?.events) ? group.events : [];
  const relevant = rows.filter((item) => {
    const t = String(item?.event?.type || '').toLowerCase();
    return t.includes('agent_intent') || t.includes('tool_call') || t.includes('approval_required') || t.includes('task_completed') || t.includes('task_failed');
  });
  const steps = [];
  for (const item of relevant) {
    const event = item?.event || {};
    const data = event.data && typeof event.data === 'object' ? event.data : {};
    const type = String(event.type || '').toLowerCase();
    let label = '';
    let status = 'done';
    if (type.includes('approval_required')) {
      label = sessionThinkingSummary(event, item?.block);
      status = 'attention';
    } else if (type.includes('tool_call')) {
      label = data.tool ? `Run ${data.tool}` : (event.message || 'Run tool');
    } else if (type.includes('agent_intent')) {
      label = event.message || 'Interpret task';
      status = 'running';
    } else if (type.includes('task_failed')) {
      label = event.message || 'Task failed';
      status = 'failed';
    } else if (type.includes('task_completed')) {
      label = 'Complete response';
    }
    label = String(label || '').trim();
    if (!label) continue;
    const previous = steps[steps.length - 1];
    if (previous && previous.label === label && previous.status === status) continue;
    steps.push({label, status, time: event.created_at || ''});
  }
  if (!steps.length && group?.summary) steps.push({label: group.summary, status: group.closed ? 'done' : 'running', time: ''});
  if (steps.length) {
    const last = steps[steps.length - 1];
    if (!group?.closed && last.status === 'done') last.status = thinkingGroupNeedsApproval(group) ? 'attention' : 'running';
  }
  return steps.slice(-6);
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
  const event = group.lastEvent || group.events?.[group.events.length - 1]?.event;
  const summary = group.summary || sessionThinkingSummary(event, null);
  const duration = formatDurationMs(((group.endedAt || new Date()).getTime()) - (group.startedAt || new Date()).getTime());
  const toolCount = thinkingGroupToolCount(group);
  const approvalPending = thinkingGroupNeedsApproval(group);
  const taskId = event?.task_id || group.taskId || '';
  const planSteps = deriveThinkingPlanSteps(group);
  group.row.className = `thought-card${group.closed ? ' complete' : ' live'}${approvalPending ? ' needs-approval' : ''}`;
  group.row.innerHTML = '';
  const main = document.createElement('button');
  main.type = 'button';
  main.className = 'thought-card-main';
  main.innerHTML = `
    <span class="thought-icon-shell">${group.closed ? '<span class="thought-icon-done" aria-hidden="true">◧</span>' : '<span class="tiny-spinner square" aria-hidden="true"></span>'}</span>
    <span class="thought-copy">
      <span class="thought-kicker">${escapeHtml(group.closed ? 'Thought' : 'Current task')}</span>
      <span class="thought-summary">${escapeHtml(summary)}</span>
      <span class="thought-meta"><span>${escapeHtml(group.closed ? `Thought for ${duration}` : `Thinking for ${duration}`)}</span><span>${toolCount} ${toolCount === 1 ? 'tool' : 'tools'}</span><span>${escapeHtml(approvalPending ? 'Awaiting approval' : group.closed ? 'Completed' : 'Thinking')}</span></span>
    </span>
    <span class="thought-open">Details</span>`;
  main.onclick = () => openSessionThinkingModal(group);
  main.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') openSessionThinkingModal(group); };
  group.row.appendChild(main);
  if (planSteps.length) {
    const plan = document.createElement('details');
    plan.className = 'thought-plan';
    if (!group.closed || approvalPending) plan.open = true;
    plan.innerHTML = `
      <summary class="thought-plan-summary">
        <span class="thought-plan-title">Plan</span>
        <span class="thought-plan-count">${planSteps.length} ${planSteps.length === 1 ? 'task' : 'tasks'}</span>
      </summary>
      <div class="thought-plan-list">
        ${planSteps.map((step, index) => `<div class="thought-plan-item ${escapeHtml(step.status)}"><span class="thought-plan-bullet">${index + 1}</span><span class="thought-plan-label">${escapeHtml(step.label)}</span><span class="thought-plan-state">${escapeHtml(step.status === 'running' ? 'Active' : step.status === 'attention' ? 'Needs approval' : step.status === 'failed' ? 'Failed' : 'Done')}</span></div>`).join('')}
      </div>`;
    group.row.appendChild(plan);
  }
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
    group.row.appendChild(actions);
  }
}
function ensureSessionThinkingGroup(event) {
  const taskId = event?.task_id || '';
  let group = getThinkingGroup(taskId);
  if (!group || group.closed || (taskId && group.taskId !== taskId)) {
    const el = document.getElementById('events');
    const row = document.createElement('article');
    row.className = 'thought-card live';
    if (el) el.appendChild(row);
    group = {events: [], startedAt: sessionEventDate(event), endedAt: null, row, closed: false, taskId};
  }
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
    group.summary = sessionThinkingSummary(endEvent, null);
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
  modal.hidden = false;
}
function closeSessionEventModal() {
  const modal = document.getElementById('sessionEventModal');
  if (modal) modal.hidden = true;
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
  if (message) message.textContent = `PAC will install ${nextVersion ? `v${nextVersion}` : 'the latest release'} and restart the controller.`;
  if (body) {
    const bullets = Array.isArray(meta?.compare_changes) ? meta.compare_changes.slice(0, 8) : [];
    body.innerHTML = `
      <div class="updates-detail-copy">
        <div>Current version: <b>v${escapeHtml(currentVersion)}</b></div>
        <div>Target version: <b>${escapeHtml(nextVersion ? `v${nextVersion}` : 'latest')}</b></div>
        ${bullets.length ? `<div style="margin-top:.65rem"><b>Included changes</b></div><ul>${bullets.map((change) => `<li>${escapeHtml(String(change))}</li>`).join('')}</ul>` : ''}
        <div style="margin-top:.65rem">The screen will remain in this state until PAC restarts and the web UI refreshes.</div>
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
  if (message) message.textContent = `PAC is applying ${version ? `v${version}` : 'the release'} and restarting now.`;
  if (body) {
    body.innerHTML = `<div class="updates-detail-copy"><div>The controller is restarting.</div><div>This screen will remain visible until the web UI refreshes automatically.</div><div>Refresh window: about ${escapeHtml(String(seconds))} seconds.</div></div>`;
  }
  if (proceed) {
    proceed.disabled = true;
    proceed.textContent = 'Restarting…';
  }
  if (cancel) cancel.hidden = true;
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
  el.scrollTop = el.scrollHeight;
}
function syncSessionPermissionQuick() {
  const select = document.getElementById('sessionPermissionQuick');
  const button = document.getElementById('applySessionPermission');
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
  if (controls && permissionSelect && permissionApply && permissionSelect.parentElement !== controls) {
    const runTask = document.getElementById('runTask');
    controls.insertBefore(permissionSelect, runTask || null);
    controls.insertBefore(permissionApply, runTask || null);
    permissionSelect.title = 'Permissions';
    permissionApply.classList.add('mini-apply-button');
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
function renderSessionSidebar(sessions = window.__pacSessions || []) {
  const list = document.getElementById('sessionSidebarList');
  if (!list) return;
  if (!sessions.length) {
    list.innerHTML = '<div class="muted">No sessions yet.</div>';
    return;
  }
  list.innerHTML = '';
  sessions.slice().reverse().forEach((s) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `session-sidebar-item${selectedSession?.id === s.id ? ' active' : ''}`;
    item.innerHTML = `<strong>${escapeHtml(s.name || s.id)}</strong><div class="session-sidebar-meta">${escapeHtml(s.agent_profile || '-')} · ${escapeHtml(s.model || '-')} · ${escapeHtml(s.permission_profile || '-')}</div><div class="session-sidebar-meta">${escapeHtml(s.workspace_path || '')}</div>`;
    item.onclick = () => { switchToTab('sessions-tab'); selectSession(s.id); };
    list.appendChild(item);
  });
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
function renderSessionSnapshotFast(snapshot, sessionId) {
  const timeline = document.getElementById('events');
  if (!timeline) return;
  const events = Array.isArray(snapshot) ? snapshot : [];
  const recentChunkSize = 220;
  const tail = events.slice(-recentChunkSize);
  const token = ++sessionHydrationToken;
  sessionHydrationActiveFor = sessionId;
  timeline.innerHTML = tail.length ? '' : '<div class="empty-timeline">No session events yet.</div>';
  resetSessionTimelineState();
  suppressSessionAutoScroll = true;
  tail.forEach((ev) => renderSessionTimelineEvent(ev));
  suppressSessionAutoScroll = false;
  timeline.scrollTop = timeline.scrollHeight;
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
  const el = document.getElementById('events');
  if (!el || !taskId) return;
  let group = sessionThinkingGroups.get(taskId);
  if (!group) {
    const row = document.createElement('article');
    row.className = 'thought-card live pending-only';
    group = {events: [], startedAt: new Date(), endedAt: null, row, closed: false, taskId, summary: 'Thinking...' };
    sessionThinkingGroups.set(taskId, group);
    row.onclick = () => openSessionThinkingModal(group);
    el.appendChild(row);
  }
  sessionPendingRows.set(taskId, group.row);
  updateSessionThinkingRow(group);
  el.scrollTop = el.scrollHeight;
}
function renderSessionTimelineEvent(event, options = {}) {
  const el = document.getElementById('events');
  if (!el || !event) return;
  const prepend = !!options.prepend;
  if (event.id && sessionEventSeen.has(event.id)) return;
  if (event.id) sessionEventSeen.add(event.id);
  if (isServerBackedEventId(event.id)) sessionLatestEventId = event.id;
  const messageKey = `${event.type || ''}:${event.task_id || ''}:${event.message || ''}`;
  if ((event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message' || event.type === 'final') && sessionMessageSeen.has(messageKey)) return;
  if (event.type === 'user_message' || event.type === 'result' || event.type === 'assistant_message' || event.type === 'final') sessionMessageSeen.add(messageKey);
  const typeLower = String(event.type || '').toLowerCase();
  if (typeLower.includes('task_completed') || typeLower.includes('task_failed') || typeLower.includes('result')) removePendingRow(event.task_id);
  if (typeLower.includes('task_approved') || typeLower.includes('task_rejected') || typeLower.includes('task_completed') || typeLower.includes('task_failed') || typeLower.includes('result')) removeSessionApprovalRow(event.task_id);
  const empty = el.querySelector('.empty-timeline');
  if (empty) empty.remove();
  const block = normalizeTimelineBlock(event);
  const role = sessionEventRole(event);
  const internal = isInternalSessionEvent(event);
  if (internal && prepend) {
    return;
  }
  if (internal) {
    const group = ensureSessionThinkingGroup(event);
    group.events.push({event, block});
    group.lastEvent = event;
    group.summary = sessionThinkingSummary(event, block);
    updateSessionThinkingRow(group);
    if (typeLower.includes('approval_required')) renderSessionApprovalRow(event);
    if (String(event?.type || '').toLowerCase().includes('task_completed') || String(event?.type || '').toLowerCase().includes('task_failed')) {
      flushSessionThinkingGroup(event);
    }
    while (el.children.length > 250) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
    return;
  }
  if (sessionLifecycleEventIsNoise(event)) return;
  flushSessionThinkingGroup(event);
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
  if (!text && role === 'assistant' && !block) return;
  if (text) appendChatText(bubble, role, text);
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
  if (prepend && el.firstChild) el.insertBefore(row, el.firstChild);
  else el.appendChild(row);
  while (el.children.length > 250) el.removeChild(el.firstChild);
  if (!suppressSessionAutoScroll) el.scrollTop = el.scrollHeight;
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

function switchSettingsPanel(name) {
  document.querySelectorAll('.settings-panel').forEach((panel) => { panel.style.display = 'none'; panel.classList.remove('active'); });
  document.querySelectorAll('.settings-sub-btn').forEach((btn) => btn.classList.remove('active'));
  const panel = document.getElementById('settings-' + name);
  if (panel) {
    panel.style.display = 'block';
    panel.classList.add('active');
  }
  const btn = document.querySelector(`.settings-sub-btn[data-settings-panel="${name}"]`);
  if (btn) btn.classList.add('active');
  if (name === 'users') { loadUsersList().catch(()=>{}); loadGroupsList().catch(()=>{}); }
  if (name === 'pi-dev') renderControllerHarnessSettings();
  if (name === 'endpoint') renderEndpointConnectionSettings();
  if (name === 'service') renderServiceMode();
  if (name === 'tls') renderTlsInfo();
  if (name === 'config') {
    const editor = document.getElementById('configEditor');
    if (editor) editor.value = JSON.stringify(config, null, 2);
    renderSystemInfo();
  }
}

function tokenHeaders() {
  const stored = localStorage.getItem(AUTH_TOKEN_KEY) || '';
  const field = document.getElementById('token')?.value.trim() || '';
  const t = stored || field;
  return t ? {Authorization: `Bearer ${t}`} : {};
}
async function api(path, opts = {}) {
  opts.headers = {...(opts.headers || {}), ...tokenHeaders()};
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
  const r = await fetch(path, opts);
  if (r.status === 401) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    currentUser = null;
    renderHeaderAuthBox();
  }
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
}
function opt(select, value, label) { const o = document.createElement('option'); o.value=value; o.textContent=label || value; select.appendChild(o); }
function fillSelects() {
  for (const id of ['agentProfile','workspaceProfile','sessionSourceContext']) { const el=document.getElementById(id); if(el) el.innerHTML = id === 'sessionSourceContext' ? '<option value="">none</option>' : ''; }
  if (document.getElementById('taskRunner')) document.getElementById('taskRunner').innerHTML = '<option value="">PAC/local</option>'; 
  document.getElementById('modelOverride').innerHTML = '<option value="">profile default</option>';
  if (document.getElementById('taskModel')) document.getElementById('taskModel').innerHTML = '<option value="">session model</option>';
  if (document.getElementById('sessionEndpoint')) document.getElementById('sessionEndpoint').innerHTML = '<option value="">select endpoint</option>';
  if (document.getElementById('sessionTopSelect')) document.getElementById('sessionTopSelect').innerHTML = '<option value="">Select session</option>';
  document.getElementById('permissionOverride').innerHTML = '<option value="">profile default</option>';
  if (document.getElementById('profileModel')) profileModel.innerHTML = '';
  if (document.getElementById('profilePlannerModel')) profilePlannerModel.innerHTML = '<option value="">same as model</option>';
  if (document.getElementById('profileContextProfile')) profileContextProfile.innerHTML = '';
  if (document.getElementById('profilePlannerContextProfile')) profilePlannerContextProfile.innerHTML = '<option value="">same as profile</option>';
  if (document.getElementById('profilePermission')) profilePermission.innerHTML = '';
  if (document.getElementById('profileTools') && profileTools.tagName === 'SELECT') profileTools.innerHTML = '';
  if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') runnerTools.innerHTML = '';
  if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.innerHTML = '<option value="">auto</option>';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.innerHTML = '<option value="">none</option>';
  if (document.getElementById('toolPackage')) toolPackage.innerHTML = '<option value="">none</option>';
  Object.entries(config.agent_profiles || {}).forEach(([k,p]) => { if (p?.model && modelAvailability(p.model).ok) { opt(agentProfile,k); const wd=document.getElementById('workspaceDefaultProfile'); if (wd) opt(wd,k); } });
  Object.keys(config.workspaces || {}).forEach(k => { if (document.getElementById('workspaceProfile')) opt(workspaceProfile,k); if (document.getElementById('runnerDefaultWorkspace')) opt(runnerDefaultWorkspace,k); });
  Object.entries(config.source_contexts || {}).forEach(([k,ctx]) => {
    const label = [k, ctx.customer_id || '', ctx.workspace_profile || ''].filter(Boolean).join(' · ');
    if (document.getElementById('sessionSourceContext')) opt(sessionSourceContext, k, label);
  });
  Object.keys(config.models || {}).forEach(k => { if (modelAvailability(k).ok) { opt(modelOverride,k); if (document.getElementById('taskModel')) opt(taskModel,k); } if (document.getElementById('profileModel')) opt(profileModel,k, `${k}${modelAvailability(k).ok ? '' : ' (not available)'}`); if (document.getElementById('profilePlannerModel')) opt(profilePlannerModel,k, `${k}${modelAvailability(k).ok ? '' : ' (not available)'}`); });
  if (document.getElementById('modelProvider')) { modelProvider.innerHTML=''; Object.keys(config.providers || {}).forEach(k => opt(modelProvider,k)); }
  fillModelEndpointOptions();
  Object.keys(config.permission_profiles || {}).forEach(k => { opt(permissionOverride,k); if (document.getElementById('profilePermission')) opt(profilePermission,k); });
  Object.keys(config.context_profiles || {}).forEach(k => { if (document.getElementById('profileContextProfile')) opt(profileContextProfile,k); if (document.getElementById('profilePlannerContextProfile')) opt(profilePlannerContextProfile,k); });
  Object.keys(config.tool_packages || {}).forEach(k => { if (document.getElementById('toolPackage')) opt(toolPackage,k); });
  Object.entries(config.tools || {}).forEach(([k,t]) => {
    const label = `${k}${t.package ? ' · '+t.package : ''}${t.enabled === false ? ' (disabled)' : ''}`;
    if (document.getElementById('profileTools') && profileTools.tagName === 'SELECT') opt(profileTools,k,label);
    if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') opt(runnerTools,k,label);
  });
  syncSessionPermissionQuick();
}
function emitUiEvent(type, message, data=null) {
  window.__pacLastUiEvent = {
    id: `${type}_${Date.now()}_${Math.random()}`,
    type,
    message: message || prettyEventType(type),
    created_at: new Date().toISOString(),
    session_id: 'system',
    data: data ? {details: data, source: 'ui'} : {source: 'ui'},
  };
  if (document.getElementById('eventsRail') && !document.getElementById('eventsRail')?.hidden) {
    loadGlobalEvents(true).catch(()=>{});
  }
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

function providerIsSessionCapable(provider) {
  const type = String(provider?.type || '');
  return ['openai','openai-codex','openai-compatible','lmstudio','vllm','groq','openrouter','deepseek','mistral','ollama'].includes(type);
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
function configuredModelMatchesProviderModel(providerName, modelId) {
  return !!findConfiguredModelByProviderModel(providerName, modelId);
}
function normalizedProviderModelCandidates(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return [];
  const clean = raw.replace(/\\/g, '/');
  const base = clean.includes('/') ? clean.split('/').pop() : clean;
  const compact = clean.replace(/[^a-z0-9]+/g, '');
  const baseCompact = base.replace(/[^a-z0-9]+/g, '');
  return Array.from(new Set([raw, clean, base, compact, baseCompact].filter(Boolean)));
}
function findConfiguredModelByProviderModel(providerName, modelId, excludeName='') {
  const candidates = new Set(normalizedProviderModelCandidates(modelId));
  return Object.entries(config.models || {}).find(([name, item]) => {
    if (excludeName && name === excludeName) return false;
    if (item.provider !== providerName) return false;
    const values = [
      name,
      item.model || '',
      providerModelKey(item.provider, item.model || ''),
      providerModelKey(item.provider, name),
    ];
    return values.some(value => normalizedProviderModelCandidates(value).some(candidate => candidates.has(candidate)));
  }) || null;
}
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
async function refreshProviderHealth(name, provider) {
  try {
    const health = await api(`/v1/providers/${encodeURIComponent(name)}/test`, {method:'POST'});
    let inspect = null;
    if (provider?.type === 'lmstudio') inspect = await api(`/v1/providers/${encodeURIComponent(name)}/lmstudio/inspect`).catch(()=>null);
    providerHealthCache.set(name, {...health, inspect, checked_at:new Date().toISOString()});
  } catch (error) {
    providerHealthCache.set(name, {ok:false, error:error.message || String(error), checked_at:new Date().toISOString()});
  }
  renderProviders();
  renderModels();
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
function renderModels() {
  const el = document.getElementById('models'); if (!el) return; el.innerHTML = '';
  const configured = document.createElement('div');
  configured.innerHTML = '<h3>Configured models</h3>';
  for (const [name,m] of Object.entries(config.models || {})) {
    const wrap=document.createElement('div'); wrap.className='model-card clickable-row';
    { const av = modelAvailability(name); wrap.innerHTML = `<code>${name} ${av.ok ? '' : '[not available]'}\nprovider: ${m.provider}\nmodel id: ${m.model || '-'}\nexecution endpoint: ${endpointName(m.runs_on)}\ncontext: ${m.context_window}\nmax out: ${m.max_output_tokens}${av.ok ? '' : `\nreason: ${av.reason}`}</code>`; }
    wrap.onclick=()=>openModelModal(name);
    const actions=document.createElement('div'); actions.className='button-row';
    const edit=document.createElement('button'); edit.textContent='Edit'; edit.onclick=(ev)=>{ ev.stopPropagation(); openModelModal(name); };
    const b=document.createElement('button'); b.textContent='Test model'; b.className='ghost-button'; b.onclick=async(ev)=>{ ev.stopPropagation(); const r=await api(`/v1/models/${name}/test`,{method:'POST'}); showInline('modelFormResult', {model:name, ...r}); };
    actions.appendChild(edit); actions.appendChild(b);
    const provider = config.providers?.[m.provider || ''];
    if (provider?.type === 'lmstudio') {
      const load=document.createElement('button'); load.textContent='Load in LM Studio'; load.className='ghost-button'; load.onclick=(ev)=>{ ev.stopPropagation(); loadLmStudioModelByName(name).catch(e=>alert(e.message)); };
      actions.appendChild(load);
    }
    wrap.appendChild(actions); configured.appendChild(wrap);
  }
  el.appendChild(configured);
  const live = document.createElement('div');
  live.innerHTML = '<h3>Live server models</h3><div id="liveModels" class="remote-models">Loading live model lists…</div>';
  el.appendChild(live);
  renderLiveModels().catch(()=>{});
}
async function renderLiveModels() {
  const live = document.getElementById('liveModels');
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
}
function providerLabel(providerName) {
  const provider = config.providers?.[providerName];
  return provider ? `${providerName} (${provider.type || 'provider'})` : providerName;
}
function providerModelKey(providerName, modelId) {
  return `${providerName}-${String(modelId || '').replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase()}`.replace(/^-+|-+$/g,'');
}
function openModelDraft(providerName, modelId) {
  openModelModal();
  modelProvider.value = providerName;
  modelId.value = modelId;
  modelName.value = providerModelKey(providerName, modelId) || String(modelId || '').replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
  modelRunsOn.value = '';
  setModalStatus('modelModalStatus', 'Review and save this model.');
}
function groupedSessionsBy(field) {
  const rows = new Map();
  for (const session of (window.__pacSessions || [])) {
    const key = String(session?.[field] || session?.metadata?.[field] || '').trim() || '(none)';
    const current = rows.get(key) || {count:0, running:0, failed:0, items:[]};
    current.count += 1;
    if (session.status === 'running') current.running += 1;
    if (session.status === 'failed') current.failed += 1;
    current.items.push(session);
    rows.set(key, current);
  }
  return rows;
}
async function inspectLmStudioModelByName(name) {
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/inspect`);
  showInline('modelFormResult', {model:name, lmstudio:r});
  return r;
}
async function unloadLmStudioModelByName(name) {
  const model = config.models?.[name];
  if (!model) throw new Error('Model not found');
  const instanceId = prompt('Instance id / loaded model id to unload', model.model || name);
  if (!instanceId) return null;
  const r = await api(`/v1/models/${encodeURIComponent(name)}/lmstudio/unload`, {method:'POST', body:JSON.stringify({instance_id: instanceId})});
  showInline('modelFormResult', {model:name, lmstudio_unload:r});
  await loadGlobalEvents(true).catch(()=>{});
  return r;
}
function recommendationCardHtml(level, title, body, detail = '') {
  return `<article class="recommendation-card ${escapeHtml(level)}"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(body)}</p>${detail ? `<div class="muted small-text">${escapeHtml(detail)}</div>` : ''}</article>`;
}
async function renderUnconfiguredModelsPanelFromLive() {
  const target = document.getElementById('unconfiguredModelsList');
  if (!target) return;
  const providerEntries = Object.entries(config.providers || {}).filter(([_, provider]) => provider.enabled !== false);
  if (!providerEntries.length) {
    target.innerHTML = '<div class="muted">No enabled providers available.</div>';
    return;
  }
  target.innerHTML = '<div class="muted small-text">Checking live providers...</div>';
  const cards = [];
  for (const [providerName, provider] of providerEntries) {
    const result = await fetchProviderModels(providerName);
    if (!result.ok) continue;
    const rows = (result.models || []).filter(model => !configuredModelMatchesProviderModel(providerName, model.id || model.name || model.model));
    if (!rows.length) continue;
    const items = rows.map(model => {
      const modelId = model.id || model.name || model.model || 'unknown';
      const draftKey = providerModelKey(providerName, modelId);
      const summary = modelSummaryLine(model) || 'live provider model';
      return `<div class="inline-browser-row">
        <div><b>${escapeHtml(modelId)}</b><div class="muted small-text">${escapeHtml(summary)}</div></div>
        <div class="button-row inline-browser-group">
          <button class="ghost-button mini-button" data-open-live-model="${escapeHtml(providerName)}::${escapeHtml(modelId)}">Configure</button>
          <button class="mini-button" data-seed-live-model="${escapeHtml(providerName)}::${escapeHtml(modelId)}">${escapeHtml(draftKey)}</button>
        </div>
      </div>`;
    }).join('');
    cards.push(`<section class="remote-provider"><div class="provider-card-head"><div><b>${escapeHtml(providerLabel(providerName))}</b><div class="muted small-text">${rows.length} unconfigured model(s)</div></div><span class="pill ${providerIsSessionCapable(provider) ? 'ok-pill' : 'warn-pill'}">${providerIsSessionCapable(provider) ? 'session-ready' : 'limited'}</span></div>${items}</section>`);
  }
  target.innerHTML = cards.join('') || '<div class="muted">All provider models are already configured in PAC.</div>';
  target.querySelectorAll('[data-open-live-model]').forEach(btn => {
    btn.onclick = () => {
      const [providerName, modelId] = String(btn.dataset.openLiveModel || '').split('::');
      openModelDraft(providerName, modelId);
    };
  });
  target.querySelectorAll('[data-seed-live-model]').forEach(btn => {
    btn.onclick = () => {
      const [providerName, modelId] = String(btn.dataset.seedLiveModel || '').split('::');
      openModelDraft(providerName, modelId);
      modelName.focus();
      modelName.select();
    };
  });
}
function renderModelRecommendations() {
  const panel = document.getElementById('modelsRecommendationsPanel');
  const body = document.getElementById('modelsRecommendationsBody');
  if (!panel || !body) return;
  const recommendations = [];
  const models = Object.entries(config.models || {});
  const endpoints = window.__pacEndpoints || [];
  const sessions = window.__pacSessions || [];
  if (!models.length) {
    const enabledProviders = Object.entries(config.providers || {}).filter(([_, provider]) => provider.enabled !== false);
    if (enabledProviders.length) recommendations.push(recommendationCardHtml('info', 'No configured session models', 'Create at least one model from the live provider inventory so profiles and sessions can use it.', 'Use Browse providers or Marketplace from the Models area.'));
  }
  for (const [name, model] of models) {
    const availability = modelAvailability(name);
    const provider = config.providers?.[model.provider || ''];
    const endpoint = endpoints.find(item => item.id === model.runs_on);
    const sessionCount = sessions.filter(item => item.model === name).length;
    if (!availability.ok) recommendations.push(recommendationCardHtml('warn', `${name} is not currently available`, availability.reason || 'The provider is not returning this model.', `${providerLabel(model.provider || '-')}${sessionCount ? ` - ${sessionCount} session(s) reference it` : ''}`));
    if (provider?.type === 'lmstudio') {
      const runtime = model.extra?.lmstudio_runtime || {};
      if (!model.runs_on && endpoints.length > 1) recommendations.push(recommendationCardHtml('info', `Pin ${name} to an endpoint`, 'This LM Studio model is not pinned to a runtime endpoint, so PAC cannot make placement decisions consistently.', 'Select an execution endpoint in the model configuration.'));
      if (!runtime.gpu_offload && (endpoint?.capabilities?.gpu?.available || endpoint?.capabilities?.gpu?.devices?.length)) recommendations.push(recommendationCardHtml('info', `Tune ${name} for GPU use`, 'A GPU-capable endpoint is available, but the LM Studio runtime fields are still mostly default.', 'Review GPU offload, context, and batch sizing in the model form.'));
      if (runtime.context_length && model.context_window && Number(runtime.context_length) < Number(model.context_window)) recommendations.push(recommendationCardHtml('warn', `LM Studio load window is shorter for ${name}`, 'PAC is configured to expect a larger context window than the LM Studio runtime will load.', 'Raise the runtime context length or lower the configured model context to keep behavior consistent.'));
      if (!runtime.context_length && model.context_window) recommendations.push(recommendationCardHtml('info', `Set an explicit LM Studio load window for ${name}`, 'The model has a configured PAC context window, but the LM Studio load runtime still relies on implicit defaults.', 'Set the runtime context length so load behavior is predictable.'));
    }
    if (model.context_window && Number(model.context_window) >= 64000 && !model.runs_on && endpoints.length) recommendations.push(recommendationCardHtml('info', `Review placement for ${name}`, 'This model is configured with a large context window and should usually be tied to a known-capacity endpoint.', 'Pinning prevents weak endpoints from being chosen implicitly.'));
  }
  const liveProviderModels = Object.entries(config.providers || {}).reduce((count, [providerName, provider]) => count + ((provider.cached_models || []).filter(model => !configuredModelMatchesProviderModel(providerName, model.id || model.name || model.model)).length), 0);
  if (liveProviderModels > 0) recommendations.push(recommendationCardHtml('info', 'Additional provider models are available', `${liveProviderModels} live model(s) are visible from connected providers but not configured in PAC yet.`, 'Browse providers to promote them into session models.'));
  const visible = recommendations.slice(0, 6);
  const hiddenCount = Math.max(0, recommendations.length - visible.length);
  body.innerHTML = (visible.join('') || '<div class="muted small-text">No adaptation recommendations right now.</div>') + (hiddenCount ? `<div class="muted small-text recommendation-summary">+ ${hiddenCount} more recommendation(s). Resolve current issues to reduce this list.</div>` : '');
  panel.hidden = false;
}
function renderModelActiveSessionsPanel() {
  const target = document.getElementById('modelsActiveSessions');
  if (!target) return;
  const grouped = groupedSessionsBy('model');
  if (!grouped.size) {
    target.innerHTML = '<div class="muted small-text">No active or historical sessions yet.</div>';
    return;
  }
  target.innerHTML = Array.from(grouped.entries()).sort((a,b) => b[1].count - a[1].count).map(([name, info]) => `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${info.running} running - ${info.failed} failed</div></div><span class="pill">${info.count} session(s)</span></div>`).join('');
}
async function renderProvidersLivePanel() {
  const target = document.getElementById('providersLive');
  if (!target) return;
  const providers = Object.entries(config.providers || {});
  if (!providers.length) {
    target.innerHTML = '<div class="muted small-text">No providers configured.</div>';
    return;
  }
  const sections = [];
  for (const [name, provider] of providers) {
    const result = await fetchProviderModels(name);
    const models = result.ok ? (result.models || []) : [];
    const summary = models.length ? models.slice(0, 4).map(model => model.id || model.name || model.model).join(', ') : (result.ok ? 'No models returned' : (result.error || 'Model listing failed'));
    sections.push(`<div class="inline-browser-row"><div><b>${escapeHtml(providerLabel(name))}</b><div class="muted small-text">${escapeHtml(summary)}</div></div><span class="pill ${result.ok ? 'ok-pill' : 'warn-pill'}">${result.ok ? `${models.length} live` : 'error'}</span></div>`);
  }
  target.innerHTML = sections.join('');
}
function renderProfileUsagePanel() {
  const target = document.getElementById('profilesUsage');
  if (!target) return;
  const grouped = groupedSessionsBy('agent_profile');
  const profiles = Object.entries(config.agent_profiles || {});
  if (!profiles.length) {
    target.innerHTML = '<div class="muted small-text">No profiles configured.</div>';
    return;
  }
  target.innerHTML = profiles.map(([name, profile]) => {
    const usage = grouped.get(name) || {count:0, running:0, failed:0};
    return `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${escapeHtml(profile.model || '-')} - ${escapeHtml(profile.permission_profile || '-')}</div></div><span class="pill">${usage.count} session(s)</span></div>`;
  }).join('');
}
function renderWorkspaceActivityPanel() {
  const target = document.getElementById('workspacesActive');
  if (!target) return;
  const sessions = window.__pacSessions || [];
  const workspaces = Object.entries(config.workspaces || {});
  if (!workspaces.length) {
    target.innerHTML = '<div class="muted small-text">No workspaces configured.</div>';
    return;
  }
  target.innerHTML = workspaces.map(([name, workspace]) => {
    const count = sessions.filter(session => {
      const path = String(session.workspace_path || '');
      return path === String(workspace.path || '') || path.includes(name);
    }).length;
    const placement = workspace.endpoint_id || workspace.endpoint_selector || 'runtime';
    return `<div class="inline-browser-row"><div><b>${escapeHtml(name)}</b><div class="muted small-text">${escapeHtml(workspace.type || 'local')} - ${escapeHtml(placement)}</div></div><span class="pill">${count} session(s)</span></div>`;
  }).join('');
}
function renderModels() {
  const el = document.getElementById('models');
  if (!el) return;
  el.className = 'model-card-grid';
  const models = Object.entries(config.models || {});
  if (!models.length) {
    el.innerHTML = '<div class="muted">No configured models yet. Add one from Marketplace or Browse providers.</div>';
  } else {
    el.innerHTML = '';
    for (const [name, model] of models) {
      const availability = modelAvailability(name);
      const provider = config.providers?.[model.provider || ''];
      const health = providerHealthSummary(model.provider || '', provider || {});
      const sessionCount = (window.__pacSessions || []).filter(item => item.model === name).length;
      const card = document.createElement('article');
      card.className = 'model-card model-overview-card clickable-row';
      const runtime = model.extra?.lmstudio_runtime || {};
      const caps = [
        model.capabilities?.supports_chat ? ['chat', 'general chat and instruction following'] : null,
        model.capabilities?.supports_tools ? ['tool use', 'function and tool invocation'] : null,
        model.capabilities?.supports_vision ? ['pictures', 'image / vision input'] : null,
        model.capabilities?.supports_json ? ['json', 'structured JSON output'] : null,
        model.capabilities?.supports_streaming ? ['streaming', 'streaming output enabled'] : null,
        model.capabilities?.reasoning && model.capabilities.reasoning !== 'none' ? [`reasoning ${model.capabilities.reasoning}`, 'reasoning-oriented model'] : null,
      ].filter(Boolean).map(([label, title]) => `<span class="pill model-cap-pill" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`).join('');
      const cardMeta = [
        provider?.type ? `${provider.type}` : '',
        model.model || '',
      ].filter(Boolean).join(' • ');
      card.innerHTML = `<div class="provider-card-head"><div class="provider-title-block"><h3>${escapeHtml(name)}</h3><span class="muted">${escapeHtml(providerLabel(model.provider || '-'))}</span></div><span class="pill ${availability.ok ? 'ok-pill' : 'warn-pill'}">${escapeHtml(availability.ok ? 'available' : 'attention')}</span></div>
        <div class="provider-health-strip"><span class="pill ${escapeHtml(health.klass)}">${escapeHtml(health.pill)}</span><span class="small-text">${escapeHtml(health.detail)}</span></div>
        <div class="model-card-subline">${escapeHtml(cardMeta)}</div>
        ${caps ? `<div class="provider-pill-list model-cap-list">${caps}</div>` : ''}
        <div class="workspace-card-grid model-stats-grid">
          <div><small>model id</small><b>${escapeHtml(model.model || '-')}</b></div>
          <div><small>endpoint</small><b>${escapeHtml(endpointName(model.runs_on))}</b></div>
          <div><small>context</small><b>${escapeHtml(model.context_window || '-')}</b></div>
          <div><small>max output</small><b>${escapeHtml(model.max_output_tokens || '-')}</b></div>
          <div><small>reasoning</small><b>${escapeHtml(model.capabilities?.reasoning || 'none')}</b></div>
          <div><small>sessions</small><b>${escapeHtml(sessionCount || 0)}</b></div>
          <div><small>input price / 1M</small><b>${escapeHtml(model.input_price_per_million ?? '-')}</b></div>
          <div><small>output price / 1M</small><b>${escapeHtml(model.output_price_per_million ?? '-')}</b></div>
        </div>
        <div class="muted small-text">${escapeHtml(availability.ok ? 'Configured and visible to PAC.' : `Issue: ${availability.reason}`)}</div>
        ${provider?.type === 'lmstudio' ? `<div class="model-runtime-strip"><span>LM Studio</span><span>ctx ${escapeHtml(runtime.context_length || model.context_window || '-')}</span><span>gpu ${escapeHtml(runtime.gpu_offload || 'default')}</span><span>batch ${escapeHtml(runtime.eval_batch_size || runtime.batch_size || 'default')}</span><span>temp ${escapeHtml(runtime.temperature ?? 'default')}</span></div>` : ''}`;
      card.onclick = () => openModelModal(name);
      const actions = document.createElement('div');
      actions.className = 'button-row model-card-actions';
      const edit = document.createElement('button');
      edit.textContent = 'Edit';
      edit.onclick = ev => { ev.stopPropagation(); openModelModal(name); };
      const test = document.createElement('button');
      test.textContent = 'Test model';
      test.className = 'ghost-button';
      test.onclick = async ev => { ev.stopPropagation(); const r = await api(`/v1/models/${name}/test`, {method:'POST'}); showInline('modelFormResult', {model:name, ...r}); };
      actions.appendChild(edit);
      actions.appendChild(test);
      if (provider?.type === 'lmstudio') {
        const inspect = document.createElement('button');
        inspect.textContent = 'Inspect';
        inspect.className = 'ghost-button mini-button';
        inspect.onclick = ev => { ev.stopPropagation(); inspectLmStudioModelByName(name).catch(e => alert(e.message)); };
        const load = document.createElement('button');
        load.textContent = 'Load';
        load.className = 'ghost-button mini-button';
        load.onclick = ev => { ev.stopPropagation(); loadLmStudioModelByName(name).catch(e => alert(e.message)); };
        const unload = document.createElement('button');
        unload.textContent = 'Unload';
        unload.className = 'ghost-button mini-button';
        unload.onclick = ev => { ev.stopPropagation(); unloadLmStudioModelByName(name).catch(e => alert(e.message)); };
        actions.appendChild(inspect);
        actions.appendChild(load);
        actions.appendChild(unload);
      }
      card.appendChild(actions);
      el.appendChild(card);
    }
  }
  renderModelRecommendations();
  renderModelActiveSessionsPanel();
  renderLiveModels().catch(()=>{});
  renderUnconfiguredModelsPanelFromLive().catch(()=>{});
}
async function renderLiveModels() {
  const live = document.getElementById('modelsLive');
  if (!live) return;
  const providers = Object.keys(config.providers || {});
  if (!providers.length) { live.textContent = 'No providers configured.'; return; }
  const chunks = [];
  for (const name of providers) {
    const result = await fetchProviderModels(name);
    if (!result.ok) {
      chunks.push(`<div class="remote-provider failed"><b>${escapeHtml(name)}</b><br><span>${escapeHtml(result.error || result.response?.error || 'model listing failed')}</span></div>`);
      continue;
    }
    const models = result.models || [];
    const rows = models.map(model => {
      const id = model.id || model.name;
      const key = providerModelKey(name, id);
      const configured = !!config.models?.[key] || Object.values(config.models || {}).some(item => item.provider === name && (item.model || '') === id);
      return `<li><button class="link-button" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${escapeHtml(id)}</button><button class="ghost-button mini-button" data-add-live-model="1" data-provider="${escapeHtml(name)}" data-model="${escapeHtml(id)}" data-key="${escapeHtml(key)}">${configured ? 'Edit' : 'Configure'}</button><span class="muted">${escapeHtml(modelSummaryLine(model))}</span></li>`;
    }).join('');
    chunks.push(`<div class="remote-provider"><b>${escapeHtml(name)}</b> <span class="pill ${models.length ? 'ok' : ''}">${models.length} models</span><ul>${rows || '<li class="muted">No models returned</li>'}</ul></div>`);
  }
  live.innerHTML = chunks.join('');
  live.querySelectorAll('button[data-model]').forEach(btn => {
    btn.onclick = () => openModelDraft(btn.dataset.provider, btn.dataset.model);
  });
  live.querySelectorAll('button[data-add-live-model]').forEach(btn => {
    btn.onclick = async () => openModelDraft(btn.dataset.provider, btn.dataset.model);
  });
}
function renderWorkspaces() {
  const el = document.getElementById('workspaces');
  if (!el) return;
  el.innerHTML = '';
  for (const [name,w] of Object.entries(config.workspaces || {})) {
    const lifecycle = w.ephemeral ? `ephemeral${w.ttl_hours ? `, ${w.ttl_hours}h TTL` : ''}` : 'persistent';
    const placement = w.endpoint_id || w.endpoint_selector || 'select at runtime';
    const data = w.data_bundle_url || w.data_bundle_path || 'none';
    const row = document.createElement('div');
    row.className = 'workspace-card clickable-row';
    row.innerHTML = `<div class="workspace-card-title"><b>${escapeHtml(name)}</b><span>${escapeHtml(lifecycle)}</span></div>
      <div class="workspace-card-grid">
        <div><small>type</small><b>${escapeHtml(w.type || 'local')}</b></div>
        <div><small>runtime</small><b>${escapeHtml(w.runtime || 'any')}</b></div>
        <div><small>placement</small><b>${escapeHtml(placement)}</b></div>
        <div><small>profile</small><b>${escapeHtml(w.default_agent_profile || '-')}</b></div>
      </div>
      <code>${escapeHtml(w.description || '')}${w.description ? '\n' : ''}path: ${escapeHtml(w.path || '-')}\nurl: ${escapeHtml(w.url || '-')}\nbranch: ${escapeHtml(w.branch || '-')}\ncontainer: ${escapeHtml(w.container_image || '-')}\ndata zip: ${escapeHtml(data)}\ndata path: ${escapeHtml(w.data_mount_path || '-')}\ndefault: ${w.is_default ? 'yes' : 'no'}</code>`;
    row.onclick = () => fillWorkspaceForm(name);
    el.appendChild(row);
  }
  renderWorkspaceActivityPanel();
}
function renderProfiles() {
  const el = document.getElementById('profiles');
  el.innerHTML = '';
  for (const [name,p] of Object.entries(config.agent_profiles || {})) {
    const av = p.model ? modelAvailability(p.model) : {ok:false, reason:'no model'};
    const valid = av.ok;
    const row = document.createElement('div');
    row.className = 'model-card clickable-row';
    row.innerHTML = `<code>${name} ${valid ? '' : '[not selectable]'}\nmodel: ${p.model}\ncontext: ${p.context_profile || p.context_mode}\npermissions: ${p.permission_profile}\ntools: ${(p.tools||[]).join(', ')}${valid ? '' : `\nreason: ${av.reason}`}</code>`;
    row.onclick = () => fillProfileForm(name);
    el.appendChild(row);
  }
  renderProfileUsagePanel();
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
  const pkgEl = document.getElementById('toolPackagesOverview');
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
    row.onclick=()=>fillToolForm(name);
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
  if ((pi.image_available || pi.available) && !pi.available) add('pi.dev image', 'available', false, 'The harness image is installed, but the runtime is not healthy yet.');
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
    lines.push(`pi image present: ${(pi.image_available || pi.available) ? 'yes' : 'no'}`);
    lines.push(`pi runtime ready: ${pi.available ? 'yes' : 'no'}`);
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
    modelSupportsChat.checked=true; modelSupportsTools.checked=false; modelSupportsVision.checked=false; modelSupportsJson.checked=false; modelSupportsStreaming.checked=true; modelReasoning.value='none'; modelInputPrice.value=''; modelOutputPrice.value=''; fillLmStudioRuntimeFields({});
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
  modelSupportsChat.checked=m.capabilities?.supports_chat !== false; modelSupportsTools.checked=!!m.capabilities?.supports_tools; modelSupportsVision.checked=!!m.capabilities?.supports_vision; modelSupportsJson.checked=!!m.capabilities?.supports_json;
  modelSupportsStreaming.checked=m.capabilities?.supports_streaming !== false;
  modelReasoning.value=m.capabilities?.reasoning || 'none';
  modelInputPrice.value=m.input_price_per_million ?? '';
  modelOutputPrice.value=m.output_price_per_million ?? '';
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
    setUpdatesDetail();
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
    setUpdatesDetail({title:'Previewed update', version:toVersion, entries:delta, body:`${result.filename || 'upload'} updates PAC from ${fromVersion} to ${toVersion}.`});
    return;
  }
  const rows = result.components.map(c => `<tr><td><code>${escapeHtml(c.path)}</code></td><td>${escapeHtml(c.kind)}</td><td>${escapeHtml(c.from_version || 'new')}</td><td>${escapeHtml(c.to_version || '-')}</td><td>${escapeHtml(c.status || '')}</td></tr>`).join('');
  box.innerHTML = `<div class="pack-summary">${result.component_count || result.components.length} source folder(s) ready from ${escapeHtml(result.filename || 'upload')}</div><table class="compact-table"><thead><tr><th>Source folder</th><th>Kind</th><th>From</th><th>To</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table>`;
  setUpdatesDetail({title:'Feature pack preview', version:result.root_version || '', body:`${result.component_count || result.components.length} source folder(s) are ready to apply.`});
}
function setUpdatesDetail(meta=null) {
  const title = document.getElementById('updatesDetailTitle');
  const version = document.getElementById('updatesDetailVersion');
  const body = document.getElementById('updatesDetailBody');
  const formatDetailBody = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const lines = raw.split('\n');
    const parts = [];
    let listItems = [];
    const flushList = () => {
      if (!listItems.length) return;
      parts.push(`<ul>${listItems.join('')}</ul>`);
      listItems = [];
    };
    const linkify = (text) => escapeHtml(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noreferrer">$1</a>');
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushList();
        return;
      }
      if (/^#{1,6}\s+/.test(trimmed)) {
        flushList();
        parts.push(`<div class="update-delta-title">${linkify(trimmed.replace(/^#{1,6}\s+/, ''))}</div>`);
        return;
      }
      const quoteLink = trimmed.match(/^"?([^":]+)"?:\s*(https?:\/\/\S+)$/);
      if (quoteLink) {
        flushList();
        const [, label, url] = quoteLink;
        parts.push(`<div><b>${escapeHtml(label)}</b>: <a href="${url}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a></div>`);
        return;
      }
      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        listItems.push(`<li>${linkify(trimmed.slice(2).trim())}</li>`);
        return;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        listItems.push(`<li>${linkify(trimmed.replace(/^\d+\.\s+/, ''))}</li>`);
        return;
      }
      flushList();
      parts.push(`<div>${linkify(trimmed)}</div>`);
    });
    flushList();
    return `<div class="small-text updates-detail-copy">${parts.join('')}</div>`;
  };
  if (!title || !version || !body) return;
  if (!meta) {
    title.textContent = 'Release details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Preview a PAC update or select an archive to inspect local preservation details.</div>';
    return;
  }
  title.textContent = meta.title || 'Release details';
  version.textContent = meta.version ? `v${meta.version}` : '';
  const entries = meta.entries || [];
  const bodyHtml = meta.html_body || null;
  const formattedBody = meta.body ? formatDetailBody(meta.body) : '';
  const linkBlock = bodyHtml ? `<div class="muted small-text updates-detail-links">${bodyHtml}</div>` : '';
  if (entries.length) {
    body.innerHTML = `${formattedBody}${formattedBody ? '<div class="updates-detail-divider"></div>' : ''}<div class="update-delta-list">${entries.map(entry => `<div class="update-delta-version"><div class="update-delta-title">${escapeHtml(entry.title || ('PAC v' + (entry.version || '')))}</div><ul>${(entry.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul></div>`).join('')}</div>${linkBlock ? `<div style="margin-top:.6rem">${linkBlock}</div>` : ''}`;
  } else {
    body.innerHTML = `${formattedBody || '<div class="muted small-text">No additional details available.</div>'}${linkBlock ? `<div style="margin-top:.6rem">${linkBlock}</div>` : ''}`;
  }
}
function setBackupDetail(meta=null) {
  const title = document.getElementById('backupDetailTitle');
  const version = document.getElementById('backupDetailVersion');
  const body = document.getElementById('backupDetailBody');
  if (!title || !version || !body) return;
  if (!meta) {
    title.textContent = 'Backup details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Select a preserved backup to inspect downloads, local-change summary, or restore the controller.</div>';
    return;
  }
  title.textContent = meta.title || 'Backup details';
  version.textContent = meta.version ? `v${meta.version}` : '';
  body.innerHTML = meta.html_body ? `<div class="muted small-text">${meta.html_body}</div>` : (meta.body ? `<div class="muted small-text">${escapeHtml(meta.body)}</div>` : '<div class="muted small-text">No additional details available.</div>');
}
function renderLocalDiffs(data) {
  const list = document.getElementById('localDiffList');
  const status = document.getElementById('localDiffStatus');
  const input = document.getElementById('localDiffVersion');
  if (input && !input.value) input.value = data?.suggested_version || '';
  if (status) status.textContent = data?.suggested_version ? `Suggested release diff version: v${data.suggested_version}` : '';
  if (!list) return;
  const diffs = data?.diffs || [];
  if (!diffs.length) {
    list.innerHTML = '<div class="muted small-text">No generated local diffs yet. Generate one from the current workspace to prepare an online update or release patch.</div>';
    return;
  }
  list.innerHTML = diffs.map((item) => {
    const size = Number(item.size || 0).toLocaleString();
    const modified = item.modified_at ? formatEventTime(item.modified_at) : '';
    return `<button class="update-archive-row" data-local-diff="${escapeHtml(item.version)}"><b>v${escapeHtml(item.version)}</b><span class="muted small-text">${escapeHtml(size)} bytes${modified ? ` • ${escapeHtml(modified)}` : ''}</span></button>`;
  }).join('');
  list.querySelectorAll('[data-local-diff]').forEach(btn => btn.onclick = async () => {
    const version = btn.dataset.localDiff || '';
    const link = `/v1/updates/diff/${encodeURIComponent(version)}`;
    setUpdatesDetail({
      title: 'Generated local diff',
      version,
      body: `Use this diff as the source patch for the next PAC release/update packaging flow.`,
      html_body: `Download: <a href="${link}">v${escapeHtml(version)}.diff</a>`,
    });
  });
}
async function loadLocalDiffs() {
  const data = await api('/v1/updates/local-diffs');
  renderLocalDiffs(data);
  return data;
}
async function generateLocalDiffNow() {
  const input = document.getElementById('localDiffVersion');
  const status = document.getElementById('localDiffStatus');
  const button = document.getElementById('generateLocalDiff');
  const version = String(input?.value || '').trim().replace(/^v/i, '');
  if (!version) return paneError('A version is required to generate a local diff');
  if (!confirm(`Generate .pac/diffs/v${version}.diff from the current local PAC workspace?`)) return;
  if (button) { button.disabled = true; button.textContent = 'Generating…'; }
  if (status) status.textContent = 'Generating local diff…';
  try {
    const result = await api(`/v1/updates/generate-local-diff?version=${encodeURIComponent(version)}`, {method:'POST'});
    if (result.ok && result.status === 'written') {
      if (status) status.textContent = `Generated v${version}.diff`;
      setUpdatesDetail({
        title: 'Generated local diff',
        version,
        body: `The local workspace diff is ready for the release/update pipeline.`,
        html_body: `Download: <a href="/v1/updates/diff/${encodeURIComponent(version)}">v${escapeHtml(version)}.diff</a>`,
      });
      await loadLocalDiffs().catch(()=>{});
      return;
    }
    if (result.ok && result.status === 'no_diff') {
      if (status) status.textContent = 'No local differences found.';
      setUpdatesDetail({title:'Generated local diff', version, body:'No local differences were found against upstream main.'});
      await loadLocalDiffs().catch(()=>{});
      return;
    }
    if (status) status.textContent = result.error || 'Local diff generation failed.';
  } catch (e) {
    if (status) status.textContent = e.message || String(e);
    throw e;
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Generate local diff'; }
  }
}
function renderUpdateArchives(data) {
  const list = document.getElementById('updateArchivesList');
  const hint = document.getElementById('updateArchiveHint');
  const modalHint = document.getElementById('backupsModalHint');
  const badge = document.getElementById('pacArchiveStatus');
  const current = document.getElementById('pacCurrentVersion');
  if (current) current.textContent = `v${data?.current_version || config.setup_status?.version || '?'}`;
  if (!list || !badge) return;
  const archives = data?.archives || [];
  badge.textContent = archives.length ? `${archives.length} archived` : 'none yet';
  badge.className = `pac-status-badge ${archives.length ? 'current-badge' : ''}`.trim();
  if (hint) hint.textContent = archives.length ? `Latest archive: ${archives[0].stamp}` : 'No preserved controller archives yet.';
  if (modalHint) modalHint.textContent = archives.length ? `${archives.length} preserved backup(s) available.` : 'No preserved controller backups yet.';
  if (!archives.length) {
    list.innerHTML = '<div class="muted small-text">No update archives available yet. Archives will appear after PAC app updates are applied.</div>';
    setBackupDetail();
    return;
  }
  list.innerHTML = archives.map(item => {
    const summary = item.summary?.file_count || {};
    return `<button class="update-archive-row" data-update-archive="${escapeHtml(item.stamp)}"><b>${escapeHtml(item.stamp)}</b><span class="muted small-text">modified ${escapeHtml(String(summary.modified || 0))} • added ${escapeHtml(String(summary.added || 0))} • removed ${escapeHtml(String(summary.removed || 0))}</span></button>`;
  }).join('');
  list.querySelectorAll('[data-update-archive]').forEach(btn => btn.onclick = async () => {
    const stamp = btn.dataset.updateArchive;
    const detail = await api(`/v1/updates/archives/${encodeURIComponent(stamp)}`);
    const summary = detail.summary || {};
    const fileCount = summary.file_count || {};
    const links = [
      detail.archive_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=archive">backup.tar.gz</a>` : '',
      detail.diff_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=diff">user diff</a>` : '',
      detail.summary_path ? `<a href="/v1/updates/archives/${encodeURIComponent(stamp)}/download?kind=summary">summary json</a>` : '',
    ].filter(Boolean).join(' • ');
    setBackupDetail({
      title: 'Preserved local changes',
      version: '',
      html_body: `${escapeHtml(stamp)}<br>modified: ${escapeHtml(String(fileCount.modified || 0))}<br>added: ${escapeHtml(String(fileCount.added || 0))}<br>removed: ${escapeHtml(String(fileCount.removed || 0))}${links ? `<br><br>Downloads: ${links}` : ''}<br><br><button id="restoreBackupArchive" class="ghost-button">Restore this backup</button>`,
    });
    const restoreBtn = document.getElementById('restoreBackupArchive');
    if (restoreBtn) restoreBtn.onclick = () => restoreBackupArchive(stamp).catch(e=>paneError('Backup restore failed', e.message));
  });
}
async function loadUpdateArchives() {
  const data = await api('/v1/updates/status');
  renderUpdateArchives(data);
  const notes = await api('/v1/updates/release-notes').catch(()=>null);
  const fallbackBody = data?.latest_archive?.summary ? 'Latest preserved local change summary is available through Backups.' : '';
  setUpdatesDetail({
    title:'Current release',
    version:data?.current_version || config.version || config.setup_status?.version || '',
    entries:notes?.entries || [],
    body:notes?.body || fallbackBody,
    html_body:notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
  });
  if (!window.__pacReleaseMeta) checkPacRelease().catch(()=>{});
  setBackupDetail();
}
function openBackupsModal() {
  const modal = document.getElementById('backupsModal');
  if (modal) modal.hidden = false;
}
function closeBackupsModal() {
  const modal = document.getElementById('backupsModal');
  if (modal) modal.hidden = true;
}
async function restoreBackupArchive(stamp) {
  if (!stamp) return;
  if (!confirm(`Restore PAC from backup ${stamp}? The current app state will be preserved first, then PAC will restart.`)) return;
  const result = await api(`/v1/updates/archives/${encodeURIComponent(stamp)}/restore?restart_after_restore=true`, {method:'POST'});
  setBackupDetail({title:'Backup restore scheduled', body:`PAC scheduled a restart after restoring backup ${stamp}. Current app state was preserved before the restore.`});
  if (result.restart_scheduled) scheduleHiddenReloadAfterRestart();
}
function renderPacReleaseStatus(meta=null) {
  const applyBtn = document.getElementById('applyPacRelease');
  const status = document.getElementById('pacReleaseStatus');
  if (!status) return;
  if (!meta || !meta.ok) {
    status.textContent = meta?.error || 'GitHub release checks have not run yet.';
    if (applyBtn) applyBtn.disabled = true;
    return;
  }
    if (meta.has_update) {
      status.textContent = `Latest release: v${meta.latest_version}`;
      if (applyBtn) applyBtn.disabled = false;
      const currentVersion = meta.current_version || config?.version || config?.setup_status?.version || '';
      api(`/v1/updates/release-notes?from_version=${encodeURIComponent(currentVersion)}&to_version=${encodeURIComponent(meta.latest_version || '')}`)
        .then((notes) => {
          const fallbackChanges = (notes?.compare_changes || []).length ? (notes.compare_changes || []) : ((meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []));
          setUpdatesDetail({
            title:'Available release',
            version:meta.latest_version,
            entries:(notes?.entries || []).length ? (notes.entries || []) : (fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : []),
            body: notes?.body || meta.body || '',
            html_body: notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
          });
        })
        .catch(() => {
          const fallbackChanges = (meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []);
          setUpdatesDetail({title:'Available release', version:meta.latest_version, entries:fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : [], body: meta.body || ''});
        });
      return;
  }
  status.textContent = `PAC is up to date${meta.latest_version ? ` at v${meta.latest_version}` : ''}.`;
  if (applyBtn) applyBtn.disabled = true;
  if (meta.latest_version) {
    const currentVersion = meta.current_version || config?.version || config?.setup_status?.version || meta.latest_version;
    api(`/v1/updates/release-notes?from_version=0.0.0&to_version=${encodeURIComponent(meta.latest_version || '')}`)
      .then((notes) => {
        const fallbackChanges = (notes?.compare_changes || []).length ? (notes.compare_changes || []) : ((meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []));
        setUpdatesDetail({
          title:'Current release',
          version:meta.latest_version,
          entries:(notes?.entries || []).length ? (notes.entries || []) : (fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : []),
          body: notes?.body || meta.body || '',
          html_body: notes?.release_url ? `Release page: <a href="${notes.release_url}" target="_blank" rel="noreferrer">${notes.release_url}</a>` : '',
        });
      })
      .catch(() => {
        const fallbackChanges = (meta.changes || []).length ? (meta.changes || []) : (meta.compare_changes || []);
        setUpdatesDetail({title:'Current release', version:meta.latest_version, entries:fallbackChanges.length ? [{title:`PAC v${meta.latest_version}`, version:meta.latest_version, changes:fallbackChanges}] : [], body: meta.body || ''});
      });
  }
}
async function checkPacRelease() {
  const meta = await api('/v1/updates/check');
  window.__pacReleaseMeta = meta;
  renderPacReleaseStatus(meta);
}
async function applyPacRelease() {
  const meta = window.__pacReleaseMeta || {};
  if (!meta.has_update) return paneError('No PAC release update is currently available');
  const btn = document.getElementById('applyPacRelease');
  const proceed = document.getElementById('updateConfirmProceed');
  const cancel = document.getElementById('updateConfirmCancel');
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  if (proceed) { proceed.disabled = true; proceed.textContent = 'Applying…'; }
  if (cancel) cancel.hidden = true;
  try {
    const result = await api('/v1/updates/apply?restart_after_update=true', {method:'POST'});
    renderPacReleaseStatus({ok:true, has_update:false, latest_version:result.latest_version, body:'The selected PAC release has been applied and a restart was scheduled.'});
    if (result.preservation_archive || result.preservation_diff) {
      setUpdatesDetail({
        title: 'Release applied',
        version: result.latest_version || '',
        body: `PAC scheduled a restart after applying the latest release.\n\nPreservation archive: ${result.preservation_archive?.archive_path || '-'}\nUser diff: ${result.preservation_diff?.diff_path || '-'}`
      });
      await loadUpdateArchives().catch(()=>{});
    }
    if (result.restart_scheduled) {
      setUpdateConfirmOverlayRestarting(result.latest_version || meta.latest_version || '', 18);
      scheduleHiddenReloadAfterRestart(18);
    } else {
      closeUpdateConfirmOverlay(true);
    }
  } finally {
    if (btn) {
      btn.textContent = 'Apply latest release';
      btn.disabled = false;
    }
    if (!window.__pacRestartReloadTimer) {
      if (proceed) {
        proceed.disabled = false;
        proceed.textContent = 'Apply and restart';
      }
      if (cancel) cancel.hidden = false;
    }
  }
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
    if (result.preservation_archive || result.preservation_diff) {
      setUpdatesDetail({
        title: 'Update applied',
        version: result.preview?.target_version || result.preview?.root_version || '',
        body: `PAC scheduled a restart after applying this update.\n\nPreservation archive: ${result.preservation_archive?.archive_path || '-'}\nUser diff: ${result.preservation_diff?.diff_path || '-'}`
      });
      loadUpdateArchives().catch(()=>{});
    }
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
    resolveCurrentSourceContext().catch(()=>{});
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
function parseJsonObject(text, label) {
  const raw = String(text || '').trim();
  if (!raw) return {};
  let value;
  try { value = JSON.parse(raw); } catch (e) { throw new Error(`${label} must be valid JSON`); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be a JSON object`);
  return value;
}
function fillSourceContextForm(ctxName='') {
  const entry = (config.source_contexts || {})[ctxName] || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceContextName', ctxName);
  set('sourceContextPathPrefix', entry.path_prefix);
  set('sourceContextCustomerId', entry.customer_id);
  set('sourceContextUserScope', entry.user_scope);
  set('sourceContextProfile', entry.profile);
  set('sourceContextWorkspaceProfile', entry.workspace_profile);
  set('sourceContextEndpoint', entry.preferred_endpoint);
  set('sourceContextContainerImage', entry.container_image);
  set('sourceContextDescription', entry.description);
  set('sourceContextNotes', entry.notes);
  set('sourceContextConfigVars', JSON.stringify(entry.config_vars || {}, null, 2));
  set('sourceContextSecretRefs', JSON.stringify(entry.secret_refs || {}, null, 2));
  if (entry.profile && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'profile';
    document.getElementById('pacRamKey').value = entry.profile;
  } else if (entry.user_scope && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'user';
    document.getElementById('pacRamKey').value = entry.user_scope;
  } else if (entry.workspace_profile && document.getElementById('pacRamKind') && document.getElementById('pacRamKey')) {
    document.getElementById('pacRamKind').value = 'workspace';
    document.getElementById('pacRamKey').value = entry.workspace_profile;
  }
}
function renderSourceContexts() {
  const select = document.getElementById('sourceContextSelect');
  if (!select) return;
  const contexts = Object.entries(config.source_contexts || {}).sort((a,b)=>a[0].localeCompare(b[0]));
  const current = select.value || document.getElementById('sourceContextName')?.value || '';
  select.innerHTML = '<option value="">Select context</option>' + contexts.map(([name, ctx]) => `<option value="${escapeHtml(name)}">${escapeHtml(name)} (${escapeHtml(ctx.path_prefix || '-')})</option>`).join('');
  if (contexts.some(([name]) => name === current)) select.value = current;
}
async function saveSourceContextFromForm() {
  try {
    const name = document.getElementById('sourceContextName')?.value?.trim();
    if (!name) throw new Error('Context name is required');
    const body = {
      description: document.getElementById('sourceContextDescription')?.value?.trim() || null,
      path_prefix: document.getElementById('sourceContextPathPrefix')?.value?.trim() || '',
      customer_id: document.getElementById('sourceContextCustomerId')?.value?.trim() || null,
      user_scope: document.getElementById('sourceContextUserScope')?.value?.trim() || null,
      profile: document.getElementById('sourceContextProfile')?.value?.trim() || null,
      workspace_profile: document.getElementById('sourceContextWorkspaceProfile')?.value?.trim() || null,
      preferred_endpoint: document.getElementById('sourceContextEndpoint')?.value?.trim() || null,
      container_image: document.getElementById('sourceContextContainerImage')?.value?.trim() || null,
      config_vars: parseJsonObject(document.getElementById('sourceContextConfigVars')?.value, 'Config vars'),
      secret_refs: parseJsonObject(document.getElementById('sourceContextSecretRefs')?.value, 'Secret refs'),
      notes: document.getElementById('sourceContextNotes')?.value?.trim() || null,
    };
    await api(`/v1/source-contexts/${encodeURIComponent(name)}`, {method:'PUT', body: JSON.stringify(body)});
    await loadConfig();
    document.getElementById('sourceContextSelect').value = name;
    fillSourceContextForm(name);
    await resolveCurrentSourceContext();
  } catch (e) {
    paneError('Source context could not be saved', e.message || String(e));
  }
}
async function deleteSourceContextFromForm() {
  const name = document.getElementById('sourceContextName')?.value?.trim() || document.getElementById('sourceContextSelect')?.value || '';
  if (!name) return paneError('Select a source context first');
  if (!confirm(`Delete source context ${name}?`)) return;
  await api(`/v1/source-contexts/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadConfig();
  fillSourceContextForm('');
  const out = document.getElementById('sourceContextResolved');
  if (out) out.textContent = 'Select a source context to inspect the resolved environment bundle.';
}
async function resolveCurrentSourceContext() {
  const out = document.getElementById('sourceContextResolved');
  if (!out) return;
  const explicitName = document.getElementById('sourceContextSelect')?.value || document.getElementById('sourceContextName')?.value?.trim() || '';
  const path = selectedSourceEntry || selectedSourcePath || selectedSourceFolder || '';
  if (!explicitName && !path) {
    out.textContent = 'Select a context or a source path first.';
    return;
  }
  try {
    const qs = explicitName ? `name=${encodeURIComponent(explicitName)}` : `path=${encodeURIComponent(path)}`;
    const data = await api(`/v1/source-contexts/resolve?${qs}&include_secrets=false`);
    out.textContent = JSON.stringify(data, null, 2);
    if (data?.name) {
      const select = document.getElementById('sourceContextSelect');
      if (select) select.value = data.name;
      fillSourceContextForm(data.name);
    }
  } catch (e) {
    out.textContent = e.message || String(e);
  }
}
function fillSecretForm(secretId='') {
  const select = document.getElementById('sourceSecretSelect');
  if (select && secretId) select.value = secretId;
  const item = ((window.__pacSecrets || []).find(s => s.id === secretId)) || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceSecretId', secretId);
  set('sourceSecretValue', '');
  set('sourceSecretMeta', JSON.stringify(item.meta || {}, null, 2));
}
async function loadSourceSecrets() {
  const select = document.getElementById('sourceSecretSelect');
  const audit = document.getElementById('sourceSecretAudit');
  if (!select || !audit) return;
  const [secretData, auditData] = await Promise.all([api('/v1/secrets'), api('/v1/secrets/audit?limit=12')]);
  window.__pacSecrets = secretData.secrets || [];
  const current = select.value || document.getElementById('sourceSecretId')?.value || '';
  select.innerHTML = '<option value="">Select secret</option>' + (window.__pacSecrets || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}</option>`).join('');
  if ((window.__pacSecrets || []).some(item => item.id === current)) select.value = current;
  audit.textContent = (auditData.items || []).length ? (auditData.items || []).map(item => `${item.created_at}  ${item.event}  ${item.secret_id}`).join('\n') : 'No secret audit events loaded yet.';
}
function fillSourceVariableForm(variableId='') {
  const select = document.getElementById('sourceVariableSelect');
  if (select && variableId) select.value = variableId;
  const item = ((window.__pacSourceVariables || []).find(v => v.id === variableId)) || {};
  const set = (id, value='') => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  set('sourceVariableId', variableId);
  set('sourceVariableDescription', item.description || '');
  set('sourceVariableTags', Array.isArray(item.tags) ? item.tags.join(', ') : '');
  set('sourceVariableValue', item.value || '');
}
async function loadSourceVariables() {
  const select = document.getElementById('sourceVariableSelect');
  const list = document.getElementById('sourceVariableList');
  if (!select || !list) return;
  const data = await api('/v1/source-variables');
  window.__pacSourceVariables = data.variables || [];
  const current = select.value || document.getElementById('sourceVariableId')?.value || '';
  select.innerHTML = '<option value="">Select variable</option>' + (window.__pacSourceVariables || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}</option>`).join('');
  if ((window.__pacSourceVariables || []).some(item => item.id === current)) select.value = current;
  list.textContent = (window.__pacSourceVariables || []).length
    ? (window.__pacSourceVariables || []).map(item => `${item.id}${item.tags?.length ? ` [${item.tags.join(', ')}]` : ''}`).join('\n')
    : 'No source variables loaded yet.';
}
async function saveSourceVariableFromForm() {
  try {
    const variableId = document.getElementById('sourceVariableId')?.value?.trim();
    const value = document.getElementById('sourceVariableValue')?.value ?? '';
    if (!variableId) throw new Error('Variable ID is required');
    const description = document.getElementById('sourceVariableDescription')?.value?.trim() || '';
    const tags = String(document.getElementById('sourceVariableTags')?.value || '').split(',').map(v => v.trim()).filter(Boolean);
    await api(`/v1/source-variables/${encodeURIComponent(variableId)}`, {method:'PUT', body: JSON.stringify({value, description, tags})});
    await loadSourceVariables();
    fillSourceVariableForm(variableId);
    await resolveCurrentSourceContext().catch(()=>{});
  } catch (e) {
    paneError('Source variable could not be saved', e.message || String(e));
  }
}
async function deleteSourceVariableFromForm() {
  const variableId = document.getElementById('sourceVariableId')?.value?.trim() || document.getElementById('sourceVariableSelect')?.value || '';
  if (!variableId) return paneError('Select a source variable first');
  if (!confirm(`Delete source variable ${variableId}?`)) return;
  await api(`/v1/source-variables/${encodeURIComponent(variableId)}`, {method:'DELETE'});
  await loadSourceVariables();
  fillSourceVariableForm('');
  await resolveCurrentSourceContext().catch(()=>{});
}
async function loadPacRam() {
  const kind = document.getElementById('pacRamKind')?.value || 'profile';
  const key = document.getElementById('pacRamKey')?.value?.trim() || '';
  const content = document.getElementById('pacRamContent');
  const summary = document.getElementById('pacRamSummary');
  if (!key) return paneError('PAC RAM key is required');
  const data = await api(`/v1/pac-ram/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`);
  if (content) content.value = data.content || '';
  if (summary) summary.textContent = `${data.kind}:${data.key}\n${data.path}\nUpdated ${data.updated_at || '-'}`;
}
async function loadPacRamIndex() {
  const summary = document.getElementById('pacRamSummary');
  if (!summary) return;
  const data = await api('/v1/pac-ram/list');
  const lines = [
    `profiles: ${(data.profiles || []).join(', ') || '-'}`,
    `users: ${(data.users || []).join(', ') || '-'}`,
    `workspaces: ${(data.workspaces || []).join(', ') || '-'}`,
  ];
  if (!document.getElementById('pacRamContent')?.value?.trim()) summary.textContent = lines.join('\n');
}
async function savePacRamFromForm() {
  try {
    const kind = document.getElementById('pacRamKind')?.value || 'profile';
    const key = document.getElementById('pacRamKey')?.value?.trim() || '';
    const content = document.getElementById('pacRamContent')?.value ?? '';
    const summary = document.getElementById('pacRamSummary');
    if (!key) throw new Error('PAC RAM key is required');
    const data = await api(`/v1/pac-ram/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`, {method:'PUT', body: JSON.stringify({content})});
    if (summary) summary.textContent = `${data.kind}:${data.key}\n${data.path}\nUpdated ${data.updated_at || '-'}`;
    await loadPacRamIndex().catch(()=>{});
  } catch (e) {
    paneError('PAC RAM could not be saved', e.message || String(e));
  }
}
async function saveSourceSecretFromForm() {
  try {
    const secretId = document.getElementById('sourceSecretId')?.value?.trim();
    const value = document.getElementById('sourceSecretValue')?.value ?? '';
    if (!secretId) throw new Error('Secret ID is required');
    if (!value) throw new Error('Secret value is required when saving');
    const meta = parseJsonObject(document.getElementById('sourceSecretMeta')?.value, 'Secret meta');
    await api(`/v1/secrets/${encodeURIComponent(secretId)}`, {method:'PUT', body: JSON.stringify({value, meta})});
    await loadSourceSecrets();
    fillSecretForm(secretId);
  } catch (e) {
    paneError('Secret could not be saved', e.message || String(e));
  }
}
async function deleteSourceSecretFromForm() {
  const secretId = document.getElementById('sourceSecretId')?.value?.trim() || document.getElementById('sourceSecretSelect')?.value || '';
  if (!secretId) return paneError('Select a secret first');
  if (!confirm(`Delete secret ${secretId}?`)) return;
  await api(`/v1/secrets/${encodeURIComponent(secretId)}`, {method:'DELETE'});
  await loadSourceSecrets();
  fillSecretForm('');
}
function renderMarketplaceResults(data) {
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  const results = data?.results || [];
  if (!results.length) {
    el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
    return;
  }
  el.innerHTML = results.map(item => {
    const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
    const quants = (item.available_quants || []).slice(0, 5).map(q => `<span class="marketplace-pill">${escapeHtml(q.toUpperCase())}</span>`).join('');
    return `<article class="marketplace-card"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></article>`;
  }).join('');
}
async function searchMarketplace() {
  const query = document.getElementById('marketplaceQuery')?.value?.trim() || '';
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  el.textContent = 'Searching marketplace…';
  try {
    const data = await api(`/v1/models/marketplace/search?q=${encodeURIComponent(query)}&limit=12`);
    renderMarketplaceResults(data);
  } catch (e) {
    el.textContent = e.message || String(e);
  }
}
function openMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = false;
  const input = document.getElementById('marketplaceModalQuery');
  if (input) input.value = document.getElementById('marketplaceQuery')?.value || '';
  renderMarketplaceModalDetail();
}
function closeMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = true;
}
function renderMarketplaceModalDetail(detail=null) {
  const title = document.getElementById('marketplaceDetailTitle');
  const version = document.getElementById('marketplaceDetailVersion');
  const body = document.getElementById('marketplaceDetailBody');
  if (!title || !version || !body) return;
  if (!detail) {
    title.textContent = 'Model details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Select a marketplace result to inspect provider fit and configure it as a PAC model.</div>';
    return;
  }
  title.textContent = detail.model_id || 'Model details';
  version.textContent = detail.params_b ? `${detail.params_b}B` : '';
  const providers = (detail.provider_scores || []).map(entry => {
    const provider = entry.provider || {};
    return `<tr><td><code>${escapeHtml(provider.name || '-')}</code></td><td>${escapeHtml(provider.type || '-')}</td><td>${escapeHtml(entry.quant_recommended || '-')}</td><td>${escapeHtml(entry.reason || '-')}</td></tr>`;
  }).join('');
  body.innerHTML = `<div class="muted small-text">Author: ${escapeHtml(detail.author || 'unknown')} • Downloads: ${escapeHtml(String(detail.downloads || 0))}</div><div class="marketplace-meta" style="margin:.6rem 0">${Object.entries(detail.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('')}</div><table class="compact-table"><thead><tr><th>Provider</th><th>Type</th><th>Quant</th><th>Fit</th></tr></thead><tbody>${providers || '<tr><td colspan="4" class="muted">No providers configured yet.</td></tr>'}</tbody></table><div class="button-row" style="margin-top:.75rem"><button id="configureMarketplaceModel">Configure as model</button></div>`;
  const btn = document.getElementById('configureMarketplaceModel');
  if (btn) btn.onclick = () => {
    const preferred = (detail.provider_scores || []).find(entry => entry.can_run && entry.provider?.name)?.provider?.name
      || (detail.provider_scores || [])[0]?.provider?.name
      || '';
    closeMarketplaceModal();
    openModelModal();
    if (preferred && modelProvider) modelProvider.value = preferred;
    if (modelId) modelId.value = detail.model_id || '';
    if (modelName) modelName.value = String(detail.model_id || '').replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
  };
}
async function searchMarketplaceModal() {
  const query = document.getElementById('marketplaceModalQuery')?.value?.trim() || '';
  const el = document.getElementById('marketplaceModalResults');
  if (!el) return;
  el.textContent = 'Searching marketplace...';
  try {
    const data = await api(`/v1/models/marketplace/search?q=${encodeURIComponent(query)}&limit=18`);
    const results = data?.results || [];
    if (!results.length) {
      el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
      return;
    }
    el.innerHTML = results.map(item => {
      const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
      return `<button class="marketplace-card marketplace-card-button" data-marketplace-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads</div></button>`;
    }).join('');
    el.querySelectorAll('[data-marketplace-model]').forEach(btn => btn.onclick = async () => {
      const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(btn.dataset.marketplaceModel || '')}`);
      renderMarketplaceModalDetail(detail);
    });
  } catch (e) {
    el.textContent = e.message || String(e);
  }
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
default: ${w.is_default ? 'yes' : 'no'}</code>`;
    row.onclick = () => fillWorkspaceForm(name);
    el.appendChild(row);
  }
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
    row.innerHTML = `<code>${name} ${valid ? '' : '[not selectable]'}\nmodel: ${p.model}${p.planner_model ? `\nplanner: ${p.planner_model}` : ''}\ncontext: ${p.context_profile || p.context_mode}${p.planner_context_profile ? `\nplanner context: ${p.planner_context_profile}` : ''}\npermissions: ${p.permission_profile}\ntools: ${(p.tools||[]).join(', ')}${valid ? '' : `\nreason: ${av.reason}`}</code>`;
    row.onclick = () => fillProfileForm(name);
    el.appendChild(row);
  }
}
function fillProfileForm(name) {
  const p = config.agent_profiles?.[name]; if (!p) return;
  profileName.value = name; profileModel.value = p.model || ''; profileContextProfile.value = p.context_profile || 'medium'; profileContextMode.value = p.context_mode || 'medium';
  if (document.getElementById('profilePlannerModel')) profilePlannerModel.value = p.planner_model || '';
  if (document.getElementById('profilePlannerContextProfile')) profilePlannerContextProfile.value = p.planner_context_profile || '';
  profilePermission.value = p.permission_profile || 'ask-first'; setSelectedToolNames(p.tools || []); profileSystemPrompt.value = p.system_prompt || 'You are a careful remote coding and infrastructure agent.';
}

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
    const piMissing = piContainer && !(piContainer.image_available || piContainer.available);
    const featureChips = endpointFeatureChips(r, effectiveTools);
    card.innerHTML = `<div class="endpoint-head"><div><h3>${escapeHtml(r.name)}</h3><div class="muted small-text">${escapeHtml(r.id)}</div></div><div><span class="pill ${r.status === 'online' ? 'ok-pill' : ''}">${escapeHtml(r.status)}</span>${localBadge}</div></div>
      <div class="endpoint-features">${featureChips}</div>
      <div class="endpoint-meta"><span>execution environment</span><span>v ${escapeHtml(version)}</span><span>${escapeHtml((r.labels||[]).join(', ') || 'no labels')}</span><span>seen ${escapeHtml(lastSeen)}</span></div>
      <div class="endpoint-meta"><span class="pill ${agentClass}">pi.dev ${escapeHtml(enablement.status || 'disabled')}</span><span>wrapper ${escapeHtml(wrapperText)}</span><span>${enablement.required ? 'required' : 'optional'}</span><span>commands controller-queued</span></div>
      <div class="hardware-grid"><div><b>CPU</b><span>${escapeHtml(hw.cpu)}</span><small>${escapeHtml(hw.cores)} threads</small></div><div><b>GPU</b><span>${escapeHtml(hw.gpu)}</span></div><div><b>RAM</b><span>${escapeHtml(hw.ram)}</span></div><div><b>Disk</b><span>${escapeHtml(hw.disk)}</span></div></div>
      <details><summary>Runtime details</summary><pre>${escapeHtml(runtimeLines)}</pre><div class="muted small-text">pi.dev: ${escapeHtml(enablement.detail || '-')}</div><div class="muted small-text">tools: ${escapeHtml(tools)}</div><div class="muted small-text">packages: ${escapeHtml(packages)}</div><div class="muted small-text">workspace: ${escapeHtml(defaultWorkspace)}</div><div class="muted small-text">models: ${escapeHtml(modelLinks || '-')}</div><pre>${escapeHtml(containers || 'No running containers reported.')}</pre></details>
      <div class="endpoint-state">${updateStatus}${maintenanceStatus}${piMissing ? '<span class="pill warn-pill">pi.dev missing</span>' : ''}</div>`;
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
  renderModelRecommendations();
  renderWorkspaceActivityPanel();
  renderProvidersLivePanel().catch(()=>{});
}



function renderStatCards(metrics) {
  const el = document.getElementById('dashboardStats');
  if (!el) return;
  const health = metrics.component_health || {};
  const providers = health.providers || {};
  const models = health.models || {};
  const endpoints = health.endpoints || {};
  const setup = health.setup || {};
  const updates = health.updates || {};
  const alerts = metrics.alert_counts || {};
  const stats = [
    ['Sessions', metrics.sessions_total, `${metrics.sessions_active || 0} active`],
    ['Tasks', metrics.tasks_total, `${metrics.tasks_running || 0} running/queued`],
    ['Failed', metrics.tasks_failed, 'tasks failed'],
    ['Approvals', metrics.approvals_pending, 'pending'],
    ['Alerts', alerts.total ?? 0, `${alerts.critical ?? 0} critical`],
    ['Endpoints', metrics.endpoints_total, `${metrics.endpoints_online || 0} online`],
    ['Providers', providers.connected ?? 0, `${providers.enabled ?? 0} enabled`],
    ['Models', models.available ?? 0, `${models.session_capable ?? 0} session-ready`],
    ['Setup', setup.required_issues ?? 0, `${setup.warnings ?? 0} warnings`],
    ['Updates', updates.archives ?? 0, `${updates.local_diffs ?? 0} local diffs`],
  ];
  el.innerHTML = stats.map(([label,value,hint]) => `<div class="metric"><b>${value ?? 0}</b><span>${label}</span><small>${hint}</small></div>`).join('');
}
function renderHealthGrid(id, sections, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!sections || !sections.length) {
    el.textContent = emptyText || 'No data yet.';
    return;
  }
  el.innerHTML = sections.map(section => {
    const rows = (section.rows || []).map(row => {
      const tone = row.tone ? ` tone-${row.tone}` : '';
      return `<div class="health-row${tone}"><span>${escapeHtml(row.label || '')}</span><b>${escapeHtml(String(row.value ?? '-'))}</b></div>`;
    }).join('');
    return `<section class="health-section"><h3>${escapeHtml(section.title || '')}</h3>${rows}</section>`;
  }).join('');
}
function renderCriticalComponentHealth(metrics) {
  const health = metrics.component_health || {};
  const providers = health.providers || {};
  const models = health.models || {};
  const endpoints = health.endpoints || {};
  const controller = health.controller || {};
  renderHealthGrid('componentHealth', [
    {
      title: 'Providers',
      rows: [
        {label:'Connected', value: `${providers.connected ?? 0}/${providers.total ?? 0}`, tone:(providers.failed || 0) ? 'warn' : 'ok'},
        {label:'Failed', value: providers.failed ?? 0, tone:(providers.failed || 0) ? 'danger' : 'ok'},
        {label:'Disabled', value: providers.disabled ?? 0},
      ],
    },
    {
      title: 'Models',
      rows: [
        {label:'Available', value: `${models.available ?? 0}/${models.total ?? 0}`, tone:(models.unavailable || 0) ? 'warn' : 'ok'},
        {label:'Unavailable', value: models.unavailable ?? 0, tone:(models.unavailable || 0) ? 'danger' : 'ok'},
        {label:'Unsupported provider', value: models.unsupported_provider ?? 0, tone:(models.unsupported_provider || 0) ? 'warn' : 'ok'},
      ],
    },
    {
      title: 'Endpoints',
      rows: [
        {label:'Online', value: `${endpoints.online ?? 0}/${endpoints.total ?? 0}`, tone:(endpoints.offline || 0) ? 'warn' : 'ok'},
        {label:'Agent ready', value: endpoints.agent_ready ?? 0, tone:(endpoints.agent_blocked || 0) ? 'warn' : 'ok'},
        {label:'GPU capable', value: endpoints.gpu_capable ?? 0},
      ],
    },
    {
      title: 'Controller',
      rows: [
        {label:'Runtime', value: controller.runtime_status || 'unknown', tone:(controller.runtime_status === 'ready') ? 'ok' : ((controller.runtime_status === 'disabled') ? '' : 'warn')},
        {label:'Wrapper', value: controller.wrapper_running ? 'running' : 'stopped', tone:controller.wrapper_running ? 'ok' : 'warn'},
        {label:'pi.dev', value: controller.pi_dev_running ? 'running' : 'stopped', tone:controller.pi_dev_running ? 'ok' : 'warn'},
        {label:'Wrapper version', value: controller.wrapper_version || '-', tone:(controller.wrapper_version && controller.wrapper_version !== metrics.version) ? 'danger' : 'ok'},
      ],
    },
  ], 'No component health is available yet.');
}
function renderOpsReadiness(metrics) {
  const health = metrics.component_health || {};
  const setup = health.setup || {};
  const secrets = health.secrets || {};
  const source = health.source || {};
  const updates = health.updates || {};
  const alerts = metrics.alert_counts || {};
  renderHealthGrid('opsReadiness', [
    {
      title: 'Alerts',
      rows: [
        {label:'Critical', value: alerts.critical ?? 0, tone:(alerts.critical || 0) ? 'danger' : 'ok'},
        {label:'Warnings', value: alerts.warning ?? 0, tone:(alerts.warning || 0) ? 'warn' : 'ok'},
        {label:'Total', value: alerts.total ?? 0, tone:(alerts.total || 0) ? 'warn' : 'ok'},
      ],
    },
    {
      title: 'Setup',
      rows: [
        {label:'Required blockers', value: setup.required_issues ?? 0, tone:(setup.required_issues || 0) ? 'danger' : 'ok'},
        {label:'Warnings', value: setup.warnings ?? 0, tone:(setup.warnings || 0) ? 'warn' : 'ok'},
        {label:'Ready', value: setup.ready ? 'yes' : 'no', tone:setup.ready ? 'ok' : 'danger'},
      ],
    },
    {
      title: 'Secrets',
      rows: [
        {label:'Backend', value: secrets.backend_ready ? 'ready' : 'degraded', tone:secrets.backend_ready ? 'ok' : 'warn'},
        {label:'Stored', value: secrets.count ?? 0},
        {label:'Path', value: secrets.store_path ? 'configured' : 'missing'},
      ],
    },
    {
      title: 'Source state',
      rows: [
        {label:'Contexts', value: source.contexts ?? 0},
        {label:'Variables', value: source.variables ?? 0},
        {label:'PAC RAM', value: (source.ram_profiles || 0) + (source.ram_users || 0) + (source.ram_workspaces || 0)},
      ],
    },
    {
      title: 'Updates',
      rows: [
        {label:'Archives', value: updates.archives ?? 0},
        {label:'Local diffs', value: updates.local_diffs ?? 0},
        {label:'UI build', value: metrics.ui_build || currentVersionInfo?.ui_build || '-'},
      ],
    },
  ], 'No setup or update data is available yet.');
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
    renderCriticalComponentHealth(metrics);
    renderOpsReadiness(metrics);
  } catch (e) {
    const el = document.getElementById('dashboardStats');
    if (el) el.innerHTML = `<div class="muted">Could not load metrics: ${escapeHtml(e.message)}</div>`;
    const component = document.getElementById('componentHealth');
    if (component) component.innerHTML = `<div class="muted">Could not load component health: ${escapeHtml(e.message)}</div>`;
    const readiness = document.getElementById('opsReadiness');
    if (readiness) readiness.innerHTML = `<div class="muted">Could not load setup state: ${escapeHtml(e.message)}</div>`;
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
  applySessionBootstrapMode();
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
    'Backend version': currentVersionInfo?.version || config.version || '-',
    'UI build': currentVersionInfo?.ui_build || '-',
    'UI updated': currentVersionInfo?.ui_updated_at || '-',
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
  const baseStatus = status || controllerHarnessStatusCache;
  const liveStatus = baseStatus?.diagnostics?.status && typeof baseStatus.diagnostics.status === 'object'
    ? {...baseStatus, ...baseStatus.diagnostics.status, diagnostics: baseStatus.diagnostics}
    : baseStatus;
  const effectiveStatus = liveStatus;
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
  const runtimeBox = document.getElementById('controllerHarnessRuntime');
  const logsBox = document.getElementById('controllerHarnessLogs');
  const actionsBox = document.getElementById('controllerHarnessActions');
  if (box) {
    const session = effectiveStatus?.session;
    const runner = effectiveStatus?.runner;
    const diag = effectiveStatus?.diagnostics || {};
    const wrapperCap = runner?.capabilities?.pac_wrapper || {};
    const wrapperProc = diag.wrapper_process || {};
    const pi = runner?.capabilities?.pi_container || {};
    const runnerMeta = runner?.metadata || {};
    const wrapperVersion = runnerMeta.runner_version || runnerMeta.endpoint_version || '';
    const serverVersion = currentVersionInfo?.version || config?.version || config?.setup_status?.version || '';
    const versionMismatch = !!(wrapperVersion && serverVersion && wrapperVersion !== serverVersion);
    const wrapperText = wrapperCap.available
      ? (wrapperCap.path || wrapperProc.path || 'available')
      : (wrapperProc.available ? (wrapperProc.path || 'installed') : (wrapperCap.reason || 'missing'));
    const piText = (pi.image_available || pi.available)
      ? `${pi.image || 'available'}${pi.available ? '' : ' (image present, runtime not ready)'}`
      : (pi.reason || 'missing');
    const state = effectiveStatus ? (effectiveStatus.ok ? 'ready' : 'needs setup') : 'not checked';
    box.innerHTML = `
      <div class="pi-dev-status-banner ${escapeHtml(effectiveStatus?.ok ? 'ok' : 'warn')}">
        <div>
          <div class="pi-dev-status-kicker">Status</div>
          <div class="pi-dev-status-title">${escapeHtml(state)}</div>
          <div class="pi-dev-status-copy">${escapeHtml(effectiveStatus?.message || 'Saved settings are shown below.')}</div>
        </div>
      </div>
      ${versionMismatch ? `<div class="pi-dev-notice critical"><b>Wrapper version mismatch</b><span>PAC server is v${escapeHtml(serverVersion)}, but the local wrapper reports v${escapeHtml(wrapperVersion)}. Rebuild/install the local wrapper before trusting controller pi.dev readiness.</span></div>` : ''}
      <div class="pi-dev-kv-grid">
        <div><span>Runner</span><code>${escapeHtml(String(runner?.name || h.runner_id || '-'))}</code></div>
        <div><span>Session</span><code>${escapeHtml(String(session?.name || '-'))}</code></div>
        <div><span>Model</span><code>${escapeHtml(String(session?.model || h.model || 'profile default'))}</code></div>
        <div><span>Workspace</span><code>${escapeHtml(String(session?.workspace_path || '-'))}</code></div>
        <div><span>PAC wrapper</span><code>${escapeHtml(String(wrapperText))}</code></div>
        <div><span>Wrapper version</span><code>${escapeHtml(String(wrapperVersion || '-'))}</code></div>
        <div><span>pi.dev image</span><code>${escapeHtml(String(piText))}</code></div>
      </div>`;
    if (actionsBox) {
      actionsBox.dataset.needsAttention = effectiveStatus?.ok ? 'false' : 'true';
    }
  }
  if (runtimeBox) {
    const diag = effectiveStatus?.diagnostics || {};
    const wrapper = diag.wrapper_process || {};
    const daemon = diag.pi_daemon || {};
    const runnerMeta = effectiveStatus?.runner?.metadata || {};
    const agentRuntime = runnerMeta.agent_runtime || {};
    const rows = {
      'Wrapper state': wrapper.running ? 'running' : 'stopped',
      'Wrapper pid': wrapper.pid || '-',
      'Wrapper exit': wrapper.return_code ?? '-',
      'Wrapper binary': wrapper.path || '-',
      'pi.dev daemon': daemon.running ? 'running' : 'stopped',
      'pi.dev daemon pid': daemon.pid || '-',
      'Agent runtime': agentRuntime.status || '-',
      'Agent detail': agentRuntime.detail || '-',
      'Wrapper log': diag.wrapper_log || '-',
    };
    runtimeBox.innerHTML = `<div class="pi-dev-kv-grid">${Object.entries(rows).map(([k,v]) => `<div><span>${k}</span><code>${escapeHtml(String(v))}</code></div>`).join('')}</div>`;
  }
  if (logsBox) logsBox.textContent = effectiveStatus?.diagnostics?.wrapper_log_tail || '';
}

async function loadControllerHarnessStatus() {
  try {
    const [status, diagnostics] = await Promise.all([
      api('/v1/controller-harness'),
      api('/v1/controller-harness/diagnostics').catch(()=>null),
    ]);
    if (diagnostics) status.diagnostics = diagnostics;
    controllerHarnessStatusCache = status;
    renderControllerHarnessSettings(status);
    return status;
  } catch (e) {
    const fallback = controllerHarnessStatusCache ? {...controllerHarnessStatusCache, ok:false, message:e.message || controllerHarnessStatusCache.message} : {ok:false, message:e.message};
    controllerHarnessStatusCache = fallback;
    renderControllerHarnessSettings(fallback);
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
  switchSettingsPanel('updates');
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
  authStatus = {...(authStatus || {}), ...(config?.auth || {})};
  sessionSlashCommands = Array.isArray(config?.session_slash_commands) ? config.session_slash_commands : [];
  fillSelects(); renderWorkspaces(); renderProfiles(); renderProviders(); renderModels(); renderTools();
  document.getElementById('configEditor').value = JSON.stringify(config, null, 2);
  renderSystemInfo();
  renderHeaderAuthBox();
  renderControllerHarnessSettings();
  renderEndpointConnectionSettings();
  renderAuthInfo();
  renderZedConfigExamples();
  renderSourceContexts();
  renderSources();
  await loadSourceSecrets().catch(()=>{});
  await loadSourceVariables().catch(()=>{});
  await loadPacRamIndex().catch(()=>{});
  await loadUsersList().catch(()=>{});
  await loadLocalDiffs().catch(()=>{});
  await loadUpdateArchives().catch(()=>{});
  renderPacReleaseStatus(window.__pacReleaseMeta || null);
  await loadTlsStatus();
  await loadServiceModeStatus();
  await loadControllerHarnessStatus();
  renderSetupWizard();
}
async function loadSessions() {
  const sessions = await api('/v1/sessions');
  window.__pacSessions = sessions;
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
    refreshSessionRunButton().catch(()=>{});
    renderModelActiveSessionsPanel();
    renderProfileUsagePanel();
    renderWorkspaceActivityPanel();
    renderSessionSidebar([]);
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
  renderModelActiveSessionsPanel();
  renderProfileUsagePanel();
  renderWorkspaceActivityPanel();
}
async function selectSession(id) {
  ensureSessionWorkspaceChrome();
  sessionHydrationToken += 1;
  selectedSession = await api(`/v1/sessions/${id}`);
  const preferredEndpoint = selectedSession.metadata?.preferred_endpoint || '';
  const endpointName = (window.__pacEndpoints || []).find(e => e.id === preferredEndpoint)?.name || preferredEndpoint || 'PAC/local';
  document.getElementById('selectedSession').innerHTML = `<span class="session-lock-dot"></span><span>Profile: ${escapeHtml(selectedSession.agent_profile || 'default')}</span><span>Permissions: ${escapeHtml(selectedSession.permission_profile || '-')}</span><span>Endpoint: ${escapeHtml(endpointName)}</span><span>Mode: ${escapeHtml(selectedSession.metadata?.execution_mode || (selectedSession.metadata?.agent_enabled === false ? 'direct model' : 'pi.dev'))}</span><span>Model: ${escapeHtml(selectedSession.model || '')}</span><span>${escapeHtml(selectedSession.workspace_path || '')}</span>`;
  if (document.getElementById('sessionTopSelect')) sessionTopSelect.value = selectedSession.id;
  if (document.getElementById('taskRunner')) taskRunner.value = preferredEndpoint || '';
  if (document.getElementById('sessionEndpointLock')) sessionEndpointLock.textContent = `Profile: ${selectedSession.agent_profile || 'default'} · permissions: ${selectedSession.permission_profile || '-'} · endpoint: ${endpointName} · model: ${selectedSession.model || 'session default'}`;
  syncSessionPermissionQuick();
  const timeline = document.getElementById('events');
  if (timeline) timeline.innerHTML = '<div class="empty-timeline">Waiting for session events.</div>';
  resetSessionTimelineState();
  renderSessionSidebar(window.__pacSessions || []);
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
    // EventSource cannot set auth headers, so auth-enabled deployments should use polling.
    source = new EventSource(`/v1/sessions/${id}/events`);
    source.onerror = () => {
      if (source) {
        source.close();
        source = null;
      }
      startSessionPolling(id);
    };
    source.onmessage = e => { try { appendEvent('message', JSON.parse(e.data)); } catch { appendEvent('message', e.data); } };
    ['user_message','agent_routing','agent_intent','task_queued','stdout','stderr','task_started','task_completed','task_failed','approval_required','task_approved','task_rejected','session_created','agent_loop_started','agent_thinking','model_response','tool_call','tool_result','result','final','full_control_enabled','subagent_started'].forEach(t => source.addEventListener(t, e => { try { appendEvent(t, JSON.parse(e.data)); } catch { appendEvent(t, e.data); } }));
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

function getStoredToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || '';
}
function setStoredToken(token) {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}
function showUserChip(user) {
  const chip = document.getElementById('userChip');
  const name = document.getElementById('userChipName');
  const loginBtn = document.getElementById('loginBtn');
  if (chip && name) {
    if (user) {
      name.textContent = user.display_name || user.username || user.id || 'User';
      chip.hidden = false;
      chip.style.display = 'inline-flex';
    } else {
      chip.hidden = true;
      chip.style.display = 'none';
      chip.setAttribute('aria-expanded', 'false');
      chip.closest('.user-menu-wrap')?.classList.remove('open');
      document.getElementById('userMenu')?.setAttribute('hidden', '');
    }
  }
  if (loginBtn) loginBtn.hidden = !!user;
}
async function fetchAuthStatus() {
  try {
    authStatus = await fetch('/v1/auth/status').then(r => r.ok ? r.json() : {enabled:false, mode:'dev-token', needs_setup:false, user_count:0});
  } catch (_) {
    authStatus = {enabled:false, mode:'dev-token', needs_setup:false, user_count:0};
  }
  return authStatus;
}
async function fetchCurrentUser() {
  if (!getStoredToken()) {
    currentUser = null;
    showUserChip(null);
    return null;
  }
  try {
    currentUser = await api('/v1/auth/me');
    showUserChip(currentUser);
    return currentUser;
  } catch (_) {
    setStoredToken('');
    currentUser = null;
    showUserChip(null);
    return null;
  }
}
function closeLoginModal() {
  const modal = document.getElementById('loginModal');
  if (modal) modal.remove();
}
function openLoginModal(mode = 'login') {
  closeLoginModal();
  const modal = document.createElement('div');
  modal.id = 'loginModal';
  modal.className = 'modal-backdrop';
  const isSetup = mode === 'setup';
  modal.innerHTML = `
    <section class="modal-card auth-modal-card" role="dialog" aria-modal="true" aria-labelledby="loginModalTitle">
      <div class="section-heading">
        <div>
          <h2 id="loginModalTitle">${isSetup ? 'Create PAC admin account' : 'Log in to PAC'}</h2>
          <p class="muted">${isSetup ? 'Initial setup is required before PAC can be used with named users.' : 'Use your PAC account to unlock the controller UI.'}</p>
        </div>
        ${isSetup ? '' : '<button id="closeLoginModalBtn" class="ghost-button" type="button">Close</button>'}
      </div>
      <div class="form-grid compact-form">
        <label>Username <input id="loginUsername" autocomplete="username" /></label>
        ${isSetup ? '<label>Display name <input id="loginDisplayName" autocomplete="name" /></label>' : ''}
        <label>Password <input id="loginPassword" type="password" autocomplete="current-password" /></label>
      </div>
      <div id="loginError" class="inline-result" hidden></div>
      <div class="button-row">
        <button id="doLoginBtn" type="button">${isSetup ? 'Create admin account' : 'Log in'}</button>
        ${isSetup ? '' : '<button id="cancelLoginBtn" class="ghost-button" type="button">Cancel</button>'}
      </div>
    </section>`;
  document.body.appendChild(modal);
  if (!isSetup) {
    document.getElementById('closeLoginModalBtn')?.addEventListener('click', closeLoginModal);
    document.getElementById('cancelLoginBtn')?.addEventListener('click', closeLoginModal);
    modal.addEventListener('click', (ev) => { if (ev.target === modal) closeLoginModal(); });
  }
  document.getElementById('doLoginBtn')?.addEventListener('click', () => submitLoginModal(mode));
  document.getElementById('loginPassword')?.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') submitLoginModal(mode); });
  document.getElementById('loginUsername')?.focus();
}
async function submitLoginModal(mode = 'login') {
  const username = document.getElementById('loginUsername')?.value.trim() || '';
  const password = document.getElementById('loginPassword')?.value || '';
  const displayName = document.getElementById('loginDisplayName')?.value.trim() || username;
  const errorEl = document.getElementById('loginError');
  if (!username || !password) {
    if (errorEl) { errorEl.hidden = false; errorEl.textContent = 'Username and password are required.'; }
    return;
  }
  const path = mode === 'setup' ? '/v1/auth/setup' : '/v1/auth/login';
  const payload = mode === 'setup' ? {username, password, display_name: displayName} : {username, password};
  try {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || 'Authentication failed');
    setStoredToken(data.token || '');
    currentUser = data.user || null;
    showUserChip(currentUser);
    renderHeaderAuthBox();
    closeLoginModal();
    await init();
  } catch (error) {
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = error.message || 'Authentication failed';
    }
  }
}
function logoutUser() {
  setStoredToken('');
  currentUser = null;
  showUserChip(null);
  renderHeaderAuthBox();
  if (authStatus?.enabled && authStatus?.mode === 'user-password') openLoginModal('login');
}
async function ensureAuthReady() {
  await fetchAuthStatus();
  if (!authStatus?.enabled) {
    currentUser = null;
    showUserChip(null);
    return true;
  }
  if (authStatus.mode === 'user-password') {
    if (authStatus.needs_setup) {
      openLoginModal('setup');
      return false;
    }
    const user = await fetchCurrentUser();
    if (!user) {
      openLoginModal('login');
      return false;
    }
    return true;
  }
  return true;
}
function renderAuthInfo() {
  const el = document.getElementById('authInfo');
  if (!el) return;
  const info = authStatus || config?.auth || {};
  el.innerHTML = '';
  const rows = [
    ['Mode', String(info.mode || 'open')],
    ['Enabled', info.enabled ? 'yes' : 'no'],
    ['Users', String(info.user_count ?? '-')],
    ['TTL', `${info.token_ttl_hours || config?.auth?.token_ttl_hours || 720}h`],
  ];
  rows.forEach(([label, value]) => {
    const row = document.createElement('div');
    row.innerHTML = `<span>${escapeHtml(label)}</span><code>${escapeHtml(value)}</code>`;
    el.appendChild(row);
  });
}
async function loadUsersList() {
  const el = document.getElementById('usersList');
  if (!el) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    el.innerHTML = '<div class="muted small-text">User management is available when auth mode is set to user-password.</div>';
    return;
  }
  try {
    const users = await api('/v1/users');
    if (!users.length) {
      el.innerHTML = '<div class="muted small-text">No users found.</div>';
      return;
    }
    el.innerHTML = users.map((user) => `
      <div class="row">
        <div><b>${escapeHtml(user.display_name || user.username)}</b><br><span class="muted small-text">${escapeHtml(user.username)} · ${escapeHtml(user.role || 'user')}</span></div>
        <div class="button-row">
          ${user.id === currentUser?.id ? '<span class="muted small-text">current</span>' : `<button class="ghost-button delete-user-btn" data-user-id="${escapeHtml(user.id)}" type="button">Delete</button>`}
        </div>
      </div>`).join('');
    el.querySelectorAll('.delete-user-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        if (!userId || !confirm(`Delete user ${userId}?`)) return;
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load users: ${escapeHtml(error.message || String(error))}</div>`;
  }
}
function renderHeaderAuthBox() {
  const tokenInput = document.getElementById('token');
  const loginBtn = document.getElementById('loginBtn');
  const auth = authStatus || config?.auth || {};
  const enabled = !!auth.enabled;
  const storedToken = getStoredToken();
  const hasToken = !!(storedToken || String(tokenInput?.value || '').trim());
  if (tokenInput) tokenInput.hidden = !!(enabled && auth.mode === 'user-password');
  if (loginBtn) loginBtn.textContent = auth.needs_setup ? 'Set up account' : 'Log in';
  showUserChip(currentUser);
}
function closePersonalSettingsModal() {
  document.getElementById('personalSettingsModal')?.remove();
}
async function loadPersonalSettingsData() {
  const [me, tokens, ram] = await Promise.all([
    api('/v1/users/me'),
    api('/v1/users/me/tokens').catch(() => []),
    api('/v1/users/me/ram').catch(() => ({content:''})),
  ]);
  return {me, tokens, ram};
}
function renderPersonalTokens(target, tokens, latestToken='') {
  if (!target) return;
  const items = Array.isArray(tokens) ? tokens : [];
  target.innerHTML = `
    ${latestToken ? `<div class="inline-result">${escapeHtml(latestToken)}</div>` : ''}
    ${items.length ? items.map((item) => `<div class="row"><div><b>${escapeHtml(item.username || currentUser?.username || 'token')}</b><br><span class="muted small-text">expires ${escapeHtml(item.expires_at || '-')}</span></div><div class="button-row"><button class="ghost-button revoke-self-token-btn" data-token="${escapeHtml(item.token)}" type="button">Revoke</button></div></div>`).join('') : '<div class="muted small-text">No personal tokens yet.</div>'}`;
  target.querySelectorAll('.revoke-self-token-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const token = btn.dataset.token || '';
    if (!token || !confirm('Revoke this token?')) return;
    await api(`/v1/users/me/tokens/${encodeURIComponent(token)}`, {method:'DELETE'});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(target, refreshed);
  }));
}
async function openPersonalSettingsModal() {
  if (!currentUser && authStatus?.enabled) {
    openLoginModal(authStatus?.needs_setup ? 'setup' : 'login');
    return;
  }
  closePersonalSettingsModal();
  const modal = document.createElement('div');
  modal.id = 'personalSettingsModal';
  modal.className = 'modal-backdrop';
  modal.innerHTML = `
    <section class="modal-card auth-modal-card personal-settings-modal" role="dialog" aria-modal="true" aria-labelledby="personalSettingsTitle">
      <div class="section-heading">
        <div><h2 id="personalSettingsTitle">Personal settings</h2><p class="muted">Profile, personal tokens, and the memory PAC stores for your user.</p></div>
        <button id="closePersonalSettingsBtn" class="ghost-button" type="button">Close</button>
      </div>
      <div class="split personal-settings-grid">
        <section class="card setting-cube compact-setting-card">
          <h3>Profile</h3>
          <div class="form-grid compact-form">
            <label>Username <input id="personalUsername" disabled /></label>
            <label>Display name <input id="personalDisplayName" /></label>
            <label>Email <input id="personalEmail" placeholder="name@example.com" /></label>
          </div>
          <label>Preferences JSON <textarea id="personalPreferences" rows="8"></textarea></label>
          <div class="button-row"><button id="savePersonalProfileBtn" type="button">Save profile</button></div>
          <div id="personalProfileStatus" class="inline-result" hidden></div>
        </section>
        <section class="card setting-cube compact-setting-card">
          <h3>Access tokens</h3>
          <div class="button-row">
            <button id="mintPersonalTokenBtn" type="button">Generate token</button>
            <label>TTL hours <input id="personalTokenTtl" type="number" value="720" min="1" max="8760" /></label>
          </div>
          <div id="personalTokensList" class="stacked-output compact-scroll-output"><div class="muted small-text">Loading tokens…</div></div>
        </section>
      </div>
      <section class="card setting-cube compact-setting-card" style="margin-top:1rem">
        <h3>Personal PAC RAM</h3>
        <p class="muted">This is the remote memory bundle PAC can use for your user.</p>
        <label><textarea id="personalRamContent" rows="10"></textarea></label>
        <div class="button-row"><button id="savePersonalRamBtn" type="button">Save memory</button></div>
        <div id="personalRamStatus" class="inline-result" hidden></div>
      </section>
    </section>`;
  document.body.appendChild(modal);
  document.getElementById('closePersonalSettingsBtn')?.addEventListener('click', closePersonalSettingsModal);
  modal.addEventListener('click', (ev) => { if (ev.target === modal) closePersonalSettingsModal(); });
  const data = await loadPersonalSettingsData();
  document.getElementById('personalUsername').value = data.me?.username || '';
  document.getElementById('personalDisplayName').value = data.me?.display_name || data.me?.username || '';
  document.getElementById('personalEmail').value = data.me?.metadata?.email || '';
  document.getElementById('personalPreferences').value = JSON.stringify(data.me?.metadata?.preferences || {}, null, 2);
  document.getElementById('personalRamContent').value = data.ram?.content || '';
  renderPersonalTokens(document.getElementById('personalTokensList'), data.tokens || []);
  document.getElementById('savePersonalProfileBtn')?.addEventListener('click', async () => {
    const status = document.getElementById('personalProfileStatus');
    try {
      const preferences = JSON.parse(document.getElementById('personalPreferences').value || '{}');
      const response = await api('/v1/users/me', {method:'PUT', body: JSON.stringify({display_name: document.getElementById('personalDisplayName').value.trim(), email: document.getElementById('personalEmail').value.trim(), preferences})});
      currentUser = response.user || currentUser;
      showUserChip(currentUser);
      if (status) { status.hidden = false; status.textContent = 'Profile saved.'; }
    } catch (error) {
      if (status) { status.hidden = false; status.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
  document.getElementById('mintPersonalTokenBtn')?.addEventListener('click', async () => {
    const ttl = Number(document.getElementById('personalTokenTtl').value || 720);
    const response = await api('/v1/users/me/tokens', {method:'POST', body: JSON.stringify({ttl_hours: ttl})});
    const refreshed = await api('/v1/users/me/tokens').catch(() => []);
    renderPersonalTokens(document.getElementById('personalTokensList'), refreshed, response.token || '');
  });
  document.getElementById('savePersonalRamBtn')?.addEventListener('click', async () => {
    const status = document.getElementById('personalRamStatus');
    try {
      await api('/v1/users/me/ram', {method:'PUT', body: JSON.stringify({content: document.getElementById('personalRamContent').value})});
      if (status) { status.hidden = false; status.textContent = 'Personal memory saved.'; }
    } catch (error) {
      if (status) { status.hidden = false; status.textContent = `Failed: ${error.message || String(error)}`; }
    }
  });
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
document.getElementById('refreshUsersBtn')?.addEventListener('click', () => loadUsersList().catch((e)=>paneError('Users could not be refreshed', e.message || String(e))));
if (document.getElementById('dismissSetupWizard')) document.getElementById('dismissSetupWizard').onclick = () => hideSetupWizard();
if (document.getElementById('recheckSetupWizard')) document.getElementById('recheckSetupWizard').onclick = () => loadConfig().catch(e => paneError('Setup recheck failed', e.message));
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
  if (isHelpSlashCommand(rawPrompt)) {
    alert(slashCommandHelpText());
    return;
  }
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
  autosizeSessionPrompt();
  if (sessionHydrationActiveFor === selectedSession.id) {
    sessionHydrationToken += 1;
    sessionHydrationActiveFor = null;
    sessionHydrationBufferedEvents = [];
  }
  const created = await api(`/v1/sessions/${selectedSession.id}/tasks`,{method:'POST',body:JSON.stringify({prompt:rawPrompt,command:'',metadata})});
  if (created && created.id) {
    activeSessionTaskId = created.id;
    refreshSessionRunButton().catch(()=>{});
    const localEvent = {
      id: `local_user_${created.id}`,
      session_id: selectedSession.id,
      task_id: created.id,
      type: 'user_message',
      message: rawPrompt,
      created_at: created.created_at || new Date().toISOString(),
      data: {role:'user', model: metadata.model || selectedSession.model, endpoint_id: metadata.runner_id || selectedSession.metadata?.preferred_endpoint, command:'', execution_mode: metadata.execution_mode, stored:true, pi_dev_enabled:selectedSession.metadata?.agent_enabled !== false, routing:'pi.dev'}
    };
    renderSessionTimelineEvent(localEvent);
    pollSessionEvents(selectedSession.id).catch(()=>{});
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
function appendPromptContextBlock(label, content) {
  const prompt = document.getElementById('taskPrompt');
  if (!prompt) return;
  const block = `\n[${label}]\n${content}\n`;
  prompt.value = `${prompt.value || ''}${block}`.trimStart();
  autosizeSessionPrompt();
  prompt.focus();
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
      (runTaskBtn?.dataset.mode === 'stop' ? stopActiveSessionTask() : sendSessionComposer()).catch(e=>alert(e.message));
      return;
    }
    if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
      ev.preventDefault();
      (runTaskBtn?.dataset.mode === 'stop' ? stopActiveSessionTask() : sendSessionComposer()).catch(e=>alert(e.message));
    }
  });
  autosizeSessionPrompt();
}
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
const sourceContextSelect = document.getElementById('sourceContextSelect');
if (sourceContextSelect) sourceContextSelect.onchange = () => { fillSourceContextForm(sourceContextSelect.value || ''); resolveCurrentSourceContext().catch(()=>{}); };
const saveSourceContextBtn = document.getElementById('saveSourceContext');
if (saveSourceContextBtn) saveSourceContextBtn.onclick = () => saveSourceContextFromForm();
const resolveSourceContextBtn = document.getElementById('resolveSourceContext');
if (resolveSourceContextBtn) resolveSourceContextBtn.onclick = () => resolveCurrentSourceContext().catch(e=>paneError('Source context could not be resolved', e.message));
const deleteSourceContextBtn = document.getElementById('deleteSourceContext');
if (deleteSourceContextBtn) deleteSourceContextBtn.onclick = () => deleteSourceContextFromForm().catch(e=>paneError('Source context could not be deleted', e.message));
const sourceSecretSelect = document.getElementById('sourceSecretSelect');
if (sourceSecretSelect) sourceSecretSelect.onchange = () => fillSecretForm(sourceSecretSelect.value || '');
const saveSourceSecretBtn = document.getElementById('saveSourceSecret');
if (saveSourceSecretBtn) saveSourceSecretBtn.onclick = () => saveSourceSecretFromForm();
const deleteSourceSecretBtn = document.getElementById('deleteSourceSecret');
if (deleteSourceSecretBtn) deleteSourceSecretBtn.onclick = () => deleteSourceSecretFromForm().catch(e=>paneError('Secret could not be deleted', e.message));
const sourceVariableSelect = document.getElementById('sourceVariableSelect');
if (sourceVariableSelect) sourceVariableSelect.onchange = () => fillSourceVariableForm(sourceVariableSelect.value || '');
const saveSourceVariableBtn = document.getElementById('saveSourceVariable');
if (saveSourceVariableBtn) saveSourceVariableBtn.onclick = () => saveSourceVariableFromForm();
const deleteSourceVariableBtn = document.getElementById('deleteSourceVariable');
if (deleteSourceVariableBtn) deleteSourceVariableBtn.onclick = () => deleteSourceVariableFromForm().catch(e=>paneError('Source variable could not be deleted', e.message));
const loadPacRamBtn = document.getElementById('loadPacRam');
if (loadPacRamBtn) loadPacRamBtn.onclick = () => loadPacRam().catch(e=>paneError('PAC RAM could not be loaded', e.message));
const savePacRamBtn = document.getElementById('savePacRam');
if (savePacRamBtn) savePacRamBtn.onclick = () => savePacRamFromForm();
const searchMarketplaceBtn = document.getElementById('searchMarketplace');
if (searchMarketplaceBtn) searchMarketplaceBtn.onclick = () => searchMarketplace().catch(e=>paneError('Marketplace search failed', e.message));
const refreshUpdateArchivesBtn = document.getElementById('refreshUpdateArchives');
if (refreshUpdateArchivesBtn) refreshUpdateArchivesBtn.onclick = async () => {
  await loadLocalDiffs().catch(e=>paneError('Local diffs unavailable', e.message));
  await loadUpdateArchives().catch(e=>paneError('Update archives unavailable', e.message));
};
const generateLocalDiffBtn = document.getElementById('generateLocalDiff');
if (generateLocalDiffBtn) generateLocalDiffBtn.onclick = () => generateLocalDiffNow().catch(e=>paneError('Local diff generation failed', e.message));
const checkPacReleaseBtn = document.getElementById('checkPacRelease');
if (checkPacReleaseBtn) checkPacReleaseBtn.onclick = () => checkPacRelease().catch(e=>paneError('PAC release check failed', e.message));
const applyPacReleaseBtn = document.getElementById('applyPacRelease');
if (applyPacReleaseBtn) applyPacReleaseBtn.onclick = () => openUpdateConfirmOverlay(window.__pacReleaseMeta || {});
const updateConfirmProceedBtn = document.getElementById('updateConfirmProceed');
if (updateConfirmProceedBtn) updateConfirmProceedBtn.onclick = () => applyPacRelease().catch(e=>paneError('PAC release apply failed', e.message));
const updateConfirmCancelBtn = document.getElementById('updateConfirmCancel');
if (updateConfirmCancelBtn) updateConfirmCancelBtn.onclick = () => closeUpdateConfirmOverlay(true);
const openBackupsModalBtn = document.getElementById('openBackupsModal');
if (openBackupsModalBtn) openBackupsModalBtn.onclick = () => { openBackupsModal(); loadUpdateArchives().catch(e=>paneError('Update archives unavailable', e.message)); };
const closeBackupsModalBtn = document.getElementById('closeBackupsModal');
if (closeBackupsModalBtn) closeBackupsModalBtn.onclick = () => closeBackupsModal();
const openMarketplaceBtn = document.getElementById('openMarketplaceModal');
if (openMarketplaceBtn) openMarketplaceBtn.onclick = () => openMarketplaceModal();
const closeMarketplaceBtn = document.getElementById('closeMarketplaceModal');
if (closeMarketplaceBtn) closeMarketplaceBtn.onclick = () => closeMarketplaceModal();
const runMarketplaceSearchBtn = document.getElementById('runMarketplaceSearch');
if (runMarketplaceSearchBtn) runMarketplaceSearchBtn.onclick = () => searchMarketplaceModal().catch(e=>paneError('Marketplace search failed', e.message));
if (document.getElementById('saveTool')) saveTool.onclick=()=>saveToolFromForm().catch(e=>paneError('Tool save failed', e.message));
if (document.getElementById('saveProfile')) saveProfile.onclick=()=>saveProfileFromForm().catch(e=>paneError('Profile save failed', e.message));
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
  const duplicate = findConfiguredModelByProviderModel(modelProvider.value, modelId.value.trim() || modelName.value.trim(), modelName.value.trim());
  if (duplicate) return alert(`This provider model is already configured as '${duplicate[0]}'. Edit that entry instead of creating a duplicate.`);
  config.models = config.models || {};
  config.models[modelName.value.trim()] = {
    provider: modelProvider.value,
    model: modelId.value.trim() || null,
    runs_on: modelRunsOn.value.trim() || null,
    context_window: Number(modelContextWindow.value || 4096),
    max_output_tokens: Number(modelMaxOutput.value || 1024),
    input_price_per_million: numberOrNull(modelInputPrice.value),
    output_price_per_million: numberOrNull(modelOutputPrice.value),
    capabilities: {
      supports_chat: !!modelSupportsChat.checked,
      supports_tools: !!modelSupportsTools.checked,
      supports_vision: !!modelSupportsVision.checked,
      supports_json: !!modelSupportsJson.checked,
      supports_streaming: !!modelSupportsStreaming.checked,
      reasoning: modelReasoning.value || 'none'
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
    planner_model: document.getElementById('profilePlannerModel')?.value || null,
    context_profile: profileContextProfile.value || null,
    planner_context_profile: document.getElementById('profilePlannerContextProfile')?.value || null,
    context_mode: profileContextMode.value || 'medium',
    permission_profile: profilePermission.value || 'ask-first',
    tools: selectedToolNames(),
    system_prompt: profileSystemPrompt.value.trim() || 'You are a careful remote coding and infrastructure agent.',
    max_runtime_minutes: 60,
  };
  const r = await api(`/v1/agent-profiles/${encodeURIComponent(name)}`,{method:'PUT',body:JSON.stringify(body)});
  config.agent_profiles = config.agent_profiles || {}; config.agent_profiles[name] = r;
  await loadConfig();
  showInline('profileFormResult', `Saved profile ${name}`);
}
async function deleteProfileFromForm() {
  const name = profileName.value.trim();
  if (!name || !config.agent_profiles?.[name]) return alert('Select an existing profile first');
  if (!confirm(`Delete profile ${name}?`)) return;
  await api(`/v1/agent-profiles/${encodeURIComponent(name)}`,{method:'DELETE'});
  await loadConfig();
  showInline('profileFormResult', `Deleted profile ${name}`);
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
  const meta = window.__pacReleaseMeta || {};
  setUpdateConfirmOverlayRestarting(meta.latest_version || config?.version || config?.setup_status?.version || '', seconds);
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
  let r = await fetch(`/v1/admin/stage-package?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
    method: 'POST',
    headers: tokenHeaders(),
    body: fd,
  });
  if (r.status === 404) {
    result.textContent = 'Primary upload endpoint returned 404; retrying compatibility endpoint...';
    r = await fetch(`/v1/update/upload?apply_update=${apply ? 'true' : 'false'}&restart_after_update=${restartAfterUpdate ? 'true' : 'false'}`, {
      method: 'POST',
      headers: tokenHeaders(),
      body: fd,
    });
  }
  const text = await r.text();
  if (!r.ok) throw new Error(`${r.status}: ${text}`);
  let payload;
  try { payload = JSON.parse(text); } catch { payload = text; }
  result.textContent = typeof payload === 'string' ? payload : (payload.message || payload.status || 'Package uploaded. Details are in Events.'); if (typeof payload !== 'string') emitUiEvent('package_upload_completed', result.textContent, payload);
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
const showUnconfigModelsBtn = document.getElementById('showUnconfigModels');
if (showUnconfigModelsBtn) showUnconfigModelsBtn.onclick = async () => {
  const panel = document.getElementById('unconfiguredModelsPanel');
  if (panel) panel.hidden = false;
  await renderUnconfiguredModelsPanelFromLive().catch(e => paneError('Provider inventory could not load', e.message));
};
const closeUnconfigModelsBtn = document.getElementById('closeUnconfigModels');
if (closeUnconfigModelsBtn) closeUnconfigModelsBtn.onclick = () => {
  const panel = document.getElementById('unconfiguredModelsPanel');
  if (panel) panel.hidden = true;
};

const sessionBootstrapModeSelect = document.getElementById('sessionBootstrapMode');
if (sessionBootstrapModeSelect) sessionBootstrapModeSelect.onchange = () => applySessionBootstrapMode();
const sessionSourceContextSelect = document.getElementById('sessionSourceContext');
if (sessionSourceContextSelect) sessionSourceContextSelect.onchange = () => {
  const name = sessionSourceContextSelect.value || '';
  if (!name) return;
  applySessionSourceContext(name).catch(e => paneError('Source context could not be applied', e.message));
};
const marketplaceQueryInput = document.getElementById('marketplaceQuery');
if (marketplaceQueryInput) marketplaceQueryInput.addEventListener('keydown', ev => {
  if (ev.key === 'Enter') { ev.preventDefault(); searchMarketplace().catch(e=>paneError('Marketplace search failed', e.message)); }
});
const marketplaceModalQueryInput = document.getElementById('marketplaceModalQuery');
if (marketplaceModalQueryInput) marketplaceModalQueryInput.addEventListener('keydown', ev => {
  if (ev.key === 'Enter') { ev.preventDefault(); searchMarketplaceModal().catch(e=>paneError('Marketplace search failed', e.message)); }
});
const createSessionBtn = document.getElementById('createSession');
if (createSessionBtn) createSessionBtn.onclick = async() => {
  const btn = document.getElementById('createSession');
  const status = document.getElementById('sessionCreateStatus');
  try {
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Creating...';
    const bootstrapMode = document.getElementById('sessionBootstrapMode')?.value || 'profile';
    const sourceContextName = document.getElementById('sessionSourceContext')?.value || '';
    const workspaceType = document.getElementById('sessionWorkspaceType')?.value || 'profile';
    const workspace = workspaceType === 'git' ? {type:'git', url:sessionWorkspaceUrl.value.trim(), branch:sessionWorkspaceBranch.value.trim() || null, path:sessionWorkspacePath.value.trim() || null} : (workspaceType === 'local' ? {type:'local', path:sessionWorkspacePath.value.trim() || null} : {type:'profile', profile:workspaceProfile.value || null});
    const endpointId = document.getElementById('sessionEndpoint')?.value || '';
    if (!endpointId) throw new Error('Select the endpoint this session should use.');
    const metadata = {preferred_endpoint:endpointId, endpoint_locked:true, agent_enabled:true, execution_mode:'pi.dev'};
    if (bootstrapMode === 'source-context') {
      if (!sourceContextName) throw new Error('Select a source context for this session bootstrap mode.');
      const resolved = await api(`/v1/source-contexts/resolve?name=${encodeURIComponent(sourceContextName)}&include_secrets=false`);
      metadata.source_context_name = sourceContextName;
      metadata.source_context_path = resolved?.context?.path_prefix || null;
      if (resolved?.context?.customer_id) metadata.customer_id = resolved.context.customer_id;
      if (resolved?.context?.user_scope) metadata.user_scope = resolved.context.user_scope;
    }
    const body = {name:sessionName.value || 'web-session', agent_profile:agentProfile.value || null, workspace, tools:[], metadata};
    if (modelOverride.value) body.model = modelOverride.value;
    if (permissionOverride.value) body.permission_profile = permissionOverride.value;
    if (contextMode.value) body.context_mode = contextMode.value;
    const s = await api('/v1/sessions', {method:'POST', body:JSON.stringify(body)});
    if (status) status.textContent = 'Created.';
    closeSessionModal();
    await loadSessions();
    await loadDashboardMetrics();
    switchToTab('sessions-tab');
    await selectSession(s.id);
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message}`;
    await loadGlobalEvents(true).catch(()=>{});
  } finally {
    if (btn) btn.disabled = false;
  }
};

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

function renderMarketplaceResults(data) {
  const el = document.getElementById('marketplaceResults');
  if (!el) return;
  const results = data?.results || [];
  marketplaceResultCache = results;
  if (!results.length) {
    el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
    return;
  }
  el.innerHTML = results.map(item => {
    const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
    const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
    return `<button class="marketplace-card marketplace-card-button" data-marketplace-source-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
  }).join('');
  el.querySelectorAll('[data-marketplace-source-model]').forEach(btn => btn.onclick = async () => {
    const modelId = btn.dataset.marketplaceSourceModel || '';
    const input = document.getElementById('marketplaceModalQuery');
    if (input) input.value = modelId;
    openMarketplaceModal();
    const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(modelId)}`);
    renderMarketplaceModalDetail(detail);
  });
}

function openMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = false;
  const input = document.getElementById('marketplaceModalQuery');
  if (input) input.value = document.getElementById('marketplaceQuery')?.value || input.value || '';
  renderMarketplaceModalDetail();
  if (input && input.value.trim()) searchMarketplaceModal().catch(e=>paneError('Marketplace search failed', e.message));
}

function closeMarketplaceModal() {
  const modal = document.getElementById('marketplaceModal');
  if (modal) modal.hidden = true;
}

function preferredMarketplaceProvider(detail) {
  return (detail.provider_scores || []).find(entry => entry.can_run && entry.provider?.name)?.provider?.name
    || (detail.provider_scores || []).find(entry => entry.provider?.type === 'lmstudio')?.provider?.name
    || (detail.provider_scores || [])[0]?.provider?.name
    || '';
}

async function downloadMarketplaceModel(detail) {
  const provider = preferredMarketplaceProvider(detail);
  if (!provider) throw new Error('No compatible provider is configured for marketplace download');
  const score = (detail.provider_scores || []).find(entry => entry.provider?.name === provider) || {};
  const quantization = score.quant_recommended || (detail.available_quants || [])[0] || 'Q4_K_M';
  const result = await api('/v1/models/marketplace/download', {
    method:'POST',
    body: JSON.stringify({model: detail.model_id, provider, quantization}),
  });
  showInline('modelFormResult', {marketplace_download: result, provider, model: detail.model_id, quantization});
  await loadGlobalEvents(true).catch(()=>{});
}

function renderMarketplaceModalDetail(detail=null) {
  const title = document.getElementById('marketplaceDetailTitle');
  const version = document.getElementById('marketplaceDetailVersion');
  const body = document.getElementById('marketplaceDetailBody');
  if (!title || !version || !body) return;
  if (!detail) {
    title.textContent = 'Model details';
    version.textContent = '';
    body.innerHTML = '<div class="muted small-text">Select a marketplace result to inspect provider fit and configure it as a PAC model.</div>';
    return;
  }
  title.textContent = detail.model_id || 'Model details';
  version.textContent = detail.params_b ? `${detail.params_b}B` : '';
  const providers = (detail.provider_scores || []).map(entry => {
    const provider = entry.provider || {};
    return `<tr><td><code>${escapeHtml(provider.name || '-')}</code></td><td>${escapeHtml(provider.type || '-')}</td><td>${escapeHtml(entry.quant_recommended || '-')}</td><td><span class="pill ${entry.can_run === true ? 'ok-pill' : (entry.can_run === false ? 'warn-pill' : '')}">${escapeHtml(entry.can_run === true ? 'fits' : (entry.can_run === false ? 'no fit' : 'unknown'))}</span> ${escapeHtml(entry.reason || '-')}</td></tr>`;
  }).join('');
  const quants = (detail.available_quants || []).slice(0, 8).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
  const hasLmStudio = (detail.provider_scores || []).some(entry => entry.provider?.type === 'lmstudio');
  body.innerHTML = `<div class="muted small-text">Author: ${escapeHtml(detail.author || 'unknown')} • Downloads: ${escapeHtml(String(detail.downloads || 0))}</div><div class="marketplace-meta" style="margin:.6rem 0">${Object.entries(detail.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('')}${quants}</div><table class="compact-table"><thead><tr><th>Provider</th><th>Type</th><th>Quant</th><th>Fit</th></tr></thead><tbody>${providers || '<tr><td colspan="4" class="muted">No providers configured yet.</td></tr>'}</tbody></table><div class="button-row" style="margin-top:.75rem"><button id="configureMarketplaceModel">Configure as model</button>${hasLmStudio ? '<button id="downloadMarketplaceModel" class="ghost-button">Download to LM Studio</button>' : ''}</div>`;
  const configureBtn = document.getElementById('configureMarketplaceModel');
  if (configureBtn) configureBtn.onclick = () => {
    const preferred = preferredMarketplaceProvider(detail);
    closeMarketplaceModal();
    openModelModal();
    if (preferred && modelProvider) modelProvider.value = preferred;
    if (modelId) modelId.value = detail.model_id || '';
    if (modelName) modelName.value = String(detail.model_id || '').replace(/[^a-zA-Z0-9_.-]+/g,'-').toLowerCase();
    setModalStatus('modelModalStatus', 'Marketplace model copied into the PAC model form.');
  };
  const downloadBtn = document.getElementById('downloadMarketplaceModel');
  if (downloadBtn) downloadBtn.onclick = () => downloadMarketplaceModel(detail).catch(e=>paneError('Marketplace download failed', e.message));
}

async function searchMarketplaceModal() {
  const query = document.getElementById('marketplaceModalQuery')?.value?.trim() || '';
  const capability = document.getElementById('marketplaceModalCapability')?.value || '';
  const sort = document.getElementById('marketplaceModalSort')?.value || 'downloads';
  const el = document.getElementById('marketplaceModalResults');
  if (!el) return;
  el.textContent = 'Searching marketplace...';
  try {
    const params = new URLSearchParams({q: query, limit: '18', sort});
    if (capability) params.set('capability', capability);
    const data = await api(`/v1/models/marketplace/search?${params.toString()}`);
    const results = data?.results || [];
    marketplaceResultCache = results;
    if (!results.length) {
      el.innerHTML = '<span class="muted">No marketplace models matched this query.</span>';
      renderMarketplaceModalDetail();
      return;
    }
    el.innerHTML = results.map(item => {
      const caps = Object.entries(item.capabilities || {}).filter(([,v]) => !!v).map(([k]) => `<span class="marketplace-pill">${escapeHtml(k)}</span>`).join('');
      const quants = (item.available_quants || []).slice(0, 4).map(q => `<span class="marketplace-pill">${escapeHtml(String(q).toUpperCase())}</span>`).join('');
      return `<button class="marketplace-card marketplace-card-button" data-marketplace-model="${escapeHtml(item.model_id)}"><b>${escapeHtml(item.model_id)}</b><div class="marketplace-meta">${caps}${quants}</div><div class="muted small-text">${escapeHtml(item.author || 'unknown author')} • ${escapeHtml(String(item.downloads || 0))} downloads • ${escapeHtml(String(item.params_b || '?'))}B</div></button>`;
    }).join('');
    el.querySelectorAll('[data-marketplace-model]').forEach(btn => btn.onclick = async () => {
      const detail = await api(`/v1/models/marketplace/model/${encodeURIComponent(btn.dataset.marketplaceModel || '')}`);
      renderMarketplaceModalDetail(detail);
    });
  } catch (e) {
    el.textContent = e.message || String(e);
  }
}

function renderAuthInfo() {
  const el = document.getElementById('authInfo');
  if (!el) return;
  const info = authStatus || config?.auth || {};
  el.innerHTML = '';
  [
    ['Mode', String(info.mode || 'open')],
    ['Enabled', info.enabled ? 'yes' : 'no'],
    ['Users', String(info.user_count ?? '-')],
    ['Groups', String(info.group_count ?? '-')],
    ['Access requests', String(info.pending_access_requests ?? 0)],
    ['TTL', `${info.token_ttl_hours || config?.auth?.token_ttl_hours || 720}h`],
  ].forEach(([label, value]) => {
    const row = document.createElement('div');
    row.innerHTML = `<span>${escapeHtml(label)}</span><code>${escapeHtml(value)}</code>`;
    el.appendChild(row);
  });
}

async function loadUsersList() {
  const el = document.getElementById('usersList');
  if (!el) return;
  if (!(authStatus?.enabled && authStatus?.mode === 'user-password')) {
    el.innerHTML = '<div class="muted small-text">User management is available when auth mode is set to user-password.</div>';
    return;
  }
  try {
    const [users, groups] = await Promise.all([api('/v1/users'), api('/v1/groups').catch(() => [])]);
    const groupIds = (groups || []).map((group) => String(group.id || ''));
    if (!users.length) {
      el.innerHTML = '<div class="muted small-text">No users found.</div>';
      return;
    }
    el.innerHTML = users.map((user) => `
      <div class="row">
        <div><b>${escapeHtml(user.display_name || user.username)}</b><br><span class="muted small-text">${escapeHtml(user.username)} · ${escapeHtml(user.role || 'user')}</span><br><span class="muted small-text">groups: ${escapeHtml((user.groups || []).join(', ') || '-')}</span></div>
        <div class="button-row">
          <input class="user-groups-input" data-user-id="${escapeHtml(user.id)}" value="${escapeHtml((user.groups || []).join(', '))}" placeholder="group-a,group-b" />
          <button class="ghost-button save-user-groups-btn" data-user-id="${escapeHtml(user.id)}" type="button">Save</button>
          ${user.id === currentUser?.id ? '<span class="muted small-text">current</span>' : `<button class="ghost-button delete-user-btn" data-user-id="${escapeHtml(user.id)}" type="button">Delete</button>`}
        </div>
      </div>`).join('');
    el.querySelectorAll('.save-user-groups-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        const input = btn.parentElement?.querySelector('.user-groups-input');
        const selected = String(input?.value || '').split(',').map((item) => item.trim()).filter(Boolean);
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'PUT', body: JSON.stringify({groups:selected})});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
    el.querySelectorAll('.delete-user-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = btn.dataset.userId || '';
        if (!userId || !confirm(`Delete user ${userId}?`)) return;
        await api(`/v1/users/${encodeURIComponent(userId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load users: ${escapeHtml(error.message || String(error))}</div>`;
  }
}

async function loadGroupsList() {
  const el = document.getElementById('groupsList');
  if (!el) return;
  try {
    const groups = await api('/v1/groups');
    if (!groups.length) {
      el.innerHTML = '<div class="muted small-text">No groups found.</div>';
      return;
    }
    el.innerHTML = groups.map((group) => `
      <div class="row">
        <div><b>${escapeHtml(group.name || group.id)}</b><br><span class="muted small-text">${escapeHtml(group.id)}</span><br><span class="muted small-text">${escapeHtml(group.description || '')}</span><br><span class="muted small-text">grants: ${escapeHtml((group.grants || []).map((grant) => `${grant.resource_type}:${grant.pattern}(${grant.access})`).join(', ') || '-')}</span></div>
        <div class="button-row"><button class="ghost-button delete-group-btn" data-group-id="${escapeHtml(group.id)}" type="button">Delete</button></div>
      </div>`).join('');
    el.querySelectorAll('.delete-group-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const groupId = btn.dataset.groupId || '';
        if (!groupId || !confirm(`Delete group ${groupId}?`)) return;
        await api(`/v1/groups/${encodeURIComponent(groupId)}`, {method:'DELETE'});
        await fetchAuthStatus();
        renderAuthInfo();
        await loadGroupsList();
        await loadUsersList();
      });
    });
  } catch (error) {
    el.innerHTML = `<div class="muted small-text">Could not load groups: ${escapeHtml(error.message || String(error))}</div>`;
  }
}

async function loadApprovals() {
  if (approvalsRequest) return approvalsRequest;
  approvalsRequest = (async () => {
    const [tasks, accessRequests] = await Promise.all([
      api('/v1/tasks/pending-approvals'),
      api('/v1/access-requests').catch(() => []),
    ]);
    const el = document.getElementById('approvals');
    if (!el) return;
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
  })();
  try {
    return await approvalsRequest;
  } finally {
    approvalsRequest = null;
  }
}

async function init(){
  loadThemeMode();
  setupTabs();
  setupEventsRail();
  await loadVersion().catch(()=>{});
  const ready = await ensureAuthReady();
  renderHeaderAuthBox();
  if (!ready) return;
  await loadConfig();
  await loadSessions();
  await loadApprovals();
  await loadGroupsList().catch(()=>{});
  await loadRunners();
  applySessionBootstrapMode();
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

const refreshGroupsBtn = document.getElementById('refreshGroupsBtn');
if (refreshGroupsBtn) refreshGroupsBtn.onclick = () => loadGroupsList().catch((e)=>paneError('Groups could not be refreshed', e.message || String(e)));
const createUserBtn = document.getElementById('createUserBtn');
if (createUserBtn) createUserBtn.onclick = async () => {
  const username = document.getElementById('newUsername')?.value.trim() || '';
  const display_name = document.getElementById('newDisplayName')?.value.trim() || username;
  const password = document.getElementById('newUserPassword')?.value || '';
  const role = document.getElementById('newUserRole')?.value || 'user';
  const groups = (document.getElementById('newUserGroups')?.value || '').split(',').map((item) => item.trim()).filter(Boolean);
  const result = document.getElementById('usersResult');
  try {
    if (!username || !password) throw new Error('Username and password are required.');
    await api('/v1/users', {method:'POST', body: JSON.stringify({username, display_name, password, role, groups})});
    if (result) result.textContent = `User created: ${username}`;
    ['newUsername', 'newDisplayName', 'newUserPassword', 'newUserGroups'].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
    await fetchAuthStatus();
    renderAuthInfo();
    await loadUsersList();
  } catch (error) {
    if (result) result.textContent = `Failed: ${error.message || String(error)}`;
  }
};
const createGroupBtn = document.getElementById('createGroupBtn');
if (createGroupBtn) createGroupBtn.onclick = async () => {
  const id = document.getElementById('newGroupId')?.value.trim() || '';
  const name = document.getElementById('newGroupName')?.value.trim() || id;
  const description = document.getElementById('newGroupDescription')?.value.trim() || '';
  const grants = (document.getElementById('newGroupGrants')?.value || '').split(',').map((item) => item.trim()).filter(Boolean).map((item) => {
    const parts = item.split(':');
    const access = (parts.pop() || 'read').trim();
    const resource_type = (parts.shift() || 'workspace').trim();
    const pattern = parts.join(':').trim();
    return {resource_type, pattern, access};
  }).filter((item) => item.pattern);
  const result = document.getElementById('groupsResult');
  try {
    if (!id) throw new Error('Group id is required.');
    await api('/v1/groups', {method:'POST', body: JSON.stringify({id, name, description, grants})});
    if (result) result.textContent = `Group created: ${id}`;
    ['newGroupId', 'newGroupName', 'newGroupDescription', 'newGroupGrants'].forEach((inputId) => { const el = document.getElementById(inputId); if (el) el.value = ''; });
    await fetchAuthStatus();
    renderAuthInfo();
    await loadGroupsList();
    await loadUsersList();
  } catch (error) {
    if (result) result.textContent = `Failed: ${error.message || String(error)}`;
  }
};
