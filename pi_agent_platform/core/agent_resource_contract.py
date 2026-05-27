from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_pac_resource_intent import PacResourcePlan, parse_pac_resource_plan, session_action, workspace_profile_action


@dataclass(frozen=True, slots=True)
class ResourceContractDecision:
    allow: bool
    replacement_action: dict[str, Any] | None = None
    reason: str = "allowed"
    event_message: str = ""
    event_data: dict[str, Any] = field(default_factory=dict)


def evaluate_final(prompt: str, transcript: list[dict[str, Any]]) -> ResourceContractDecision:
    plan = parse_pac_resource_plan(prompt)
    if not plan.applies:
        return ResourceContractDecision(allow=True)
    state = _resource_state(transcript)
    if plan.needs_workspace and not state["workspace_created"]:
        action = workspace_profile_action(plan)
        return _replace(
            action,
            reason="resource_contract_requires_workspace_profile",
            message="PAC resource request needs the workspace profile to be created before finalizing.",
            plan=plan,
            state=state,
        )
    if plan.needs_session and not state["session_created"]:
        action = session_action(plan)
        return _replace(
            action,
            reason="resource_contract_requires_session",
            message="PAC resource request needs the requested programming session to be created before finalizing.",
            plan=plan,
            state=state,
        )
    return ResourceContractDecision(allow=True)


def _replace(action: dict[str, Any], *, reason: str, message: str, plan: PacResourcePlan, state: dict[str, Any]) -> ResourceContractDecision:
    return ResourceContractDecision(
        allow=False,
        replacement_action=action,
        reason=reason,
        event_message=message,
        event_data={"resource_plan": _plan_data(plan), "resource_state": state, "action": action},
    )


def _resource_state(transcript: list[dict[str, Any]]) -> dict[str, bool]:
    workspace_created = False
    session_created = False
    for entry in transcript or []:
        if not isinstance(entry, dict):
            continue
        tool = str(entry.get("tool") or "")
        observation = str(entry.get("observation") or "")
        failed = '"ok": false' in observation.lower() or "DENIED:" in observation or "failed" in observation.lower()
        if failed:
            continue
        if tool == "pac_create_workspace_profile":
            workspace_created = True
        if tool == "pac_create_session":
            session_created = True
    return {"workspace_created": workspace_created, "session_created": session_created}


def _plan_data(plan: PacResourcePlan) -> dict[str, Any]:
    return {
        "name": plan.name,
        "url": plan.url,
        "container_image": plan.container_image,
        "needs_workspace": plan.needs_workspace,
        "needs_session": plan.needs_session,
    }
