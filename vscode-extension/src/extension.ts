import * as vscode from 'vscode';

type Session = { id: string; name?: string; agent_profile?: string; model: string; permission_profile: string; context_mode: string; workspace_path: string };
type Task = { id: string; status: string; output?: string; error?: string; command?: string; prompt: string };

function headers(): Record<string, string> {
  const cfg = vscode.workspace.getConfiguration('piAgent');
  const token = cfg.get<string>('token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}
function baseUrl(): string { return (vscode.workspace.getConfiguration('piAgent').get<string>('baseUrl') || 'https://localhost').replace(/\/$/, ''); }
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const h = { ...(init.headers as any || {}), ...headers() } as any;
  if (init.body && !h['content-type']) h['content-type'] = 'application/json';
  const r = await fetch(`${baseUrl()}${path}`, { ...init, headers: h });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return await r.json() as T;
}

async function pickProfile(): Promise<{agent_profile: string; workspace_profile: string}> {
  const profiles = await api<any>('/v1/profiles');
  const agent_profile = await vscode.window.showQuickPick(Object.keys(profiles.agent_profiles || {}), { placeHolder: 'Profile' });
  if (!agent_profile) throw new Error('No agent profile selected');
  const workspace_profile = await vscode.window.showQuickPick(Object.keys(profiles.workspaces || {}), { placeHolder: 'Workspace profile' });
  if (!workspace_profile) throw new Error('No workspace profile selected');
  return { agent_profile, workspace_profile };
}

async function createSession(): Promise<Session> {
  const selected = await pickProfile();
  const name = await vscode.window.showInputBox({ prompt: 'Session name', value: 'vscode-session' });
  return await api<Session>('/v1/sessions', {
    method: 'POST',
    body: JSON.stringify({ name, agent_profile: selected.agent_profile, workspace: { type: 'profile', profile: selected.workspace_profile } })
  });
}

async function runTask(session: Session, wait = false): Promise<Task> {
  const editor = vscode.window.activeTextEditor;
  const selectedText = editor?.document.getText(editor.selection);
  const prompt = await vscode.window.showInputBox({ prompt: 'Prompt for Pi Agent', value: selectedText ? `Work with this selected text:\n\n${selectedText}` : 'Run pwd and list files' });
  if (!prompt) throw new Error('No prompt');
  const command = await vscode.window.showInputBox({ prompt: 'Optional command to execute remotely', value: selectedText ? '' : 'pwd && ls -la' });
  return await api<Task>(`/v1/sessions/${session.id}/tasks${wait ? '?wait=true' : ''}`, {
    method: 'POST', body: JSON.stringify({ prompt, command: command || undefined })
  });
}

async function showSession(session: Session, task?: Task) {
  const events = await api<any[]>(`/v1/sessions/${session.id}/events/snapshot`);
  const status = await api<{status:string}>(`/v1/sessions/${session.id}/git/status`).catch(() => ({status: ''}));
  const diff = await api<{diff:string}>(`/v1/sessions/${session.id}/diff`).catch(() => ({diff: ''}));
  const body = [
    `# Pi Agent Session`,
    ``,
    `- session: ${session.id}`,
    `- profile: ${session.agent_profile || 'custom'}`,
    `- model: ${session.model}`,
    `- permissions: ${session.permission_profile}`,
    `- context: ${session.context_mode}`,
    `- workspace: ${session.workspace_path}`,
    task ? `- task: ${task.id} (${task.status})` : '',
    ``,
    `## Events`,
    '```text',
    events.map(e => `[${e.type}] ${e.message}`).join('\n'),
    '```',
    `## Git status`,
    '```text', status.status, '```',
    `## Git diff`,
    '```diff', diff.diff, '```'
  ].join('\n');
  const doc = await vscode.workspace.openTextDocument({ content: body, language: 'markdown' });
  await vscode.window.showTextDocument(doc);
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.createSession', async () => {
    try { const s = await createSession(); await showSession(s); } catch (e:any) { vscode.window.showErrorMessage(e.message); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.runTask', async () => {
    try { const s = await createSession(); const t = await runTask(s, false); await showSession(s, t); vscode.window.showInformationMessage(`Pi Agent task ${t.status}: ${t.id}`); } catch (e:any) { vscode.window.showErrorMessage(e.message); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('piAgent.runTaskWait', async () => {
    try { const s = await createSession(); const t = await runTask(s, true); await showSession(s, t); } catch (e:any) { vscode.window.showErrorMessage(e.message); }
  }));
}
export function deactivate() {}
