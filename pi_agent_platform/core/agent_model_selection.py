from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import AppConfig
from .models import Session, Task
from .coding_session_readiness import is_coding_session
from .agent_model_advisor import order_coding_candidates

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
    raw_chain = []
    for chain_source in (task.metadata.get("model_fallback_chain"), session.metadata.get("model_fallback_chain") if isinstance(session.metadata, dict) else None):
        if isinstance(chain_source, list):
            raw_chain.extend(chain_source)
        elif isinstance(chain_source, str):
            raw_chain.extend([item.strip() for item in chain_source.split(",") if item.strip()])
    for name in raw_chain:
        value = str(name or "").strip()
        if value and value not in candidates:
            candidates.append(value)
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


def resolve_fallback_model(
    config: AppConfig,
    session: Session,
    task: Task,
    current_model: str,
    *,
    require_structured: bool = False,
    prefer_coding: bool = False,
) -> str:
    ranked_candidates: list[tuple[tuple[int, int, int], str]] = []
    for name in _candidate_models(session, task):
        if name == current_model:
            continue
        rank = _capability_rank(config, name)
        if rank[0] < 0:
            continue
        ranked_candidates.append((rank, name))
    existing_names = {item[1] for item in ranked_candidates}
    for name in config.models:
        if name == current_model or name in existing_names:
            continue
        rank = _capability_rank(config, name)
        if rank[0] < 0:
            continue
        ranked_candidates.append((rank, name))
    candidate_names = [item[1] for item in ranked_candidates]
    ordered_names = (
        order_coding_candidates(config, session, task, candidate_names)
        if prefer_coding and is_coding_session(session)
        else [name for _rank, name in sorted(ranked_candidates, key=lambda item: item[0], reverse=True)]
    )
    for candidate in ordered_names:
        if not require_structured or model_is_structured_agent_capable(config, candidate):
            return candidate
    return ""


def resolve_agent_models(
    config: AppConfig,
    session: Session,
    task: Task,
    request_policy: AgentRequestPolicy,
) -> AgentModelSelection:
    session_meta = session.metadata if isinstance(session.metadata, dict) else {}
    executor_model = str(task.metadata.get("model") or session.model or "").strip()
    planning_model = str(task.metadata.get("planner_model") or executor_model).strip()
    if not executor_model:
        return AgentModelSelection(decision_model="", planning_model=planning_model or "", reason="no_executor_model")
    needs_structured_decision = bool(
        request_policy.needs_plan
        or request_policy.needs_workspace_index
        or request_policy.needs_work_intent
        or session_meta.get("controller_harness")
        or session_meta.get("system_context")
        or request_policy.prefer_local_inspection
    )
    if not needs_structured_decision:
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
    candidate_names = [item[1] for item in ranked_candidates]
    ordered_names = (
        order_coding_candidates(config, session, task, candidate_names)
        if is_coding_session(session)
        else [name for _rank, name in sorted(ranked_candidates, key=lambda item: item[0], reverse=True)]
    )
    for candidate in ordered_names:
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
