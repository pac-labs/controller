from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends

from pi_agent_platform.core.llmfit import llmfit_recommendations, llmfit_status
from pi_agent_platform.core.model_advisor import coding_improvement_advice


def create_model_advisor_router(
    *,
    require_auth: Callable[..., Any] | Any,
    config: Any,
    require_resource_access: Callable[..., None] | Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/model-advisors/llmfit/status")
    def get_llmfit_status(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, "provider", "*", "read")
        return llmfit_status()

    @router.get("/v1/model-advisors/llmfit/recommendations")
    def get_llmfit_recommendations(
        use_case: str = "coding",
        limit: int = 5,
        max_context: int | None = None,
        force_runtime: str | None = None,
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, "provider", "*", "read")
        return llmfit_recommendations(
            use_case=use_case,
            limit=limit,
            max_context=max_context,
            force_runtime=force_runtime,
        )

    @router.get("/v1/model-advisors/coding-opportunities")
    def get_coding_opportunities(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, "provider", "*", "read")
        return coding_improvement_advice(config)

    return router
