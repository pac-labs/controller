from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import AppConfig
from .models import Session, Task

if TYPE_CHECKING:
    from .agent_request_policy import AgentRequestPolicy


@dataclass(slots=True)
class AgentModelSelection:
    decision_model: str
    planning_model: str
    switched_decision_model: bool = False
    reason: str = ""


def _capability_rank(config: AppConfig, model_name: str) -> tuple[int, int, int]:
    model = config.models.get(str(model_name or "").strip())
    if not model:
        return (-1, -1, -1)
    caps = getattr(model, "capabilities", None)
    if not caps or getattr(caps, "supports_chat", True) is False:
        return (-1, -1, -1)
    json_rank = 2 if getattr(caps, "supports_json", False) else 0
    tool_rank = 2 if getattr(caps, "supports_tools", False) else 0
    reasoning_rank = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
    }.get(str(getattr(caps, "reasoning", "none") or "none"), 0)
    return (json_rank + tool_rank, reasoning_rank, int(model.context_window or 0))


def model_is_structured_agent_capable(config: AppConfig, model_name: str) -> bool:
    primary, reasoning, _window = _capability_rank(config, model_name)
    return primary >= 2 or (primary >= 1 and reasoning >= 1)


def _candidate_models(session: Session, task: Task) -> list[str]:
    candidates: list[str] = []
    for name in (
        task.metadata.get("planner_model"),
        task.metadata.get("reviewer_model"),
        task.metadata.get("retrieval_model"),
        task.metadata.get("model"),
        session.metadata.get("planner_model") if isinstance(session.metadata, dict) else None,
        session.metadata.get("reviewer_model") if isinstance(session.metadata, dict) else None,
        session.metadata.get("retrieval_model") if isinstance(session.metadata, dict) else None,
        session.model,
    ):
        value = str(name or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def resolve_agent_models(
    config: AppConfig,
    session: Session,
    task: Task,
    request_policy: AgentRequestPolicy,
) -> AgentModelSelection:
    executor_model = str(task.metadata.get("model") or session.model or "").strip()
    planning_model = str(task.metadata.get("planner_model") or executor_model).strip()
    if not executor_model:
        return AgentModelSelection(decision_model="", planning_model=planning_model or "", reason="no_executor_model")
    if not (request_policy.needs_plan or request_policy.needs_workspace_index or request_policy.needs_work_intent):
        return AgentModelSelection(decision_model=executor_model, planning_model=planning_model or executor_model, reason="simple_request")
    if model_is_structured_agent_capable(config, executor_model):
        return AgentModelSelection(decision_model=executor_model, planning_model=planning_model or executor_model, reason="executor_capable")

    ranked_candidates = []
    for name in _candidate_models(session, task):
        rank = _capability_rank(config, name)
        if rank[0] < 0:
            continue
        ranked_candidates.append((rank, name))
    for name, model in config.models.items():
        if name in {item[1] for item in ranked_candidates}:
            continue
        rank = _capability_rank(config, name)
        if rank[0] < 0:
            continue
        ranked_candidates.append((rank, name))
    ranked_candidates.sort(key=lambda item: item[0], reverse=True)
    for _rank, candidate in ranked_candidates:
        if candidate == executor_model:
            continue
        if model_is_structured_agent_capable(config, candidate):
            return AgentModelSelection(
                decision_model=candidate,
                planning_model=planning_model or candidate,
                switched_decision_model=True,
                reason=f"executor_model_not_structured_capable:{executor_model}->{candidate}",
            )
    return AgentModelSelection(decision_model=executor_model, planning_model=planning_model or executor_model, reason="no_structured_fallback")
