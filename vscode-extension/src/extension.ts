import * as vscode from 'vscode';

type Session = {
  id: string;
  name?: string;
  agent_profile?: string;
  model: string;
  permission_profile: string;
  context_mode: string;
  workspace_path: string;
  metadata?: Record<string, unknown>;
};

type Task = {
  id: string;
  status: string;
  output?: string;
  error?: string;
  command?: string;
  prompt: string;
};

type ProfilesPayload = {
  agent_profiles: Record<string, { model?: string; permission_profile?: string; context_mode?: string }>;
  workspaces: Record<string, { description?: string; default_agent_profile?: string; path?: string; type?: string }>;
  models: Record<string, unknown>;
};

type SourceContextSummary = {
  name: string;
  description?: string;
  path_prefix?: string;
  customer_id?: string;
  user_scope?: string;
  workspace_profile?: string;
  preferred_endpoint?: string;
  profile?: string;
};

type SourceContextResolvePayload = {
  name: string;
  context: SourceContextSummary;
  environment?: Record<string, string>;
  config_vars?: Record<string, string>;
  secret_refs?: Record<string, string>;
};

type SessionPlan = {
  name: string;
  agent_profile?: string;
  workspace: Record<string, unknown>;
  model?: string;
  metadata: Record<string, unknown>;
  summary: string[];
};

function headers(): Record<string, string> {
  const cfg = vscode.workspace.getConfiguration('piAgent');
  const token = cfg.get<string>('token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function baseUrl(): string {
  return (vscode.workspace.getConfiguration('piAgent').get<string>('baseUrl') || 'https://localhost').replace(/\/$/, '');
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const h = { ...(init.headers as Record<string, string> || {}), ...headers() };
  if (init.body && !h['content-type']) h['content-type'] = 'application/json';
  const r = await fetch(`${baseUrl()}${path}`, { ...init, headers: h });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return await r.json() as T;
}

function activeWorkspacePath(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function workspaceSummary(workspace: { description?: string; path?: string; type?: string }): string {
  return [workspace.type || 'workspace', workspace.description || workspace.path || ''].filter(Boolean).join(' - ');
}

async function pickAgentProfile(profiles: ProfilesPayload, preferred?: string): Promise<string> {
  const names = Object.keys(profiles.agent_profiles || {});
  if (!names.length) throw new Error('No PAC agent profiles are configured');
  const ordered = preferred && names.includes(preferred) ? [preferred, ...names.filter(name => name !== preferred)] : names;
  const items = ordered.map(name => {
    const profile = profiles.agent_profiles[name] || {};
    return {
      label: name,
      description: [profile.model || 'no model', profile.permission_profile || 'permissions', profile.context_mode || 'context'].join(' - '),
    };
  });
  const picked = await vscode.window.showQuickPick(items, { placeHolder: 'Select a PAC agent profile' });
  if (!picked) throw new Error('No agent profile selected');
  return picked.label;
}

async function pickModelOverride(profiles: ProfilesPayload): Promise<string | undefined> {
  const modelNames = Object.keys(profiles.models || {});
  if (!modelNames.length) return undefined;
  const picked = await vscode.window.showQuickPick(
    [{ label: '(profile default)', description: 'Use the model configured on the selected profile' }, ...modelNames.map(name => ({ label: name }))],
    { placeHolder: 'Optional model override' },
  );
  if (!picked || picked.label === '(profile default)') return undefined;
  return picked.label;
}

async function pickWorkspacePayload(profiles: ProfilesPayload, preferredWorkspace?: string): Promise<Record<string, unknown>> {
  const localPath = activeWorkspacePath();
  const savedWorkspaceNames = Object.keys(profiles.workspaces || {});
  const defaultSaved = preferredWorkspace && savedWorkspaceNames.includes(preferredWorkspace) ? preferredWorkspace : undefined;
  const options = [
    defaultSaved ? { label: `Saved workspace: ${defaultSaved}`, description: workspaceSummary(profiles.workspaces[defaultSaved] || {}) } : undefined,
    ...savedWorkspaceNames.filter(name => name !== defaultSaved).map(name => ({ label: `Saved workspace: ${name}`, description: workspaceSummary(profiles.workspaces[name] || {}) })),
    localPath ? { label: 'Current local workspace', description: localPath } : undefined,
  ].filter(Boolean) as { label: string; description?: string }[];
  if (!options.length) throw new Error('No PAC workspaces are configured and no local VS Code workspace is open');
  const picked = await vscode.window.showQuickPick(options, { placeHolder: 'Select the PAC workspace for this session' });
  if (!picked) throw new Error('No workspace selected');
  if (picked.label.startsWith('Saved workspace: ')) {
    return { type: 'profile', profile: picked.label.replace('Saved workspace: ', '') };
  }
  return { type: 'local', path: localPath };
}

async function fetchProfiles(): Promise<ProfilesPayload> {
  return await api<ProfilesPayload>('/v1/profiles');
}

async function fetchSourceContexts(): Promise<SourceContextSummary[]> {
  const payload = await api<{ items: SourceContextSummary[] }>('/v1/source-contexts');
  return payload.items || [];
}

async function resolveSourceContext(name: string): Promise<SourceContextResolvePayload> {
  return await api<SourceContextResolvePayload>(`/v1/source-contexts/resolve?name=${encodeURIComponent(name)}&include_secrets=false`);
}

async function createProfileSessionPlan(): Promise<SessionPlan> {
  const profiles = await fetchProfiles();
  const agentProfile = await pickAgentProfile(profiles);
  const workspace = await pickWorkspacePayload(profiles);
  const model = await pickModelOverride(profiles);
  const name = await vscode.window.showInputBox({ prompt: 'Session name', value: 'vscode-session' });
  return {
    name: name || 'vscode-session',
    agent_profile: agentProfile,
    workspace,
    model,
    metadata: { session_origin: 'vscode-extension' },
    summary: [`Profile: ${agentProfile}`, `Workspace: ${typeof workspace.profile === 'string' ? workspace.profile : (workspace.path || 'local workspace')}`],
  };
}

async function createContextSessionPlan(): Promise<SessionPlan> {
  const contexts = await fetchSourceContexts();
  if (!contexts.length) throw new Error('No PAC source contexts are configured');
  const contextPick = await vscode.window.showQuickPick(
    contexts.map(ctx => ({
      label: ctx.name,
      description: [ctx.customer_id || '', ctx.user_scope || '', ctx.path_prefix || ''].filter(Boolean).join(' - '),
      detail: ctx.description || '',
    })),
    { placeHolder: 'Select a PAC source context' },
  );
  if (!contextPick) throw new Error('No source context selected');
  const resolved = await resolveSourceContext(contextPick.label);
  const profiles = await fetchProfiles();
  const preferredProfile = resolved.context.profile || profiles.workspaces?.[resolved.context.workspace_profile || '']?.default_agent_profile;
  const agentProfile = await pickAgentProfile(profiles, preferredProfile);
  const workspace = await pickWorkspacePayload(profiles, resolved.context.workspace_profile);
  const model = await pickModelOverride(profiles);
  const defaultName = `vscode-${resolved.name.replace(/[^a-zA-Z0-9_.-]+/g, '-')}`;
  const name = await vscode.window.showInputBox({ prompt: 'Session name', value: defaultName });
  const metadata: Record<string, unknown> = {
    session_origin: 'vscode-extension',
    source_context_name: resolved.name,
    source_context_path: resolved.context.path_prefix,
    customer_id: resolved.context.customer_id || undefined,
    user_scope: resolved.context.user_scope || undefined,
  };
  if (resolved.context.preferred_endpoint) metadata.preferred_endpoint = resolved.context.preferred_endpoint;
  return {
    name: name || defaultName,
    agent_profile: agentProfile,
    workspace,
    model,
    metadata,
    summary: [
      `Source context: ${resolved.name}`,
      `Customer: ${resolved.context.customer_id || '-'}`,
      `User scope: ${resolved.context.user_scope || '-'}`,
      `Workspace: ${typeof workspace.profile === 'string' ? workspace.profile : (workspace.path || 'local workspace')}`,
      `Preferred endpoint: ${String(metadata.preferred_endpoint || '-')}`,
      `Config vars: ${Object.keys(resolved.config_vars || {}).length}`,
      `Secret refs: ${Object.keys(resolved.secret_refs || {}).length}`,
    ],
  };
}

async function chooseSessionPlan(): Promise<SessionPlan> {
  const contexts = await fetchSourceContexts().catch(() => []);
  const items = [
    { label: 'Profile session', detail: 'Pick a profile and workspace directly from PAC' },
    contexts.length ? { label: 'Source-context session', detail: 'Start from a PAC source context with customer and endpoint defaults' } : undefined,
  ].filter(Boolean) as { label: string; detail?: string }[];
  const picked = await vscode.window.showQuickPick(items, { placeHolder: 'Choose the PAC session bootstrap mode' });
  if (!picked) throw new Error('No session mode selected');
  if (picked.label === 'Source-context session') return await createContextSessionPlan();
  return await createProfileSessionPlan();
}

async function createSessionFromPlan(plan: SessionPlan): Promise<Session> {
  return await api<Session>('/v1/sessions', {
    method: 'POST',
    body: JSON.stringify({
      name: plan.name,
      agent_profile: plan.agent_profile,
      model: plan.model,
      workspace: plan.workspace,
      metadata: plan.metadata,
    }),
  });
}

async function createSession(): Promise<{ session: Session; plan: SessionPlan }> {
  const plan = await chooseSessionPlan();
  const session = await createSessionFromPlan(plan);
  return { session, plan };
}

async function runTask(session: Session, wait = false): Promise<Task> {
  const editor = vscode.window.activeTextEditor;
  const selectedText = editor?.document.getText(editor.selection);
  const prompt = await vscode.window.showInputBox({
    prompt: 'Prompt for PAC',
    value: selectedText ? `Work with this selected text:\n\n${selectedText}` : 'Inspect the workspace and continue from there',
  });
  if (!prompt) throw new Error('No prompt');
  const command = await vscode.window.showInputBox({
    prompt: 'Optional command to execute remotely',
    value: selectedText ? '' : 'pwd && ls -la',
  });
  return await api<Task>(`/v1/sessions/${session.id}/tasks${wait ? '?wait=true' : ''}`, {
    method: 'POST',
    body: JSON.stringify({ prompt, command: command || undefined }),
  });
}

async function showSession(session: Session, task?: Task, plan?: SessionPlan) {
  const events = await api<any[]>(`/v1/sessions/${session.id}/events/snapshot`);
  const status = await api<{ status: string }>(`/v1/sessions/${session.id}/git/status`).catch(() => ({ status: '' }));
  const diff = await api<{ diff: string }>(`/v1/sessions/${session.id}/diff`).catch(() => ({ diff: '' }));
  const summary = [
    `- session: ${session.id}`,
    `- profile: ${session.agent_profile || 'custom'}`,
    `- model: ${session.model}`,
    `- permissions: ${session.permission_profile}`,
    `- context: ${session.context_mode}`,
    `- workspace: ${session.workspace_path}`,
    session.metadata?.source_context_name ? `- source context: ${String(session.metadata.source_context_name)}` : '',
    session.metadata?.preferred_endpoint ? `- endpoint: ${String(session.metadata.preferred_endpoint)}` : '',
    task ? `- task: ${task.id} (${task.status})` : '',
  ].filter(Boolean);
  const body = [
    `# PAC Session`,
    '',
    ...summary,
    '',
    plan ? '## Bootstrap' : '',
    ...(plan ? plan.summary.map(line => `- ${line}`) : []),
    ...(plan ? [''] : []),
    `## Events`,
    '```text',
    events.map(e => `[${e.type}] ${e.message}`).join('\n'),
    '```',
    `## Git status`,
    '```text', status.status, '```',
    `## Git diff`,
    '```diff', diff.diff, '```',
  ].join('\n');
  const doc = await vscode.workspace.openTextDocument({ content: body, language: 'markdown' });
  await vscode.window.showTextDocument(doc);
}

async function commandCreateSession() {
  const { session, plan } = await createSession();
  await showSession(session, undefined, plan);
  vscode.window.showInformationMessage(`PAC session created: ${session.id}`);
}

async function commandRunTask(wait: boolean) {
  const { session, plan } = await createSession();
  const task = await runTask(session, wait);
  await showSession(session, task, plan);
  if (!wait) vscode.window.showInformationMessage(`PAC task ${task.status}: ${task.id}`);
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.createSession', async () => {
    try {
      await commandCreateSession();
    } catch (e: any) {
      vscode.window.showErrorMessage(e.message);
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.runTask', async () => {
    try {
      await commandRunTask(false);
    } catch (e: any) {
      vscode.window.showErrorMessage(e.message);
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.runTaskWait', async () => {
    try {
      await commandRunTask(true);
    } catch (e: any) {
      vscode.window.showErrorMessage(e.message);
    }
  }));
}

export function deactivate() {}
