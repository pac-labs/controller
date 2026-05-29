from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from ..config import AppConfig
from ..models import Session, Task
from .pipeline_policy import is_mutating_tool, is_read_only_tool

ExecuteTool = Callable[[Session, Task, str, dict[str, Any], AppConfig], Awaitable[tuple[str, bool]]]


def _normalise_calls(inp: dict[str, Any]) -> list[dict[str, Any]]:
    calls = inp.get("calls") or []
    return calls if isinstance(calls, list) else []


async def try_execute_batch_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    execute_tool: ExecuteTool,
) -> tuple[str, bool] | None:
    if tool != "batch_tools":
        return None
    calls = _normalise_calls(inp)
    if not calls:
        return "DENIED: batch_tools requires at least one call", False
    if len(calls) > 8:
        return "DENIED: batch_tools supports at most 8 calls", False

    normalised: list[tuple[str, dict[str, Any]]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            return f"DENIED: calls[{index}] must be an object", False
        nested_tool = str(call.get("tool") or "").strip()
        nested_input = call.get("input") or {}
        if not nested_tool:
            return f"DENIED: calls[{index}].tool is required", False
        if nested_tool == "batch_tools":
            return "DENIED: nested batch_tools calls are not allowed", False
        if not isinstance(nested_input, dict):
            return f"DENIED: calls[{index}].input must be an object", False
        if is_mutating_tool(nested_tool, config) or not is_read_only_tool(nested_tool, config):
            return f"DENIED: batch_tools only allows read-only tools; {nested_tool} is not read-only", False
        normalised.append((nested_tool, nested_input))

    semaphore = asyncio.Semaphore(4)

    async def run_one(index: int, nested_tool: str, nested_input: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            observation, paused = await execute_tool(session, task, nested_tool, nested_input, config)
            return {
                "index": index,
                "tool": nested_tool,
                "paused": paused,
                "observation": str(observation or "")[:6000],
            }

    results = await asyncio.gather(*(run_one(index, nested_tool, nested_input) for index, (nested_tool, nested_input) in enumerate(normalised)))
    return json.dumps({"tool": "batch_tools", "count": len(results), "results": results}, indent=2), False
