// Session creation submit handler, composer submit path, and quick selectors

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
  if (contextId && (!selectedSession || (window.selectedSessionContextId?.() || '') !== contextId)) {
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

