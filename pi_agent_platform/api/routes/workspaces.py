from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import WorkspaceProfile
from pi_agent_platform.core.models import Event

DEFAULT_ADMIN_CONTEXT_NAME = 'PAC/core'


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

    return router
