// Focused session UI helpers extracted from sessions.js.

function sessionEventTimestampMs(event) {
  const raw = event?.created_at || event?.createdAt || '';
  const value = raw ? new Date(raw).getTime() : 0;
  return Number.isFinite(value) && value > 0 ? value : Date.now();
}

function rememberSessionUserTask(event, text = '') {
  const taskId = event?.task_id || '';
  if (!taskId) return;
  const type = String(event?.type || '').toLowerCase();
  if (!(type === 'user_message' || type.includes('user_message'))) return;
  const prompt = String(text || event?.message || '').trim();
  if (prompt) sessionTaskPrompts.set(taskId, prompt);
  const existing = sessionUserTaskMeta.get(taskId) || {};
  sessionUserTaskMeta.set(taskId, {
    taskId,
    prompt: prompt || existing.prompt || '',
    createdAtMs: existing.createdAtMs || sessionEventTimestampMs(event),
    createdAt: existing.createdAt || event?.created_at || '',
    sequence: existing.sequence || ++sessionTaskSequence,
  });
}

function sessionReplyScopeInfo(event) {
  const taskId = event?.task_id || '';
  if (!taskId) return null;
  const origin = sessionUserTaskMeta.get(taskId);
  if (!origin) return null;
  const eventTime = sessionEventTimestampMs(event);
  const newer = Array.from(sessionUserTaskMeta.values())
    .filter(item => item.taskId !== taskId && item.createdAtMs > origin.createdAtMs && item.createdAtMs <= eventTime)
    .sort((a, b) => b.createdAtMs - a.createdAtMs || b.sequence - a.sequence)[0];
  if (!newer) return null;
  const prompt = origin.prompt || sessionTaskPrompts.get(taskId) || 'Earlier request';
  return {
    taskId,
    newerTaskId: newer.taskId,
    label: 'Reply to earlier request',
    prompt: prompt.length > 140 ? `${prompt.slice(0, 137)}…` : prompt,
  };
}

function appendReplyScopeNotice(parent, event) {
  const info = sessionReplyScopeInfo(event);
  if (!info) return null;
  const notice = document.createElement('div');
  notice.className = 'reply-scope-notice';
  notice.innerHTML = `<span>${escapeHtml(info.label)}</span><small>${escapeHtml(info.prompt)}</small>`;
  parent.appendChild(notice);
  return notice;
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
  if (data.internal === true) return true;
  if (String(data.role || '').toLowerCase() === 'system') return true;
  if (data.visibility === 'internal' || data.hidden === true) return true;
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
