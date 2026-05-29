from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from pi_agent_platform.core.config import AppConfig, ProxyRoute
from pi_agent_platform.core.credentials import credential_expired, hash_token_secret
from pi_agent_platform.core.models import Event


def create_proxy_router(
    *,
    require_auth: Callable[..., Any],
    get_config: Callable[[], AppConfig],
    save_config: Callable[[AppConfig], None],
    store: Any,
    bearer_token: Callable[[str], str | None],
) -> APIRouter:
    router = APIRouter()

    @router.get('/v1/proxy-routes')
    def list_proxy_routes(_auth: None = Depends(require_auth)) -> list[dict[str, Any]]:
        config = get_config()
        return [{'name': name, **route.model_dump()} for name, route in config.proxy_routes.items()]

    @router.post('/v1/proxy-routes')
    def create_proxy_route(payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        name = str(payload.get('name') or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail='name is required')
        if name in config.proxy_routes:
            raise HTTPException(status_code=409, detail='Route already exists')
        route = ProxyRoute(
            target=str(payload.get('target') or '').strip(),
            allowed=[str(a).strip() for a in (payload.get('allowed') or []) if str(a).strip()],
            description=str(payload.get('description') or '').strip(),
        )
        config.proxy_routes[name] = route
        save_config(config)
        store.add_event(Event(session_id='system', type='proxy_route_created', message=f'Proxy route created: {name}', data={'name': name, 'target': route.target}))
        return {'ok': True, 'name': name, **route.model_dump()}

    @router.get('/v1/proxy-routes/{route_name}')
    def get_proxy_route(route_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        route = get_config().proxy_routes.get(route_name)
        if not route:
            raise HTTPException(status_code=404, detail='Route not found')
        return {'name': route_name, **route.model_dump()}

    @router.put('/v1/proxy-routes/{route_name}')
    def update_proxy_route(route_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        if route_name not in config.proxy_routes:
            raise HTTPException(status_code=404, detail='Route not found')
        route = config.proxy_routes[route_name]
        if 'target' in payload:
            route.target = str(payload['target']).strip()
        if 'allowed' in payload:
            route.allowed = [str(a).strip() for a in payload['allowed'] if str(a).strip()]
        if 'description' in payload:
            route.description = str(payload['description']).strip()
        save_config(config)
        store.add_event(Event(session_id='system', type='proxy_route_updated', message=f'Proxy route updated: {route_name}', data={'name': route_name}))
        return {'ok': True, 'name': route_name, **route.model_dump()}

    @router.delete('/v1/proxy-routes/{route_name}')
    def delete_proxy_route(route_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        if route_name not in config.proxy_routes:
            raise HTTPException(status_code=404, detail='Route not found')
        del config.proxy_routes[route_name]
        save_config(config)
        store.add_event(Event(session_id='system', type='proxy_route_deleted', message=f'Proxy route deleted: {route_name}'))
        return {'ok': True, 'deleted': route_name}

    @router.post('/v1/proxy-routes/{route_name}/test')
    def test_proxy_route(route_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        route = get_config().proxy_routes.get(route_name)
        if not route:
            raise HTTPException(status_code=404, detail='Route not found')
        target_url = route.target.rstrip('/') + '/'
        headers = {"User-Agent": "PAC-ProxyRoute/1.0"}
        try:
            req = urllib.request.Request(target_url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode(errors='replace')[:2000]
                return {'ok': True, 'route': route_name, 'target': route.target, 'status': resp.status, 'reachable': True, 'body': body[:500]}
        except urllib.error.HTTPError as exc:
            return {'ok': True, 'route': route_name, 'target': route.target, 'status': exc.code, 'reachable': True, 'error': str(exc)}
        except Exception as exc:
            return {'ok': True, 'route': route_name, 'target': route.target, 'reachable': False, 'error': str(exc)}

    @router.api_route('/v1/proxy/{route_name}/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
    def reverse_proxy(route_name: str, path: str, request: Request, _auth: None = Depends(require_auth)) -> Response:
        route = get_config().proxy_routes.get(route_name)
        if not route:
            raise HTTPException(status_code=404, detail='Route not found')
        auth_header = request.headers.get('authorization', '')
        token = bearer_token(auth_header)
        session_profile = None
        if token:
            credential = store.get_directory_credential_by_secret_hash(hash_token_secret(token)) if hasattr(store, 'get_directory_credential_by_secret_hash') else None
            if credential and not credential_expired(credential):
                user = store.get_user(credential.principal_id)
                if user:
                    session_profile = user.metadata.get('permission_profile') if user.metadata else None
        if route.allowed and session_profile and session_profile not in route.allowed:
            raise HTTPException(status_code=403, detail='Session permission profile not allowed for this route')
        target_url = route.target.rstrip('/') + '/' + path
        query = request.url.query
        if query:
            target_url = target_url + '?' + query
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ('host', 'authorization')}
        body = request.body()
        try:
            req = urllib.request.Request(target_url, data=body, headers=headers, method=request.method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()
                return Response(content=content, status_code=resp.status, headers=dict(resp.headers))
        except urllib.error.HTTPError as exc:
            return Response(content=exc.read(), status_code=exc.code)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f'Proxy error: {exc}')

    return router
