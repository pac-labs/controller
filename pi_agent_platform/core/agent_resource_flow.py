from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .agent_pac_resource_intent import parse_pac_resource_plan, session_action, workspace_profile_action


@dataclass(frozen=True, slots=True)
class ResourceAction:
    tool: str
    input: dict[str, Any]
    reason: str


def build_resource_action_sequence(prompt: str, transcript: list[dict[str, Any]] | None = None) -> list[ResourceAction]:
    """Return deterministic PAC resource actions that are still missing.

    Resource creation is controller state work, not codebase exploration.  When a
    user asks PAC to create a git workspace and programming session, the agent
    should not wait for another model turn between the profile and session
    steps; it should run the bounded control-plane sequence directly.
    """

    plan = parse_pac_resource_plan(prompt)
    if not plan.applies:
        return []

    completed = _completed_resource_tools(transcript or [])
    actions: list[ResourceAction] = []
    if plan.needs_workspace and "pac_create_workspace_profile" not in completed:
        action = workspace_profile_action(plan)
        payload = dict(action.get("input") or {})
        payload.setdefault("idempotent", True)
        actions.append(
            ResourceAction(
                tool="pac_create_workspace_profile",
                input=payload,
                reason="resource_flow_workspace_profile",
            )
        )
    if plan.needs_session and "pac_create_session" not in completed:
        action = session_action(plan)
        payload = dict(action.get("input") or {})
        payload.setdefault("idempotent", True)
        actions.append(
            ResourceAction(
                tool="pac_create_session",
                input=payload,
                reason="resource_flow_programming_session",
            )
        )
    return actions


def resource_completion_message(prompt: str, transcript: list[dict[str, Any]]) -> str | None:
    plan = parse_pac_resource_plan(prompt)
    if not plan.applies:
        return None
    completed = _completed_resource_tools(transcript)
    if plan.needs_workspace and "pac_create_workspace_profile" not in completed:
        return None
    if plan.needs_session and "pac_create_session" not in completed:
        return None

    session_info = _last_tool_payload(transcript, "pac_create_session")
    workspace_info = _last_tool_payload(transcript, "pac_create_workspace_profile")
    lines = ["Created the requested PAC resources."]
    if workspace_info:
        name = workspace_info.get("name") or plan.name
        lines.append(f"Workspace profile: {name}")
    if session_info:
        session = session_info.get("session") if isinstance(session_info.get("session"), dict) else {}
        session_name = session.get("name") or plan.name
        session_id = session.get("id")
        if session_id:
            lines.append(f"Session: {session_name} ({session_id})")
        else:
            lines.append(f"Session: {session_name}")
        materialization = session_info.get("workspace_materialization")
        if isinstance(materialization, dict):
            action = materialization.get("action")
            path = materialization.get("path")
            if action and path:
                lines.append(f"Workspace materialization: {action} at {path}")
    return "\n".join(lines)


def _completed_resource_tools(transcript: list[dict[str, Any]]) -> set[str]:
    completed: set[str] = set()
    for entry in transcript or []:
        if not isinstance(entry, dict):
            continue
        tool = str(entry.get("tool") or "")
        if tool not in {"pac_create_workspace_profile", "pac_create_session"}:
            continue
        observation = str(entry.get("observation") or "")
        failed = '"ok": false' in observation.lower() or "DENIED:" in observation or "failed" in observation.lower()
        if not failed:
            completed.add(tool)
    return completed


def _last_tool_payload(transcript: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    for entry in reversed(transcript or []):
        if not isinstance(entry, dict) or entry.get("tool") != tool_name:
            continue
        try:
            payload = json.loads(str(entry.get("observation") or "{}"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}
