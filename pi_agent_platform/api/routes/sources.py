from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable
import zipfile

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import SourceContextConfig, load_config, save_config
from pi_agent_platform.core.models import Event
from pi_agent_platform.core.pac_ram import all_ram, bundle_ram, list_ram, read_ram, search_ram, write_ram
from pi_agent_platform.core.platform_home import pacp_path
from pi_agent_platform.core.secrets import secret_store
from pi_agent_platform.core.source_library import (
    apply_feature_pack as source_apply_feature_pack,
    binary_artifact_path as source_binary_artifact_path,
    build_binary as source_build_binary,
    build_container as source_build_container,
    create_entry as source_create_entry,
    delete_binary_artifact as source_delete_binary_artifact,
    delete_entry as source_delete_entry,
    ensure_source_library,
    fetch_online_package_updates as source_fetch_online_package_updates,
    inspect_feature_pack as source_inspect_feature_pack,
    list_binary_artifacts as source_list_binary_artifacts,
    list_tree as source_list_tree,
    make_archive as source_make_archive,
    prune_binary_artifacts as source_prune_binary_artifacts,
    read_text as source_read_text,
    rename_entry as source_rename_entry,
    write_text as source_write_text,
)
from pi_agent_platform.core.source_variables import source_variable_store


class SourceWriteRequest(BaseModel):
    path: str
    content: str


class SourceCreateRequest(BaseModel):
    path: str
    type: str = 'file'


class SourceRenameRequest(BaseModel):
    path: str
    new_name: str


class SourceDeleteRequest(BaseModel):
    path: str


class SourceBuildRequest(BaseModel):
    path: str
    runtime: str = 'auto'
    tag: str | None = None
    targets: list[str] | None = None
    server_url: str | None = None
    binary_name: str | None = None
    endpoint_name: str | None = None
    runner_enabled: bool | None = None
    workspace_path: str | None = None


class SourceContextUpdateRequest(BaseModel):
    description: str | None = None
    path_prefix: str
    customer_id: str | None = None
    user_scope: str | None = None
    workspace_profile: str | None = None
    preferred_endpoint: str | None = None
    container_image: str | None = None
    profile: str | None = None
    config_vars: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class SecretUpdateRequest(BaseModel):
    value: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SourceVariableUpdateRequest(BaseModel):
    value: str
    description: str = ''
    tags: list[str] = Field(default_factory=list)


class PacRamWriteRequest(BaseModel):
    content: str


class SourceFeaturePackApplyRequest(BaseModel):
    upload_id: str


CurrentUser = Any


def create_sources_router(
    *,
    require_auth: Callable[..., Any],
    get_config: Callable[[], Any],
    set_config: Callable[[Any], None],
    store: Any,
    user_has_resource_access: Callable[..., bool],
    require_resource_access: Callable[..., None],
    runner_from_auth_headers: Callable[..., Any],
    admin_auth_valid: Callable[[str | None], bool],
    get_user_from_auth: Callable[..., Any],
    require_admin_or_runner: Callable[..., None],
    resolve_variable_tokens: Callable[[dict[str, str]], tuple[dict[str, str], dict[str, Any]]],
    require_no_source_builds: Callable[[str], None],
    set_source_build_active: Callable[[dict[str, Any] | None], None],
    apply_version_package_from_path: Callable[[Path, str, bool], dict[str, Any]],
    schedule_local_restart: Callable[[BackgroundTasks, str], None],
) -> APIRouter:
    router = APIRouter()

    def _normalise_source_context_name(name: str) -> str:
        value = str(name or '').strip()
        if not value:
            raise HTTPException(status_code=400, detail='Source context name is required')
        if '/' in value or '\\' in value:
            raise HTTPException(status_code=400, detail='Source context name must not contain path separators')
        return value

    def _normalise_source_context_path(path: str | None) -> str:
        value = str(path or '').strip().replace('\\', '/').strip('/')
        if not value:
            raise HTTPException(status_code=400, detail='path_prefix is required')
        return value

    def _save_source_context(name: str, payload: SourceContextUpdateRequest) -> dict[str, Any]:
        current = get_config()
        context = SourceContextConfig.model_validate(
            {
                **payload.model_dump(),
                'path_prefix': _normalise_source_context_path(payload.path_prefix),
            }
        )
        current.source_contexts[name] = context
        save_config(current)
        refreshed = load_config()
        set_config(refreshed)
        result = refreshed.source_contexts[name].model_dump()
        store.add_event(Event(session_id='system', type='source_context_saved', message=f'Source context saved: {name}', data={'name': name, **result}))
        return result

    def _match_source_context(path: str | None = None, name: str | None = None) -> tuple[str, SourceContextConfig]:
        current = get_config()
        if name:
            context = current.source_contexts.get(name)
            if not context:
                raise HTTPException(status_code=404, detail='Source context not found')
            return name, context
        clean = str(path or '').strip().replace('\\', '/').strip('/')
        if not clean:
            raise HTTPException(status_code=400, detail='path or name is required')
        matches: list[tuple[int, str, SourceContextConfig]] = []
        for ctx_name, ctx in (current.source_contexts or {}).items():
            prefix = str(ctx.path_prefix or '').strip('/').replace('\\', '/')
            if not prefix:
                continue
            if clean == prefix or clean.startswith(prefix + '/'):
                matches.append((len(prefix), ctx_name, ctx))
        if not matches:
            raise HTTPException(status_code=404, detail='No source context matches this path')
        _len, matched_name, matched_context = sorted(matches, key=lambda item: item[0], reverse=True)[0]
        return matched_name, matched_context

    def _resolve_source_context(path: str | None = None, name: str | None = None, include_secret_values: bool = False) -> dict[str, Any]:
        context_name, context = _match_source_context(path=path, name=name)
        config_vars, resolved_variables = resolve_variable_tokens(dict(context.config_vars or {}))
        secret_refs = dict(context.secret_refs or {})
        resolved_secrets: dict[str, str | None] = {}
        for env_name, secret_id in secret_refs.items():
            try:
                resolved_secrets[env_name] = secret_store.get(secret_id) if include_secret_values else None
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            'name': context_name,
            'context': context.model_dump(),
            'path': str(path or '').strip().replace('\\', '/'),
            'environment': {
                **config_vars,
                **({env_name: value for env_name, value in resolved_secrets.items() if value is not None} if include_secret_values else {}),
            },
            'config_vars': config_vars,
            'resolved_variables': resolved_variables,
            'secret_refs': secret_refs,
            'resolved_secrets': resolved_secrets,
        }

    @router.get('/v1/sources')
    def get_sources(path: str = '', _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            info = ensure_source_library()
            tree = source_list_tree(path)
            return {'root': info['root'], 'top_level': info['top_level'], **tree}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Source path not found')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get('/v1/sources/content')
    def get_source_content(path: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            return source_read_text(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Source file not found')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.put('/v1/sources/content')
    def put_source_content(payload: SourceWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = source_write_text(payload.path, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        store.add_event(Event(session_id='system', type='source_file_saved', message=f'Source saved: {result["path"]}', data=result))
        return {'status': 'saved', **result}

    @router.get('/v1/source-contexts')
    @router.get('/v1/ide/contexts')
    def list_source_contexts(_auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        items = []
        for name, ctx in sorted((get_config().source_contexts or {}).items()):
            resource_id = f'context:{name}'
            if user_has_resource_access(_auth, 'source_context', resource_id, 'read'):
                items.append({'name': name, **ctx.model_dump()})
        return {'contexts': items}

    @router.get('/v1/source-contexts/resolve')
    @router.get('/v1/ide/context/resolve')
    def resolve_source_context(
        path: str | None = None,
        name: str | None = None,
        include_secrets: bool = Query(default=False),
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        runner = runner_from_auth_headers(authorization, x_pac_runner_id, x_pac_runner_key)
        include_secret_values = include_secrets and (admin_auth_valid(authorization) or runner is not None)
        result = _resolve_source_context(path=path, name=name, include_secret_values=include_secret_values)
        context_name = str(result.get('name') or name or '').strip()
        if context_name and runner is None and not admin_auth_valid(authorization):
            auth = get_user_from_auth(authorization)
            require_resource_access(auth, 'source_context', f'context:{context_name}', 'read', reason='Resolve this source context')
        if runner:
            result['requested_by'] = {'kind': 'endpoint', 'runner_id': runner.id, 'runner_name': runner.name}
        elif admin_auth_valid(authorization):
            result['requested_by'] = {'kind': 'admin'}
        return result

    @router.get('/v1/source-contexts/{name}')
    @router.get('/v1/ide/contexts/{name}')
    def get_source_context(name: str, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        key = _normalise_source_context_name(name)
        require_resource_access(_auth, 'source_context', f'context:{key}', 'read', reason='View this source context')
        context = get_config().source_contexts.get(key)
        if not context:
            raise HTTPException(status_code=404, detail='Source context not found')
        return {'name': key, **context.model_dump()}

    @router.put('/v1/source-contexts/{name}')
    @router.put('/v1/ide/contexts/{name}')
    def put_source_context(name: str, payload: SourceContextUpdateRequest, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        key = _normalise_source_context_name(name)
        require_resource_access(_auth, 'source_context', f'context:{key}', 'write', reason='Edit this source context')
        result = _save_source_context(key, payload)
        return {'status': 'saved', 'name': key, **result}

    @router.delete('/v1/source-contexts/{name}')
    @router.delete('/v1/ide/contexts/{name}')
    def delete_source_context(name: str, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        key = _normalise_source_context_name(name)
        require_resource_access(_auth, 'source_context', f'context:{key}', 'write', reason='Delete this source context')
        current = get_config()
        if key not in current.source_contexts:
            raise HTTPException(status_code=404, detail='Source context not found')
        del current.source_contexts[key]
        save_config(current)
        set_config(load_config())
        store.add_event(Event(session_id='system', type='source_context_deleted', message=f'Source context deleted: {key}', data={'name': key}))
        return {'status': 'deleted', 'name': key}

    @router.get('/v1/source-variables')
    @router.get('/v1/ide/variables')
    def list_source_variables(
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        return {'variables': source_variable_store.list()}

    @router.get('/v1/source-variables/{variable_id}')
    @router.get('/v1/ide/variables/{variable_id}')
    def get_source_variable(
        variable_id: str,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            item = source_variable_store.get(variable_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail='Variable not found')
        return item

    @router.put('/v1/source-variables/{variable_id}')
    @router.put('/v1/ide/variables/{variable_id}')
    def put_source_variable(variable_id: str, payload: SourceVariableUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            item = source_variable_store.set(variable_id, payload.value, payload.description, payload.tags)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='source_variable_saved', message=f'Source variable saved: {item["id"]}', data=item))
        return {'status': 'saved', **item}

    @router.delete('/v1/source-variables/{variable_id}')
    @router.delete('/v1/ide/variables/{variable_id}')
    def delete_source_variable(variable_id: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            deleted = source_variable_store.delete(variable_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail='Variable not found')
        store.add_event(Event(session_id='system', type='source_variable_deleted', message=f'Source variable deleted: {variable_id}', data={'id': variable_id}))
        return {'status': 'deleted', 'id': variable_id}

    @router.get('/v1/pac-ram/list')
    @router.get('/v1/ide/pac-ram/list')
    def get_pac_ram_list(
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        return list_ram()

    @router.get('/v1/pac-ram/all')
    @router.get('/v1/ide/pac-ram/all')
    def get_all_pac_ram(
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        return all_ram()

    @router.get('/v1/pac-ram/bundle')
    @router.get('/v1/ide/pac-ram/bundle')
    def get_pac_ram_bundle(
        profile: str | None = None,
        user: str | None = None,
        workspace: str | None = None,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            return bundle_ram(profile=profile, user=user, workspace=workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get('/v1/pac-ram/search')
    @router.get('/v1/ide/pac-ram/search')
    def search_pac_ram(
        q: str,
        kind: str | None = None,
        limit: int = 10,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            return search_ram(q, kind=kind, limit=max(1, min(limit, 50)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get('/v1/pac-ram/profile/{profile}')
    def get_profile_ram(
        profile: str,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            return read_ram('profile', profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put('/v1/pac-ram/profile/{profile}')
    def put_profile_ram(profile: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = write_ram('profile', profile, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM profile saved: {result["key"]}', data={'kind': 'profile', **result}))
        return result

    @router.get('/v1/pac-ram/user/{user_id}')
    def get_user_ram(
        user_id: str,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            return read_ram('user', user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get('/v1/users/me/ram')
    def get_current_user_ram(_auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not have user memory')
        try:
            return read_ram('user', _auth.user.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put('/v1/users/me/ram')
    def put_current_user_ram(payload: PacRamWriteRequest, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not have user memory')
        try:
            result = write_ram('user', _auth.user.id, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM user saved: {result["key"]}', data={'kind': 'user', **result}))
        return result

    @router.put('/v1/pac-ram/user/{user_id}')
    def put_user_ram(user_id: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = write_ram('user', user_id, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM user saved: {result["key"]}', data={'kind': 'user', **result}))
        return result

    @router.get('/v1/pac-ram/workspace/{workspace}')
    def get_workspace_ram(
        workspace: str,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        try:
            return read_ram('workspace', workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put('/v1/pac-ram/workspace/{workspace}')
    def put_workspace_ram(workspace: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = write_ram('workspace', workspace, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM workspace saved: {result["key"]}', data={'kind': 'workspace', **result}))
        return result

    @router.get('/v1/secrets')
    @router.get('/v1/ide/secrets')
    def list_secrets(_auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        try:
            items = secret_store.list()
            if _auth.is_admin:
                return {'secrets': items}
            filtered = [item for item in items if user_has_resource_access(_auth, 'secret', f"secret:{item.get('id')}", 'read')]
            return {'secrets': filtered}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get('/v1/secrets/audit')
    @router.get('/v1/ide/secrets/audit')
    def list_secret_audit(limit: int = 20, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        try:
            items = secret_store.audit_tail(max(1, min(limit, 200)))
            if _auth.is_admin:
                return {'items': items}
            filtered = [item for item in items if user_has_resource_access(_auth, 'secret', f"secret:{item.get('secret_id')}", 'read')]
            return {'items': filtered}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.put('/v1/secrets/{secret_id}')
    @router.put('/v1/ide/secrets/{secret_id}')
    def put_secret(secret_id: str, payload: SecretUpdateRequest, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'secret', f'secret:{secret_id}', 'write', reason='Update this secret')
        try:
            item = secret_store.set(secret_id, payload.value, actor='web-ui', meta=payload.meta)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='secret_saved', message=f'Secret saved: {secret_id}', data={'secret_id': secret_id, 'meta': payload.meta}))
        return {'status': 'saved', **item}

    @router.delete('/v1/secrets/{secret_id}')
    @router.delete('/v1/ide/secrets/{secret_id}')
    def delete_secret(secret_id: str, _auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'secret', f'secret:{secret_id}', 'write', reason='Delete this secret')
        try:
            deleted = secret_store.delete(secret_id, actor='web-ui')
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail='Secret not found')
        store.add_event(Event(session_id='system', type='secret_deleted', message=f'Secret deleted: {secret_id}', data={'secret_id': secret_id}))
        return {'status': 'deleted', 'secret_id': secret_id}

    @router.get('/v1/secrets/{secret_id}')
    @router.get('/v1/ide/secrets/{secret_id}')
    def get_secret(
        secret_id: str,
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        runner = runner_from_auth_headers(authorization, x_pac_runner_id, x_pac_runner_key)
        if not runner and not admin_auth_valid(authorization):
            auth = get_user_from_auth(authorization)
            require_resource_access(auth, 'secret', f'secret:{secret_id}', 'read', reason='Read this secret')
        try:
            value = secret_store.get(secret_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if value is None:
            raise HTTPException(status_code=404, detail='Secret not found')
        return {
            'secret_id': secret_id,
            'value': value,
            'requested_by': {'kind': 'endpoint', 'runner_id': runner.id} if runner else {'kind': 'admin'},
        }

    @router.post('/v1/sources/entry')
    def create_source_entry(payload: SourceCreateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = source_create_entry(payload.path, payload.type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        store.add_event(Event(session_id='system', type='source_entry_created', message=f'Source {result["type"]} created: {result["path"]}', data=result))
        return result

    @router.post('/v1/sources/entry/rename')
    def rename_source_entry(payload: SourceRenameRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = source_rename_entry(payload.path, payload.new_name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Source path not found')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        store.add_event(Event(session_id='system', type='source_entry_renamed', message=f'Source renamed: {result["path"]} -> {result["new_path"]}', data=result))
        return result

    @router.delete('/v1/sources/entry')
    def delete_source_entry(path: str | None = Query(default=None), payload: SourceDeleteRequest | None = Body(default=None), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = source_delete_entry((payload.path if payload else None) or path or '')
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Source path not found')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        store.add_event(Event(session_id='system', type='source_entry_deleted', message=f'Source deleted: {result["path"]}', data=result))
        return result

    @router.post('/v1/sources/build-container')
    def build_source_container(payload: SourceBuildRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        set_source_build_active({'kind': 'container', 'path': payload.path, 'status': 'running', 'message': 'Container build is running'})
        try:
            result = source_build_container(payload.path, runtime=payload.runtime, tag=payload.tag)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Container source folder not found')
        except Exception as exc:
            store.add_event(Event(session_id='system', type='source_container_build_failed', message=f'Container build failed: {payload.path}', data={'path': payload.path, 'error': str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            set_source_build_active(None)
        store.add_event(Event(session_id='system', type='source_container_built' if result.get('ok') else 'source_container_build_failed', message=f'Container build {"completed" if result.get("ok") else "failed"}: {result.get("image")}', data=result))
        return result

    @router.post('/v1/sources/build-binary')
    def build_source_binary(payload: SourceBuildRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        set_source_build_active({'kind': 'binary', 'path': payload.path, 'status': 'running', 'message': 'Binary build is running'})
        try:
            compiled_url = (payload.server_url or str(get_config().server.public_url) or '').strip().rstrip('/')
            result = source_build_binary(
                payload.path,
                targets=payload.targets,
                runtime=payload.runtime,
                binary_name=payload.binary_name,
                compiled_server_url=compiled_url,
                compiled_endpoint_name=payload.endpoint_name,
                compiled_runner_enabled=payload.runner_enabled,
                compiled_workspace_root=payload.workspace_path,
            )
            result['compiled_server_url'] = compiled_url
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Binary source folder not found')
        except Exception as exc:
            store.add_event(Event(session_id='system', type='source_binary_build_failed', message=f'Binary build failed: {payload.path}', data={'path': payload.path, 'error': str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            set_source_build_active(None)
        store.add_event(Event(session_id='system', type='source_binary_built' if result.get('ok') else 'source_binary_build_failed', message=f'Binary build {"completed" if result.get("ok") else "failed"}: {payload.path}', data=result))
        return result

    @router.post('/v1/sources/feature-pack/inspect')
    def inspect_source_feature_pack(file: UploadFile = File(...), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        require_no_source_builds('Feature update inspection')
        if not file.filename or not file.filename.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail='Feature update must be a .zip file')
        upload_dir = pacp_path('cache', 'feature-packs')
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_id = uuid.uuid4().hex[:12]
        path = upload_dir / f'{upload_id}.zip'
        with path.open('wb') as dst:
            shutil.copyfileobj(file.file, dst)
        try:
            result = source_inspect_feature_pack(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            store.add_event(Event(session_id='system', type='feature_pack_inspect_failed', message=f'Feature update inspection failed: {exc}', data={'filename': file.filename, 'error': str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc))
        result['upload_id'] = upload_id
        result['pending_apply_url'] = '/v1/sources/feature-pack/apply'
        if result.get('package_type') == 'pac_app_update':
            message = f'PAC app update inspected: {result.get("current_version", "unknown")} -> {result.get("target_version", "unknown")}'
        else:
            message = f'Feature update inspected: {len(result.get("components", []))} source folders'
        store.add_event(Event(session_id='system', type='feature_pack_inspected', message=message, data=result))
        return result

    @router.post('/v1/sources/feature-pack/apply')
    def apply_source_feature_pack(background_tasks: BackgroundTasks, payload: SourceFeaturePackApplyRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        require_no_source_builds('Feature update apply')
        upload_id = ''.join(ch for ch in payload.upload_id if ch.isalnum())[:32]
        path = pacp_path('cache', 'feature-packs', f'{upload_id}.zip')
        if not path.is_file():
            raise HTTPException(status_code=404, detail='Feature update upload was not found; inspect the zip again')
        try:
            preview = source_inspect_feature_pack(path)
            if preview.get('package_type') == 'pac_app_update':
                result = apply_version_package_from_path(path, preview.get('filename') or path.name, True)
                result.update({'preview': preview})
                schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying app update: {path.name}')
                return result
            result = source_apply_feature_pack(path)
        except Exception as exc:
            store.add_event(Event(session_id='system', type='feature_pack_apply_failed', message=f'Feature update failed: {exc}', data={'upload_id': upload_id, 'error': str(exc)}))
            raise HTTPException(status_code=400, detail=str(exc))
        store.add_event(Event(session_id='system', type='feature_pack_applied', message=f'Feature update applied: {len(result.get("components", []))} source folders', data=result))
        path.unlink(missing_ok=True)
        return result

    @router.get('/v1/sources/online-updates')
    def check_source_online_updates(manifest_url: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        url = manifest_url or getattr(get_config().source_updates, 'packages_manifest_url', None)
        result = source_fetch_online_package_updates(url)
        event_type = 'source_online_updates_checked' if result.get('ok') else 'source_online_updates_failed'
        message = f"Source package updates checked: {result.get('update_count', 0)} available" if result.get('ok') else f"Source package update check failed: {result.get('error', 'unknown error')}"
        store.add_event(Event(session_id='system', type=event_type, message=message, data=result))
        return result

    @router.get('/v1/sources/binary-artifacts')
    def list_source_binary_artifacts(project: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return source_list_binary_artifacts(project)

    @router.get('/v1/sources/binary-artifacts/{project}/{filename}', response_model=None)
    def download_source_binary_artifact(project: str, filename: str, format: str | None = Query(default=None), _auth: None = Depends(require_auth)) -> Response:
        try:
            path = source_binary_artifact_path(project, filename)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Binary artifact not found')
        if str(format or '').strip().lower() == 'zip':
            zip_name = f'{path.name}.zip'
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(path, arcname=path.name)
            buffer.seek(0)
            headers = {'Content-Disposition': f'attachment; filename="{zip_name}"'}
            return StreamingResponse(buffer, media_type='application/zip', headers=headers)
        return FileResponse(path, filename=path.name)

    @router.get('/v1/sources/binary-artifacts/{project}/{filename}/install.ps1', response_model=None)
    def download_source_binary_install_script(project: str, filename: str, request: Request, _auth: None = Depends(require_auth)) -> Response:
        try:
            path = source_binary_artifact_path(project, filename)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Binary artifact not found')
        if not path.name.lower().endswith('.exe'):
            raise HTTPException(status_code=400, detail='Install script is only available for Windows executable artifacts')
        base_url = str(request.base_url).rstrip('/')
        project = str(project).strip()
        filename = path.name
        zip_url = f'{base_url}/v1/sources/binary-artifacts/{project}/{filename}?format=zip'
        safe_filename = filename.replace("'", "''")
        script = f"""param(
    [string]$PacUrl = "{base_url}",
    [string]$Token = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\\PAC\\bin",
    [switch]$Insecure,
    [switch]$AddToUserPath
)

$ErrorActionPreference = "Stop"
$artifactName = '{safe_filename}'
$zipUrl = ($PacUrl.TrimEnd('/') + '/v1/sources/binary-artifacts/{project}/{filename}?format=zip')
$tmpRoot = Join-Path $env:TEMP ("pac-install-" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpRoot ($artifactName + ".zip")
$extractDir = Join-Path $tmpRoot "extract"

New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$headers = @()
if ($Token) {{
    $headers += @('-H', "Authorization: Bearer $Token")
}}
$curlArgs = @('-L', '-o', $zipPath)
if ($Insecure) {{
    $curlArgs += '-k'
}}
$curlArgs += $headers
$curlArgs += $zipUrl

& curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {{
    throw "Download failed for $zipUrl"
}}

Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
$sourceExe = Join-Path $extractDir $artifactName
if (-not (Test-Path -LiteralPath $sourceExe)) {{
    throw "Expected extracted file not found: $sourceExe"
}}
$targetExe = Join-Path $InstallDir $artifactName
Copy-Item -LiteralPath $sourceExe -Destination $targetExe -Force
try {{
    Unblock-File -LiteralPath $targetExe -ErrorAction SilentlyContinue
}} catch {{}}

if ($AddToUserPath) {{
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @($userPath -split ';' | Where-Object {{ $_ }})
    if ($parts -notcontains $InstallDir) {{
        $newPath = (($parts + $InstallDir) -join ';')
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Host "Added to user PATH: $InstallDir"
    }}
}}

Write-Host "Installed $artifactName to $targetExe"
Write-Host "ZIP source: $zipUrl"
"""
        headers = {'Content-Disposition': f'attachment; filename="{path.stem}-install.ps1"'}
        return Response(content=script, media_type='text/plain; charset=utf-8', headers=headers)

    @router.delete('/v1/sources/binary-artifacts/{project}/{filename}')
    def delete_source_binary_artifact(project: str, filename: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        try:
            result = source_delete_binary_artifact(project, filename)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Binary artifact not found')
        store.add_event(Event(session_id='system', type='source_binary_artifact_deleted', message=f'Binary artifact deleted: {project}/{filename}', data=result))
        return result

    @router.post('/v1/sources/binary-artifacts/prune')
    def prune_source_binary_artifacts(payload: dict[str, Any] | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        payload = payload or {}
        project = payload.get('project') or None
        keep_versions = int(payload.get('keep_versions') or 1)
        dry_run = bool(payload.get('dry_run') or False)
        result = source_prune_binary_artifacts(project=project, keep_versions=keep_versions, dry_run=dry_run)
        store.add_event(Event(session_id='system', type='source_binary_artifacts_pruned', message=f'Binary artifacts prune {"previewed" if dry_run else "completed"}: kept newest {keep_versions} version(s)', data={**result, 'project': project}))
        return result

    @router.get('/v1/sources/archive')
    def download_source_archive(_auth: None = Depends(require_auth)) -> FileResponse:
        archive = source_make_archive()
        return FileResponse(archive, filename='pac-sources.tar.gz')

    return router
