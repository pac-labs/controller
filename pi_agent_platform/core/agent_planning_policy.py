from __future__ import annotations

from .config import AppConfig
from .models import Session


def should_skip_model_planning(
    config: AppConfig,
    session: Session,
    *,
    planning_model: str,
    decision_model: str,
) -> tuple[bool, str | None]:
    """Decide when to skip a separate model-planning round-trip.

    Local LM Studio coding sessions are currently more stable when PAC avoids
    issuing a planning request and a decision request back-to-back against the
    same model. In that case we use the deterministic fallback plan instead of
    overlapping provider work.
    """

    if not planning_model or not decision_model:
        return False, None
    if planning_model != decision_model:
        return False, None
    if not session.metadata.get("coding_session"):
        return False, None
    model = config.models.get(planning_model)
    if not model:
        return False, None
    provider = config.providers.get(model.provider)
    provider_type = str(getattr(provider, "type", "") or "").strip().lower()
    if provider_type == "lmstudio":
        return True, "same_model_lmstudio_coding_session"
    return False, None
