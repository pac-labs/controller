from __future__ import annotations

import json
from typing import Any

from ..config import AppConfig, save_config
from ..controller_component_context import get_controller_store
from ..directory_identities import ensure_provider_principal
from ..local_inference import create_lmstudio_models_from_inventory, discover_lmstudio, lmstudio_health, register_lmstudio_provider
from ..models import Event, Session, Task

_LOCAL_INFERENCE_TOOLS = {"local_inference_discover", "local_inference_health", "local_inference_register"}


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, sort_keys=True)[:20000]


async def try_execute_local_inference_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    allowed: set[str],
) -> tuple[str, bool] | None:
    if tool not in _LOCAL_INFERENCE_TOOLS:
        return None
    if tool not in allowed:
        return f"DENIED: {tool} is not enabled for this session", False
    store = get_controller_store()
    if tool == "local_inference_discover":
        urls = inp.get("urls") or ([inp.get("url")] if inp.get("url") else [])
        result = discover_lmstudio(store, extra_urls=[str(item) for item in urls if str(item or '').strip()], timeout_seconds=float(inp.get("timeout_seconds") or 1.5))
        if store:
            store.add_event(Event(session_id=session.id, task_id=task.id, type="local_provider_discovery", message="LM Studio discovery completed", data={"ok": result.get("ok"), "candidates": len(result.get("candidates") or [])}))
        return _json(result), False
    if tool == "local_inference_health":
        base_url = str(inp.get("base_url") or inp.get("url") or "").strip()
        if not base_url:
            return "ERROR: base_url is required", False
        result = lmstudio_health(base_url, timeout_seconds=float(inp.get("timeout_seconds") or 3.0), chat_test=bool(inp.get("chat_test", False)), model=inp.get("model"))
        return _json(result), False
    if tool == "local_inference_register":
        if store is None:
            return "ERROR: controller store is not available", False
        base_url = str(inp.get("base_url") or inp.get("url") or "").strip()
        if not base_url:
            return "ERROR: base_url is required", False
        health = lmstudio_health(base_url, timeout_seconds=float(inp.get("timeout_seconds") or 3.0), chat_test=bool(inp.get("chat_test", False)))
        if not health.get("ok") and not bool(inp.get("force", False)):
            return _json({"ok": False, "error": "LM Studio server is not healthy. Pass force=true to register anyway.", "health": health}), False
        provider_name, provider = register_lmstudio_provider(
            config,
            name=inp.get("name"),
            base_url=base_url,
            enabled=bool(inp.get("enabled", True)),
            overwrite=bool(inp.get("overwrite", False)),
            cached_models=health.get("models") or [],
        )
        created_models: list[str] = []
        if bool(inp.get("create_models", True)):
            created_models = create_lmstudio_models_from_inventory(config, provider_name, health.get("models") or [], limit=int(inp.get("model_limit") or 12))
        save_config(config)
        ensure_provider_principal(store, provider_name, provider)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="local_provider_registered", message=f"LM Studio provider registered: {provider_name}", data={"provider": provider_name, "models": len(provider.cached_models), "created_models": created_models}))
        return _json({"ok": True, "provider": provider_name, "created_models": created_models, "health": health}), False
    return None
