from __future__ import annotations

import asyncio
import fnmatch
import os
import subprocess

from .config import AppConfig
from .models import Event, Session, SessionStatus, Task, TaskStatus
from .workspace_bootstrap import ensure_workspace_materialized
from .store import store


def ensure_workspace(session: Session) -> None:
    ensure_workspace_materialized(session)


def _matches(patterns: list[str], command: str) -> bool:
    return any(pattern in command or fnmatch.fnmatch(command, pattern) for pattern in patterns)


def _looks_mutating_command(command: str) -> bool:
    text = (command or '').strip().lower()
    if not text:
        return False
    write_markers = [
        ' rm ', ' rmdir ', ' del ', ' move ', ' mv ', ' cp ', ' copy ', ' rename ', ' ren ',
        ' chmod ', ' chown ', ' mkdir ', ' touch ', ' tee ', ' git apply ', ' git commit ',
        ' git add ', ' git rm ', ' git checkout ', ' git switch ', ' git clean ', ' patch ',
        ' sed -i', '>>', ' >', 'truncate ', 'echo ', 'cat >', 'python -c', 'node -e',
    ]
    padded = f' {text} '
    return any(marker in padded for marker in write_markers)


def _looks_observational_command(command: str) -> bool:
    text = (command or '').strip().lower()
    if not text:
        return False
    normalized = ' '.join(text.split())
    safe_prefixes = (
        'rg ', 'ripgrep ', 'fd ', 'find ', 'ls', 'dir', 'pwd', 'where ', 'which ',
        'git status', 'git diff', 'git log', 'git show', 'git branch', 'git rev-parse',
        'git ls-files', 'cat ', 'type ', 'bat ', 'more ', 'head ', 'tail ', 'wc ',
        'jq ', 'python --version', 'python -v', 'python3 --version', 'node --version',
        'npm --version', 'pip --version', 'go version',
    )
    if normalized in {'ls', 'dir', 'pwd', 'git status', 'git diff'}:
        return True
    return any(normalized.startswith(prefix) for prefix in safe_prefixes)


def command_policy(command: str, session: Session, config: AppConfig) -> tuple[str, str | None]:
    if 'shell' not in session.tools:
        return 'deny', 'Session does not have the shell tool enabled'
    shell_cfg = config.tools.get('shell')
    if shell_cfg and not shell_cfg.enabled:
        return 'deny', 'Shell tool is disabled by config'

    profile = config.permission_profiles.get(session.permission_profile)
    if not profile:
        return 'deny', f'Unknown permission profile: {session.permission_profile}'

    # Data access gating comes first. Shell is broad enough that blocked read access
    # should block shell entirely, and write gating should apply before command/tool
    # specific approval patterns.
    if profile.file_read == 'deny':
        return 'deny', 'Shell execution is denied because this permission profile blocks reading workspace data'
    if _looks_mutating_command(command):
        if profile.file_write == 'deny':
            return 'deny', 'Command appears to modify workspace data, but this permission profile blocks changes'
        if profile.file_write == 'ask':
            return 'ask', 'Command appears to modify workspace data and requires change approval first'

    if _matches(profile.command_deny_patterns, command):
        return 'deny', 'Command matched deny policy'
    if profile.shell == 'deny':
        return 'deny', 'Shell execution is denied by permission profile'
    if profile.shell == 'ask' and _looks_observational_command(command):
        return 'allow', None
    if _matches(profile.command_ask_patterns, command):
        return 'ask', 'Command matched approval policy'
    if shell_cfg and _matches(shell_cfg.approval_required_patterns, command):
        return 'ask', 'Command matched shell tool approval policy'
    if profile.shell == 'ask':
        return 'ask', 'Shell execution requires approval by permission profile'
    return 'allow', None


async def run_shell_task(session: Session, task: Task, config: AppConfig) -> Task:
    ensure_workspace(session)
    command = task.command
    if not command:
        task.status = TaskStatus.completed
        task.output = 'No command supplied. Stage 4 still treats the LLM loop as an integration point; command execution, sessions, profiles, IDE and MCP wrappers are included.'
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'agent_profile': session.agent_profile, 'command': task.command}))
        return task

    decision, reason = command_policy(command, session, config)
    if decision == 'deny':
        task.status = TaskStatus.failed
        task.error = reason
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='task_failed', message=reason or 'Command rejected'))
        return task

    if task.status != TaskStatus.approval_required and (decision == 'ask' or task.metadata.get('require_approval') is True):
        task.status = TaskStatus.approval_required
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='approval_required', message=f'Command requires approval: {command}', data={'command': command, 'reason': reason}))
        return task

    task.status = TaskStatus.running
    session.status = SessionStatus.running
    store.add_session(session)
    store.add_task(task)
    store.add_event(Event(session_id=session.id, task_id=task.id, type='task_started', message=command, data={'permission_profile': session.permission_profile, 'agent_profile': session.agent_profile, 'model': session.model, 'endpoint_id': task.metadata.get('runner_id')}))

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=session.workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'PI_AGENT_SESSION_ID': session.id, 'PI_AGENT_TASK_ID': task.id, 'PI_AGENT_PROFILE': session.agent_profile or ''},
    )

    chunks: list[str] = []

    async def read_stream(stream: asyncio.StreamReader | None, event_type: str) -> None:
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors='replace')
            chunks.append(text)
            store.add_event(Event(session_id=session.id, task_id=task.id, type=event_type, message=text[-4000:]))

    try:
        await asyncio.wait_for(
            asyncio.gather(read_stream(proc.stdout, 'stdout'), read_stream(proc.stderr, 'stderr'), proc.wait()),
            timeout=config.runtime.command_timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        task.status = TaskStatus.failed
        task.error = 'Command timed out'
        session.status = SessionStatus.failed
        store.add_task(task)
        store.add_session(session)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='task_failed', message=task.error))
        return task

    output = ''.join(chunks)
    task.exit_code = proc.returncode
    task.output = output[-20000:]
    task.status = TaskStatus.completed if proc.returncode == 0 else TaskStatus.failed
    session.status = SessionStatus.created
    store.add_task(task)
    store.add_session(session)
    store.add_event(Event(session_id=session.id, task_id=task.id, type='task_completed' if proc.returncode == 0 else 'task_failed', message=f'Command exited with {proc.returncode}', data={'exit_code': proc.returncode, 'role': 'assistant', 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'command': task.command}))
    return task


def git_diff(session: Session) -> str:
    ensure_workspace(session)
    try:
        result = subprocess.run(['git', 'diff', '--'], cwd=session.workspace_path, check=False, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr
    except Exception as exc:
        return f'Unable to collect git diff: {exc}'


def git_status(session: Session) -> str:
    ensure_workspace(session)
    try:
        result = subprocess.run(['git', 'status', '--short', '--branch'], cwd=session.workspace_path, check=False, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr
    except Exception as exc:
        return f'Unable to collect git status: {exc}'
