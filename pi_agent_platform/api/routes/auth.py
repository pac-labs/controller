from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from pi_agent_platform.core.models import AccessRequestStatus, DirectoryMember, DirectoryPrincipal, Event, Group, ResourceGrant, User
from pi_agent_platform.core.directory import add_member_to_group, build_directory_tree, explain_principal_membership, normalize_group_id, public_principal, remove_member_from_group, resolve_effective_group_ids
from pi_agent_platform.core.access_control import can as access_can, effective_grants, explain_access, grant_to_principal, resource_match
from pi_agent_platform.core.credentials import new_certificate_credential, new_token_credential, public_credential, token_kind_for_principal
from pi_agent_platform.core.profiles import public_profile_payload


def public_user(user: User) -> dict[str, Any]:
    return {
        'id': user.id,
        'username': user.username,
        'name': user.username,
        'display_name': user.display_name or user.username,
        'role': user.role,
        'created_at': user.created_at.isoformat(),
        'updated_at': user.updated_at.isoformat(),
        'metadata': user.metadata or {},
    }


def public_group(group: Group) -> dict[str, Any]:
    return {
        'id': group.id,
        'name': group.name,
        'description': group.description,
        'members': [member.model_dump() for member in (group.members or [])],
        'grants': [grant.model_dump() for grant in group.grants],
        'source': group.source,
        'system_managed': group.system_managed,
        'created_at': group.created_at.isoformat(),
        'updated_at': group.updated_at.isoformat(),
    }


def _principal_from_user(store: Any, user: User) -> dict[str, Any]:
    payload = {
        'id': user.id,
        'kind': 'user',
        'name': user.username,
        'display_name': user.display_name or user.username,
        'description': None,
        'status': 'active',
        'source': 'local',
        'system_managed': False,
        'created_at': user.created_at.isoformat(),
        'updated_at': user.updated_at.isoformat(),
        'metadata': user.metadata or {},
    }
    payload['direct_groups'] = sorted(explain_principal_membership(store, user.id, 'user').get('direct_groups', []))
    payload['effective_groups'] = sorted(resolve_effective_group_ids(store, user.id, 'user'))
    return payload


def _principal_from_group(group: Group) -> dict[str, Any]:
    return {
        'id': group.id,
        'kind': 'group',
        'name': group.name,
        'display_name': group.name,
        'description': group.description,
        'status': 'active',
        'source': group.source,
        'system_managed': group.system_managed,
        'created_at': group.created_at.isoformat(),
        'updated_at': group.updated_at.isoformat(),
        'metadata': group.metadata or {},
    }


def _directory_principal_payloads(store: Any, kind: str | None = None) -> list[dict[str, Any]]:
    principals: list[dict[str, Any]] = []
    if kind in (None, 'user'):
        principals.extend(_principal_from_user(store, user) for user in store.list_users())
    if kind in (None, 'group'):
        principals.extend(_principal_from_group(group) for group in store.list_groups())
    if hasattr(store, 'list_directory_principals'):
        for principal in store.list_directory_principals(kind=None if kind in (None, 'user', 'group') else kind):
            if kind and principal.kind != kind:
                continue
            principals.append(public_principal(principal))
    return sorted(principals, key=lambda item: (item.get('kind') or '', item.get('name') or item.get('id') or ''))


def _principal_payload(store: Any, principal_id: str, principal_kind: str) -> dict[str, Any]:
    if principal_kind == 'user':
        user = store.get_user(principal_id)
        if user:
            return _principal_from_user(store, user)
    if principal_kind == 'group':
        group = store.get_group(normalize_group_id(principal_id))
        if group:
            return _principal_from_group(group)
    if hasattr(store, 'get_directory_principal'):
        principal = store.get_directory_principal(principal_id)
        if principal:
            return public_principal(principal)
    return {'id': principal_id, 'kind': principal_kind, 'name': principal_id, 'display_name': principal_id}


def _principal_exists(store: Any, kind: str, principal_id: str) -> bool:
    if kind == 'user':
        return store.get_user(principal_id) is not None
    if kind == 'group':
        return store.get_group(normalize_group_id(principal_id)) is not None
    if hasattr(store, 'get_directory_principal'):
        principal = store.get_directory_principal(principal_id)
        return principal is not None and principal.kind == kind
    return False


def _resolve_principal_kind(store: Any, principal_id: str) -> str | None:
    if store.get_user(principal_id):
        return 'user'
    if store.get_group(normalize_group_id(principal_id)):
        return 'group'
    if hasattr(store, 'get_directory_principal'):
        principal = store.get_directory_principal(principal_id)
        if principal:
            return principal.kind
    return None


def _ensure_credential_principal(store: Any, principal_id: str) -> str:
    principal_kind = _resolve_principal_kind(store, principal_id)
    if not principal_kind:
        raise HTTPException(status_code=404, detail='Directory principal not found')
    if principal_kind == 'group':
        raise HTTPException(status_code=400, detail='Groups cannot authenticate directly; create a user or service account principal')
    return principal_kind


def _principal_subject(principal_id: str, principal_kind: str) -> Any:
    return SimpleNamespace(principal_id=principal_id, principal_kind=principal_kind, user=None, is_admin=False)


def _directory_effective_access_payload(store: Any, subject: Any) -> dict[str, Any]:
    return {
        'principal_id': getattr(subject, 'principal_id', None) or getattr(getattr(subject, 'user', None), 'id', None),
        'principal_kind': getattr(subject, 'principal_kind', None) or ('user' if getattr(subject, 'user', None) else 'controller'),
        'explain': explain_access(store, subject),
        'grants': [grant.model_dump() for grant in effective_grants(store, subject)],
    }


def _directory_available_resources(store: Any, config: Any, subject: Any) -> dict[str, Any]:
    profile_items = []
    for name, profile in (getattr(config, 'agent_profiles', None) or {}).items():
        try:
            profile_items.append(public_profile_payload(name, profile, subject, store=store))
        except Exception:
            if access_can(store, subject, 'profile', name, 'use', allow_unrestricted=True):
                profile_items.append({'name': name, 'display_name': name, 'can_use': True})
    workspaces = []
    principal_id = str(getattr(subject, 'principal_id', '') or getattr(getattr(subject, 'user', None), 'id', '') or '')
    for item in getattr(store, 'list_user_workspaces', lambda: [])():
        if access_can(store, subject, 'workspace', f'user:{item.id}', 'read', owner_id=getattr(item, 'owner_id', None)):
            workspaces.append({'id': item.id, 'name': item.name, 'owner_id': item.owner_id, 'owner_username': item.owner_username})
    contexts = []
    for item in getattr(store, 'list_agent_contexts', lambda: [])():
        if access_can(store, subject, 'agent_context', item.id, 'use', owner_id=item.owner_id, allowed_groups=item.use_groups, allow_unrestricted=not item.use_groups):
            contexts.append({'id': item.id, 'name': item.name, 'kind': item.kind, 'owner_id': item.owner_id, 'owner_username': item.owner_username})
    source_contexts = []
    for name, ctx in (getattr(config, 'source_contexts', None) or {}).items():
        if access_can(store, subject, 'source_context', name, 'read', allow_unrestricted=True):
            source_contexts.append({'id': name, 'name': name, 'type': getattr(ctx, 'type', None), 'path': getattr(ctx, 'path', None)})
    return {'profiles': profile_items, 'workspaces': workspaces, 'contexts': contexts, 'source_contexts': source_contexts}


def _replace_user_group_memberships(store: Any, user: User, group_ids: list[str]) -> None:
    wanted = {normalize_group_id(item) for item in group_ids if str(item).strip()}
    for group_id in sorted(wanted):
        if not store.get_group(group_id):
            store.add_group(Group(id=group_id, name=group_id))
    for group in store.list_groups():
        has_user = any(member.kind == 'user' and member.id == user.id for member in (group.members or []))
        should_have_user = group.id in wanted
        if has_user and not should_have_user:
            group.members = [member for member in (group.members or []) if not (member.kind == 'user' and member.id == user.id)]
            store.add_group(group)
        elif should_have_user and not has_user:
            group.members.append(DirectoryMember(kind='user', id=user.id))
            store.add_group(group)


def _public_user_with_directory(store: Any, user: User) -> dict[str, Any]:
    payload = public_user(user)
    effective = sorted(resolve_effective_group_ids(store, user.id, 'user'))
    payload['direct_groups'] = sorted(explain_principal_membership(store, user.id, 'user').get('direct_groups', []))
    payload['effective_groups'] = effective
    return payload


def create_auth_router(
    *,
    require_auth: Callable[..., Any],
    require_admin: Callable[..., Any],
    config: Any,
    store: Any,
    ensure_auth_admin_scaffolding: Callable[[], None],
) -> APIRouter:
    router = APIRouter()

    @router.get('/v1/auth/status')
    def auth_status() -> dict[str, Any]:
        ensure_auth_admin_scaffolding()
        user_count = len(store.list_users())
        return {
            'enabled': config.auth.enabled,
            'mode': config.auth.mode,
            'needs_setup': config.auth.mode == 'user-password' and user_count == 0,
            'user_count': user_count,
            'group_count': len(store.list_groups()),
            'pending_access_requests': len(store.list_access_requests(status='pending')),
            'token_ttl_hours': config.auth.token_ttl_hours,
        }

    @router.post('/v1/auth/setup')
    def auth_setup(payload: dict[str, Any]) -> dict[str, Any]:
        if config.auth.mode != 'user-password':
            raise HTTPException(status_code=400, detail='User-password auth not enabled')
        if store.list_users():
            raise HTTPException(status_code=403, detail='System already has users. Use /v1/auth/login.')
        username = str(payload.get('username') or '').strip()
        password = str(payload.get('password') or '')
        display_name = str(payload.get('display_name') or username).strip() or username
        if not username or not password:
            raise HTTPException(status_code=400, detail='username and password required')
        if len(password) < 8:
            raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
        user = User(id=username, username=username, display_name=display_name, role='admin')
        user.set_password(password)
        store.add_user(user)
        ensure_auth_admin_scaffolding()
        user = store.get_user(username) or user
        credential, token = new_token_credential(user.id, name='Initial setup token', ttl_hours=max(1, int(config.auth.token_ttl_hours or 720)), kind='api_token', metadata={'created_by': 'initial_setup'})
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='initial_setup', message=f'Initial admin user created: {username}', data={'username': username}))
        return {'ok': True, 'token': token, 'expires_at': credential.expires_at.isoformat() if credential.expires_at else None, 'credential': public_credential(credential), 'user': _public_user_with_directory(store, user)}

    @router.post('/v1/auth/login')
    def auth_login(payload: dict[str, Any]) -> dict[str, Any]:
        if config.auth.mode != 'user-password':
            raise HTTPException(status_code=400, detail='User-password auth not enabled')
        username = str(payload.get('username') or '').strip()
        password = str(payload.get('password') or '')
        if not username or not password:
            raise HTTPException(status_code=400, detail='username and password required')
        user = store.get_user_by_username(username)
        if not user or not user.verify_password(password):
            raise HTTPException(status_code=401, detail='Invalid credentials')
        credential, token = new_token_credential(user.id, name='Login token', ttl_hours=max(1, int(config.auth.token_ttl_hours or 720)), kind='api_token', metadata={'created_by': 'login'})
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='user_login', message=f'User login: {username}', data={'username': username, 'credential_id': credential.id}))
        return {'ok': True, 'token': token, 'expires_at': credential.expires_at.isoformat() if credential.expires_at else None, 'credential': public_credential(credential), 'user': _public_user_with_directory(store, user)}

    @router.get('/v1/auth/me')
    def auth_me(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            return {'id': 'controller', 'username': 'controller', 'display_name': 'Controller', 'role': 'admin'}
        return _public_user_with_directory(store, _auth.user)

    @router.get('/v1/users/me')
    def users_me(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return auth_me(_auth)

    @router.put('/v1/users/me')
    def update_users_me(payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            return {'ok': True, 'user': auth_me(_auth)}
        user = _auth.user
        if 'display_name' in payload:
            user.display_name = str(payload.get('display_name') or '').strip() or user.username
        metadata = dict(user.metadata or {})
        if 'email' in payload:
            email = str(payload.get('email') or '').strip()
            if email:
                metadata['email'] = email
            else:
                metadata.pop('email', None)
        if 'preferences' in payload:
            prefs = payload.get('preferences')
            metadata['preferences'] = prefs if isinstance(prefs, dict) else {}
        user.metadata = metadata
        store.add_user(user)
        store.add_event(Event(session_id='system', type='user_profile_updated', message=f'User profile updated: {user.username}', data={'user_id': user.id}))
        return {'ok': True, 'user': _public_user_with_directory(store, user)}

    @router.get('/v1/users')
    def list_users(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        return [_public_user_with_directory(store, user) for user in store.list_users()]

    @router.post('/v1/users')
    def create_user(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        username = str(payload.get('username') or payload.get('id') or '').strip()
        password = str(payload.get('password') or '')
        if not username:
            raise HTTPException(status_code=400, detail='username required')
        if not password:
            raise HTTPException(status_code=400, detail='password required')
        if len(password) < 8:
            raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
        if store.get_user_by_username(username):
            raise HTTPException(status_code=409, detail='User already exists')
        user = User(
            id=username,
            username=username,
            display_name=str(payload.get('display_name') or username).strip() or username,
            role=str(payload.get('role') or 'user'),
            metadata=payload.get('metadata') or {},
        )
        user.set_password(password)
        store.add_user(user)
        ensure_auth_admin_scaffolding()
        user = store.get_user(username) or user
        store.add_event(Event(session_id='system', type='user_created', message=f'User created: {username}', data={'username': username}))
        return {'ok': True, 'user': _public_user_with_directory(store, user)}

    @router.put('/v1/users/{user_id}')
    def update_user(user_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        if 'display_name' in payload:
            user.display_name = str(payload.get('display_name') or user.username).strip() or user.username
        if 'role' in payload:
            user.role = str(payload.get('role') or user.role)
        if 'metadata' in payload and isinstance(payload.get('metadata'), dict):
            user.metadata = payload.get('metadata') or {}
        if payload.get('password'):
            password = str(payload.get('password') or '')
            if len(password) < 8:
                raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
            user.set_password(password)
        store.add_user(user)
        ensure_auth_admin_scaffolding()
        user = store.get_user(user_id) or user
        store.add_event(Event(session_id='system', type='user_updated', message=f'User updated: {user.username}', data={'username': user.username}))
        return {'ok': True, 'user': _public_user_with_directory(store, user)}

    @router.delete('/v1/users/{user_id}')
    def delete_user(user_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        for group in store.list_groups():
            if any(member.kind == 'user' and member.id == user_id for member in (group.members or [])):
                group.members = [member for member in (group.members or []) if not (member.kind == 'user' and member.id == user_id)]
                store.add_group(group)
        if not store.delete_user(user_id):
            raise HTTPException(status_code=404, detail='User not found')
        store.add_event(Event(session_id='system', type='user_deleted', message=f'User deleted: {user_id}', data={'user_id': user_id}))
        return {'ok': True}

    @router.get('/v1/groups')
    def list_groups(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        return [public_group(group) for group in store.list_groups()]

    @router.post('/v1/groups')
    def create_group(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        raw_group_id = str(payload.get('id') or payload.get('name') or '').strip()
        group_id = normalize_group_id(raw_group_id)
        if not group_id:
            raise HTTPException(status_code=400, detail='group id required')
        if store.get_group(group_id):
            raise HTTPException(status_code=409, detail='Group already exists')
        grants = [ResourceGrant.model_validate(item) for item in (payload.get('grants') or [])]
        group = Group(id=group_id, name=str(payload.get('name') or raw_group_id).strip() or group_id, description=str(payload.get('description') or '').strip() or None, members=[], grants=grants, source=str(payload.get('source') or 'local'), system_managed=bool(payload.get('system_managed') or False))
        store.add_group(group)
        for item in (payload.get('members') or []):
            member = DirectoryMember.model_validate(item)
            if not _principal_exists(store, member.kind, member.id):
                raise HTTPException(status_code=400, detail=f'Directory principal not found: {member.kind}:{member.id}')
            group = add_member_to_group(store, group.id, member)
        store.add_event(Event(session_id='system', type='group_created', message=f'Group created: {group_id}', data={'group_id': group_id}))
        return {'ok': True, 'group': public_group(group)}

    @router.put('/v1/groups/{group_id}')
    def update_group(group_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        group = store.get_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail='Group not found')
        if 'name' in payload:
            group.name = str(payload.get('name') or group.name).strip() or group.id
        if 'description' in payload:
            group.description = str(payload.get('description') or '').strip() or None
        if 'grants' in payload:
            group.grants = [ResourceGrant.model_validate(item) for item in (payload.get('grants') or [])]
        store.add_group(group)
        store.add_event(Event(session_id='system', type='group_updated', message=f'Group updated: {group_id}', data={'group_id': group_id}))
        return {'ok': True, 'group': public_group(group)}

    @router.delete('/v1/groups/{group_id}')
    def delete_group(group_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        if not store.delete_group(group_id):
            raise HTTPException(status_code=404, detail='Group not found')
        for group in store.list_groups():
            if any(member.kind == 'group' and member.id == group_id for member in (group.members or [])):
                group.members = [member for member in (group.members or []) if not (member.kind == 'group' and member.id == group_id)]
                store.add_group(group)
        store.add_event(Event(session_id='system', type='group_deleted', message=f'Group deleted: {group_id}', data={'group_id': group_id}))
        return {'ok': True}


    @router.get('/v1/directory/principals')
    def directory_principals(kind: str | None = Query(default=None), _auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        allowed = {None, 'user', 'group', 'service_account', 'endpoint', 'provider', 'certificate_identity'}
        if kind not in allowed:
            raise HTTPException(status_code=400, detail='Unsupported principal kind')
        return _directory_principal_payloads(store, kind=kind)

    @router.get('/v1/directory/groups')
    def directory_groups(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        return [public_group(group) for group in store.list_groups()]

    @router.post('/v1/directory/users')
    def directory_create_user(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        username = str(payload.get('username') or payload.get('id') or '').strip()
        password = str(payload.get('password') or '')
        if not username:
            raise HTTPException(status_code=400, detail='username required')
        if not password:
            raise HTTPException(status_code=400, detail='password required')
        if len(password) < 8:
            raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
        if store.get_user_by_username(username):
            raise HTTPException(status_code=409, detail='User already exists')
        user = User(
            id=username,
            username=username,
            display_name=str(payload.get('display_name') or username).strip() or username,
            role=str(payload.get('role') or 'user'),
            metadata=payload.get('metadata') or {},
        )
        user.set_password(password)
        store.add_user(user)
        for group_id in [str(item).strip() for item in (payload.get('group_ids') or []) if str(item).strip()]:
            target_group_id = normalize_group_id(group_id)
            if not store.get_group(target_group_id):
                store.add_group(Group(id=target_group_id, name=target_group_id, source='local'))
            add_member_to_group(store, target_group_id, DirectoryMember(kind='user', id=user.id))
        ensure_auth_admin_scaffolding()
        user = store.get_user(username) or user
        store.add_event(Event(session_id='system', type='directory_user_created', message=f'Directory user created: {username}', data={'username': username}))
        return {'ok': True, 'principal': _principal_from_user(store, user), 'user': _public_user_with_directory(store, user)}

    @router.post('/v1/directory/groups')
    def directory_create_group(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        raw_group_id = str(payload.get('id') or payload.get('name') or '').strip()
        group_id = normalize_group_id(raw_group_id)
        if not group_id:
            raise HTTPException(status_code=400, detail='group id required')
        if store.get_group(group_id):
            raise HTTPException(status_code=409, detail='Group already exists')
        grants = [ResourceGrant.model_validate(item) for item in (payload.get('grants') or [])]
        group = Group(
            id=group_id,
            name=str(payload.get('name') or raw_group_id or group_id).strip() or group_id,
            description=str(payload.get('description') or '').strip() or None,
            members=[],
            grants=grants,
            source=str(payload.get('source') or 'local'),
            system_managed=bool(payload.get('system_managed') or False),
            metadata=payload.get('metadata') or {},
        )
        store.add_group(group)
        for item in (payload.get('members') or []):
            member = DirectoryMember.model_validate(item)
            if not _principal_exists(store, member.kind, member.id):
                raise HTTPException(status_code=400, detail=f'Directory principal not found: {member.kind}:{member.id}')
            group = add_member_to_group(store, group.id, member)
        store.add_event(Event(session_id='system', type='directory_group_created', message=f'Directory group created: {group.id}', data={'group_id': group.id}))
        return {'ok': True, 'principal': _principal_from_group(group), 'group': public_group(group)}


    @router.put('/v1/directory/groups/{group_id}')
    def directory_update_group(group_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        group = store.get_group(normalize_group_id(group_id))
        if not group:
            raise HTTPException(status_code=404, detail='Group not found')
        if 'name' in payload:
            group.name = str(payload.get('name') or group.name).strip() or group.id
        if 'description' in payload:
            group.description = str(payload.get('description') or '').strip() or None
        if 'grants' in payload:
            group.grants = [ResourceGrant.model_validate(item) for item in (payload.get('grants') or [])]
        store.add_group(group)
        store.add_event(Event(session_id='system', type='directory_group_updated', message=f'Directory group updated: {group.id}', data={'group_id': group.id}))
        return {'ok': True, 'principal': _principal_from_group(group), 'group': public_group(group)}

    @router.delete('/v1/directory/groups/{group_id}')
    def directory_delete_group(group_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        normalized_id = normalize_group_id(group_id)
        if normalized_id == 'pacadm:admins':
            raise HTTPException(status_code=400, detail='The PAC admin group cannot be deleted')
        if not store.delete_group(normalized_id):
            raise HTTPException(status_code=404, detail='Group not found')
        for parent in store.list_groups():
            if any(member.kind == 'group' and member.id == normalized_id for member in (parent.members or [])):
                parent.members = [member for member in (parent.members or []) if not (member.kind == 'group' and member.id == normalized_id)]
                store.add_group(parent)
        store.add_event(Event(session_id='system', type='directory_group_deleted', message=f'Directory group deleted: {normalized_id}', data={'group_id': normalized_id}))
        return {'ok': True}

    @router.post('/v1/directory/service-accounts')
    def directory_create_service_account(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        raw_name = str(payload.get('name') or payload.get('id') or '').strip()
        if not raw_name:
            raise HTTPException(status_code=400, detail='name required')
        principal_id = str(payload.get('id') or '').strip() or 'sa_' + ''.join(ch.lower() if ch.isalnum() else '-' for ch in raw_name).strip('-')
        if not principal_id:
            principal_id = f'sa_{uuid.uuid4().hex[:12]}'
        if store.get_user(principal_id) or store.get_group(principal_id) or (hasattr(store, 'get_directory_principal') and store.get_directory_principal(principal_id)):
            raise HTTPException(status_code=409, detail='Principal already exists')
        principal = DirectoryPrincipal(
            id=principal_id,
            kind='service_account',
            name=raw_name,
            display_name=str(payload.get('display_name') or raw_name).strip() or raw_name,
            description=str(payload.get('description') or '').strip() or None,
            status=str(payload.get('status') or 'active'),
            source=str(payload.get('source') or 'local'),
            metadata=payload.get('metadata') or {},
        )
        store.add_directory_principal(principal)
        for group_id in [str(item).strip() for item in (payload.get('group_ids') or []) if str(item).strip()]:
            target_group_id = normalize_group_id(group_id)
            if not store.get_group(target_group_id):
                store.add_group(Group(id=target_group_id, name=target_group_id, source='local'))
            add_member_to_group(store, target_group_id, DirectoryMember(kind='service_account', id=principal.id))
        store.add_event(Event(session_id='system', type='directory_service_account_created', message=f'Service account created: {principal.name}', data={'principal_id': principal.id}))
        return {'ok': True, 'principal': public_principal(principal)}

    @router.get('/v1/directory/tree')
    def directory_tree(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return build_directory_tree(store)

    @router.get('/v1/directory/users/{user_id}/effective-access')
    def directory_user_effective_access(user_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        return explain_access(store, user)

    @router.get('/v1/directory/users/{user_id}/membership')
    def directory_user_membership(user_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not store.get_user(user_id):
            raise HTTPException(status_code=404, detail='User not found')
        return explain_principal_membership(store, user_id, 'user')

    @router.get('/v1/directory/groups/{group_id}/effective-access')
    def directory_group_effective_access(group_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        group = store.get_group(normalize_group_id(group_id))
        if not group:
            raise HTTPException(status_code=404, detail='Group not found')
        return {'group': public_group(group), 'grants': [grant.model_dump() for grant in (group.grants or [])]}


    @router.get('/v1/directory/principals/{principal_id}/effective-access')
    def directory_principal_effective_access(principal_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        principal_kind = _resolve_principal_kind(store, principal_id)
        if not principal_kind:
            raise HTTPException(status_code=404, detail='Directory principal not found')
        subject = _principal_subject(principal_id, principal_kind)
        payload = _directory_effective_access_payload(store, subject)
        payload['principal'] = _principal_payload(store, principal_id, principal_kind)
        payload['membership'] = explain_principal_membership(store, principal_id, principal_kind)
        payload['available'] = _directory_available_resources(store, config, subject)
        return payload

    @router.post('/v1/directory/groups/{group_id}/members')
    def directory_add_group_member(group_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        try:
            member = DirectoryMember.model_validate(payload)
            if not _principal_exists(store, member.kind, member.id):
                raise ValueError(f'Directory principal not found: {member.kind}:{member.id}')
            group = add_member_to_group(store, group_id, member)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='directory_member_added', message=f'Directory member added to {group.id}', data={'group_id': group.id, 'member': payload}))
        return {'ok': True, 'group': public_group(group)}

    @router.delete('/v1/directory/groups/{group_id}/members/{kind}/{member_id}')
    def directory_remove_group_member(group_id: str, kind: str, member_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        try:
            group = remove_member_from_group(store, group_id, kind, member_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        store.add_event(Event(session_id='system', type='directory_member_removed', message=f'Directory member removed from {group.id}', data={'group_id': group.id, 'kind': kind, 'member_id': member_id}))
        return {'ok': True, 'group': public_group(group)}

    @router.get('/v1/directory/principals/{principal_id}/credentials')
    def directory_principal_credentials(principal_id: str, _auth: Any = Depends(require_admin)) -> list[dict[str, Any]]:
        _ensure_credential_principal(store, principal_id)
        return [public_credential(item) for item in store.list_directory_credentials(principal_id=principal_id)]

    @router.post('/v1/directory/principals/{principal_id}/tokens')
    def directory_create_principal_token(principal_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        principal_kind = _ensure_credential_principal(store, principal_id)
        ttl_hours = payload.get('ttl_hours', config.auth.token_ttl_hours or 720)
        ttl_int = max(1, min(int(ttl_hours), 24 * 365 * 5))
        credential, token = new_token_credential(
            principal_id,
            name=str(payload.get('name') or 'API token').strip() or 'API token',
            ttl_hours=ttl_int,
            kind=token_kind_for_principal(principal_kind),
            metadata={
                **(payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}),
                'principal_kind': principal_kind,
                'created_by': _auth.principal_id if hasattr(_auth, 'principal_id') else None,
            },
        )
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='directory_token_created', message=f'Directory token created for {principal_id}', data={'principal_id': principal_id, 'principal_kind': principal_kind, 'credential_id': credential.id}))
        return {'ok': True, 'token': token, 'credential': public_credential(credential), 'expires_at': credential.expires_at.isoformat() if credential.expires_at else None}

    @router.post('/v1/directory/principals/{principal_id}/certificates')
    def directory_create_principal_certificate(principal_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        principal_kind = _ensure_credential_principal(store, principal_id)
        try:
            credential = new_certificate_credential(
                principal_id,
                name=str(payload.get('name') or 'Certificate').strip() or 'Certificate',
                certificate_pem=str(payload.get('certificate_pem') or '').strip() or None,
                fingerprint=str(payload.get('fingerprint') or '').strip() or None,
                metadata={
                    **(payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}),
                    'principal_kind': principal_kind,
                    'created_by': _auth.principal_id if hasattr(_auth, 'principal_id') else None,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='directory_certificate_created', message=f'Directory certificate registered for {principal_id}', data={'principal_id': principal_id, 'principal_kind': principal_kind, 'credential_id': credential.id, 'fingerprint': credential.fingerprint}))
        return {'ok': True, 'credential': public_credential(credential)}

    @router.delete('/v1/directory/credentials/{credential_id}')
    def directory_delete_credential(credential_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        credential = store.get_directory_credential(credential_id)
        if not credential:
            raise HTTPException(status_code=404, detail='Credential not found')
        credential.status = 'revoked'
        store.add_directory_credential(credential)
        store.delete_directory_credential(credential_id)
        store.add_event(Event(session_id='system', type='directory_credential_revoked', message=f'Directory credential revoked: {credential_id}', data={'credential_id': credential_id, 'principal_id': credential.principal_id, 'kind': credential.kind}))
        return {'ok': True, 'revoked': credential_id}

    @router.get('/v1/access-requests')
    def list_access_requests(status: str = Query(default='pending'), _auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        items = store.list_access_requests(status=status or None)
        return [item.model_dump(mode='json') for item in items]

    @router.post('/v1/access-requests/{request_id}/approve')
    def approve_access_request(request_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        request = store.get_access_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail='Access request not found')
        if request.status != AccessRequestStatus.pending:
            return {'ok': True, 'request': request.model_dump(mode='json')}
        user = store.get_user(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        grant = ResourceGrant(resource_type=request.resource_type, pattern=request.resource_id, access=request.access)
        grant_group = grant_to_principal(store, 'user', user.id, grant)
        request.status = AccessRequestStatus.approved
        request.resolved_at = datetime.utcnow()
        request.resolved_by = _auth.user.username if _auth.user else 'controller'
        store.add_access_request(request)
        store.add_event(Event(session_id='system', type='access_request_approved', message=f'Access approved: {request.username} -> {request.resource_type}:{request.resource_id}', data={'request_id': request.id, 'resolved_by': request.resolved_by}))
        return {'ok': True, 'request': request.model_dump(mode='json'), 'grant_group': public_group(grant_group), 'user': _public_user_with_directory(store, user)}

    @router.post('/v1/access-requests/{request_id}/reject')
    def reject_access_request(request_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        request = store.get_access_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail='Access request not found')
        request.status = AccessRequestStatus.rejected
        request.resolved_at = datetime.utcnow()
        request.resolved_by = _auth.user.username if _auth.user else 'controller'
        store.add_access_request(request)
        store.add_event(Event(session_id='system', type='access_request_rejected', message=f'Access rejected: {request.username} -> {request.resource_type}:{request.resource_id}', data={'request_id': request.id, 'resolved_by': request.resolved_by}))
        return {'ok': True, 'request': request.model_dump(mode='json')}

    @router.get('/v1/users/me/access')
    def current_user_access(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not getattr(_auth, 'principal_id', None) or _auth.principal_id == 'controller':
            return {'principal': {'id': 'controller', 'kind': 'controller', 'name': 'Controller'}, 'membership': {'direct_groups': [], 'effective_groups': []}, 'available': _directory_available_resources(store, config, _auth), 'credentials': [], 'access_requests': []}
        principal_kind = str(getattr(_auth, 'principal_kind', '') or ('user' if _auth.user else 'service_account'))
        principal_payload = _principal_from_user(store, _auth.user) if _auth.user else _principal_payload(store, _auth.principal_id, principal_kind)
        own_requests = []
        if _auth.user:
            own_requests = [item.model_dump(mode='json') for item in store.list_access_requests(status=None) if item.user_id == _auth.user.id]
        return {
            'principal': principal_payload,
            'membership': explain_principal_membership(store, _auth.principal_id, principal_kind),
            'access': _directory_effective_access_payload(store, _auth),
            'available': _directory_available_resources(store, config, _auth),
            'credentials': [public_credential(item) for item in store.list_directory_credentials(principal_id=_auth.principal_id)],
            'access_requests': own_requests,
            'rule': {'token_question': 'Who are you?', 'directory_question': 'What are you allowed to do?'},
        }

    @router.get('/v1/auth/tokens')
    def auth_tokens(_auth: Any = Depends(require_admin)) -> list[dict[str, Any]]:
        return [public_credential(item) for item in store.list_directory_credentials()]

    @router.get('/v1/users/me/tokens')
    def current_user_tokens(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        if not getattr(_auth, 'principal_id', None) or _auth.principal_id == 'controller':
            return []
        return [public_credential(item) for item in store.list_directory_credentials(principal_id=_auth.principal_id)]

    @router.post('/v1/users/me/tokens')
    def create_current_user_token(payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not mint user tokens')
        ttl_hours = int(payload.get('ttl_hours') or config.auth.token_ttl_hours or 720)
        ttl_hours = max(1, min(ttl_hours, 24 * 365))
        credential, token = new_token_credential(_auth.user.id, name=str(payload.get('name') or 'User token').strip() or 'User token', ttl_hours=ttl_hours, kind='api_token', metadata={'created_by': _auth.user.username})
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='directory_token_created', message=f'Token minted for: {_auth.user.username}', data={'username': _auth.user.username, 'created_by': _auth.user.username, 'credential_id': credential.id}))
        return {'ok': True, 'token': token, 'expires_at': credential.expires_at.isoformat() if credential.expires_at else None, 'credential': public_credential(credential), 'user': _public_user_with_directory(store, _auth.user)}

    @router.delete('/v1/users/me/tokens/{token}')
    def revoke_current_user_token(token: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not manage user tokens')
        credential = store.get_directory_credential(token)
        if not credential or credential.principal_id != _auth.user.id:
            raise HTTPException(status_code=404, detail='Token not found')
        store.delete_directory_credential(credential.id)
        store.add_event(Event(session_id='system', type='directory_credential_revoked', message=f'Token revoked for: {_auth.user.username}', data={'username': _auth.user.username, 'credential_id': credential.id}))
        return {'ok': True, 'revoked': credential.id}

    @router.post('/v1/auth/tokens')
    def create_auth_token(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        username = str(payload.get('username') or '').strip()
        ttl_hours = int(payload.get('ttl_hours') or config.auth.token_ttl_hours or 720)
        if not username:
            raise HTTPException(status_code=400, detail='username required')
        user = store.get_user_by_username(username)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        credential, token = new_token_credential(user.id, name=str(payload.get('name') or 'Admin-created token').strip() or 'Admin-created token', ttl_hours=max(1, ttl_hours), kind='api_token', metadata={'created_by': _auth.principal_id if hasattr(_auth, 'principal_id') else 'controller'})
        store.add_directory_credential(credential)
        store.add_event(Event(session_id='system', type='directory_token_created', message=f'Token minted for: {username}', data={'username': username, 'created_by': _auth.user.username if _auth.user else 'controller', 'credential_id': credential.id}))
        return {'ok': True, 'token': token, 'expires_at': credential.expires_at.isoformat() if credential.expires_at else None, 'credential': public_credential(credential), 'user': _public_user_with_directory(store, user)}

    @router.delete('/v1/auth/tokens/{credential_id}')
    def revoke_auth_token(credential_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        if not store.delete_directory_credential(credential_id):
            raise HTTPException(status_code=404, detail='Credential not found')
        return {'ok': True, 'revoked': credential_id}

    return router
