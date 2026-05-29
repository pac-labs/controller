from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..auto_approve import should_auto_approve
from ..models import TaskStatus
from ..runtime import command_policy
from ..store import store
from .permission_guard import PermissionGuard
from .pipeline_policy import permission_class_for_tool

PIPELINE_APPROVED_KEY = "__pac_pipeline_approved"


@dataclass(slots=True)
class ApprovalDecision:
    state: str
    reason: str | None = None
    permission_class: str | None = None

    @property
    def allowed(self) -> bool:
        return self.state == "allow"

    @property
    def denied(self) -> bool:
        return self.state == "deny"

    @property
    def needs_approval(self) -> bool:
        return self.state == "ask"


def command_text(tool: str, inp: dict[str, Any]) -> str:
    if tool in {"shell", "shell_bg"}:
        return str(inp.get("command") or "").strip()
    return ""


def approval_input(inp: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in (inp or {}).items() if key != PIPELINE_APPROVED_KEY}


def approval_message(tool: str, inp: dict[str, Any], reason: str | None) -> str:
    clean = approval_input(inp)
    if tool in {"shell", "shell_bg"}:
        return f"Agent wants to run: {clean.get('command') or ''}"
    if tool == "write_file":
        return f"Agent wants to write file: {clean.get('path') or ''}"
    if tool == "edit_file":
        return f"Agent wants to edit file: {clean.get('path') or ''}"
    if tool == "web_fetch":
        return f"Agent wants to fetch URL: {clean.get('url') or ''}"
    if tool == "web_search":
        return f"Agent wants to search web: {clean.get('query') or ''}"
    if reason:
        return f"Agent wants to run {tool}: {reason}"
    return f"Agent wants to run {tool}"


def approval_data(tool: str, inp: dict[str, Any], reason: str | None, permission_class: str | None) -> dict[str, Any]:
    clean = approval_input(inp)
    data: dict[str, Any] = {
        "tool": tool,
        "reason": reason,
        "permission_class": permission_class,
    }
    for key in ("path", "url", "query", "command", "name"):
        if key in clean:
            data[key] = clean.get(key)
    return data


def decide_approval(tool: str, inp: dict[str, Any], session: Any, config: Any, permission: Any) -> ApprovalDecision:
    if session.permission_profile == "full-control":
        return ApprovalDecision("allow")
    guard = PermissionGuard(permission)
    if tool == "shell":
        decision, reason = command_policy(command_text(tool, inp), session, config)
        if decision == "deny":
            return ApprovalDecision("deny", reason, "shell")
        if decision == "ask":
            return ApprovalDecision("ask", reason, "shell")
        return ApprovalDecision("allow", reason, "shell")
    if tool == "shell_bg":
        decision, reason = command_policy(command_text(tool, inp), session, config)
        if decision == "deny":
            return ApprovalDecision("deny", reason, "shell")
        if decision == "ask":
            return ApprovalDecision("ask", reason, "shell")
        return ApprovalDecision("allow", reason, "shell")
    permission_class = permission_class_for_tool(tool, config)
    if permission_class and guard.level(permission_class) == "ask":
        return ApprovalDecision("ask", f"{permission_class} access requires approval by permission profile", permission_class)
    return ApprovalDecision("allow")


def mark_pipeline_approved(inp: dict[str, Any]) -> None:
    inp[PIPELINE_APPROVED_KEY] = True


def is_pipeline_approved(inp: dict[str, Any]) -> bool:
    return bool((inp or {}).get(PIPELINE_APPROVED_KEY))


def should_pause_for_approval(tool: str, inp: dict[str, Any], session: Any, task: Any, config: Any, permission: Any) -> tuple[bool, str | None, dict[str, Any]]:
    decision = decide_approval(tool, inp, session, config, permission)
    if decision.denied:
        return False, f"DENIED: {decision.reason or 'Tool call denied by policy'}", {}
    if decision.allowed:
        mark_pipeline_approved(inp)
        return False, None, {}

    approved, auto_reason = should_auto_approve(tool, approval_input(inp))
    if approved:
        mark_pipeline_approved(inp)
        return False, auto_reason, {"auto_approved": True, "permission_class": decision.permission_class}

    task.status = TaskStatus.approval_required
    task.metadata["agent_loop"] = True
    task.metadata["pending_tool"] = {"tool": tool, "input": approval_input(inp)}
    store.add_task(task)
    return True, decision.reason, approval_data(tool, inp, decision.reason, decision.permission_class)
