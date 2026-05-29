// Session timeline snapshot, polling, pending rows, and event rendering.

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
  tail.forEach((ev) => {
    const block = normalizeTimelineBlock(ev);
    const text = timelineText(ev, block);
    rememberSessionUserTask(ev, text);
  });
  suppressSessionAutoScroll = true;
  renderSubagentSummaryPanel(tail);
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
  rememberSessionUserTask(event, text);
  const internal = isInternalSessionEvent(event) || looksLikeInternalResultMessage(event, text);
  const hiddenSystemMessage = !internal && String(event?.data?.role || '').toLowerCase() === 'system';
  if (internal && prepend) {
    return;
  }
  if (internal) {
    const group = ensureSessionThinkingGroup(event);
    group.events.push({event, block});
    group.lastEvent = event;
    if (isSessionIntentEvent(event) || typeLower.includes('agent_phase_running') || typeLower.includes('model_stream_progress') || typeLower.includes('model_call_')) {
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
  if (hiddenSystemMessage) return;
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
  if (role === 'assistant') appendReplyScopeNotice(bubble, event);
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

