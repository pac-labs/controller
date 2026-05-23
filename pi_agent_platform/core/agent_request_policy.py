from __future__ import annotations

from dataclasses import dataclass

from .agent_inspection_policy import is_broad_codebase_request, prompt_requests_codebase_inspection
from .models import Session, Task


GREETING_PREFIXES = (
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
)

DIRECT_ACTION_HINTS = (
    "list ",
    "show ",
    "open ",
    "read ",
    "grep ",
    "search ",
    "find ",
    "cat ",
    "inspect ",
    "check ",
)

COMPLEXITY_HINTS = (
    "implement",
    "refactor",
    "investigate",
    "diagnose",
    "fix",
    "improve",
    "change",
    "update",
    "create",
    "build",
    "design",
    "explain why",
)


@dataclass(frozen=True, slots=True)
class AgentRequestPolicy:
    prompt_kind: str
    needs_workspace_index: bool
    needs_plan: bool
    prefer_local_inspection: bool
    reason: str


def classify_request(session: Session, task: Task) -> AgentRequestPolicy:
    prompt = str(task.prompt or "").strip()
    lower = prompt.lower()
    controller_session = bool(session.metadata.get("controller_harness"))
    explicit_plan = bool(task.metadata.get("plan_only")) or bool(task.metadata.get("always_plan"))

    if not lower:
        return AgentRequestPolicy(
            prompt_kind="empty",
            needs_workspace_index=False,
            needs_plan=False,
            prefer_local_inspection=controller_session,
            reason="empty prompt",
        )

    if _is_greeting(lower):
        return AgentRequestPolicy(
            prompt_kind="greeting",
            needs_workspace_index=False,
            needs_plan=False,
            prefer_local_inspection=False,
            reason="short greeting or acknowledgement",
        )

    if lower.startswith("/"):
        return AgentRequestPolicy(
            prompt_kind="slash-command",
            needs_workspace_index=False,
            needs_plan=False,
            prefer_local_inspection=controller_session,
            reason="explicit slash command",
        )

    if _looks_like_direct_action(lower):
        return AgentRequestPolicy(
            prompt_kind="direct-action",
            needs_workspace_index=False,
            needs_plan=explicit_plan,
            prefer_local_inspection=controller_session or prompt_requests_codebase_inspection(lower),
            reason="direct single action request",
        )

    broad_codebase = prompt_requests_codebase_inspection(lower) or is_broad_codebase_request(lower)
    complex_request = _looks_complex(lower)
    needs_index = broad_codebase or bool(task.metadata.get("force_workspace_index"))
    needs_plan = explicit_plan or complex_request or broad_codebase

    if controller_session and not needs_index and not needs_plan and _looks_like_local_fact_question(lower):
        return AgentRequestPolicy(
            prompt_kind="controller-fact",
            needs_workspace_index=False,
            needs_plan=False,
            prefer_local_inspection=True,
            reason="controller-local fact question",
        )

    return AgentRequestPolicy(
        prompt_kind="complex" if (needs_index or needs_plan) else "simple",
        needs_workspace_index=needs_index,
        needs_plan=needs_plan,
        prefer_local_inspection=controller_session or broad_codebase,
        reason=_reason(needs_index, needs_plan, controller_session, broad_codebase, complex_request),
    )


def _is_greeting(lower: str) -> bool:
    compact = " ".join(lower.split())
    if compact in {"ok", "thanks", "thank you", "cool", "nice"}:
        return True
    return len(compact) <= 32 and any(compact.startswith(prefix) for prefix in GREETING_PREFIXES)


def _looks_like_direct_action(lower: str) -> bool:
    compact = " ".join(lower.split())
    if len(compact) <= 140 and any(compact.startswith(prefix) for prefix in DIRECT_ACTION_HINTS):
        return True
    if any(token in compact for token in ("readme", "package.json", "config.yaml", "version")) and len(compact) <= 120:
        return True
    return False


def _looks_complex(lower: str) -> bool:
    compact = " ".join(lower.split())
    if len(compact) > 220:
        return True
    if any(hint in compact for hint in COMPLEXITY_HINTS):
        return True
    if compact.count(" and ") >= 2 or compact.count(",") >= 3:
        return True
    return False


def _looks_like_local_fact_question(lower: str) -> bool:
    compact = " ".join(lower.split())
    if len(compact) > 180:
        return False
    local_terms = ("pac", "profile", "provider", "endpoint", "wrapper", "session", "plugin", "model", "config")
    if not any(term in compact for term in local_terms):
        return False
    return compact.startswith(("what ", "where ", "which ", "show ", "list ", "is ", "does "))


def _reason(needs_index: bool, needs_plan: bool, controller_session: bool, broad_codebase: bool, complex_request: bool) -> str:
    parts: list[str] = []
    if controller_session:
        parts.append("controller session")
    if broad_codebase:
        parts.append("codebase-wide inspection")
    if complex_request:
        parts.append("multi-step request")
    if needs_index:
        parts.append("workspace index required")
    if needs_plan:
        parts.append("planning required")
    return ", ".join(parts) or "simple request"
