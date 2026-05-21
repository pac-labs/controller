from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from pi_agent_platform.core.models import AccessRequestStatus, Event, Group, ResourceGrant, User


def public_user(user: User) -> dict[str, Any]:
    grants = user.metadata.get('resource_grants') if isinstance(user.metadata, dict) else []
    return {
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'role': user.role,
        'groups': list(user.groups or []),
        'resource_grants': grants if isinstance(grants, list) else [],
        'created_at': user.created_at.isoformat(),
        'updated_at': user.updated_at.isoformat(),
        'metadata': user.metadata or {},
    }


def public_group(group: Group) -> dict[str, Any]:
    return {
        'id': group.id,
        'name': group.name,
        'description': group.description,
        'grants': [grant.model_dump() for grant in group.grants],
        'created_at': group.created_at.isoformat(),
        'updated_at': group.updated_at.isoformat(),
    }


def create_auth_router(
    *,
    require_auth: Callable[..., Any],
    require_admin: Callable[..., Any],
    config: Any,
    store: Any,
    ensure_auth_admin_scaffolding: Callable[[], None],
    resource_grants_from_user: Callable[[User | None], list[ResourceGrant]],
    resource_match: Callable[[ResourceGrant, str, str, str], bool],
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
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(hours=max(1, int(config.auth.token_ttl_hours or 720)))).isoformat()
        store.add_user_token(token, user.id, expires_at)
        store.add_event(Event(session_id='system', type='initial_setup', message=f'Initial admin user created: {username}', data={'username': username}))
        return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': public_user(user)}

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
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(hours=max(1, int(config.auth.token_ttl_hours or 720)))).isoformat()
        store.add_user_token(token, user.id, expires_at)
        store.add_event(Event(session_id='system', type='user_login', message=f'User login: {username}', data={'username': username}))
        return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': public_user(user)}

    @router.get('/v1/auth/me')
    def auth_me(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            return {'id': 'controller', 'username': 'controller', 'display_name': 'Controller', 'role': 'admin'}
        return public_user(_auth.user)

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
        return {'ok': True, 'user': public_user(user)}

    @router.get('/v1/users')
    def list_users(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        return [public_user(user) for user in store.list_users()]

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
            groups=[str(item).strip() for item in (payload.get('groups') or []) if str(item).strip()],
            metadata=payload.get('metadata') or {},
        )
        user.set_password(password)
        store.add_user(user)
        ensure_auth_admin_scaffolding()
        user = store.get_user(username) or user
        store.add_event(Event(session_id='system', type='user_created', message=f'User created: {username}', data={'username': username}))
        return {'ok': True, 'user': public_user(user)}

    @router.put('/v1/users/{user_id}')
    def update_user(user_id: str, payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        if 'display_name' in payload:
            user.display_name = str(payload.get('display_name') or user.username).strip() or user.username
        if 'role' in payload:
            user.role = str(payload.get('role') or user.role)
        if 'groups' in payload:
            user.groups = [str(item).strip() for item in (payload.get('groups') or []) if str(item).strip()]
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
        return {'ok': True, 'user': public_user(user)}

    @router.delete('/v1/users/{user_id}')
    def delete_user(user_id: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        if not store.delete_user(user_id):
            raise HTTPException(status_code=404, detail='User not found')
        store.add_event(Event(session_id='system', type='user_deleted', message=f'User deleted: {user_id}', data={'user_id': user_id}))
        return {'ok': True}

    @router.get('/v1/groups')
    def list_groups(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        return [public_group(group) for group in store.list_groups()]

    @router.post('/v1/groups')
    def create_group(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        group_id = str(payload.get('id') or payload.get('name') or '').strip()
        if not group_id:
            raise HTTPException(status_code=400, detail='group id required')
        if store.get_group(group_id):
            raise HTTPException(status_code=409, detail='Group already exists')
        grants = [ResourceGrant.model_validate(item) for item in (payload.get('grants') or [])]
        group = Group(id=group_id, name=str(payload.get('name') or group_id).strip() or group_id, description=str(payload.get('description') or '').strip() or None, grants=grants)
        store.add_group(group)
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
        for user in store.list_users():
            if group_id in (user.groups or []):
                user.groups = [item for item in (user.groups or []) if item != group_id]
                store.add_user(user)
        store.add_event(Event(session_id='system', type='group_deleted', message=f'Group deleted: {group_id}', data={'group_id': group_id}))
        return {'ok': True}

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
        grants = resource_grants_from_user(user)
        if not any(resource_match(grant, request.resource_type, request.resource_id, request.access) for grant in grants):
            grants.append(ResourceGrant(resource_type=request.resource_type, pattern=request.resource_id, access=request.access))
        metadata = dict(user.metadata or {})
        metadata['resource_grants'] = [grant.model_dump() for grant in grants]
        user.metadata = metadata
        store.add_user(user)
        request.status = AccessRequestStatus.approved
        request.resolved_at = datetime.utcnow()
        request.resolved_by = _auth.user.username if _auth.user else 'controller'
        store.add_access_request(request)
        store.add_event(Event(session_id='system', type='access_request_approved', message=f'Access approved: {request.username} -> {request.resource_type}:{request.resource_id}', data={'request_id': request.id, 'resolved_by': request.resolved_by}))
        return {'ok': True, 'request': request.model_dump(mode='json'), 'user': public_user(user)}

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

    @router.get('/v1/auth/tokens')
    def auth_tokens(_auth: Any = Depends(require_admin)) -> list[dict[str, Any]]:
        return store.list_user_tokens()

    @router.get('/v1/users/me/tokens')
    def current_user_tokens(_auth: Any = Depends(require_auth)) -> list[dict[str, Any]]:
        if not _auth.user:
            return []
        return [item for item in store.list_user_tokens() if item.get('user_id') == _auth.user.id]

    @router.post('/v1/users/me/tokens')
    def create_current_user_token(payload: dict[str, Any], _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not mint user tokens')
        ttl_hours = int(payload.get('ttl_hours') or config.auth.token_ttl_hours or 720)
        ttl_hours = max(1, min(ttl_hours, 24 * 365))
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
        store.add_user_token(token, _auth.user.id, expires_at)
        store.add_event(Event(session_id='system', type='token_created', message=f'Token minted for: {_auth.user.username}', data={'username': _auth.user.username, 'created_by': _auth.user.username}))
        return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': public_user(_auth.user)}

    @router.delete('/v1/users/me/tokens/{token}')
    def revoke_current_user_token(token: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        if not _auth.user:
            raise HTTPException(status_code=400, detail='Controller auth does not manage user tokens')
        matches = [item for item in store.list_user_tokens() if item.get('user_id') == _auth.user.id and item.get('token') == token]
        if not matches:
            raise HTTPException(status_code=404, detail='Token not found')
        store.delete_user_token(token)
        store.add_event(Event(session_id='system', type='token_revoked', message=f'Token revoked for: {_auth.user.username}', data={'username': _auth.user.username}))
        return {'ok': True, 'revoked': token}

    @router.post('/v1/auth/tokens')
    def create_auth_token(payload: dict[str, Any], _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        username = str(payload.get('username') or '').strip()
        ttl_hours = int(payload.get('ttl_hours') or config.auth.token_ttl_hours or 720)
        if not username:
            raise HTTPException(status_code=400, detail='username required')
        user = store.get_user_by_username(username)
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(hours=max(1, ttl_hours))).isoformat()
        store.add_user_token(token, user.id, expires_at)
        store.add_event(Event(session_id='system', type='token_created', message=f'Token minted for: {username}', data={'username': username, 'created_by': _auth.user.username if _auth.user else 'controller'}))
        return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': public_user(user)}

    @router.delete('/v1/auth/tokens/{token}')
    def revoke_auth_token(token: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        store.delete_user_token(token)
        return {'ok': True}

    return router
