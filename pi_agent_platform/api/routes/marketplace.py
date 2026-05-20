from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pi_agent_platform.core.config import AppConfig
from pi_agent_platform.core.marketplace import (
    marketplace_download_model,
    marketplace_model_detail,
    marketplace_provider_profiles,
    marketplace_search_models,
)


class MarketplaceDownloadRequest(BaseModel):
    model: str
    provider: str
    quantization: str | None = None


def create_marketplace_router(config: AppConfig, store: Any, require_auth: Callable[..., Any]) -> APIRouter:
    router = APIRouter()

    @router.get('/v1/models/marketplace/providers')
    def marketplace_providers(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return {'providers': marketplace_provider_profiles(config)}

    @router.get('/v1/models/marketplace/search')
    def marketplace_search(
        q: str = '',
        limit: int = 20,
        sort: str = 'downloads',
        capability: str | None = None,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        return marketplace_search_models(config, q=q, limit=limit, sort=sort, capability=capability)

    @router.get('/v1/models/marketplace/model/{model_id:path}')
    def marketplace_detail(model_id: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return marketplace_model_detail(config, model_id)

    @router.post('/v1/models/marketplace/download')
    def marketplace_download(payload: MarketplaceDownloadRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return marketplace_download_model(config, store, model=payload.model, provider_name=payload.provider, quantization=payload.quantization)

    return router
