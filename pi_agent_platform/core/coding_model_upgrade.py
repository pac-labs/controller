from __future__ import annotations

import re
from typing import Any

from .config import AppConfig, ModelConfig, save_config
from .models import Event, Session
from .providers import lmstudio_load_model


def stash_pending_model_upgrade(
    session: Session,
    recommendation: dict[str, Any],
    *,
    current_models: list[str],
    failure_count: int,
) -> None:
    metadata = dict(session.metadata or {})
    metadata["pending_model_upgrade"] = {
        **dict(recommendation or {}),
        "current_models": [str(item).strip() for item in current_models if str(item).strip()],
        "failure_count": int(max(failure_count, 0)),
    }
    session.metadata = metadata


def maybe_apply_model_upgrade_reply(
    config: AppConfig,
    store: Any,
    session: Session,
    prompt: str,
) -> dict[str, Any] | None:
    pending = (session.metadata or {}).get("pending_model_upgrade")
    if not isinstance(pending, dict):
        return None
    decision = _parse_upgrade_reply(prompt, pending)
    if decision["kind"] == "ignore":
        return None
    if decision["kind"] == "dismiss":
        _clear_pending(session, store)
        return {
            "ok": True,
            "status": "dismissed",
            "message": "Okay. PAC will keep the current model for this coding session.",
        }
    candidate = _select_candidate(pending, decision)
    if not candidate:
        _clear_pending(session, store)
        return {
            "ok": False,
            "status": "failed",
            "message": "PAC could not match that request to one of the recommended coding models.",
        }
    result = _apply_candidate(config, store, session, candidate)
    _clear_pending(session, store)
    return result


def _parse_upgrade_reply(prompt: str, pending: dict[str, Any]) -> dict[str, Any]:
    text = str(prompt or "").strip()
    lowered = text.lower()
    if not text:
        return {"kind": "ignore"}
    if re.search(r"\b(no|not now|skip|keep current|leave it|stay)\b", lowered):
        return {"kind": "dismiss"}
    if not re.search(r"\b(yes|use|switch|download|configure|go ahead|do it|please do|try)\b", lowered):
        return {"kind": "ignore"}
    index_match = re.search(r"\b([1-9])\b", lowered)
    selector = int(index_match.group(1)) if index_match else None
    return {"kind": "approve", "selector": selector, "text": lowered, "pending": pending}


def _select_candidate(pending: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any] | None:
    candidates = pending.get("candidates") if isinstance(pending, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return None
    selector = decision.get("selector")
    if isinstance(selector, int) and 1 <= selector <= len(candidates):
        item = candidates[selector - 1]
        return item if isinstance(item, dict) else None
    text = str(decision.get("text") or "")
    for item in candidates:
        if not isinstance(item, dict):
            continue
        provider_name = str(item.get("provider_name") or "").lower()
        provider_model_id = str(item.get("provider_model_id") or item.get("name") or "").lower()
        configured_model_name = str(item.get("configured_model_name") or "").lower()
        if provider_name and provider_name in text:
            return item
        if provider_model_id and provider_model_id in text:
            return item
        if configured_model_name and configured_model_name in text:
            return item
    item = candidates[0]
    return item if isinstance(item, dict) else None


def _apply_candidate(config: AppConfig, store: Any, session: Session, candidate: dict[str, Any]) -> dict[str, Any]:
    provider_name = str(candidate.get("provider_name") or "").strip()
    provider_model_id = str(candidate.get("provider_model_id") or candidate.get("name") or "").strip()
    configured_model_name = str(candidate.get("configured_model_name") or "").strip()
    if not provider_name or not provider_model_id:
        return {"ok": False, "status": "failed", "message": "Recommended model is missing provider metadata."}
    provider = config.providers.get(provider_name)
    if not provider:
        return {"ok": False, "status": "failed", "message": f"Provider is no longer configured: {provider_name}."}
    created_model = False
    if not configured_model_name:
        configured_model_name = _create_model_config(config, session, provider_name, provider_model_id)
        created_model = True
    load_result = None
    if str(getattr(provider, "type", "") or "").lower() == "lmstudio":
        load_result = lmstudio_load_model(provider, provider_model_id, _load_runtime_options(config, session))
        if load_result.get("ok") is False:
            return {
                "ok": False,
                "status": "failed",
                "message": f"PAC could not load {provider_model_id} on {provider_name}: {load_result.get('error') or load_result.get('response') or 'unknown error'}.",
            }
    session.model = configured_model_name
    _update_bound_context(store, session, configured_model_name)
    store.add_session(session)
    save_config(config)
    store.add_event(
        Event(
            session_id=session.id,
            type="session_model_upgraded",
            message=f"Session model switched to {configured_model_name}",
            data={
                "internal": True,
                "provider": provider_name,
                "provider_model_id": provider_model_id,
                "configured_model_name": configured_model_name,
                "created_model": created_model,
                "load_result": load_result,
            },
        )
    )
    action = "configured and switched" if created_model else "switched"
    return {
        "ok": True,
        "status": "applied",
        "message": f"PAC {action} this coding session to {configured_model_name} ({provider_name} -> {provider_model_id}).",
    }


def _create_model_config(config: AppConfig, session: Session, provider_name: str, provider_model_id: str) -> str:
    model_name = _suggest_model_name(provider_name, provider_model_id)
    if model_name in config.models:
        return model_name
    template = config.models.get(session.model or "")
    capabilities = (
        template.capabilities.model_dump(mode="json")
        if template and getattr(template, "capabilities", None)
        else {
            "supports_chat": True,
            "supports_tools": True,
            "supports_json": True,
            "supports_streaming": True,
            "supports_vision": False,
            "reasoning": "medium",
        }
    )
    extra = dict(getattr(template, "extra", {}) or {})
    config.models[model_name] = ModelConfig.model_validate(
        {
            "display_name": provider_model_id.split("/")[-1],
            "provider": provider_name,
            "model": provider_model_id,
            "runs_on": provider_name,
            "context_window": int(getattr(template, "context_window", 32768) or 32768),
            "max_output_tokens": int(getattr(template, "max_output_tokens", 4096) or 4096),
            "capabilities": capabilities,
            "extra": extra,
        }
    )
    return model_name


def _load_runtime_options(config: AppConfig, session: Session) -> dict[str, Any]:
    model = config.models.get(session.model or "")
    runtime = dict((getattr(model, "extra", {}) or {}).get("lmstudio_runtime", {})) if model else {}
    if not runtime.get("context_length") and model:
        runtime["context_length"] = int(model.context_window or 32768)
    return runtime


def _update_bound_context(store: Any, session: Session, configured_model_name: str) -> None:
    context_id = str((session.metadata or {}).get("agent_context_id") or "").strip()
    if not context_id or not hasattr(store, "get_agent_context"):
        return
    context = store.get_agent_context(context_id)
    if not context:
        return
    context.executor_model = configured_model_name
    context.touch()
    store.add_agent_context(context)


def _suggest_model_name(provider_name: str, provider_model_id: str) -> str:
    provider_part = re.sub(r"[^a-z0-9]+", "-", provider_name.lower()).strip("-") or "model"
    model_part = re.sub(r"[^a-z0-9]+", "-", provider_model_id.lower()).strip("-") or "model"
    return f"{provider_part}-{model_part}"


def _clear_pending(session: Session, store: Any) -> None:
    metadata = dict(session.metadata or {})
    metadata.pop("pending_model_upgrade", None)
    session.metadata = metadata
    store.add_session(session)
