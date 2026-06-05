from __future__ import annotations

import asyncio
import json
import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import CODING_SESSION_PERMISSION_PROFILE
from pi_agent_platform.core.models import Event, Session, SessionCreate, SessionStatus, Task, TaskCreate, TaskStatus, WorkspaceSpec
from pi_agent_platform.core.runtime import git_diff, git_status, run_shell_task
from pi_agent_platform.core.workspace_bootstrap import WorkspaceBootstrapError, ensure_workspace_materialized
from pi_agent_platform.core.coding_session_readiness import CodingSessionReadinessError, prepare_coding_session
from pi_agent_platform.core.agent_loop import run_agent_loop, execute_tool
from pi_agent_platform.core.agent_loop_runner import run_agent_loop_safely
from pi_agent_platform.core.session_commands import parse_session_slash_command, slash_help_text
from pi_agent_platform.core.model_switch import model_options_text, switch_session_model
from pi_agent_platform.core.subagents import spawn_pi_dev_subagent
from pi_agent_platform.core.subagent_chains import start_subagent_chain
from pi_agent_platform.core.shared_storage import controller_storage_path, shared_storage_binding
from pi_agent_platform.core.profiles import can_use_profile, profile_context_name
from pi_agent_platform.core.diagnostics_bundle import build_session_diagnostics, build_session_diagnostics_zip
from pi_agent_platform.core.platform_debug_bundle import build_platform_debug_zip
from pi_agent_platform.core.model_metrics import model_metrics
from pi_agent_platform.core.agent_session_tools import (
    is_known_agent_tool,
    merge_agent_session_tools,
    requires_endpoint_advertisement,
)
from pi_agent_platform.core.coding_model_upgrade import maybe_apply_model_upgrade_reply


create_session_for_internal_use: Callable[..., Session] | None = None


class TimelineEventCreate(BaseModel):
    type: str = 'agent_note'
    message: str = ''
    task_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class UiEventCreate(BaseModel):
    type: str = 'ui_event'
    message: str = ''
    session_id: str | None = None
    task_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class FileWriteRequest(BaseModel):
    path: str
    content: str


class SessionFileCreateRequest(BaseModel):
    path: str
    type: str = 'file'


class SessionFileRenameRequest(BaseModel):
    path: str
    new_name: str


class SourceDeleteRequest(BaseModel):
    path: str


def create_sessions_router(
    *,
    require_auth: Callable[..., Any],
    config: Any,
    store: Any,
    model_available: Callable[[str], tuple[bool, str | None]],
    session_resource_ref: Callable[[Session], tuple[str, str]],
    user_has_resource_access: Callable[..., bool],
    require_resource_access: Callable[..., None],
    is_coding_session_metadata: Callable[[dict[str, Any] | None], bool],
    preferred_endpoint_for_storage: Callable[[dict[str, Any]], str | None],
    default_coding_endpoint_id: Callable[[], str | None],
    default_coding_container_image: Callable[[WorkspaceSpec, dict[str, Any] | None], str],
    session_agent_enabled: Callable[[Session], bool],
    runner_target_from_task: Callable[[Task], dict[str, Any] | None],
    queue_task_on_runner: Callable[[Session, Task, dict[str, Any]], Task],
    agent_prompt_for_task: Callable[[str, str | None, dict[str, Any]], str],
    safe_workspace_path: Callable[[Session, str], Path],
    noisy_event_types: set[str],
    effective_context: Callable[[Any, str, str], dict[str, Any]],
    sync_context_bound_session: Callable[[Session, Any], Session],
) -> APIRouter:
    router = APIRouter()
    _model_available = model_available
    _session_resource_ref = session_resource_ref
    _user_has_resource_access = user_has_resource_access
    _require_resource_access = require_resource_access
    _is_coding_session_metadata = is_coding_session_metadata
    _preferred_endpoint_for_storage = preferred_endpoint_for_storage
    _default_coding_endpoint_id = default_coding_endpoint_id
    _default_coding_container_image = default_coding_container_image
    _session_agent_enabled = session_agent_enabled
    _runner_target_from_task = runner_target_from_task
    _queue_task_on_runner = queue_task_on_runner
    _agent_prompt_for_task = agent_prompt_for_task
    _safe_workspace_path = safe_workspace_path
    _noisy_event_types = noisy_event_types
    _effective_context = effective_context
    _sync_context_bound_session = sync_context_bound_session

    @router.get('/v1/sessions', response_model=list[Session])
    def list_sessions(_auth: Any = Depends(require_auth)) -> list[Session]:
        if _auth.is_admin:
            return store.list_sessions()
        visible: list[Session] = []
        for session in store.list_sessions():
            resource_type, resource_id = _session_resource_ref(session)
            if _user_has_resource_access(_auth, resource_type, resource_id, 'read'):
                visible.append(session)
        return visible


    @router.post('/v1/sessions', response_model=Session)
    def create_session(payload: SessionCreate, _auth: Any = Depends(require_auth)) -> Session:
        # Resolve workspace first so a workspace default_agent_profile can satisfy
        # session creation. Previously this happened after model resolution, so a
        # modal request with only a workspace profile could fail with
        # "Session requires model or agent_profile" and appear to do nothing.
        workspace = payload.workspace
        if workspace.type == 'profile' and not workspace.profile:
            if config.workspaces:
                workspace.profile = next(iter(config.workspaces.keys()))
            else:
                workspace.type = 'local'
        if workspace.type == 'profile':
            if not workspace.profile or workspace.profile not in config.workspaces:
                raise HTTPException(status_code=400, detail='Unknown workspace profile')
            _require_resource_access(_auth, 'workspace', f'profile:{workspace.profile}', 'write', reason='Start a session in this workspace profile')
            w = config.workspaces[workspace.profile]
            workspace.type = w.type
            workspace.path = w.path
            workspace.url = w.url
            workspace.branch = w.branch
            if w.shared_storage_id and (storage := store.get_shared_storage(w.shared_storage_id)):
                payload.metadata.update(shared_storage_binding(storage, w.storage_subpath, w.storage_mount_path))
                payload.metadata['workspace_storage_required'] = True
                workspace.path = controller_storage_path(storage, w.storage_subpath) or workspace.path
            if not payload.agent_profile and w.default_agent_profile and w.default_agent_profile in config.agent_profiles:
                default_profile = config.agent_profiles[w.default_agent_profile]
                if not can_use_profile(default_profile, _auth, store=store, profile_name=w.default_agent_profile):
                    raise HTTPException(
                        status_code=403,
                        detail=f'The workspace default profile "{w.default_agent_profile}" is restricted to groups you are not a member of. Select another profile or ask an administrator for access.',
                    )
                payload.agent_profile = w.default_agent_profile

        coding_session = _is_coding_session_metadata(payload.metadata)
        storage_bound_session = bool(payload.metadata.get('workspace_storage_required'))
        if coding_session:
            payload.metadata['coding_session'] = True
            payload.metadata['agent_enabled'] = True
            payload.metadata['execution_mode'] = 'container'
            payload.metadata['preferred_execution_mode'] = 'container'
            if not payload.metadata.get('preferred_endpoint'):
                payload.metadata['preferred_endpoint'] = _preferred_endpoint_for_storage(payload.metadata) or _default_coding_endpoint_id()
            if not payload.metadata.get('container_image'):
                payload.metadata['container_image'] = _default_coding_container_image(workspace, payload.metadata)
        if storage_bound_session:
            payload.metadata['agent_enabled'] = True
            payload.metadata['execution_mode'] = 'container'
            payload.metadata['preferred_execution_mode'] = 'container'
            storage_endpoint = _preferred_endpoint_for_storage(payload.metadata)
            if storage_endpoint:
                payload.metadata['preferred_endpoint'] = storage_endpoint
            elif not payload.metadata.get('preferred_endpoint'):
                payload.metadata['preferred_endpoint'] = _default_coding_endpoint_id()

        agent_profile = config.agent_profiles.get(payload.agent_profile) if payload.agent_profile else None
        if payload.agent_profile and not agent_profile:
            raise HTTPException(status_code=400, detail=f'Unknown agent profile: {payload.agent_profile}')
        if agent_profile and not can_use_profile(agent_profile, _auth, store=store, profile_name=payload.agent_profile):
            raise HTTPException(status_code=403, detail=f'You are not allowed to use agent profile "{payload.agent_profile}"')

        selected_model = payload.model
        if not selected_model:
            raise HTTPException(status_code=400, detail='Session requires a model or an agent context that resolves one')
        if selected_model not in config.models:
            raise HTTPException(status_code=400, detail=f'Unknown model: {selected_model}')
        model_available, model_reason = _model_available(selected_model)
        if not model_available:
            raise HTTPException(status_code=400, detail=f'Model is not available for sessions: {selected_model} ({model_reason})')

        selected_model_config = config.models[selected_model]
        model_runtime_target = str(selected_model_config.runs_on or '').strip()
        if model_runtime_target and 'preferred_endpoint' not in payload.metadata and store.get_runner(model_runtime_target):
            payload.metadata['preferred_endpoint'] = model_runtime_target
        if payload.metadata.get('preferred_endpoint'):
            endpoint_id = str(payload.metadata.get('preferred_endpoint'))
            if not store.get_runner(endpoint_id):
                raise HTTPException(status_code=400, detail=f'Unknown endpoint: {endpoint_id}')
            payload.metadata['endpoint_locked'] = True

        selected_tools = list(payload.tools or [])
        if payload.metadata.get('agent_enabled'):
            selected_tools = merge_agent_session_tools(
                config,
                selected_tools,
                coding_session=bool(coding_session or storage_bound_session),
            )
        unknown_tools = [t for t in selected_tools if not is_known_agent_tool(config, t)]
        if unknown_tools:
            raise HTTPException(status_code=400, detail=f'Unknown tools: {unknown_tools}')
        preferred_endpoint = payload.metadata.get('preferred_endpoint')
        if selected_tools and preferred_endpoint:
            endpoint = store.get_runner(preferred_endpoint)
            endpoint_tools = (endpoint.metadata.get('agent_tools', []) if endpoint else [])
            if endpoint_tools:
                missing_on_endpoint = [
                    t for t in selected_tools
                    if requires_endpoint_advertisement(config, t) and t not in endpoint_tools
                ]
                if missing_on_endpoint:
                    raise HTTPException(status_code=400, detail=f'Endpoint does not provide selected tools: {missing_on_endpoint}')

        selected_permission = CODING_SESSION_PERMISSION_PROFILE if coding_session else (payload.permission_profile or (agent_profile.permission_profile if agent_profile else 'ask-first'))
        if selected_permission not in config.permission_profiles:
            raise HTTPException(status_code=400, detail=f'Unknown permission profile: {selected_permission}')

        if coding_session or storage_bound_session:
            endpoint_id = str(payload.metadata.get('preferred_endpoint') or '').strip()
            if not endpoint_id:
                raise HTTPException(status_code=400, detail='Container-backed sessions require an online endpoint with container execution enabled')
            endpoint = store.get_runner(endpoint_id)
            if not endpoint:
                raise HTTPException(status_code=400, detail=f'Unknown endpoint: {endpoint_id}')
            if not endpoint.allow_container_execution:
                raise HTTPException(status_code=400, detail='Container-backed sessions require an endpoint that allows container execution')
            container_image = str(payload.metadata.get('container_image') or '').strip()
            if not container_image:
                raise HTTPException(status_code=400, detail='Container-backed sessions require a container image')
        if storage_bound_session and not (payload.metadata.get('shared_storage_controller_path') or workspace.path):
            raise HTTPException(status_code=400, detail='Shared-storage sessions require a controller-mounted workspace path')

        root = Path(config.server.default_workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        safe_name = (payload.name or payload.agent_profile or 'session').replace('/', '-').replace(' ', '-')
        workspace_path = workspace.path or str(root / f'workspace-{safe_name}')
        if workspace.type != 'profile':
            _require_resource_access(_auth, 'workspace', f'path:{workspace_path}', 'write', reason='Start a session in this workspace path')

        payload.metadata.setdefault('agent_enabled', True)
        payload.metadata.setdefault('execution_mode', 'container' if coding_session else 'pi.dev')

        context_name = payload.context_mode or (profile_context_name(agent_profile) if agent_profile else 'medium')
        session = Session(
            name=payload.name,
            agent_profile=payload.agent_profile,
            permission_profile=selected_permission,
            context_mode=context_name,
            workspace=workspace,
            workspace_path=workspace_path,
            model=selected_model,
            tools=selected_tools,
            metadata=payload.metadata,
        )
        store.add_session(session)
        try:
            if coding_session:
                readiness = prepare_coding_session(session, config, store=store)
                workspace_materialization = session.metadata.get('workspace_materialization') or readiness.get('materialization') or {}
            else:
                workspace_materialization = ensure_workspace_materialized(session)
                session.metadata['workspace_materialization'] = workspace_materialization
                store.add_session(session)
        except (WorkspaceBootstrapError, CodingSessionReadinessError) as exc:
            session.status = SessionStatus.failed
            session.metadata['coding_readiness'] = {'status': 'failed', 'stage': 'session_create', 'error': str(exc)}
            store.add_session(session)
            store.add_event(Event(session_id=session.id, type='session_readiness_failed', message=str(exc), data={'error': str(exc), 'workspace_path': session.workspace_path, 'endpoint': session.metadata.get('preferred_endpoint')}))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        store.add_event(Event(session_id=session.id, type='session_created', message='Session created', data={'workspace_path': session.workspace_path, 'workspace_materialization': workspace_materialization, 'coding_readiness': session.metadata.get('coding_readiness'), 'agent_profile': session.agent_profile, 'permission_profile': session.permission_profile, 'context_mode': session.context_mode, 'endpoint': session.metadata.get('preferred_endpoint'), 'endpoint_locked': session.metadata.get('endpoint_locked'), 'agent_enabled': session.metadata.get('agent_enabled', True), 'execution_mode': session.metadata.get('execution_mode', 'pi.dev'), 'effective_context': _effective_context(config, session.model, context_name)}))
        return session


    @router.get('/v1/sessions/{session_id}', response_model=Session)
    def get_session(session_id: str, _auth: Any = Depends(require_auth)) -> Session:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='Open this session', session_id=session.id)
        return session


    @router.put('/v1/sessions/{session_id}', response_model=Session)
    def update_session(session_id: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> Session:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        changed = False
        permission_profile = payload.get('permission_profile')
        if permission_profile is not None:
            if permission_profile not in config.permission_profiles:
                raise HTTPException(status_code=400, detail=f'Unknown permission profile: {permission_profile}')
            if session.permission_profile != permission_profile:
                session.permission_profile = permission_profile
                changed = True
                store.add_event(Event(session_id=session.id, type='session_permission_profile_changed', message='Session permission profile updated', data={'permission_profile': permission_profile}))
        if not changed:
            return session
        store.add_session(session)
        return session


    @router.get('/v1/sessions/{session_id}/tasks', response_model=list[Task])
    def list_tasks(session_id: str, _auth: Any = Depends(require_auth)) -> list[Task]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='List tasks for this session', session_id=session.id)
        return store.list_tasks(session_id)


    @router.post('/v1/sessions/{session_id}/tasks', response_model=Task)
    async def create_task(session_id: str, payload: TaskCreate, background_tasks: BackgroundTasks, wait: bool = Query(default=False), _auth: Any = Depends(require_auth)) -> Task:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        session = _sync_context_bound_session(session, _auth)
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'write', reason='Send prompts or commands to this session', session_id=session.id)

        metadata = dict(payload.metadata or {})
        upgrade_result = maybe_apply_model_upgrade_reply(config, store, session, payload.prompt)
        if upgrade_result is not None:
            task = Task(session_id=session_id, prompt=payload.prompt, metadata={**metadata, "coding_model_upgrade_reply": True})
            task.status = TaskStatus.completed if upgrade_result.get("ok") else TaskStatus.failed
            task.output = str(upgrade_result.get("message") or "")
            if not upgrade_result.get("ok"):
                task.error = task.output
            store.add_task(task)
            message_meta = {
                'role': 'user',
                'model': session.model,
                'session_model': session.model,
                'endpoint_id': session.metadata.get('preferred_endpoint'),
                'endpoint_name': None,
                'command': None,
                'execution_mode': session.metadata.get('execution_mode'),
                'stored': True,
            }
            store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data=message_meta))
            store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'agent_profile': session.agent_profile, 'coding_model_upgrade_reply': True}))
            return task
        literal_tool_call = _parse_literal_tool_call(payload.prompt)
        parsed_slash = parse_session_slash_command(payload.prompt)
        if literal_tool_call and not parsed_slash:
            metadata['direct_tool_call'] = literal_tool_call
        if parsed_slash:
            if parsed_slash.get('error'):
                raise HTTPException(status_code=400, detail=parsed_slash['error'])
            metadata.update(parsed_slash.get('metadata') or {})
            if parsed_slash['kind'] == 'help':
                task = Task(session_id=session_id, prompt=payload.prompt, metadata={**metadata, 'slash_command': 'help'})
                task.status = TaskStatus.completed
                task.output = slash_help_text()
                store.add_task(task)
                store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data={'role': 'user', 'model': metadata.get('model') or session.model, 'session_model': session.model, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'command': None, 'execution_mode': metadata.get('execution_mode'), 'stored': True}))
                store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'slash_command': 'help'}))
                return task
            if parsed_slash['kind'] == 'model':
                task = Task(session_id=session_id, prompt=payload.prompt, metadata={**metadata, 'slash_command': 'model'})
                task.status = TaskStatus.completed
                selector = str(parsed_slash.get('selector') or '').strip()
                store.add_task(task)
                store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data={'role': 'user', 'model': metadata.get('model') or session.model, 'session_model': session.model, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'command': None, 'execution_mode': metadata.get('execution_mode'), 'stored': True}))
                if not selector:
                    task.output = model_options_text(config, session)
                    store.add_task(task)
                    store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'agent_profile': session.agent_profile, 'slash_command': 'model', 'timeline': {'title': 'Model options', 'summary': 'Available models for this PAC session.', 'fields': {'Current': session.model}}}))
                    return task
                result = switch_session_model(config, session, selector, task=task, role=str(parsed_slash.get('role') or 'session'), fallback_selectors=parsed_slash.get('fallback') or [], source='slash_command')
                if result.ok:
                    task.output = f"Model switched to {result.selected_model}." + (f" Fallbacks: {', '.join(result.fallback_chain)}." if result.fallback_chain else '')
                else:
                    task.status = TaskStatus.failed
                    task.error = result.reason
                    task.output = result.reason
                store.add_task(task)
                store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'agent_profile': session.agent_profile, 'slash_command': 'model', 'model_switch': result.to_dict()}))
                return task
            payload = TaskCreate(
                prompt=parsed_slash.get('prompt') or payload.prompt,
                command=parsed_slash.get('command') or payload.command,
                require_approval=payload.require_approval,
                metadata=metadata,
            )
            if parsed_slash['kind'] == 'tool':
                metadata['execution_mode'] = 'host'
            elif parsed_slash['kind'] in {'subagent', 'subagent_chain'}:
                metadata['execution_mode'] = metadata.get('execution_mode') or 'pi_container'
        if _is_coding_session_metadata(session.metadata):
            metadata['coding_session'] = True
            metadata['execution_mode'] = 'container'
            metadata['preferred_execution_mode'] = 'container'
            metadata['runner_id'] = metadata.get('runner_id') or session.metadata.get('preferred_endpoint')
            metadata['container_image'] = metadata.get('container_image') or session.metadata.get('container_image')
            if not metadata.get('runner_id'):
                raise HTTPException(status_code=400, detail='Coding session has no endpoint configured for container execution')
            if not metadata.get('container_image'):
                raise HTTPException(status_code=400, detail='Coding session has no container image configured')
            if parsed_slash and parsed_slash.get('kind') == 'tool' and metadata.get('slash_command'):
                metadata['slash_command_execution_mode'] = 'container'

        locked_endpoint = session.metadata.get('preferred_endpoint') if session.metadata.get('endpoint_locked') else None
        if locked_endpoint:
            requested_endpoint = metadata.get('runner_id') or metadata.get('target_runner_id')
            if requested_endpoint and requested_endpoint != locked_endpoint:
                raise HTTPException(status_code=400, detail=f'Session is locked to endpoint: {locked_endpoint}')
            metadata['runner_id'] = locked_endpoint
            metadata['endpoint_locked'] = True
        task = Task(session_id=session_id, prompt=payload.prompt, command=payload.command, metadata=metadata)
        store.add_task(task)
        target = _runner_target_from_task(task)
        endpoint_id = metadata.get('runner_id') or metadata.get('target_runner_id')
        endpoint_name = None
        if endpoint_id:
            endpoint_obj = store.get_runner(str(endpoint_id))
            endpoint_name = endpoint_obj.name if endpoint_obj else str(endpoint_id)
        message_meta = {
            'role': 'user',
            'model': metadata.get('model') or session.model,
            'session_model': session.model,
            'endpoint_id': endpoint_id,
            'endpoint_name': endpoint_name,
            'command': payload.command,
            'execution_mode': metadata.get('execution_mode'),
            'stored': True,
        }
        store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data=message_meta))
        if metadata.get('direct_tool_call'):
            direct = metadata['direct_tool_call'] if isinstance(metadata.get('direct_tool_call'), dict) else {}
            tool = str(direct.get('tool') or '').strip()
            inp = direct.get('input') if isinstance(direct.get('input'), dict) else {}
            if not tool:
                raise HTTPException(status_code=400, detail='Tool call is missing tool name')
            task.status = TaskStatus.running
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='tool_call', message=tool, data={'tool': tool, 'input': inp, 'direct': True, 'endpoint_id': endpoint_id, 'endpoint_name': endpoint_name}))
            output, paused = await execute_tool(session, task, tool, inp, config)
            if paused:
                return store.get_task(task.id) or task
            task.status = TaskStatus.completed
            task.output = output[-4000:] if isinstance(output, str) else str(output)
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': endpoint_id, 'endpoint_name': endpoint_name, 'direct_tool_call': tool, 'timeline': {'title': f'Direct tool call: {tool}', 'summary': task.output[:400] if isinstance(task.output, str) else str(task.output)[:400], 'fields': {'Endpoint': endpoint_name or endpoint_id or '-', 'Tool': tool}}}))
            return task
        if metadata.get('context_action') == 'compact':
            task.status = TaskStatus.completed
            task.output = 'Context compaction requested for this session.'
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='context_compacted', message='Context compaction requested', data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'slash_command': metadata.get('slash_command')}))
            return task
        if metadata.get('subagent_chain'):
            started = await start_subagent_chain(
                session,
                task,
                str(metadata.get('subagent_instruction') or payload.prompt or ''),
                config,
                run_agent_loop,
                profiles=metadata.get('subagent_chain_profiles') or None,
                chain_name=str(metadata.get('subagent_chain') or 'code_change'),
            )
            task.status = TaskStatus.running
            task.output = started.get('message') or 'Specialist chain started.'
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'subagent_chain': metadata.get('subagent_chain'), 'timeline': {'title': 'Specialist chain launched', 'summary': task.output, 'fields': {'Chain': metadata.get('subagent_chain') or 'code_change', 'Endpoint': metadata.get('runner_id') or session.metadata.get('preferred_endpoint') or '-'}}}))
            return task
        if metadata.get('subagent'):
            spawned = await spawn_pi_dev_subagent(session, task, str(metadata.get('subagent_instruction') or payload.prompt or ''), config, run_agent_loop, profile_key=str(metadata.get('subagent_profile') or '') or None)
            child_session = spawned['session']
            child_task = spawned['task']
            task.status = TaskStatus.completed
            task.output = f"{spawned['message']} Open session {child_session.id} to follow it."
            task.metadata['subagent_session_id'] = child_session.id
            task.metadata['subagent_task_id'] = child_task.id
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'subagent_session_id': child_session.id, 'subagent_task_id': child_task.id, 'slash_command': metadata.get('slash_command'), 'timeline': {'title': 'Subagent launched', 'summary': task.output, 'fields': {'Session': child_session.id, 'Task': child_task.id, 'Mode': 'pi.dev', 'Endpoint': metadata.get('runner_id') or session.metadata.get('preferred_endpoint') or '-'}}}))
            return task
        agent_enabled = _session_agent_enabled(session) and metadata.get('direct_model') is not True
        store.add_event(Event(session_id=session_id, task_id=task.id, type='task_queued', message='Task queued', data={**message_meta, 'internal': True, 'agent_enabled': agent_enabled}))

        if agent_enabled:
            task.metadata['agent_loop'] = True
            task.metadata['agent_enabled'] = True
            task.metadata['requested_command'] = task.command
            task.metadata['routing'] = 'agent'
            if target and not task.metadata.get('execution_mode'):
                task.metadata['execution_mode'] = target['execution_mode']
            if target:
                task.metadata['runner_id'] = target['runner_id']
                task.metadata['endpoint_locked'] = True
            # Commands and slash-tool invocations are not executed directly in an agent-enabled session.
            # The agent receives the command as intent/context and chooses the next action.
            task.prompt = _agent_prompt_for_task(task.prompt, task.command, task.metadata)
            task.command = None
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_routing', message='Routed to session agent', data={'agent_profile': session.agent_profile, 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'requested_command': task.metadata.get('requested_command')}))
            if wait:
                await run_agent_loop_safely(session, task, config)
            else:
                background_tasks.add_task(run_agent_loop_safely, session, task, config)
            return store.get_task(task.id) or task

        if target:
            if task.command:
                decision, reason = __import__('pi_agent_platform.core.runtime', fromlist=['command_policy']).command_policy(task.command, session, config)
                if decision == 'deny':
                    task.status = TaskStatus.failed
                    task.error = reason
                    store.add_task(task)
                    store.add_event(Event(session_id=session.id, task_id=task.id, type='task_failed', message=reason or 'Command denied'))
                    return task
                if task.status != TaskStatus.approval_required and (decision == 'ask' or payload.require_approval is True):
                    task.status = TaskStatus.approval_required
                    store.add_task(task)
                    store.add_event(Event(session_id=session.id, task_id=task.id, type='approval_required', message=f'Runner command requires approval: {task.command}', data={'command': task.command, 'runner_id': target['runner_id'], 'reason': reason}))
                    return task
            return _queue_task_on_runner(session, task, target)
        if task.command:
            if str(task.command).startswith('tool:') and metadata.get('tool_name'):
                # Local-control-plane endpoints do not use the polling endpoint queue.
                # Convert the named tool invocation into a safe local shell command.
                tool = str(metadata.get('tool_name') or '').strip()
                if tool == 'bad':
                    tool = 'bat'
                args = metadata.get('args') if isinstance(metadata.get('args'), list) else []
                task.command = shlex.join([tool, *[str(a) for a in args]])
                store.add_task(task)
            if wait:
                await run_shell_task(session, task, config)
            else:
                background_tasks.add_task(run_shell_task, session, task, config)
        else:
            task.metadata['agent_loop'] = True
            if wait:
                await run_agent_loop_safely(session, task, config)
            else:
                background_tasks.add_task(run_agent_loop_safely, session, task, config)
        return store.get_task(task.id) or task




    @router.get('/v1/tasks/pending-approvals', response_model=list[Task])
    def pending_approvals(_auth: None = Depends(require_auth)) -> list[Task]:
        return [task for task in store.list_tasks() if task.status == TaskStatus.approval_required]


    @router.get('/v1/tasks/{task_id}', response_model=Task)
    def get_task(task_id: str, _auth: None = Depends(require_auth)) -> Task:
        task = store.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        return task


    @router.post('/v1/tasks/{task_id}/approve', response_model=Task)
    async def approve_task(task_id: str, background_tasks: BackgroundTasks, wait: bool = Query(default=False), _auth: None = Depends(require_auth)) -> Task:
        task = store.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        if task.status != TaskStatus.approval_required:
            return task
        session = store.get_session(task.session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        task.status = TaskStatus.queued
        task.error = None
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='task_approved', message='Approved'))
        target = _runner_target_from_task(task)
        if target:
            return _queue_task_on_runner(session, task, target)
        if task.metadata.get('agent_loop') and not task.command:
            if wait:
                await run_agent_loop_safely(session, task, config)
            else:
                background_tasks.add_task(run_agent_loop_safely, session, task, config)
        else:
            if wait:
                await run_shell_task(session, task, config)
            else:
                background_tasks.add_task(run_shell_task, session, task, config)
        return store.get_task(task.id) or task


    @router.post('/v1/tasks/{task_id}/reject', response_model=Task)
    def reject_task(task_id: str, reason: str = 'Rejected by user', _auth: None = Depends(require_auth)) -> Task:
        task = store.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        task.status = TaskStatus.failed
        task.error = reason
        store.add_task(task)
        store.add_event(Event(session_id=task.session_id, task_id=task.id, type='task_rejected', message=reason))
        return task


    @router.post('/v1/tasks/{task_id}/stop', response_model=Task)
    def stop_task(task_id: str, _auth: None = Depends(require_auth)) -> Task:
        task = store.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        session = store.get_session(task.session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        if task.status in {TaskStatus.completed, TaskStatus.failed}:
            return task
        task.metadata = dict(task.metadata or {})
        task.metadata['stop_requested'] = True
        task.metadata['stop_requested_at'] = datetime.now(timezone.utc).isoformat()
        if task.status in {TaskStatus.queued, TaskStatus.approval_required}:
            task.status = TaskStatus.completed
            task.output = 'Agent stopped by user.'
            task.error = None
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_stop', message='Agent stopped by user', data={'stop_reason': 'user_stop'}))
            store.add_event(Event(session_id=session.id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'agent_profile': session.agent_profile, 'permission_profile': session.permission_profile, 'stop_reason': 'user_stop'}))
            session.status = SessionStatus.created
            store.add_session(session)
            return task
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_stop', message='Stop requested; the agent will stop after the current step.', data={'stop_reason': 'user_stop'}))
        return task




    @router.get('/v1/events/recent')
    def recent_events(limit: int = Query(default=80, ge=1, le=500), include_noisy: bool = False, _auth: None = Depends(require_auth)) -> list[Event]:
        return store.list_recent_events(limit=limit, exclude_types=None if include_noisy else _noisy_event_types)


    @router.post('/v1/events/ui', response_model=Event)
    def add_ui_event(payload: UiEventCreate, _auth: None = Depends(require_auth)) -> Event:
        event_type = re.sub(r'[^a-zA-Z0-9_:-]+', '_', payload.type or 'ui_event')[:80]
        session_id = (payload.session_id or 'system').strip() or 'system'
        event = Event(
            session_id=session_id,
            task_id=payload.task_id,
            type=event_type,
            message=payload.message or event_type,
            data={**(payload.data or {}), 'source': (payload.data or {}).get('source') or 'ui'},
        )
        store.add_event(event)
        return event


    @router.post('/v1/sessions/{session_id}/events', response_model=Event)
    def add_session_event(session_id: str, payload: TimelineEventCreate, _auth: None = Depends(require_auth)) -> Event:
        if not store.get_session(session_id):
            raise HTTPException(status_code=404, detail='Session not found')
        event_type = re.sub(r'[^a-zA-Z0-9_:-]+', '_', payload.type or 'agent_note')[:80]
        event = Event(session_id=session_id, task_id=payload.task_id, type=event_type, message=payload.message or event_type, data=payload.data or {})
        store.add_event(event)
        return event


    def _load_loose_json_object(text: str) -> dict[str, Any] | None:
        raw = str(text or '').strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
        normalized = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)', r'\1"\2"\3', raw)
        normalized = normalized.replace("'", '"')
        normalized = re.sub(r':\s*True\b', ': true', normalized)
        normalized = re.sub(r':\s*False\b', ': false', normalized)
        normalized = re.sub(r':\s*None\b', ': null', normalized)
        def _quote_bare_value(match: re.Match[str]) -> str:
            prefix = match.group(1)
            raw_value = str(match.group(2) or '')
            stripped = raw_value.strip()
            if not stripped:
                return prefix + raw_value
            if stripped[0] in '"{[':
                return prefix + raw_value
            if stripped in {'true', 'false', 'null'}:
                return prefix + stripped
            if re.fullmatch(r'-?\d+(?:\.\d+)?', stripped):
                return prefix + stripped
            return prefix + json.dumps(stripped)
        normalized = re.sub(r'(:\s*)([^"\{\[\],][^,\}\]]*)', _quote_bare_value, normalized)
        try:
            parsed = json.loads(normalized)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None


    def _parse_literal_tool_call(prompt: str) -> dict[str, Any] | None:
        raw = str(prompt or '').strip()
        if not raw:
            return None
        wrapped = re.fullmatch(r'<\|tool_call\>\s*call:([A-Za-z0-9_:-]+)\s*(\{.*\})\s*<tool_call\|>', raw, re.DOTALL)
        if wrapped:
            tool = wrapped.group(1).strip()
            if tool.startswith('tool_call:'):
                tool = tool.split('tool_call:', 1)[1].strip()
            payload = _load_loose_json_object(wrapped.group(2)) or {}
            if isinstance(payload.get('input'), dict):
                payload = payload.get('input') or {}
            return {'tool': tool, 'input': payload}
        parsed = _load_loose_json_object(raw)
        if not parsed:
            return None
        if str(parsed.get('type') or '').strip().lower() != 'tool_call':
            return None
        tool = str(parsed.get('tool') or '').strip()
        if tool.startswith('tool_call:'):
            tool = tool.split('tool_call:', 1)[1].strip()
        if not tool:
            return None
        payload = parsed.get('input')
        if not isinstance(payload, dict):
            payload = {}
        return {'tool': tool, 'input': payload}


    @router.get('/v1/sessions/{session_id}/model-usage')
    def get_session_model_usage(
        session_id: str,
        since_hours: int = Query(default=168, ge=1, le=24 * 90),
        limit: int = Query(default=1000, ge=1, le=10000),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='Read session model usage metrics')
        summary = model_metrics.summarize_usage(session_id=session_id, since_hours=since_hours, limit=limit)
        return summary


    @router.get('/v1/sessions/{session_id}/diagnostics')
    def get_session_diagnostics(
        session_id: str,
        include_events: int = Query(default=1000, ge=1, le=10000),
        full: bool = Query(default=False),
        include_workspace_state: bool = Query(default=True),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='Download session diagnostics')
        return build_session_diagnostics(
            store=store,
            config=config,
            session=session,
            include_events=include_events,
            include_full=full,
            include_workspace_state=include_workspace_state,
        )


    @router.get('/v1/sessions/{session_id}/diagnostics.zip')
    def download_session_diagnostics(
        session_id: str,
        include_events: int = Query(default=1000, ge=1, le=10000),
        full: bool = Query(default=False),
        include_workspace_state: bool = Query(default=True),
        _auth: Any = Depends(require_auth),
    ) -> Response:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='Download session diagnostics')
        bundle = build_session_diagnostics_zip(
            store=store,
            config=config,
            session=session,
            include_events=include_events,
            include_full=full,
            include_workspace_state=include_workspace_state,
        )
        filename = f'pac-diagnostics-{session.id}.zip'
        return Response(
            content=bundle,
            media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )


    @router.get('/v1/sessions/{session_id}/debug-bundle.zip')
    def download_session_debug_bundle(
        session_id: str,
        include_events: int = Query(default=3000, ge=1, le=10000),
        full: bool = Query(default=True),
        active_task_id: str | None = Query(default=None),
        _auth: Any = Depends(require_auth),
    ) -> Response:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        resource_type, resource_id = _session_resource_ref(session)
        _require_resource_access(_auth, resource_type, resource_id, 'read', reason='Download session debug bundle')
        bundle = build_platform_debug_zip(
            store=store,
            config=config,
            session=session,
            include_events=include_events,
            include_full=full,
            active_task_id=active_task_id,
        )
        filename = f'pac-debug-{session.id}.zip'
        return Response(
            content=bundle,
            media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )


    @router.get('/v1/sessions/{session_id}/events')
    async def stream_events(session_id: str, _auth: None = Depends(require_auth)):
        if not store.get_session(session_id):
            raise HTTPException(status_code=404, detail='Session not found')

        async def event_stream():
            last_id = None
            while True:
                events = store.get_events(session_id, after_id=last_id)
                for event in events:
                    last_id = event.id
                    yield f"event: {event.type}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type='text/event-stream')


    @router.get('/v1/sessions/{session_id}/events/snapshot')
    def event_snapshot(session_id: str, after_id: str | None = None, limit: int = 500, latest: bool = False, _auth: None = Depends(require_auth)) -> list[Event]:
        if not store.get_session(session_id):
            raise HTTPException(status_code=404, detail='Session not found')
        return store.get_events(session_id, after_id=after_id, limit=limit, latest=latest if not after_id else False)


    @router.get('/v1/sessions/{session_id}/files')
    def list_files(session_id: str, path: str = '.', _auth: None = Depends(require_auth)) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        target = safe_workspace_path(session, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail='Path not found')
        if target.is_file():
            return {'path': path, 'type': 'file', 'size': target.stat().st_size}
        items = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]:
            rel = '.' if item == target else str(item.relative_to(Path(session.workspace_path))).replace('\\', '/')
            items.append({'name': item.name, 'path': rel, 'type': 'dir' if item.is_dir() else 'file', 'size': item.stat().st_size if item.is_file() else None})
        normalized = '' if path in ('.', '', '/') else str(path).replace('\\', '/').strip('/')
        return {'path': normalized, 'type': 'dir', 'items': items}


    @router.get('/v1/sessions/{session_id}/files/content')
    def read_file(session_id: str, path: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        target = safe_workspace_path(session, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail='File not found')
        return {'path': path, 'content': target.read_text(errors='replace')}


    @router.put('/v1/sessions/{session_id}/files/content')
    def write_file(session_id: str, payload: FileWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        target = safe_workspace_path(session, payload.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload.content)
        store.add_event(Event(session_id=session.id, type='file_written', message=payload.path))
        return {'status': 'written', 'path': payload.path}


    @router.post('/v1/sessions/{session_id}/files/entry')
    def create_session_file_entry(session_id: str, payload: SessionFileCreateRequest, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        path = str(payload.path or '').replace('\\', '/').strip('/')
        if not path:
            raise HTTPException(status_code=400, detail='Path is required')
        entry_type = str(payload.type or 'file').strip().lower()
        if entry_type not in {'file', 'dir'}:
            raise HTTPException(status_code=400, detail='Type must be file or dir')
        target = safe_workspace_path(session, path)
        if target.exists():
            raise HTTPException(status_code=409, detail='Path already exists')
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry_type == 'dir':
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.write_text('')
        store.add_event(Event(session_id=session.id, type='file_created', message=path, data={'path': path, 'type': entry_type}))
        return {'status': 'created', 'path': path, 'type': entry_type}


    @router.post('/v1/sessions/{session_id}/files/entry/rename')
    def rename_session_file_entry(session_id: str, payload: SessionFileRenameRequest, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        path = str(payload.path or '').replace('\\', '/').strip('/')
        new_name = str(payload.new_name or '').strip()
        if not path or not new_name:
            raise HTTPException(status_code=400, detail='Path and new_name are required')
        source = safe_workspace_path(session, path)
        if not source.exists():
            raise HTTPException(status_code=404, detail='Path not found')
        if '/' in new_name or '\\' in new_name:
            raise HTTPException(status_code=400, detail='new_name must not contain path separators')
        target = source.with_name(new_name)
        root = Path(session.workspace_path).resolve()
        target_resolved = target.resolve()
        if root not in target_resolved.parents and target_resolved != root:
            raise HTTPException(status_code=400, detail='Target would escape workspace root')
        if target.exists():
            raise HTTPException(status_code=409, detail='Target already exists')
        source.rename(target)
        new_path = str(target_resolved.relative_to(root)).replace('\\', '/')
        store.add_event(Event(session_id=session.id, type='file_renamed', message=f'{path} -> {new_path}', data={'path': path, 'new_path': new_path}))
        return {'status': 'renamed', 'path': path, 'new_path': new_path}


    @router.delete('/v1/sessions/{session_id}/files/entry')
    def delete_session_file_entry(session_id: str, path: str | None = Query(default=None), payload: SourceDeleteRequest | None = Body(default=None), _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        rel_path = str((payload.path if payload else None) or path or '').replace('\\', '/').strip('/')
        if not rel_path:
            raise HTTPException(status_code=400, detail='Path is required')
        target = safe_workspace_path(session, rel_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail='Path not found')
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        store.add_event(Event(session_id=session.id, type='file_deleted', message=rel_path, data={'path': rel_path}))
        return {'status': 'deleted', 'path': rel_path}


    @router.get('/v1/sessions/{session_id}/diff')
    def get_diff(session_id: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        return {'diff': git_diff(session)}


    @router.get('/v1/sessions/{session_id}/git/status')
    def get_git_status(session_id: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        return {'status': git_status(session)}


    @router.delete('/v1/sessions/{session_id}')
    def delete_session(session_id: str, remove_workspace: bool = False, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
        workspace_path = session.workspace_path
        store.delete_session(session_id)
        if remove_workspace and workspace_path:
            shutil.rmtree(workspace_path, ignore_errors=True)
        store.add_event(Event(session_id=session_id, type='session_deleted', message='Session deleted', data={'session_id': session_id, 'workspace_removed': bool(remove_workspace and workspace_path)}))
        return {'ok': True, 'deleted': session_id}


    globals()['create_session_for_internal_use'] = create_session
    return router
