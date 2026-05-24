// Session composer controls, attachments, diagnostics, and prompt actions.

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
  const contextId = window.selectedSessionContextId?.() || document.getElementById('composerAgentContext')?.value || '';
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
    else status.textContent = selectedSession ? 'Ready for a message.' : 'Create or select a session.';
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

function composerAttachmentKey(label, kind='context') {
  return `${String(kind || 'context').toLowerCase()}::${String(label || '').trim().toLowerCase()}`;
}

function rememberComposerAttachment(label, kind='context') {
  const key = composerAttachmentKey(label, kind);
  if (composerAttachedItems.some((item) => composerAttachmentKey(item.label, item.kind) === key)) {
    renderComposerAttachmentTray();
    updateComposerChrome();
    return;
  }
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
  const current = String(prompt.value || '');
  const trimmedBlock = block.trim();
  if (!current.includes(trimmedBlock)) {
    prompt.value = `${current}${block}`.trimStart();
  }
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
