from __future__ import annotations

import asyncio
import json
import re
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import WorkspaceProfile
from pi_agent_platform.core.models import Event, WorkspaceAgent, WorkspaceAgentCommand, WorkspaceAgentCommandEvent, WorkspaceAgentCommandStatus, WorkspaceAgentStatus, now_utc

DEFAULT_ADMIN_CONTEXT_NAME = 'PAC/core'
WORKSPACE_OFFLINE_AFTER = timedelta(seconds=90)


class UserWorkspacePayload(BaseModel):
    name: str
    description: str | None = None
    template_id: str | None = None
    workspace_type: str | None = None
    workspace_profile: str | None = None
    path: str | None = None
    url: str | None = None
    branch: str | None = None
    shared_storage_id: str | None = None
    storage_subpath: str | None = None
    storage_mount_path: str | None = None
    endpoint_id: str | None = None
    endpoint_selector: str | None = None
    container_image: str | None = None
    agent_profile: str | None = None
    permission_profile: str | None = None
    model: str | None = None
    context_mode: str | None = None
    open_files: list[str] = Field(default_factory=list)
    pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentContextPayload(BaseModel):
    name: str
    description: str | None = None
    kind: str | None = None
    workspace_id: str | None = None
    workspace_template_id: str | None = None
    controller_workdir: str | None = None
    shared_storage_id: str | None = None
    storage_subpath: str | None = None
    storage_mount_path: str | None = None
    endpoint_id: str | None = None
    endpoint_selector: str | None = None
    container_image: str | None = None
    requires_container: bool = True
    agent_profile: str | None = None
    permission_profile: str | None = None
    context_mode: str | None = None
    executor_model: str | None = None
    planner_model: str | None = None
    reviewer_model: str | None = None
    retrieval_model: str | None = None
    tools: list[str] = Field(default_factory=list)
    use_groups: list[str] = Field(default_factory=list)
    editor_groups: list[str] = Field(default_factory=list)
    pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SharedStoragePayload(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    driver: str | None = None
    network_path: str | None = None
    controller_path: str | None = None
    mount_path: str | None = None
    endpoint_selector: str | None = None
    endpoint_ids: list[str] = Field(default_factory=list)
    writable: bool = True
    default_subpath: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)



class WorkspaceAgentRegisterPayload(BaseModel):
    workspace_id: str | None = None
    name: str | None = None
    root: str | None = None
    lifetime: str = 'persistent'
    labels: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    inventory: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class WorkspaceAgentHeartbeatPayload(BaseModel):
    workspace_id: str
    endpoint_id: str | None = None
    status: str = 'online'
    version: str | None = None
    root: str | None = None
    labels: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    inventory: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCommandPayload(BaseModel):
    command: str
    wait: bool = False
    workspace_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCommandCompletePayload(BaseModel):
    status: str = 'completed'
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCommandEventPayload(BaseModel):
    stream: str = 'stdout'
    data: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCommandCancelPayload(BaseModel):
    reason: str | None = None
    force: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_workspaces_router(
    *,
    require_auth: Callable[..., Any],
    require_admin: Callable[..., Any],
    config: Any,
    store: Any,
    save_config: Callable[..., Any],
    workspace_template_catalog: Callable[[], dict[str, dict[str, Any]]],
    public_workspace_template: Callable[[dict[str, Any]], dict[str, Any]],
    public_user_workspace: Callable[[Any], dict[str, Any]],
    workspace_owner: Callable[[Any], tuple[str, str]],
    workspace_payload_to_item: Callable[[Any, UserWorkspacePayload, Any], Any],
    ensure_user_workspace_session: Callable[[Any, Any], Any],
    context_visibility_owner_ids: Callable[[Any], tuple[str, str]],
    public_agent_context: Callable[[Any], dict[str, Any]],
    can_use_agent_context: Callable[[Any, Any], bool],
    can_edit_agent_context: Callable[[Any, Any], bool],
    can_resource_access: Callable[..., bool],
    is_pac_system_context: Callable[[Any], bool],
    app_dir: Callable[[], Any],
    agent_context_payload_to_item: Callable[[Any, AgentContextPayload, Any], Any],
    ensure_agent_context_session: Callable[[Any, Any], Any],
    storage_catalog: Callable[[], list[Any]],
    shared_storage_payload_to_item: Callable[[Any, SharedStoragePayload], Any],
    public_shared_storage: Callable[[Any], dict[str, Any]],
) -> APIRouter:
    router = APIRouter()
    _workspace_template_catalog = workspace_template_catalog
    _public_workspace_template = public_workspace_template
    _public_user_workspace = public_user_workspace
    _workspace_owner = workspace_owner
    _workspace_payload_to_item = workspace_payload_to_item
    _ensure_user_workspace_session = ensure_user_workspace_session
    _context_visibility_owner_ids = context_visibility_owner_ids
    _public_agent_context = public_agent_context
    _can_use_agent_context = can_use_agent_context
    _can_edit_agent_context = can_edit_agent_context
    _can_resource_access = can_resource_access
    _is_pac_system_context = is_pac_system_context
    _app_dir = app_dir
    _agent_context_payload_to_item = agent_context_payload_to_item
    _ensure_agent_context_session = ensure_agent_context_session
    _storage_catalog = storage_catalog
    _shared_storage_payload_to_item = shared_storage_payload_to_item
    _public_shared_storage = public_shared_storage

    @router.get('/v1/workspace-templates')
    def list_workspace_templates(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        templates = [_public_workspace_template(item) for item in _workspace_template_catalog().values()]
        templates.sort(key=lambda item: (0 if item.get('is_default') else 1, str(item.get('name') or '').lower()))
        return {'templates': templates}


    @router.get('/v1/my-workspaces')
    def list_my_workspaces(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        owner_id, _ = _workspace_owner(_auth)
        items = [_public_user_workspace(item) for item in store.list_user_workspaces(owner_id=owner_id)]
        return {'items': items}


    @router.post('/v1/my-workspaces')
    def create_my_workspace(payload: UserWorkspacePayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        owner_id, _ = _workspace_owner(_auth)
        existing = store.find_user_workspace_by_name(owner_id, payload.name.strip())
        if existing:
            raise HTTPException(status_code=409, detail='A personal workspace with that name already exists')
        item = _workspace_payload_to_item(None, payload, _auth)
        store.add_user_workspace(item)
        store.add_event(Event(session_id='system', type='user_workspace_created', message=f'Workspace created: {item.name}', data={'workspace_id': item.id, 'owner': item.owner_username}))
        return {'ok': True, 'workspace': _public_user_workspace(item)}


    @router.get('/v1/my-workspaces/{workspace_id}')
    def get_my_workspace(workspace_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_user_workspace(workspace_id)
        if not item:
            raise HTTPException(status_code=404, detail='Workspace not found')
        owner_id, _ = _workspace_owner(_auth)
        if not _can_resource_access(_auth, 'workspace', f'user:{item.id}', 'read', owner_id=item.owner_id):
            raise HTTPException(status_code=403, detail='Workspace not available')
        return {'workspace': _public_user_workspace(item)}


    @router.put('/v1/my-workspaces/{workspace_id}')
    def update_my_workspace(workspace_id: str, payload: UserWorkspacePayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_user_workspace(workspace_id)
        if not item:
            raise HTTPException(status_code=404, detail='Workspace not found')
        owner_id, _ = _workspace_owner(_auth)
        if not _can_resource_access(_auth, 'workspace', f'user:{item.id}', 'write', owner_id=item.owner_id):
            raise HTTPException(status_code=403, detail='Workspace not available')
        conflict = store.find_user_workspace_by_name(item.owner_id, payload.name.strip())
        if conflict and conflict.id != item.id:
            raise HTTPException(status_code=409, detail='A personal workspace with that name already exists')
        updated = _workspace_payload_to_item(item, payload, _auth)
        store.add_user_workspace(updated)
        store.add_event(Event(session_id='system', type='user_workspace_updated', message=f'Workspace updated: {updated.name}', data={'workspace_id': updated.id, 'owner': updated.owner_username}))
        return {'ok': True, 'workspace': _public_user_workspace(updated)}


    @router.delete('/v1/my-workspaces/{workspace_id}')
    def delete_my_workspace(workspace_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_user_workspace(workspace_id)
        if not item:
            raise HTTPException(status_code=404, detail='Workspace not found')
        owner_id, _ = _workspace_owner(_auth)
        if not _can_resource_access(_auth, 'workspace', f'user:{item.id}', 'manage', owner_id=item.owner_id):
            raise HTTPException(status_code=403, detail='Workspace not available')
        store.delete_user_workspace(workspace_id)
        store.add_event(Event(session_id='system', type='user_workspace_deleted', message=f'Workspace deleted: {item.name}', data={'workspace_id': item.id, 'owner': item.owner_username}))
        return {'ok': True, 'deleted': workspace_id}


    @router.post('/v1/my-workspaces/{workspace_id}/session')
    def ensure_my_workspace_session(workspace_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_user_workspace(workspace_id)
        if not item:
            raise HTTPException(status_code=404, detail='Workspace not found')
        owner_id, _ = _workspace_owner(_auth)
        if not _can_resource_access(_auth, 'workspace', f'user:{item.id}', 'use', owner_id=item.owner_id):
            raise HTTPException(status_code=403, detail='Workspace not available')
        session = _ensure_user_workspace_session(item, _auth)
        return {'ok': True, 'workspace': _public_user_workspace(item), 'session': session.model_dump(mode='json')}


    @router.get('/v1/agent-contexts')
    def list_agent_contexts(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        owner_id, _ = _context_visibility_owner_ids(_auth)
        items = [
            _public_agent_context(item)
            for item in store.list_agent_contexts()
            if (item.owner_id == owner_id or _can_use_agent_context(item, _auth))
        ]
        return {'items': items}


    @router.post('/v1/agent-contexts')
    def create_agent_context(payload: AgentContextPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        owner_id, _ = _context_visibility_owner_ids(_auth)
        existing = store.find_agent_context_by_name(owner_id, payload.name.strip())
        if existing:
            raise HTTPException(status_code=409, detail='An agent context with that name already exists')
        item = _agent_context_payload_to_item(None, payload, _auth)
        store.add_agent_context(item)
        store.add_event(Event(session_id='system', type='agent_context_created', message=f'Agent context created: {item.name}', data={'context_id': item.id, 'owner': item.owner_username}))
        return {'ok': True, 'context': _public_agent_context(item)}


    @router.get('/v1/agent-contexts/{context_id}')
    def get_agent_context(context_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_agent_context(context_id)
        if not item:
            raise HTTPException(status_code=404, detail='Agent context not found')
        if not _can_use_agent_context(item, _auth):
            raise HTTPException(status_code=403, detail='Agent context not available')
        return {'context': _public_agent_context(item)}


    @router.put('/v1/agent-contexts/{context_id}')
    def update_agent_context(context_id: str, payload: AgentContextPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_agent_context(context_id)
        if not item:
            raise HTTPException(status_code=404, detail='Agent context not found')
        if not _can_edit_agent_context(item, _auth):
            raise HTTPException(status_code=403, detail='Agent context not editable')
        if _is_pac_system_context(item):
            payload.workspace_id = None
            payload.workspace_template_id = None
            payload.shared_storage_id = None
            payload.storage_subpath = None
            payload.storage_mount_path = None
            payload.kind = 'controller'
            payload.controller_workdir = str(_app_dir())
            payload.requires_container = False
            payload.name = DEFAULT_ADMIN_CONTEXT_NAME
        conflict = store.find_agent_context_by_name(item.owner_id, payload.name.strip())
        if conflict and conflict.id != item.id:
            raise HTTPException(status_code=409, detail='An agent context with that name already exists')
        updated = _agent_context_payload_to_item(item, payload, _auth)
        store.add_agent_context(updated)
        synced_session = None
        if updated.last_session_id and store.get_session(updated.last_session_id):
            synced_session = _ensure_agent_context_session(updated, _auth)
        store.add_event(Event(session_id='system', type='agent_context_updated', message=f'Agent context updated: {updated.name}', data={'context_id': updated.id, 'owner': updated.owner_username, 'session_synced': bool(synced_session)}))
        result = {'ok': True, 'context': _public_agent_context(updated)}
        if synced_session:
            result['session'] = synced_session.model_dump(mode='json')
        return result


    @router.delete('/v1/agent-contexts/{context_id}')
    def delete_agent_context(context_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_agent_context(context_id)
        if not item:
            raise HTTPException(status_code=404, detail='Agent context not found')
        if not _can_edit_agent_context(item, _auth):
            raise HTTPException(status_code=403, detail='Agent context not editable')
        if _is_pac_system_context(item):
            raise HTTPException(status_code=403, detail='PAC/core context cannot be deleted')
        store.delete_agent_context(context_id)
        store.add_event(Event(session_id='system', type='agent_context_deleted', message=f'Agent context deleted: {item.name}', data={'context_id': item.id, 'owner': item.owner_username}))
        return {'ok': True, 'deleted': context_id}


    @router.post('/v1/agent-contexts/{context_id}/session')
    def ensure_agent_context_session(context_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        item = store.get_agent_context(context_id)
        if not item:
            raise HTTPException(status_code=404, detail='Agent context not found')
        if not _can_use_agent_context(item, _auth):
            raise HTTPException(status_code=403, detail='Agent context not available')
        session = _ensure_agent_context_session(item, _auth)
        return {'ok': True, 'context': _public_agent_context(item), 'session': session.model_dump(mode='json')}


    @router.get('/v1/shared-storages')
    def list_shared_storages(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return {'items': [_public_shared_storage(item) for item in _storage_catalog()]}


    @router.post('/v1/shared-storages')
    def create_shared_storage(payload: SharedStoragePayload, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        existing = next((item for item in store.list_shared_storages() if item.name == payload.name.strip()), None)
        if existing:
            raise HTTPException(status_code=409, detail='A shared storage with that name already exists')
        item = _shared_storage_payload_to_item(None, payload)
        store.add_shared_storage(item)
        store.add_event(Event(session_id='system', type='shared_storage_created', message=f'Shared storage created: {item.name}', data={'storage_id': item.id, 'driver': item.driver}))
        return {'ok': True, 'storage': _public_shared_storage(item)}


    @router.put('/v1/shared-storages/{storage_id}')
    def update_shared_storage(storage_id: str, payload: SharedStoragePayload, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        item = store.get_shared_storage(storage_id)
        if not item:
            raise HTTPException(status_code=404, detail='Shared storage not found')
        conflict = next((entry for entry in store.list_shared_storages() if entry.name == payload.name.strip() and entry.id != storage_id), None)
        if conflict:
            raise HTTPException(status_code=409, detail='A shared storage with that name already exists')
        updated = _shared_storage_payload_to_item(item, payload)
        store.add_shared_storage(updated)
        store.add_event(Event(session_id='system', type='shared_storage_updated', message=f'Shared storage updated: {updated.name}', data={'storage_id': updated.id, 'driver': updated.driver}))
        return {'ok': True, 'storage': _public_shared_storage(updated)}


    @router.delete('/v1/shared-storages/{storage_id}')
    def delete_shared_storage(storage_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        item = store.get_shared_storage(storage_id)
        if not item:
            raise HTTPException(status_code=404, detail='Shared storage not found')
        for workspace in store.list_user_workspaces():
            if workspace.shared_storage_id == storage_id:
                raise HTTPException(status_code=409, detail=f'Storage is still used by workspace {workspace.name}')
        for context in store.list_agent_contexts():
            if context.shared_storage_id == storage_id:
                raise HTTPException(status_code=409, detail=f'Storage is still used by context {context.name}')
        for profile in (config.workspaces or {}).values():
            if profile.shared_storage_id == storage_id:
                raise HTTPException(status_code=409, detail='Storage is still used by a workspace template')
        store.delete_shared_storage(storage_id)
        store.add_event(Event(session_id='system', type='shared_storage_deleted', message=f'Shared storage deleted: {item.name}', data={'storage_id': item.id}))
        return {'ok': True, 'deleted': storage_id}

    @router.put('/v1/workspaces/{workspace_name}')
    def save_workspace_profile(workspace_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
        name = workspace_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail='Workspace name is required')
        wtype = payload.get('type') or 'local'
        if wtype not in {'local', 'git', 'container'}:
            raise HTTPException(status_code=400, detail='Workspace type must be local, git or container')
        default_agent_profile = payload.get('default_agent_profile') or None
        if default_agent_profile and default_agent_profile not in config.agent_profiles:
            raise HTTPException(status_code=400, detail=f'Unknown default agent profile: {default_agent_profile}')
        endpoint_id = payload.get('endpoint_id') or None
        if endpoint_id and not store.get_runner(endpoint_id):
            raise HTTPException(status_code=400, detail=f'Unknown endpoint: {endpoint_id}')
        shared_storage_id = payload.get('shared_storage_id') or None
        if shared_storage_id and not store.get_shared_storage(shared_storage_id):
            raise HTTPException(status_code=400, detail=f'Unknown shared storage: {shared_storage_id}')
        runtime = payload.get('runtime') or 'any'
        if runtime not in {'any', 'local', 'container'}:
            raise HTTPException(status_code=400, detail='Workspace runtime must be any, local or container')
        if wtype == 'git' and not payload.get('url'):
            raise HTTPException(status_code=400, detail='Git URL is required for git workspaces')
        ttl_hours = payload.get('ttl_hours')
        if ttl_hours in ('', None):
            ttl_hours = None
        elif isinstance(ttl_hours, str):
            try:
                ttl_hours = int(ttl_hours)
            except ValueError:
                raise HTTPException(status_code=400, detail='TTL must be a number of hours')
        if ttl_hours is not None and ttl_hours < 1:
            raise HTTPException(status_code=400, detail='TTL must be at least 1 hour')
        config.workspaces[name] = WorkspaceProfile(
            description=payload.get('description') or None,
            type=wtype,
            path=payload.get('path') or None,
            url=payload.get('url') or None,
            branch=payload.get('branch') or None,
            default_agent_profile=default_agent_profile,
            endpoint_id=endpoint_id,
            endpoint_selector=payload.get('endpoint_selector') or None,
            runtime=runtime,
            shared_storage_id=shared_storage_id,
            storage_subpath=payload.get('storage_subpath') or None,
            storage_mount_path=payload.get('storage_mount_path') or None,
            container_image=payload.get('container_image') or None,
            data_bundle_url=payload.get('data_bundle_url') or None,
            data_bundle_path=payload.get('data_bundle_path') or None,
            data_mount_path=payload.get('data_mount_path') or None,
            ephemeral=bool(payload.get('ephemeral')),
            ttl_hours=ttl_hours,
            delete_on_expire=bool(payload.get('delete_on_expire', True)),
            is_default=bool(payload.get('is_default')),
        )
        save_config(config)
        store.add_event(Event(session_id='system', type='workspace_saved', message=f'Workspace saved: {name}', data={'workspace': name, 'type': wtype}))
        return {'ok': True, 'name': name, **config.workspaces[name].model_dump()}


    @router.delete('/v1/workspaces/{workspace_name}')
    def delete_workspace_profile(workspace_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        if workspace_name not in config.workspaces:
            raise HTTPException(status_code=404, detail='Workspace not found')
        del config.workspaces[workspace_name]
        if not config.workspaces:
            config.workspaces['scratch'] = WorkspaceProfile(description='Default local workspace', type='local', path=None)
        save_config(config)
        store.add_event(Event(session_id='system', type='workspace_deleted', message=f'Workspace deleted: {workspace_name}'))
        return {'ok': True, 'deleted': workspace_name}



    def _merge_agent_metadata(current: dict[str, Any] | None, incoming: dict[str, Any] | None, inventory: dict[str, Any] | None, metrics: dict[str, Any] | None) -> dict[str, Any]:
        metadata = {**(current or {}), **(incoming or {})}
        inv = inventory or metadata.get('inventory') or {}
        met = metrics or metadata.get('metrics') or {}
        if inv:
            metadata['inventory'] = inv
            metadata['hardware'] = inv
        if met:
            metadata['metrics'] = met
            metadata['latest_metrics'] = met
        return metadata

    def _public_workspace_agent(agent: WorkspaceAgent) -> dict[str, Any]:
        last_seen = agent.last_seen_at
        status = agent.status.value if hasattr(agent.status, 'value') else str(agent.status)
        if last_seen and now_utc() - last_seen > timedelta(seconds=90):
            status = 'offline'
        elif last_seen and now_utc() - last_seen > timedelta(seconds=30):
            status = 'degraded'
        return {
            'id': agent.id,
            'workspace_id': agent.workspace_id,
            'name': agent.name,
            'status': status,
            'endpoint_id': agent.endpoint_id,
            'root': agent.root,
            'lifetime': agent.lifetime,
            'labels': agent.labels,
            'capabilities': agent.capabilities,
            'metadata': agent.metadata,
            'inventory': (agent.metadata or {}).get('inventory') or (agent.metadata or {}).get('hardware') or {},
            'metrics': (agent.metadata or {}).get('metrics') or (agent.metadata or {}).get('latest_metrics') or {},
            'created_at': agent.created_at.isoformat(),
            'updated_at': agent.updated_at.isoformat(),
            'last_seen_at': agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        }

    def _workspace_agent_or_404(workspace_id: str) -> WorkspaceAgent:
        agent = store.get_workspace_agent(workspace_id)
        if not agent:
            raise HTTPException(status_code=404, detail='Workspace agent not found')
        return agent

    def _append_workspace_command_event(command: WorkspaceAgentCommand, *, stream: str, data: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_stream = stream if stream in {'stdout', 'stderr', 'system', 'status'} else 'system'
        command.stream_seq = int(command.stream_seq or 0) + 1
        event_model = WorkspaceAgentCommandEvent(
            workspace_id=command.workspace_id,
            command_id=command.id,
            seq=command.stream_seq,
            stream=safe_stream,
            data=data or '',
            metadata=metadata or {},
        )
        event = event_model.model_dump(mode='json')
        if safe_stream == 'stdout' and data:
            command.output = (command.output or '') + data
        elif safe_stream == 'stderr' and data:
            command.error = (command.error or '') + data
        # Keep only a compact recent tail on the command record. The complete,
        # append-only event history lives in workspace_agent_command_events.
        command.events.append(event)
        if len(command.events) > 200:
            command.events = command.events[-200:]
        store.add_workspace_agent_command_event(event_model)
        store.add_workspace_agent_command(command)
        return event

    def _terminal_command_status(command: WorkspaceAgentCommand) -> bool:
        status = command.status.value if hasattr(command.status, 'value') else str(command.status)
        return status in {'completed', 'failed', 'interrupted'}

    @router.get('/v1/workspaces')
    def list_workspaces(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        profiles = []
        for name, profile in (config.workspaces or {}).items():
            profiles.append({'name': name, **profile.model_dump()})
        agents = [_public_workspace_agent(agent) for agent in store.list_workspace_agents()]
        user_items = []
        try:
            owner_id, _ = _workspace_owner(_auth)
            user_items = [_public_user_workspace(item) for item in store.list_user_workspaces(owner_id=owner_id)]
        except Exception:
            user_items = []
        return {'items': agents, 'agents': agents, 'profiles': profiles, 'user_workspaces': user_items}

    @router.get('/v1/workspaces/{workspace_id}')
    def get_workspace_status(workspace_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        agent = store.get_workspace_agent(workspace_id)
        if agent:
            commands = []
            for cmd in store.list_workspace_agent_commands(workspace_id, limit=25):
                payload = cmd.model_dump(mode='json')
                payload['event_count'] = store.count_workspace_agent_command_events(cmd.id)
                commands.append(payload)
            return {'workspace': _public_workspace_agent(agent), 'commands': commands}
        if workspace_id in config.workspaces:
            return {'workspace': {'name': workspace_id, **config.workspaces[workspace_id].model_dump()}, 'commands': []}
        item = store.get_user_workspace(workspace_id)
        if item:
            owner_id, _ = _workspace_owner(_auth)
            if not _can_resource_access(_auth, 'workspace', f'user:{item.id}', 'read', owner_id=item.owner_id):
                raise HTTPException(status_code=403, detail='Workspace not available')
            return {'workspace': _public_user_workspace(item), 'commands': []}
        raise HTTPException(status_code=404, detail='Workspace not found')

    @router.post('/v1/workspace-agents/register')
    def register_workspace_agent(payload: WorkspaceAgentRegisterPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        raw_name = (payload.name or payload.workspace_id or '').strip()
        if not raw_name:
            raise HTTPException(status_code=400, detail='Workspace name or id is required')
        workspace_id = (payload.workspace_id or re.sub(r'[^a-zA-Z0-9_.:-]+', '-', raw_name).strip('-') or raw_name).strip()
        existing = store.get_workspace_agent(workspace_id)
        agent = existing or WorkspaceAgent(workspace_id=workspace_id, name=raw_name)
        agent.name = raw_name
        agent.status = WorkspaceAgentStatus.online
        agent.root = payload.root or agent.root
        agent.lifetime = 'ephemeral' if payload.lifetime == 'ephemeral' else 'persistent'
        agent.labels = sorted(set([*(agent.labels or []), *(payload.labels or [])]))
        agent.capabilities = {**(agent.capabilities or {}), **(payload.capabilities or {})}
        agent.metadata = _merge_agent_metadata(agent.metadata, payload.metadata, payload.inventory, payload.metrics)
        agent.last_seen_at = now_utc()
        store.add_workspace_agent(agent)
        store.add_event(Event(session_id='system', type='workspace_agent_registered', message=f'Workspace agent online: {agent.name}', data={'workspace_id': workspace_id, 'agent_id': agent.id}))
        return {'ok': True, 'workspace_id': workspace_id, 'agent_id': agent.id, 'workspace': _public_workspace_agent(agent)}

    @router.post('/v1/workspace-agents/heartbeat')
    def heartbeat_workspace_agent(payload: WorkspaceAgentHeartbeatPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        workspace_id = payload.workspace_id.strip()
        if not workspace_id:
            raise HTTPException(status_code=400, detail='workspace_id is required')
        agent = store.get_workspace_agent(workspace_id) or WorkspaceAgent(workspace_id=workspace_id, name=workspace_id)
        agent.status = WorkspaceAgentStatus.online if payload.status == 'online' else WorkspaceAgentStatus.degraded
        agent.endpoint_id = payload.endpoint_id or agent.endpoint_id
        agent.root = payload.root or agent.root
        agent.labels = sorted(set([*(agent.labels or []), *(payload.labels or [])]))
        agent.capabilities = {**(agent.capabilities or {}), **(payload.capabilities or {})}
        metadata = _merge_agent_metadata(agent.metadata, payload.metadata, payload.inventory, payload.metrics)
        if payload.version:
            metadata['endpoint_version'] = payload.version
        agent.metadata = metadata
        agent.last_seen_at = now_utc()
        store.add_workspace_agent(agent)
        return {'ok': True, 'workspace_id': workspace_id, 'status': agent.status.value}

    @router.post('/v1/workspaces/{workspace_id}/commands')
    def queue_workspace_command(workspace_id: str, payload: WorkspaceCommandPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not store.get_workspace_agent(workspace_id):
            raise HTTPException(status_code=404, detail='Workspace agent is not online or registered')
        command_text = str(payload.command or '').strip()
        if not command_text:
            raise HTTPException(status_code=400, detail='command is required')
        command = WorkspaceAgentCommand(workspace_id=workspace_id, command=command_text, workspace_path=payload.workspace_path, metadata=payload.metadata or {})
        store.add_workspace_agent_command(command)
        store.add_event(Event(session_id='system', type='workspace_command_queued', message=f'Workspace command queued for {workspace_id}', data={'workspace_id': workspace_id, 'command_id': command.id}))
        return {'ok': True, 'command': command.model_dump(mode='json')}

    @router.get('/v1/workspace-agents/{workspace_id}/commands/next')
    def claim_workspace_command(workspace_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any] | None:
        agent = _workspace_agent_or_404(workspace_id)
        agent.last_seen_at = now_utc()
        agent.status = WorkspaceAgentStatus.online
        store.add_workspace_agent(agent)
        command = store.claim_next_workspace_agent_command(workspace_id)
        if not command:
            return None
        _append_workspace_command_event(command, stream='system', data='Workspace command claimed by agent.\n')
        store.add_event(Event(session_id='system', type='workspace_command_claimed', message=f'Workspace command claimed by {workspace_id}', data={'workspace_id': workspace_id, 'command_id': command.id}))
        return {'id': command.id, 'command': command.command, 'workspace_path': command.workspace_path or agent.root, 'metadata': command.metadata}

    @router.get('/v1/workspaces/{workspace_id}/commands/{command_id}')
    def get_workspace_command(workspace_id: str, command_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        command = store.get_workspace_agent_command(command_id)
        if not command or command.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail='Workspace command not found')
        agent = store.get_workspace_agent(workspace_id)
        payload = command.model_dump(mode='json')
        payload['event_count'] = store.count_workspace_agent_command_events(command.id)
        payload['events'] = [event.model_dump(mode='json') for event in store.list_workspace_agent_command_events(command.id, limit=200)]
        return {
            'command': payload,
            'workspace': _public_workspace_agent(agent) if agent else None,
        }

    @router.get('/v1/workspaces/{workspace_id}/commands/{command_id}/events')
    def list_workspace_command_events(workspace_id: str, command_id: str, cursor: int = 0, limit: int = 500, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        command = store.get_workspace_agent_command(command_id)
        if not command or command.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail='Workspace command not found')
        events = store.list_workspace_agent_command_events(command_id, after_seq=cursor, limit=limit)
        return {
            'events': [event.model_dump(mode='json') for event in events],
            'next_cursor': events[-1].seq if events else int(cursor or 0),
            'count': len(events),
        }

    @router.post('/v1/workspace-agents/{workspace_id}/commands/{command_id}/events')
    def append_workspace_command_event(workspace_id: str, command_id: str, payload: WorkspaceCommandEventPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        command = store.get_workspace_agent_command(command_id)
        if not command or command.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail='Workspace command not found')
        event = _append_workspace_command_event(command, stream=payload.stream, data=payload.data, metadata=payload.metadata)
        return {'ok': True, 'event': event}


    @router.post('/v1/workspaces/{workspace_id}/commands/{command_id}/cancel')
    def cancel_workspace_command(workspace_id: str, command_id: str, payload: WorkspaceCommandCancelPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        command = store.get_workspace_agent_command(command_id)
        if not command or command.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail='Workspace command not found')
        if _terminal_command_status(command):
            return {'ok': True, 'command': command.model_dump(mode='json'), 'already_terminal': True}
        metadata = {**(command.metadata or {})}
        metadata['cancel_requested'] = True
        metadata['cancel_force'] = bool(payload.force)
        metadata['cancel_reason'] = payload.reason or 'cancel requested'
        metadata['cancel_metadata'] = payload.metadata or {}
        metadata['cancel_requested_at'] = now_utc().isoformat()
        command.metadata = metadata
        if command.status == WorkspaceAgentCommandStatus.queued:
            command.status = WorkspaceAgentCommandStatus.interrupted
            command.exit_code = 130
            command.completed_at = now_utc()
            _append_workspace_command_event(command, stream='status', data='Workspace command cancelled before agent claim.\n', metadata={'reason': metadata['cancel_reason'], 'cancelled': True})
        else:
            _append_workspace_command_event(command, stream='system', data='Interrupt requested for workspace command.\n', metadata={'reason': metadata['cancel_reason'], 'force': bool(payload.force)})
            store.add_workspace_agent_command(command)
        store.add_event(Event(session_id='system', type='workspace_command_interrupt_requested', message=f'Workspace command interrupt requested: {workspace_id}', data={'workspace_id': workspace_id, 'command_id': command.id, 'reason': metadata['cancel_reason'], 'force': bool(payload.force)}))
        return {'ok': True, 'command': command.model_dump(mode='json')}

    @router.get('/v1/workspaces/{workspace_id}/commands/{command_id}/stream')
    async def stream_workspace_command(workspace_id: str, command_id: str, cursor: int = 0, _auth: Any = Depends(require_auth)) -> StreamingResponse:
        async def generate():
            next_seq = max(1, int(cursor or 0) + 1)
            terminal_sent = False
            while True:
                command = store.get_workspace_agent_command(command_id)
                if not command or command.workspace_id != workspace_id:
                    yield json.dumps({'stream': 'system', 'data': 'Workspace command not found.\n', 'status': 'missing'}) + '\n'
                    return
                events = [event for event in (command.events or []) if int(event.get('seq') or 0) >= next_seq]
                for event in events:
                    next_seq = max(next_seq, int(event.get('seq') or 0) + 1)
                    yield json.dumps({'type': 'event', **event}) + '\n'
                if _terminal_command_status(command):
                    if not terminal_sent:
                        terminal_sent = True
                        yield json.dumps({'type': 'status', 'seq': command.stream_seq, 'status': command.status.value if hasattr(command.status, 'value') else str(command.status), 'exit_code': command.exit_code, 'created_at': now_utc().isoformat()}) + '\n'
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(generate(), media_type='application/x-ndjson')

    @router.post('/v1/workspace-agents/{workspace_id}/commands/{command_id}/complete')
    def complete_workspace_command(workspace_id: str, command_id: str, payload: WorkspaceCommandCompletePayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        command = store.get_workspace_agent_command(command_id)
        if not command or command.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail='Workspace command not found')
        if command.status == WorkspaceAgentCommandStatus.interrupted or payload.status == 'interrupted':
            command.status = WorkspaceAgentCommandStatus.interrupted
            command.exit_code = command.exit_code if command.exit_code is not None else (payload.exit_code if payload.exit_code is not None else 130)
        else:
            command.status = WorkspaceAgentCommandStatus.completed if payload.status == 'completed' else WorkspaceAgentCommandStatus.failed
        if payload.output is not None:
            command.output = payload.output
        if payload.error is not None:
            command.error = payload.error
        if payload.exit_code is not None:
            command.exit_code = payload.exit_code
        command.metadata = {**(command.metadata or {}), **(payload.metadata or {})}
        command.completed_at = now_utc()
        _append_workspace_command_event(command, stream='status', data=f'Workspace command {command.status.value}.\n', metadata={'exit_code': command.exit_code})
        store.add_event(Event(session_id='system', type='workspace_command_completed', message=f'Workspace command {command.status.value}: {workspace_id}', data={'workspace_id': workspace_id, 'command_id': command.id, 'exit_code': command.exit_code}))
        return {'ok': True, 'command': command.model_dump(mode='json')}

    return router
