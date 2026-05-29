from __future__ import annotations

import json
from typing import Any, Callable

from .config import AppConfig
from .providers import chat_complete
from .agent_model_calls import run_blocking_provider_call


PLAN_PROMPT = (
    "You are PAC's planning pass. Return exactly one JSON object with this shape:\n"
    '{"summary":"short summary","steps":["step 1","step 2","step 3"]}\n'
    "Rules:\n"
    "- Keep the summary under 120 characters.\n"
    "- Keep between 2 and 6 concrete steps.\n"
    "- Use imperative, execution-oriented steps.\n"
    "- Do not add markdown, prose, or wrapper text.\n"
)


def fallback_plan(prompt: str) -> dict[str, Any]:
    request = str(prompt or "").strip() or "the current request"
    brief = request.splitlines()[0][:120]
    return {
        "summary": f"Plan the work for: {brief}",
        "steps": [
            "Inspect the relevant workspace and current state.",
            "Choose the most direct next action or tool call.",
            "Execute the change or collect the needed evidence.",
            "Review the result and respond clearly.",
        ],
    }


def _normalize_plan(data: Any, prompt: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return fallback_plan(prompt)
    summary = str(data.get("summary") or "").strip()
    raw_steps = data.get("steps")
    steps = []
    if isinstance(raw_steps, list):
        for item in raw_steps:
            text = str(item or "").strip()
            if text:
                steps.append(text)
    if not summary:
        summary = fallback_plan(prompt)["summary"]
    if not steps:
        steps = fallback_plan(prompt)["steps"]
    return {"summary": summary[:160], "steps": steps[:6]}


async def generate_plan(
    config: AppConfig,
    *,
    model: str,
    prompt: str,
    extra_context: list[str] | None = None,
    max_tokens: int = 700,
    session_id: str | None = None,
    task_id: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    timeout_seconds: int | None = None,
    on_abandoned: Callable[[], None] | None = None,
    on_late_completed: Callable[[bool], None] | None = None,
) -> dict[str, Any]:
    messages = [{"role": "system", "content": PLAN_PROMPT}]
    if extra_context:
        for block in extra_context:
            text = str(block or "").strip()
            if text:
                messages.append({"role": "system", "content": text})
    messages.append({"role": "user", "content": str(prompt or "").strip() or "Plan the current request."})
    try:
        raw = await run_blocking_provider_call(
            lambda: chat_complete(
                config,
                model,
                messages,
                max_tokens=max_tokens,
                telemetry={"session_id": session_id, "task_id": task_id, "call_type": "plan"},
                progress_callback=progress_callback,
            ),
            timeout_seconds=timeout_seconds,
            on_abandoned=on_abandoned,
            on_late_completed=on_late_completed,
        )
    except Exception:
        return fallback_plan(prompt)
    try:
        parsed = json.loads(str(raw or "").strip())
    except Exception:
        return fallback_plan(prompt)
    return _normalize_plan(parsed, prompt)
