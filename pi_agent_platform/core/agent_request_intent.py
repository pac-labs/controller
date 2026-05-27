from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .models import Session, Task
from .providers import chat_complete


_PROMPT = (
    "You are PAC's request-intent resolver. "
    "Decide whether the user is asking the agent to do work now or simply answer. "
    "Return exactly one JSON object with this shape:\n"
    "{\n"
    '  "intent": "work" | "answer",\n'
    '  "tool": "workspace_manifest" | "find_code_paths" | "list_files" | "ripgrep" | "read_file" | "git_status" | "none",\n'
    '  "input": {},\n'
    '  "needs_plan": true | false,\n'
    '  "reason": "short reason"\n'
    "}\n"
    "Rules:\n"
    "- If the user asks to inspect, index, explain a workspace/codebase, fix, build, change, implement, update, or investigate something, intent must be work.\n"
    "- Prefer safe first-step tools.\n"
    "- Use workspace_manifest first for broad workspace/codebase overview requests.\n"
    "- Use list_files for a simple directory listing request.\n"
    "- Use find_code_paths for broad PAC/core location questions with intent words such as session window, composer, timeline, atlas, dashboard, or visualization.\n"
    "- Use ripgrep only when the request mentions a concrete symbol, exact term, or topic to search.\n"
    "- Use read_file only when a specific file path is named.\n"
    "- Use git_status for repository state questions.\n"
    "- Use tool=none only when no tool work is needed.\n"
)


@dataclass(frozen=True, slots=True)
class RequestIntentResolution:
    model: str
    intent: str
    tool: str
    input: dict[str, Any]
    needs_plan: bool
    reason: str

    @property
    def should_bootstrap_work(self) -> bool:
        return self.intent == "work" and self.tool not in {"", "none"}


def should_resolve_request_intent(config: AppConfig, task: Task, policy: Any) -> bool:
    if not getattr(config.runtime, "request_intent_enabled", True):
        return False
    if not getattr(config.runtime, "request_intent_for_work_requests", True):
        return False
    if task.metadata.get("plan_only"):
        return False
    if task.metadata.get("request_intent_resolved"):
        return False
    return bool(getattr(policy, "needs_work_intent", False))


async def resolve_request_intent(config: AppConfig, session: Session, task: Task, policy: Any) -> RequestIntentResolution | None:
    model_name = _choose_intent_model(config, session)
    if not model_name:
        return fallback_request_intent(session, task, policy)
    try:
        raw = await chat_complete(
            config,
            model_name,
            [
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "prompt": task.prompt,
                            "policy": {
                                "prompt_kind": getattr(policy, "prompt_kind", ""),
                                "reason": getattr(policy, "reason", ""),
                                "needs_workspace_index": bool(getattr(policy, "needs_workspace_index", False)),
                                "needs_plan": bool(getattr(policy, "needs_plan", False)),
                                "prefer_local_inspection": bool(getattr(policy, "prefer_local_inspection", False)),
                            },
                            "session": {
                                "model": session.model,
                                "agent_profile": session.agent_profile,
                                "workspace_path": session.workspace_path,
                                "controller_harness": bool((session.metadata or {}).get("controller_harness")),
                            },
                        }
                    ),
                },
            ],
            max_tokens=300,
            telemetry={"session_id": session.id, "task_id": task.id, "call_type": "request_intent"},
        )
    except Exception:
        return fallback_request_intent(session, task, policy)
    payload = _extract_json(raw)
    if not isinstance(payload, dict):
        return fallback_request_intent(session, task, policy)
    tool = str(payload.get("tool") or "none").strip()
    tool_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    return RequestIntentResolution(
        model=model_name,
        intent=str(payload.get("intent") or "answer").strip().lower(),
        tool=tool,
        input=tool_input,
        needs_plan=bool(payload.get("needs_plan")),
        reason=str(payload.get("reason") or "").strip(),
    )


def fallback_request_intent(session: Session, task: Task, policy: Any) -> RequestIntentResolution:
    prompt = str(task.prompt or "").strip()
    lower = prompt.lower()
    if _looks_like_git_request(lower):
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="git_status",
            input={},
            needs_plan=False,
            reason="repository-state fallback",
        )
    if path := _extract_named_path(prompt):
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="read_file",
            input={"path": path},
            needs_plan=False,
            reason="specific-file fallback",
        )
    if _looks_like_search_request(lower):
        query = _extract_search_query(prompt)
        if _looks_like_broad_location_question(lower):
            return RequestIntentResolution(
                model="heuristic-fallback",
                intent="work",
                tool="find_code_paths",
                input={"query": query, "max_results": 12},
                needs_plan=bool(getattr(policy, "needs_plan", False)),
                reason="code-locator fallback",
            )
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="ripgrep",
            input={"pattern": query, "path": "."},
            needs_plan=bool(getattr(policy, "needs_plan", False)),
            reason="search fallback",
        )
    if getattr(policy, "needs_workspace_index", False) or _looks_like_workspace_overview_request(lower):
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="workspace_manifest",
            input={"max_files": 300},
            needs_plan=bool(getattr(policy, "needs_plan", False)),
            reason="workspace-overview fallback",
        )
    if lower.startswith(("list ", "show ", "open ", "inspect ")):
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="list_files",
            input={"path": "."},
            needs_plan=False,
            reason="directory-listing fallback",
        )
    return RequestIntentResolution(
        model="heuristic-fallback",
        intent="answer",
        tool="none",
        input={},
        needs_plan=bool(getattr(policy, "needs_plan", False)),
        reason="fallback answer",
    )


def _choose_intent_model(config: AppConfig, session: Session) -> str | None:
    explicit = str(getattr(config.runtime, "request_intent_model", "") or "").strip()
    if explicit and explicit in config.models:
        return explicit
    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    for name, model in (config.models or {}).items():
        provider = config.providers.get(model.provider)
        if not provider or provider.enabled is False or provider.status in {"disabled", "failed"}:
            continue
        model_id = str(model.model or name).lower()
        if "embed" in model_id or "embedding" in model_id:
            continue
        if getattr(model.capabilities, "supports_chat", True) is False:
            continue
        reasoning_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}.get(str(getattr(model.capabilities, "reasoning", "medium") or "medium"), 2)
        json_rank = 0 if getattr(model.capabilities, "supports_json", False) else 1
        score = (json_rank, reasoning_rank, int(model.context_window or 0), int(model.max_output_tokens or 0))
        candidates.append((score, name))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    return session.model


def _extract_json(raw: str) -> Any:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _extract_named_path(prompt: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_./\\\\-]+\.[A-Za-z0-9_]+)", prompt)
    if not match:
        return None
    path = match.group(1).replace("\\", "/")
    if path.startswith(("http://", "https://")):
        return None
    return path


def _looks_like_git_request(lower: str) -> bool:
    return "git status" in lower or "repository state" in lower or "repo status" in lower


def _looks_like_search_request(lower: str) -> bool:
    return any(token in lower for token in ("search for ", "grep ", "find references", "find usages", "where is "))


def _looks_like_broad_location_question(lower: str) -> bool:
    return any(
        token in lower
        for token in ("session window", "composer", "timeline", "atlas", "dashboard", "visualization", "visualisation", "where is")
    )


def _extract_search_query(prompt: str) -> str:
    text = " ".join(str(prompt or "").strip().split())
    for marker in ("search for ", "grep ", "where is "):
        idx = text.lower().find(marker)
        if idx >= 0:
            return text[idx + len(marker):].strip(" ?\"'") or text
    return text


def _looks_like_workspace_overview_request(lower: str) -> bool:
    return any(
        token in lower
        for token in (
            "index the local workspace",
            "index the workspace",
            "explain the code base",
            "explain the codebase",
            "scan the workspace",
            "understand the code base",
            "understand the codebase",
        )
    )
