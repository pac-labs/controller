from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


BuildInfoProvider = Callable[[], dict[str, Any]]


def create_version_router(*, pac_version: str, ui_build_info: BuildInfoProvider) -> APIRouter:
    """Register small controller metadata routes.

    This keeps stable, low-dependency controller identity endpoints out of the
    main application file while the larger API split is performed in phases.
    """
    router = APIRouter()

    @router.get('/v1/version')
    def get_version() -> dict[str, Any]:
        ui = ui_build_info()
        return {
            'version': pac_version,
            'name': 'PAC',
            'full_name': 'Pi Agent Control',
            'ui_build': ui['asset_stamp'],
            'ui_updated_at': ui['updated_at'],
        }

    return router
