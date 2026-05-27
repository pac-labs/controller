from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .agent_pac_resource_intent import parse_pac_resource_plan, session_action, workspace_profile_action
from .config import AppConfig
from .models import Session, Task
from .providers import chat_complete


_PROMPT = (
    "You are PAC's request-intent resolver. "
    "Decide whether the user is asking the agent to do work now or simply answer. "
    "Return exactly one JSON object with this shape:\n"
    "{\n"
    '  "intent": "work" | "answer",\n'
    '  "tool": "workspace_manifest" | "find_code_paths" | "list_files" | "ripgrep" | "read_file" | "git_status" | "pac_list_components" | "pac_create_workspace_profile" | "pac_create_session" | "none",\n'
    '  "input": {},\n'
    '  "needs_plan": true | false,\n'
    '  "reason": "short reason"\n'
    "}\n"
    "Rules:\n"
    "- If the user asks to inspect, index, explain a workspace/codebase, fix, build, change, implement, update, or investigate something, intent must be work.\n"
    "- If the user asks to create PAC resources such as workspaces, endpoint records, providers, models, or sessions, intent must be work and the tool must be a pac_* control-plane tool, not read_file.\n"
    "- For a prompt that asks to create a git workspace and then a session for it, use pac_create_workspace_profile first with type=git, url, runtime/container_image when present, and needs_plan=true so the loop can create the session next.\n"
    "- Prefer safe first-step tools.\n"
    "- Use workspace_manifest first for implementation/change/fix requests that do not name one exact file.\n"
    "- Use workspace_manifest first for broad workspace/codebase overview requests.\n"
    "- Use list_files for a simple directory listing request.\n"
    "- Use find_code_paths for broad PAC/core location questions with intent words such as session window, composer, timeline, atlas, dashboard, or visualization.\n"
    "- Use ripgrep only when the request mentions a concrete symbol, exact term, or topic to search.\n"
    "- Use read_file only when a specific local workspace file path is named. Never use read_file for http(s) URLs, repository URLs, domains, or paths outside the workspace.\n"
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
    normalized = _normalize_model_resolution(model_name, payload, session, task, policy)
    if normalized is not None:
        return normalized
    return fallback_request_intent(session, task, policy)


def fallback_request_intent(session: Session, task: Task, policy: Any) -> RequestIntentResolution:
    prompt = str(task.prompt or "").strip()
    lower = prompt.lower()
    if pac_resource := _pac_resource_bootstrap(prompt):
        return pac_resource
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
    if _looks_like_code_change_request(lower):
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool="workspace_manifest",
            input={"max_files": 300},
            needs_plan=True,
            reason="code-change bootstrap fallback",
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


def _normalize_model_resolution(model_name: str, payload: dict[str, Any], session: Session, task: Task, policy: Any) -> RequestIntentResolution | None:
    prompt = str(task.prompt or "").strip()
    tool = str(payload.get("tool") or "none").strip()
    tool_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    intent = str(payload.get("intent") or "answer").strip().lower()
    needs_plan = bool(payload.get("needs_plan"))
    reason = str(payload.get("reason") or "").strip()

    if pac_resource := _pac_resource_bootstrap(prompt):
        if tool not in {"pac_list_components", "pac_create_workspace_profile", "pac_create_session"}:
            return RequestIntentResolution(
                model=model_name,
                intent=pac_resource.intent,
                tool=pac_resource.tool,
                input=pac_resource.input,
                needs_plan=pac_resource.needs_plan,
                reason=f"PAC resource heuristic override after model chose {tool or 'none'}",
            )

    if tool == "read_file" and _path_is_remote_or_unsafe(tool_input.get("path")):
        fallback = fallback_request_intent(session, task, policy)
        return RequestIntentResolution(
            model=model_name,
            intent=fallback.intent,
            tool=fallback.tool,
            input=fallback.input,
            needs_plan=fallback.needs_plan,
            reason=f"Unsafe read_file bootstrap replaced: {reason or 'remote/non-local path'}",
        )

    allowed_tools = {
        "workspace_manifest",
        "find_code_paths",
        "list_files",
        "ripgrep",
        "read_file",
        "git_status",
        "pac_list_components",
        "pac_create_workspace_profile",
        "pac_create_session",
        "none",
        "",
    }
    if tool not in allowed_tools:
        return fallback_request_intent(session, task, policy)

    return RequestIntentResolution(
        model=model_name,
        intent=intent,
        tool=tool,
        input=tool_input,
        needs_plan=needs_plan,
        reason=reason,
    )


def _pac_resource_bootstrap(prompt: str) -> RequestIntentResolution | None:
    plan = parse_pac_resource_plan(prompt)
    if not plan.applies:
        return None
    if plan.needs_workspace:
        action = workspace_profile_action(plan)
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool=action["tool"],
            input=action["input"],
            needs_plan=True,
            reason="PAC workspace/session creation fallback",
        )
    if plan.needs_session:
        action = session_action(plan)
        return RequestIntentResolution(
            model="heuristic-fallback",
            intent="work",
            tool=action["tool"],
            input=action["input"],
            needs_plan=True,
            reason="PAC session creation fallback",
        )
    return RequestIntentResolution(
        model="heuristic-fallback",
        intent="work",
        tool="pac_list_components",
        input={},
        needs_plan=True,
        reason="PAC resource request needs current component state",
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
    scrubbed = re.sub(r"https?://[^\s]+", " ", str(prompt or ""))
    for match in re.finditer(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)", scrubbed):
        path = match.group(1).replace("\\", "/")
        if _path_is_remote_or_unsafe(path):
            continue
        if "/" not in path and not path.startswith("."):
            continue
        return path
    return None


def _path_is_remote_or_unsafe(path: Any) -> bool:
    value = str(path or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/|$)", value):
        return True
    if value.startswith(("/", "../", "..\\")):
        return True
    return False


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


def _looks_like_code_change_request(lower: str) -> bool:
    compact = " ".join(str(lower or "").split())
    if not compact:
        return False
    prefixes = (
        "add ",
        "please add ",
        "can you add ",
        "could you add ",
        "implement ",
        "please implement ",
        "fix ",
        "change ",
        "update ",
        "wire ",
        "persist ",
        "store ",
        "save ",
        "make it ",
        "make the ",
        "allow ",
        "enable ",
    )
    if compact.startswith(prefixes):
        return True
    return any(term in compact for term in (" so we can ", " should ", " needs to ")) and any(
        verb in compact for verb in ("add", "implement", "fix", "change", "update", "persist", "store", "save")
    )
