from __future__ import annotations

import json
import subprocess
from typing import Any

from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from .permission_guard import PermissionGuard


async def try_execute_git_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "git_status":
        result = subprocess.run(["git", "status", "--short", "--branch"], cwd=session.workspace_path, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr or "No git status output", False

    if tool == "git_diff":
        result = subprocess.run(["git", "diff", "--"], cwd=session.workspace_path, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr or "No diff", False

    # --- Stage 4: ops + runtime tools ---

    if tool == "auto_commit":
        if denied := permission_guard.require("shell"):
            return denied
        workspace = str(inp.get("workspace") or session.workspace_path or "")
        message = str(inp.get("message") or "").strip()
        push = bool(inp.get("push") or False)
        if not workspace:
            return "auto_commit requires workspace path", False
        from ..auto_commit import auto_commit as _ac, auto_push as _ap
        result = _ac(workspace, message, task.id, commit_message=message or None)
        if result.get("committed"):
            events.emit("auto_committed", f"Committed: {result.get('sha', '')[:12]}", result)
            if push:
                push_result = _ap(workspace)
                result["pushed"] = push_result.get("pushed")
                result["push_error"] = push_result.get("error")
            return json.dumps(result), False
        return json.dumps({"committed": False, "error": result.get("error", "unknown")}), False

    if tool == "git_changes":
        workspace = str(inp.get("workspace") or session.workspace_path or "")
        if not workspace:
            return "git_changes requires workspace path", False
        from ..auto_commit import get_git_changes
        result = get_git_changes(workspace)
        return json.dumps(result, indent=2)[:10000], False

    return None
