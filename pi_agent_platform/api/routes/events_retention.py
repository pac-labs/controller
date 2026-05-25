from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class EventRetentionPolicyPayload(BaseModel):
    retention_enabled: bool = True
    retain_days: int = 30
    emergency_retain_days: int = 180
    max_events: int = 20000
    prune_on_startup: bool = True


def create_events_retention_router(
    *,
    require_auth: Callable[..., Any],
    store: Any,
) -> APIRouter:
    router = APIRouter()

    def _require_admin(auth: Any) -> None:
        if not getattr(auth, "is_admin", False):
            raise HTTPException(status_code=403, detail="Administrator access is required")

    @router.get('/v1/events/retention')
    def get_event_retention_policy(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return {
            'policy': store.get_event_retention_policy(),
            'counts': store.get_event_retention_counts(),
        }

    @router.put('/v1/events/retention')
    def update_event_retention_policy(payload: EventRetentionPolicyPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        _require_admin(_auth)
        policy = store.set_event_retention_policy(payload.model_dump())
        return {
            'ok': True,
            'policy': policy,
            'counts': store.get_event_retention_counts(),
        }

    @router.post('/v1/events/retention/prune')
    def prune_event_retention(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        _require_admin(_auth)
        return {
            'ok': True,
            'policy': store.get_event_retention_policy(),
            'result': store.prune_events_by_retention(),
            'counts': store.get_event_retention_counts(),
        }

    return router
