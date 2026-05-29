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
  model: {kind:'session', label:'/model [model|provider:model]', description:'Show or switch the active model for this session.'},
  subagent: {kind:'pi.dev', label:'/subagent [explore|plan|coder|verify|general] <instruction>', description:'Create a scoped specialist subagent task.'},
  explore: {kind:'pi.dev', label:'/explore <instruction>', description:'Spawn a read-only Explore sub-agent.'},
  coder: {kind:'pi.dev', label:'/coder <instruction>', description:'Spawn a scoped Coder sub-agent.'},
  verify: {kind:'pi.dev', label:'/verify <instruction>', description:'Spawn a Verify sub-agent for tests/review.'},
  general: {kind:'pi.dev', label:'/general <instruction>', description:'Spawn a General-purpose sub-agent.'},
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
  if (spec.kind === 'session' && verb === 'model') {
    const fallback = [];
    const remaining = [];
    let role = 'session';
    for (const part of parts) {
      if (String(part).startsWith('--fallback=')) fallback.push(...String(part).split('=')[1].split(',').map(x => x.trim()).filter(Boolean));
      else if (String(part).startsWith('--role=')) role = String(part).split('=')[1] || 'session';
      else remaining.push(part);
    }
    const selector = remaining.join(' ').trim();
    return {kind:'model', verb, prompt: selector ? `Switch session model to ${selector}` : 'Show available session models', metadata:{slash_command:'model', model_selector:selector, model_fallback_selectors:fallback, model_role:role}};
  }
  if (spec.kind === 'pi.dev') {
    let profile = null;
    if (verb === 'subagent' && parts.length) {
      const maybeProfile = String(parts[0] || '').toLowerCase();
      if (['explore','plan','coder','verify','general','default','inspect','review','test','code'].includes(maybeProfile)) {
        profile = parts.shift();
      }
    } else if (['explore','coder','verify','general'].includes(verb)) {
      profile = verb;
    }
    const instruction = parts.join(' ').trim();
    const label = profile ? `${profile} subagent` : 'Subagent';
    return {kind:'subagent', verb, prompt: instruction ? `${label}: ${instruction}` : `${label} task`, metadata:{slash_command:verb, subagent:true, subagent_instruction:instruction, subagent_profile:profile}};
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
  const commands = (typeof sessionSlashCommands !== 'undefined' && sessionSlashCommands && sessionSlashCommands.length) ? sessionSlashCommands : Object.values(SESSION_SLASH_COMMANDS);
  return commands.map(c => `${c.label} - ${c.description}`).join('\n');
}
function isHelpSlashCommand(raw) {
  return String(raw || '').trim().toLowerCase() === '/help';
}
