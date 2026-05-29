from __future__ import annotations

import asyncio
import json
from typing import Any

from ..agent_action_recovery import _default_consult_models
from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from ..providers import chat_complete
from ..web_tools import as_json_text


async def try_execute_model_consult_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    allowed: set[str],
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    if tool == "consult_model":
        if "consult_model" not in allowed:
            return "DENIED: consult_model is not enabled for this session", False
        requested_models = inp.get("models")
        if isinstance(requested_models, list):
            target_models = [str(model).strip() for model in requested_models if str(model).strip()]
        else:
            single = str(inp.get("model") or "").strip()
            target_models = [single] if single else []
        if not target_models:
            target_models = _default_consult_models(config, session.model, limit=2)
        unknown = [model for model in target_models if model not in config.models]
        if unknown:
            events.model_routing_issue(message=f"Consult model unavailable: {', '.join(unknown)}", data={"requested_models": target_models, "unknown_models": unknown, "session_model": session.model})
            target_models = [model for model in target_models if model in config.models]
        if not target_models:
            fallback = session.model if session.model in config.models else None
            if fallback:
                target_models = [fallback]
                events.model_routing_issue(message=f"No separate consult model is configured; using session model {fallback} for self-consultation.", data={"session_model": session.model, "fallback_model": fallback})
            else:
                return as_json_text({"ok": False, "error": "CONSULT_MODEL_FAILED", "message": "No requested consult model is configured and no session model fallback is available. Continue with the current model and explain the limitation."}), False
        prompt = str(inp.get("prompt") or inp.get("question") or "").strip()
        if not prompt:
            return "CONSULT_MODEL_FAILED: prompt is required", False
        max_tokens = int(inp.get("max_tokens") or 1200)
        include_recent = bool(inp.get("include_recent_context", True))
        recent_context = ""
        if include_recent:
            transcript = list(task.metadata.get("agent_transcript") or [])[-6:]
            if transcript:
                recent_context = "\n\nRecent agent context:\n" + json.dumps(transcript, indent=2)
        consult_messages = [
            {
                "role": "system",
                "content": "You are an internal PAC planning consultant. Be concise, actionable, and explicit about risks or missing information.",
            },
            {"role": "user", "content": prompt + recent_context},
        ]

        async def _consult(target_model: str) -> dict[str, Any]:
            try:
                response = await asyncio.to_thread(
                    chat_complete,
                    config,
                    target_model,
                    consult_messages,
                    max_tokens=max_tokens,
                    telemetry={"session_id": session.id, "task_id": task.id, "call_type": "consult", "metadata": {"requested_by": "consult_model"}},
                )
                return {"model": target_model, "ok": True, "response": response}
            except Exception as exc:
                return {"model": target_model, "ok": False, "error": str(exc)}

        results = await asyncio.gather(*[_consult(model_name) for model_name in target_models])
        events.model_consult(models=target_models, model_count=len(target_models), ok=sum(1 for item in results if item.get('ok')), failed=sum(1 for item in results if not item.get('ok')))
        return as_json_text({"results": results}), False


    return None
