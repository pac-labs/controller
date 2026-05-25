let config = null;
let workspaceTemplates = [];
let personalWorkspaces = [];
let agentContexts = [];
let sharedStorages = [];
let selectedSession = null;
let selectedSourcePath = null;
let selectedSourceFolder = '';
let selectedIdeContextId = '';
let selectedIdeWorkspaceId = '';
let selectedIdeWorkspaceProfile = '';
let selectedIdeSessionId = '';
let selectedBinaryArtifactFilter = '';
let sourceBinaryArtifactProjects = [];
let sourceOpenTabs = [];
let sourceFileState = new Map();
let selectedSourceEntry = '';
let sourceExpandedDirs = new Set(['', 'plugins']);
let sourceTreeCache = new Map();
let sourceLibraryRoot = '';
let sourceResolvedContext = null;
let sourceCodingSessionId = '';
let sourceSelectedToolId = '';
let sourceCodingPoll = null;
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
let setupWizardStepIndex = 0;
let sessionWizardStepIndex = 0;
let agentContextWizardStepIndex = 0;
let setupWizardSteps = [];
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
let sessionTaskPrompts = new Map();
let sessionUserTaskMeta = new Map();
let sessionTaskSequence = 0;
let latestAssistantReplyState = null;
let sessionAutoScrollPinned = true;
let providerHealthCache = new Map();
let controllerHarnessStatusCache = null;

const AUTH_TOKEN_KEY = 'pac_auth_token';

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
    const uiBuild = document.getElementById('pacUiBuildVersion');
    if (uiBuild) {
      uiBuild.textContent = ui;
      uiBuild.title = v?.ui_updated_at ? `UI updated: ${v.ui_updated_at}` : 'UI build identifier';
    }
    window.PacUpdateCenter?.refreshFromVersionInfo?.(v);
    if (v?.version) document.title = `PAC - Pi Agent Control v${v.version}`;
  } catch (_) {}
}
function applyThemeMode(mode = 'system') {
  pacThemeMode = ['system', 'dark', 'light', 'terminal', 'dusk'].includes(String(mode)) ? String(mode) : 'system';
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




function setupTabs() {
  if (window.PacShellNav?.setupTabs) {
    window.PacShellNav.setupTabs(activateMainTab, typeof showRail === 'function' ? showRail : null);
    return;
  }
  window.__pacTabGroups = {NAV_GROUPS: {}, TAB_TO_GROUP: {}, renderGroup: () => {}};
}

function activateMainTab(tabId) {
  if (!tabId) return;
  const tabGroups = window.__pacTabGroups || {};
  const groupName = tabGroups.TAB_TO_GROUP?.[tabId] || 'operate';
  tabGroups.renderGroup?.(groupName, tabId);
  document.querySelectorAll('.tab[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabId));
  document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
  const panel = document.getElementById(tabId);
  if (panel) panel.classList.add('active');
  if (tabId === 'settings-tab') switchSettingsPanel(window.__pacActiveSettingsPanel || 'updates');
  if (tabId === 'observe-tab' && typeof loadObservePanel === 'function') loadObservePanel().catch(()=>{});
  const overflowMenu = document.getElementById('tabsOverflowMenu');
  const overflowBtn = document.getElementById('tabsOverflowButton');
  if (overflowMenu) overflowMenu.hidden = true;
  if (overflowBtn) overflowBtn.setAttribute('aria-expanded', 'false');
  updateTabsOverflow();
}

function updateTabsOverflow() {
  const nav = document.querySelector('.tabs');
  const primary = document.getElementById('tabsPrimary');
  const groups = document.getElementById('tabsGroups');
  const wrap = document.getElementById('tabsOverflowWrap');
  const menu = document.getElementById('tabsOverflowMenu');
  const overflowBtn = document.getElementById('tabsOverflowButton');
  if (!nav || !primary || !groups || !wrap || !menu || !overflowBtn) return;
  const tabs = Array.from(primary.querySelectorAll('.tab[data-tab]'));
  tabs.forEach((tab) => { tab.hidden = false; });
  groups.hidden = false;
  primary.hidden = false;
  wrap.hidden = true;
  menu.hidden = true;
  menu.innerHTML = '';
  nav.classList.remove('tabs-compact-mode');
  overflowBtn.textContent = 'More';
  overflowBtn.classList.remove('compact-nav-trigger');
  const activeTab = tabs.find((tab) => tab.classList.contains('active'))?.dataset.tab || 'dashboard';
  const requiredForTwoRows = (groups.scrollWidth || 0) + (primary.scrollWidth || 0) + 120;
  if (requiredForTwoRows > nav.clientWidth) {
    nav.classList.add('tabs-compact-mode');
    groups.hidden = true;
    primary.hidden = true;
    renderCompactNavMenu(activeTab);
    return;
  }
  const navStyles = getComputedStyle(nav);
  const gap = parseFloat(navStyles.columnGap || navStyles.gap || '0') || 0;
  const reserve = 104;
  let used = 0;
  const hiddenTabs = [];
  const available = Math.max(0, nav.clientWidth - reserve);
  tabs.forEach((tab) => {
    const width = Math.ceil(tab.getBoundingClientRect().width || tab.offsetWidth || 0);
    const next = used === 0 ? width : used + gap + width;
    if (next > available && tabs.length > 1) {
      hiddenTabs.push(tab);
    } else {
      used = next;
    }
  });
  if (!hiddenTabs.length) return;
  hiddenTabs.forEach((tab) => { tab.hidden = true; });
  hiddenTabs.forEach((tab) => {
    const clone = tab.cloneNode(true);
    clone.hidden = false;
    clone.classList.remove('active');
    if (tab.classList.contains('active')) clone.classList.add('active');
    clone.onclick = () => activateMainTab(clone.dataset.tab || '');
    menu.appendChild(clone);
  });
  wrap.hidden = false;
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
  if (document.getElementById('profileEditorContextProfile')) profileEditorContextProfile.innerHTML = '';
  if (document.getElementById('profileEditorPlannerContextProfile')) profileEditorPlannerContextProfile.innerHTML = '<option value="">same as context profile</option>';
  if (document.getElementById('profileEditorPermissionProfile')) profileEditorPermissionProfile.innerHTML = '';
  if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') runnerTools.innerHTML = '';
  if (document.getElementById('wizardRunnerTools') && wizardRunnerTools.tagName === 'SELECT') wizardRunnerTools.innerHTML = '';
  if (document.getElementById('runnerDefaultWorkspace')) runnerDefaultWorkspace.innerHTML = '<option value="">auto</option>';
  if (document.getElementById('wizardRunnerDefaultWorkspace')) wizardRunnerDefaultWorkspace.innerHTML = '<option value="">auto</option>';
  if (document.getElementById('workspaceEndpoint')) workspaceEndpoint.innerHTML = '<option value="">none</option>';
  if (document.getElementById('toolPackage')) toolPackage.innerHTML = '<option value="">none</option>';
  Object.entries(config.agent_profiles || {}).forEach(([k]) => {
    opt(agentProfile, k);
    const wd = document.getElementById('workspaceDefaultProfile');
    if (wd) opt(wd, k);
  });
  Object.keys(config.workspaces || {}).forEach(k => { if (document.getElementById('workspaceProfile')) opt(workspaceProfile,k); if (document.getElementById('runnerDefaultWorkspace')) opt(runnerDefaultWorkspace,k); if (document.getElementById('wizardRunnerDefaultWorkspace')) opt(wizardRunnerDefaultWorkspace,k); });
  Object.entries(config.source_contexts || {}).forEach(([k,ctx]) => {
    const label = [k, ctx.customer_id || '', ctx.workspace_profile || ''].filter(Boolean).join(' · ');
    if (document.getElementById('sessionSourceContext')) opt(sessionSourceContext, k, label);
  });
  Object.keys(config.models || {}).forEach(k => {
    if (modelAvailability(k).ok) {
      opt(modelOverride, k);
      if (document.getElementById('taskModel')) opt(taskModel, k);
    }
    if (document.getElementById('profileModel')) opt(profileModel, k, k);
    if (document.getElementById('profilePlannerModel')) opt(profilePlannerModel, k, k);
  });
  if (document.getElementById('modelProvider')) { modelProvider.innerHTML=''; Object.keys(config.providers || {}).forEach(k => opt(modelProvider,k)); }
  fillModelEndpointOptions();
  Object.keys(config.permission_profiles || {}).forEach(k => {
    opt(permissionOverride, k);
    if (document.getElementById('profilePermission')) opt(profilePermission, k);
    if (document.getElementById('profileEditorPermissionProfile')) opt(profileEditorPermissionProfile, k);
  });
  Object.keys(config.context_profiles || {}).forEach(k => {
    if (document.getElementById('profileContextProfile')) opt(profileContextProfile, k);
    if (document.getElementById('profilePlannerContextProfile')) opt(profilePlannerContextProfile, k);
    if (document.getElementById('profileEditorContextProfile')) opt(profileEditorContextProfile, k);
    if (document.getElementById('profileEditorPlannerContextProfile')) opt(profileEditorPlannerContextProfile, k);
  });
  Object.keys(config.tool_packages || {}).forEach(k => { if (document.getElementById('toolPackage')) opt(toolPackage,k); });
  Object.entries(config.tools || {}).forEach(([k,t]) => {
    const label = `${k}${t.package ? ' · '+t.package : ''}${t.enabled === false ? ' (disabled)' : ''}`;
    if (document.getElementById('profileTools') && profileTools.tagName === 'SELECT') opt(profileTools,k,label);
    if (document.getElementById('runnerTools') && runnerTools.tagName === 'SELECT') opt(runnerTools,k,label);
    if (document.getElementById('wizardRunnerTools') && wizardRunnerTools.tagName === 'SELECT') opt(wizardRunnerTools,k,label);
  });
  syncSessionPermissionQuick();
  updateWizardToolPackagePreview();
}
function emitUiEvent(type, message, data=null) {
  const event = {
    id: `${type}_${Date.now()}_${Math.random()}`,
    type,
    message: message || prettyEventType(type),
    created_at: new Date().toISOString(),
    session_id: selectedSession?.id || 'system',
    data: data ? {details: data, source: 'ui'} : {source: 'ui'},
  };
  window.__pacLastUiEvent = event;
  const railOpen = document.getElementById('eventsRail') && !document.getElementById('eventsRail')?.hidden;
  if (railOpen && typeof renderGlobalEvent === 'function') renderGlobalEvent(event, true);
  if (typeof api === 'function') {
    api('/v1/events/ui', {
      method: 'POST',
      body: JSON.stringify({
        type: event.type,
        message: event.message,
        session_id: event.session_id,
        data: event.data,
      }),
    }).then((saved) => {
      if (saved) window.__pacLastUiEvent = saved;
    }).catch(() => {
      // Local rendering above keeps the UI responsive when PAC is restarting or auth is not ready.
    });
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










const AGENT_CONTEXT_WIZARD_STEPS = [
  {id: 'agentContextStepBasics', label: 'Basics'},
  {id: 'agentContextStepRuntime', label: 'Runtime'},
  {id: 'agentContextStepBehavior', label: 'Behavior'},
  {id: 'agentContextStepAccess', label: 'Access'},
];

































// ---- Model Sync from Provider Modal ----
let _modelSyncData = [];






// Add warning badge to model cards with mismatch


// ---- Proxy Routes UI ----









// Wire up proxy route buttons
const addProxyRouteBtn = document.getElementById('addProxyRouteBtn');
if (addProxyRouteBtn) addProxyRouteBtn.onclick = () => openProxyRouteForm(null);
const saveProxyRouteBtn = document.getElementById('saveProxyRoute');
if (saveProxyRouteBtn) saveProxyRouteBtn.onclick = saveProxyRoute;
const cancelProxyRouteBtn = document.getElementById('cancelProxyRoute');
if (cancelProxyRouteBtn) cancelProxyRouteBtn.onclick = cancelProxyRoute;

// Modal close button bindings
const closeModelSyncModalBtn = document.getElementById('closeModelSyncModal');
if (closeModelSyncModalBtn) closeModelSyncModalBtn.onclick = closeModelSyncModal;
const closeModelSyncModal2Btn = document.getElementById('closeModelSyncModal2');
if (closeModelSyncModal2Btn) closeModelSyncModal2Btn.onclick = closeModelSyncModal;
const applyAllModelSyncBtn = document.getElementById('applyAllModelSync');
if (applyAllModelSyncBtn) applyAllModelSyncBtn.onclick = applyAllModelSync;







function fillProfileForm(name) {
  if (typeof openProfileModal === 'function') openProfileModal(name);
}

async function loadConfig() {
  config = await api('/v1/config');
  authStatus = {...(authStatus || {}), ...(config?.auth || {})};
  sessionSlashCommands = Array.isArray(config?.session_slash_commands) ? config.session_slash_commands : [];
  await loadWorkspaceCatalogs();
  fillSelects(); renderSharedStorages(); renderAgentContexts(); renderWorkspaces(); renderProfiles(); renderProviders(); renderModels(); renderTools();
  document.getElementById('configEditor').value = JSON.stringify(config, null, 2);
  renderSystemInfo();
  renderHeaderAuthBox();
  renderControllerHarnessSettings();
  renderEndpointConnectionSettings();
  renderAuthInfo();
  renderZedConfigExamples();
  renderSourceContexts();
  renderIdeWorkspaceSelectors();
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
const loadDiffBtn = document.getElementById('loadDiff');
if (loadDiffBtn) loadDiffBtn.onclick=()=>openGitDiffModal();
document.getElementById('saveConfig').onclick=async()=>{ const body={config:JSON.parse(configEditor.value)}; await api('/v1/config',{method:'PUT',body:JSON.stringify(body)}); await init(); };
if (document.getElementById('saveEndpointConnection')) document.getElementById('saveEndpointConnection').onclick=()=>saveEndpointConnectionSettings().catch(e=>paneError('Saving endpoint URL failed', e.message));
if (document.getElementById('saveControllerHarness')) document.getElementById('saveControllerHarness').onclick=()=>saveControllerHarnessSettings().catch(e=>paneError('Saving controller pi.dev failed', e.message));
if (document.getElementById('updateControllerHarnessWrapper')) document.getElementById('updateControllerHarnessWrapper').onclick=()=>updateControllerHarnessWrapper().catch(e=>paneError('Updating controller wrapper failed', e.message));
if (document.getElementById('bootstrapControllerHarness')) document.getElementById('bootstrapControllerHarness').onclick=()=>bootstrapControllerHarness().catch(e=>paneError('Starting controller pi.dev bootstrap failed', e.message));
if (document.getElementById('openControllerHarnessSession')) document.getElementById('openControllerHarnessSession').onclick=()=>openControllerHarnessSession().catch(e=>paneError('Opening controller pi.dev failed', e.message));
if (document.getElementById('providerPreset')) providerPreset.onchange=()=>applyProviderPreset(providerPreset.value);
if (document.getElementById('saveProvider')) saveProvider.onclick=()=>saveProviderFromForm().catch(e=>paneError('Provider save failed', e.message));
if (document.getElementById('connectProviderForm')) connectProviderForm.onclick=()=>connectProviderFromForm().catch(e=>paneError('Provider connect failed', e.message));
if (typeof bindProfilesPage === 'function') bindProfilesPage();
if (document.getElementById('saveModel')) saveModel.onclick=()=>saveModelFromForm().catch(e=>paneError('Model save failed', e.message));
if (document.getElementById('testModelForm')) testModelForm.onclick=()=>testModelFromForm().catch(e=>paneError('Model test failed', e.message));
if (document.getElementById('modelProvider')) modelProvider.onchange=()=>{ const providerName = modelProvider.value || ''; const providerDisplay = document.getElementById('modelProviderDisplay'); if (providerDisplay) providerDisplay.textContent = providerName; updateLmStudioModelControls(); syncSuggestedModelKey(true); refreshModelProviderCandidates(providerName).catch(()=>{}); };
if (document.getElementById('modelId')) modelId.oninput = () => syncSuggestedModelKey();
if (document.getElementById('modelManualIdOverride')) modelManualIdOverride.onchange = () => refreshModelIdManualOverrideState();
if (document.getElementById('modelFunction')) document.getElementById('modelFunction').onchange = () => syncSuggestedModelKey(true);
if (document.getElementById('modelName')) modelName.oninput = () => { modelName.dataset.auto = 'false'; };
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
const ideContextSelect = document.getElementById('ideContextSelect');
if (ideContextSelect) ideContextSelect.onchange = async () => {
  selectedIdeContextId = ideContextSelect.value || '';
  applyIdeContextSelection(selectedIdeContextId);
  selectedIdeSessionId = '';
  sourceCodingSessionId = '';
  sourceTreeCache.clear();
  sourceExpandedDirs = new Set(['']);
  sourceOpenTabs = [];
  sourceFileState.clear();
  selectedSourcePath = null;
  selectedSourceFolder = '';
  selectedSourceEntry = '';
  if (selectedIdeWorkspaceId) fillUserWorkspaceForm(selectedIdeWorkspaceId);
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  await renderSources('');
};
const ideWorkspaceSelect = document.getElementById('ideWorkspaceSelect');
if (ideWorkspaceSelect) ideWorkspaceSelect.onchange = async () => {
  selectedIdeWorkspaceId = ideWorkspaceSelect.value || '';
  selectedIdeSessionId = '';
  sourceCodingSessionId = '';
  sourceTreeCache.clear();
  sourceExpandedDirs = new Set(['']);
  sourceOpenTabs = [];
  sourceFileState.clear();
  selectedSourcePath = null;
  selectedSourceFolder = '';
  selectedSourceEntry = '';
  if (selectedIdeWorkspaceId) fillUserWorkspaceForm(selectedIdeWorkspaceId);
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  await renderSources('');
};
const ideSessionSelect = document.getElementById('ideSessionSelect');
if (ideSessionSelect) ideSessionSelect.onchange = async () => {
  selectedIdeSessionId = ideSessionSelect.value || '';
  sourceCodingSessionId = selectedIdeSessionId || '';
  const session = currentIdeSession();
  const userWorkspace = userWorkspaceForIdeSession(session);
  if (userWorkspace?.id) selectedIdeWorkspaceId = userWorkspace.id;
  sourceTreeCache.clear();
  sourceExpandedDirs = new Set(['']);
  sourceOpenTabs = [];
  sourceFileState.clear();
  selectedSourcePath = null;
  selectedSourceFolder = '';
  selectedSourceEntry = '';
  renderIdeWorkspaceSelectors();
  updateSourceCodingPanel();
  await renderSources('');
};
if (document.getElementById('userWorkspaceSelect')) userWorkspaceSelect.onchange = () => fillUserWorkspaceForm(userWorkspaceSelect.value || '');
if (document.getElementById('userWorkspaceTemplate')) userWorkspaceTemplate.onchange = () => {
  const template = workspaceTemplates.find((item) => item.id === userWorkspaceTemplate.value);
  if (!template) return;
  if (document.getElementById('userWorkspaceType') && !userWorkspaceType.value) userWorkspaceType.value = template.workspace_type || 'local';
  if (document.getElementById('userWorkspaceProfile') && !userWorkspaceProfile.value) userWorkspaceProfile.value = template.workspace_profile || '';
  if (document.getElementById('userWorkspaceSharedStorage') && !userWorkspaceSharedStorage.value) userWorkspaceSharedStorage.value = template.shared_storage_id || '';
  if (document.getElementById('userWorkspaceStorageSubpath') && !userWorkspaceStorageSubpath.value) userWorkspaceStorageSubpath.value = template.storage_subpath || '';
  if (document.getElementById('userWorkspaceStorageMountPath') && !userWorkspaceStorageMountPath.value) userWorkspaceStorageMountPath.value = template.storage_mount_path || '';
  if (document.getElementById('userWorkspaceEndpoint') && !userWorkspaceEndpoint.value) userWorkspaceEndpoint.value = template.endpoint_id || '';
  if (document.getElementById('userWorkspaceContainerImage') && !userWorkspaceContainerImage.value) userWorkspaceContainerImage.value = template.container_image || '';
  if (document.getElementById('userWorkspaceAgentProfile') && !userWorkspaceAgentProfile.value) userWorkspaceAgentProfile.value = template.agent_profile || '';
  if (document.getElementById('userWorkspaceDescription') && !userWorkspaceDescription.value) userWorkspaceDescription.value = template.description || '';
};
if (document.getElementById('saveUserWorkspace')) saveUserWorkspace.onclick = () => saveUserWorkspaceFromForm().catch(e=>paneError('Saving personal workspace failed', e.message));
if (document.getElementById('deleteUserWorkspace')) deleteUserWorkspace.onclick = () => deleteUserWorkspaceFromForm().catch(e=>paneError('Deleting personal workspace failed', e.message));
if (document.getElementById('openUserWorkspaceIde')) openUserWorkspaceIde.onclick = () => openUserWorkspaceInIde().catch(e=>paneError('Opening workspace in IDE failed', e.message));
if (document.getElementById('agentContextSelect')) agentContextSelect.onchange = () => fillAgentContextForm(agentContextSelect.value || '');
if (document.getElementById('saveAgentContext')) saveAgentContext.onclick = () => saveAgentContextFromForm().catch(e=>paneError('Saving agent context failed', e.message));
if (document.getElementById('deleteAgentContext')) deleteAgentContext.onclick = () => deleteAgentContextFromForm().catch(e=>paneError('Deleting agent context failed', e.message));
if (document.getElementById('openAgentContextSession')) openAgentContextSession.onclick = () => openAgentContextSessionFromForm().catch(e=>paneError('Opening agent context session failed', e.message));
const openAgentContextWizardBtn = document.getElementById('openAgentContextWizard');
if (openAgentContextWizardBtn) openAgentContextWizardBtn.onclick = () => openAgentContextWizard('');
const closeAgentContextWizardBtn = document.getElementById('closeAgentContextWizard');
if (closeAgentContextWizardBtn) closeAgentContextWizardBtn.onclick = () => closeAgentContextWizard();
const agentContextWizardBackBtn = document.getElementById('agentContextWizardBack');
if (agentContextWizardBackBtn) agentContextWizardBackBtn.onclick = () => { agentContextWizardStepIndex = Math.max(0, agentContextWizardStepIndex - 1); renderAgentContextWizard(); };
const agentContextWizardNextBtn = document.getElementById('agentContextWizardNext');
if (agentContextWizardNextBtn) agentContextWizardNextBtn.onclick = () => { agentContextWizardStepIndex = Math.min(AGENT_CONTEXT_WIZARD_STEPS.length - 1, agentContextWizardStepIndex + 1); renderAgentContextWizard(); };
if (document.getElementById('sharedStorageSelect')) sharedStorageSelect.onchange = () => fillSharedStorageForm(sharedStorageSelect.value || '');
if (document.getElementById('saveSharedStorage')) saveSharedStorage.onclick = () => saveSharedStorageFromForm().catch(e=>paneError('Saving shared storage failed', e.message));
if (document.getElementById('deleteSharedStorage')) deleteSharedStorage.onclick = () => deleteSharedStorageFromForm().catch(e=>paneError('Deleting shared storage failed', e.message));
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
const openSourceSetupModalBtn = document.getElementById('openSourceSetupModal');
const openSourceProfileConfigBtn = document.getElementById('openSourceProfileConfig');
const closeSourceSetupModalBtn = document.getElementById('closeSourceSetupModal');
if (openSourceSetupModalBtn) openSourceSetupModalBtn.onclick = () => { const modal = document.getElementById('sourceSetupModal'); if (modal) modal.hidden = false; };
if (openSourceProfileConfigBtn) openSourceProfileConfigBtn.onclick = () => {
  openPersonalSettingsModal().catch((e)=>paneError('Personal settings could not be opened', e.message || String(e)));
};
if (closeSourceSetupModalBtn) closeSourceSetupModalBtn.onclick = () => { const modal = document.getElementById('sourceSetupModal'); if (modal) modal.hidden = true; };
const sourceSetupModal = document.getElementById('sourceSetupModal');
if (sourceSetupModal) sourceSetupModal.onclick = (ev) => { if (ev.target === sourceSetupModal) sourceSetupModal.hidden = true; };
const sourceCodingToolsEl = document.getElementById('sourceCodingTools');
  if (sourceCodingToolsEl) sourceCodingToolsEl.onclick = async (ev) => {
  const openBtn = ev.target.closest('[data-tool-open]');
  if (openBtn) {
    const toolId = openBtn.getAttribute('data-tool-open') || '';
    const tool = sourceToolEntries().find(item => item.id === toolId);
    if (tool?.sourceAvailable) {
      try {
        await openSourcePath(tool.sourcePath, 'dir');
      } catch (e) {
        paneError('Tool source could not be opened', e.message || String(e));
      }
    }
    return;
  }
  const createBtn = ev.target.closest('[data-tool-create]');
  if (createBtn) {
    const toolId = createBtn.getAttribute('data-tool-create') || '';
    try {
      await createSourceToolScaffold(toolId);
    } catch (e) {
      paneError('Tool source could not be created', e.message || String(e));
    }
    return;
  }
  const selectBtn = ev.target.closest('[data-tool-select]');
  if (selectBtn) {
    sourceSelectedToolId = selectBtn.getAttribute('data-tool-select') || '';
    renderSourceToolCatalog();
    updateSourceCodingPanel();
  }
};
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
const bootstrapSourceCodingSessionBtn = document.getElementById('bootstrapSourceCodingSession');
if (bootstrapSourceCodingSessionBtn) bootstrapSourceCodingSessionBtn.onclick = async () => {
  const status = document.getElementById('sourceCodingStatus');
  try {
    if (status) { status.hidden = false; status.textContent = 'Starting coding session…'; }
    const session = await ensureSourceCodingSession();
    if (status) status.textContent = `Coding session ready: ${session.name || session.id}`;
    updateSourceCodingPanel();
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
    paneError('Coding session could not start', e.message || String(e));
  }
};
const openSourceCodingSessionBtn = document.getElementById('openSourceCodingSession');
if (openSourceCodingSessionBtn) openSourceCodingSessionBtn.onclick = async () => {
  try {
    const session = sourceCodingSessionId ? ((window.__pacSessions || []).find(s => s.id === sourceCodingSessionId) || await ensureSourceCodingSession()) : await ensureSourceCodingSession();
    switchToTab('sessions-tab');
    await selectSession(session.id);
  } catch (e) {
    paneError('Coding session could not be opened', e.message || String(e));
  }
};
const askSourceCodingSessionBtn = document.getElementById('askSourceCodingSession');
if (askSourceCodingSessionBtn) askSourceCodingSessionBtn.onclick = async () => {
  const status = document.getElementById('sourceCodingStatus');
  const prompt = document.getElementById('sourceCodingPrompt')?.value || '';
  try {
    if (status) { status.hidden = false; status.textContent = 'Sending to coding session…'; }
    await sendPromptToSourceCodingSession(prompt);
    if (status) status.textContent = 'Sent to coding session.';
  } catch (e) {
    if (status) status.textContent = `Failed: ${e.message || String(e)}`;
    paneError('Coding session prompt failed', e.message || String(e));
  }
};
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
if (document.getElementById('saveWorkspace')) saveWorkspace.onclick=()=>saveWorkspaceFromForm().catch(e=>paneError('Workspace save failed', e.message));
if (document.getElementById('deleteWorkspace')) deleteWorkspace.onclick=()=>deleteWorkspaceFromForm().catch(e=>paneError('Workspace delete failed', e.message));
if (document.getElementById('deleteTool')) deleteTool.onclick=()=>deleteToolFromForm().catch(e=>paneError('Tool delete failed', e.message));
if (document.getElementById('uploadStagePackage')) uploadStagePackage.onclick=()=>uploadStagePackageFromForm().catch(e=>{ showInline('stagePackageResult', `Failed: ${e.message}`); paneError('Package upload failed', e.message); });
if (document.getElementById('restartPac')) restartPac.onclick=()=>restartPacFromForm().catch(e=>{ showInline('stagePackageResult', `Failed: ${e.message}`); paneError('Restart request failed', e.message); });
if (document.getElementById('refreshTlsStatus')) refreshTlsStatus.onclick=()=>loadTlsStatus().catch(e=>paneError('TLS status failed', e.message));
if (document.getElementById('setHostService')) setHostService.onclick=()=>setServiceMode('host').catch(e=>paneError('Service mode change failed', e.message));
if (document.getElementById('setUserService')) setUserService.onclick=()=>setServiceMode('user').catch(e=>paneError('Service mode change failed', e.message));











const binaryFolderFilter = document.getElementById('binaryFolderFilter');
if (binaryFolderFilter) binaryFolderFilter.onchange = () => {
  selectedBinaryArtifactFilter = binaryFolderFilter.value || '';
  loadSourceBinaryArtifacts(selectedBinaryArtifactFilter).catch(e=>paneError('Binary downloads unavailable', e.message));
};
const downloadFilterText = document.getElementById('downloadFilterText');
if (downloadFilterText) downloadFilterText.oninput = () => {
  renderBinaryDownloads(sourceBinaryArtifactProjects || []);
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

// Sync from Provider button
const syncModelProviderBtn = document.getElementById('syncModelProviderBtn');
if (syncModelProviderBtn) syncModelProviderBtn.onclick = () => openModelSyncModal();


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
if (sessionBootstrapModeSelect) sessionBootstrapModeSelect.onchange = () => { applySessionBootstrapMode(); updateSessionWizardReview(); };
const sessionAgentContextSelect = document.getElementById('sessionAgentContext');
if (sessionAgentContextSelect) sessionAgentContextSelect.onchange = () => {
  const id = sessionAgentContextSelect.value || '';
  if (id) applyIdeContextSelection(id);
  updateSessionWizardReview();
};
const composerAgentContextSelect = document.getElementById('composerAgentContext');
if (composerAgentContextSelect) composerAgentContextSelect.onchange = () => {
  const id = composerAgentContextSelect.value || '';
  if (id) applyIdeContextSelection(id);
};
const sessionSourceContextSelect = document.getElementById('sessionSourceContext');
if (sessionSourceContextSelect) sessionSourceContextSelect.onchange = () => {
  const name = sessionSourceContextSelect.value || '';
  if (!name) return;
  applySessionSourceContext(name).catch(e => paneError('Source context could not be applied', e.message));
};
['sessionName','agentProfile','workspaceProfile','sessionWorkspaceType','sessionWorkspacePath','sessionWorkspaceUrl','sessionWorkspaceBranch','sessionEndpoint','modelOverride','permissionOverride','contextMode'].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', updateSessionWizardReview);
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) el.addEventListener('input', updateSessionWizardReview);
});
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
    const contextId = document.getElementById('sessionAgentContext')?.value || '';
    if (contextId) {
      const ensured = await api(`/v1/agent-contexts/${encodeURIComponent(contextId)}/session`, {method:'POST'});
      const s = ensured.session;
      if (status) status.textContent = 'Created.';
      closeSessionModal();
      await loadSessions(); await loadDashboardMetrics(); switchToTab('sessions-tab'); await selectSession(s.id);
      return;
    }
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
const sessionWizardBackBtn = document.getElementById('sessionWizardBack');
if (sessionWizardBackBtn) sessionWizardBackBtn.onclick = () => advanceSessionWizard(-1);
const sessionWizardNextBtn = document.getElementById('sessionWizardNext');
if (sessionWizardNextBtn) sessionWizardNextBtn.onclick = () => advanceSessionWizard(1);
const sessionModal = document.getElementById('sessionModal');
if (sessionModal) sessionModal.onclick = (ev) => { if (ev.target === sessionModal) closeSessionModal(); };
const dashboardRefreshBtn = document.getElementById('dashboardRefreshMetrics');
if (dashboardRefreshBtn) dashboardRefreshBtn.onclick = () => loadDashboardMetrics();










async function init(){
  loadThemeMode();
  setupTabs();
  setupEventsRail();
  if (typeof setupDashboardTopologyUi === 'function') setupDashboardTopologyUi();
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
  if (typeof loadDashboardTopology === 'function') await loadDashboardTopology().catch(()=>{});
  if (typeof loadNotificationSummary === 'function') await loadNotificationSummary().catch(()=>{});
  await loadGlobalEvents(true);
  loadMcpBuildStatus().catch(()=>{});
  await loadBinaryFolderFilters().catch(()=>{});
  await loadSourceBinaryArtifacts().catch(()=>{});
  updateSourceActions();
}
init().catch(e=>paneError('PAC UI could not load', e.message || String(e)));

const openEndpointBtn = document.getElementById('openEndpointModal');
if (openEndpointBtn) openEndpointBtn.onclick = openEndpointModal;


