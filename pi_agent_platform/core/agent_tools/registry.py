from __future__ import annotations

from typing import Any

from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from ..runtime import ensure_workspace
from .artifacts import try_execute_artifact_tool
from .diagnostics import try_execute_diagnostics_tool
from .file_ops import try_execute_file_tool
from .git import try_execute_git_tool
from .memory import try_execute_memory_tool
from .model_consult import try_execute_model_consult_tool
from .pty import try_execute_pty_tool
from .shell import _run_shell, _run_tool_via_runner
from .task_control import try_execute_task_control_tool
from .web import try_execute_web_tool
from .workspace import try_execute_workspace_tool


def _normalize_tool_alias(tool: str, session: Session, config: AppConfig) -> tuple[str, dict[str, Any] | None]:
    raw = str(tool or "").strip()
    normalized = raw.lower().replace(".", "_").replace("-", "_")
    if normalized == "pi_dev_agent":
        allowed = set(session.tools or [])
        available = set(getattr(config, "tools", {}).keys())
        if (not allowed or "workspace_manifest" in allowed) and "workspace_manifest" in available:
            return "workspace_manifest", {"max_files": 300}
        if not allowed or "list_files" in allowed:
            return "list_files", {"path": "."}
    return raw, None


def _get_run_agent_loop():
    # Imported lazily to avoid a circular import: agent_loop imports this registry.
    from ..agent_loop import run_agent_loop
    return run_agent_loop


def _permission(session: Session, config: AppConfig):
    return config.permission_profiles.get(session.permission_profile)


async def execute_tool(session: Session, task: Task, tool: str, inp: dict[str, Any], config: AppConfig) -> tuple[str, bool]:
    ensure_workspace(session)
    tool, alias_input = _normalize_tool_alias(tool, session, config)
    if alias_input is not None and not inp:
        inp = alias_input
    allowed = set(session.tools)
    perm = _permission(session, config)
    if not perm:
        return f"DENIED: unknown permission profile {session.permission_profile}", False

    runner_result = await _run_tool_via_runner(session, task, tool, inp, config)
    if runner_result is not None:
        AgentEvents(session, task).tool_result(tool=tool, message=f"{tool} executed in workspace container", data={"endpoint_id": task.metadata.get("runner_id") or session.metadata.get("preferred_endpoint"), "execution_mode": "container"})
        return runner_result

    for handler in (
        lambda: try_execute_file_tool(session, task, tool, inp, config, perm),
        lambda: try_execute_workspace_tool(session, task, tool, inp, config, perm),
        lambda: try_execute_artifact_tool(session, task, tool, inp, config),
        lambda: try_execute_model_consult_tool(session, task, tool, inp, config, allowed),
        lambda: try_execute_memory_tool(session, task, tool, inp, config, allowed),
        lambda: try_execute_web_tool(session, task, tool, inp, config, perm, allowed),
        lambda: try_execute_git_tool(session, task, tool, inp, config, perm),
        lambda: try_execute_diagnostics_tool(session, task, tool, inp, config, perm),
        lambda: try_execute_task_control_tool(session, task, tool, inp, config, execute_tool, _get_run_agent_loop),
        lambda: try_execute_pty_tool(session, task, tool, inp, config, perm),
    ):
        result = await handler()
        if result is not None:
            return result

    if tool == "shell":
        if "shell" not in allowed:
            return "DENIED: shell tool is not enabled for this session", False
        return await _run_shell(session, task, str(inp.get("command") or ""), config)

    return f"Unknown tool: {tool}", False
