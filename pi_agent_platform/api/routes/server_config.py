from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pi_agent_platform.core.config import AppConfig
from pi_agent_platform.core.models import Event


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class ServerConnectionRequest(BaseModel):
    public_url: str
    mdns_enabled: bool | None = None


def create_server_config_router(
    *,
    require_auth: Callable[..., Any],
    get_config: Callable[[], AppConfig],
    set_config: Callable[[AppConfig], None],
    save_config: Callable[[AppConfig], None],
    load_config: Callable[[], AppConfig],
    store: Any,
    config_payload: Callable[[], dict[str, Any]],
    stop_mdns_advertiser: Callable[[], None],
    start_mdns_advertiser: Callable[[], None],
) -> APIRouter:
    router = APIRouter()

    @router.put('/v1/config')
    def update_config(payload: ConfigUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        new_config = AppConfig.model_validate(payload.config)
        save_config(new_config)
        set_config(load_config())
        store.add_event(Event(session_id='system', type='config_updated', message='Configuration updated from Web UI'))
        return config_payload()

    @router.post('/v1/server/connection')
    def update_server_connection(payload: ServerConnectionRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        config = get_config()
        public_url = str(payload.public_url or '').strip().rstrip('/')
        if public_url and not (public_url.startswith('https://') or public_url.startswith('http://')):
            public_url = f'https://{public_url}'
        parsed = urllib.parse.urlparse(public_url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail='Controller URL must be a valid host or host:port value')
        config.server.public_url = public_url
        if payload.mdns_enabled is not None:
            config.mdns.enabled = bool(payload.mdns_enabled)
        save_config(config)
        set_config(load_config())
        config = get_config()
        try:
            stop_mdns_advertiser()
            start_mdns_advertiser()
        except Exception:
            pass
        store.add_event(Event(session_id='system', type='server_connection_updated', message=f'Endpoint controller URL set to {config.server.public_url}', data={'public_url': config.server.public_url, 'mdns_enabled': config.mdns.enabled}))
        return {'ok': True, 'public_url': config.server.public_url, 'mdns_enabled': config.mdns.enabled, 'message': 'Endpoint connection settings saved. Rebuild endpoint/agent binaries to compile this URL in.'}

    return router
