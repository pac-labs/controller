from __future__ import annotations

import json
from datetime import datetime, timezone
from shlex import join as shlex_join
from typing import Any, Awaitable, Callable

from ..checkpoint import load_latest_checkpoint, list_checkpoints
from ..config import AppConfig
from ..models import Session, Task, TaskStatus
from ..agent_events import AgentEvents
from ..session_commands import parse_session_slash_command, slash_help_text
from ..model_switch import model_options_text, switch_session_model
from ..store import store
from ..subagents import spawn_pi_dev_subagent
from ..subagent_chains import start_subagent_chain, import_subagent_summaries


async def try_execute_task_control_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    execute_tool_fn: Callable[[Session, Task, str, dict[str, Any], AppConfig], Awaitable[tuple[str, bool]]],
    get_run_agent_loop_fn: Callable[[], Any],
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    if tool == "spawn_subagent":
        instruction = str(inp.get("instruction") or inp.get("prompt") or "").strip()
        profile_key = str(inp.get("profile") or inp.get("kind") or "").strip() or None
        spawned = await spawn_pi_dev_subagent(
            session,
            task,
            instruction,
            config,
            get_run_agent_loop_fn(),
            profile_key=profile_key,
        )
        child_session = spawned["session"]
        child_task = spawned["task"]
        profile = spawned.get("profile")
        return json.dumps({
            "ok": True,
            "message": spawned["message"],
            "subagent_session_id": child_session.id,
            "subagent_task_id": child_task.id,
            "profile": getattr(profile, "key", profile_key or "general"),
            "display_name": getattr(profile, "display_name", "Subagent"),
            "turn_budget": getattr(profile, "turn_budget", None),
            "locked_tools": list(child_session.tools or []),
        }, indent=2), False


    if tool == "run_subagent_chain":
        instruction = str(inp.get("instruction") or inp.get("prompt") or task.prompt or "").strip()
        raw_profiles = inp.get("profiles") if isinstance(inp.get("profiles"), list) else None
        profiles = [str(item).strip() for item in raw_profiles if str(item).strip()] if raw_profiles else None
        started = await start_subagent_chain(
            session,
            task,
            instruction,
            config,
            get_run_agent_loop_fn(),
            profiles=profiles,
            chain_name=str(inp.get("chain") or "code_change"),
        )
        return json.dumps(started, indent=2), False

    if tool == "import_subagent_summary":
        imported = import_subagent_summaries(session, task, source_task_id=str(inp.get("parent_task_id") or inp.get("task_id") or "").strip() or None)
        return json.dumps(imported, indent=2), False

    if tool == "slash_command":
        parsed = parse_session_slash_command(str(inp.get("command") or ""))
        if not parsed:
            return "Invalid slash command input", False
        if parsed.get("error"):
            return parsed["error"], False
        if parsed["kind"] == "help":
            return slash_help_text(), False
        if parsed["kind"] == "compact":
            task.metadata["_compact_now"] = True
            return "Context compaction requested.", False
        if parsed["kind"] == "model":
            selector = str(parsed.get("selector") or "").strip()
            if not selector:
                return model_options_text(config, session), False
            result = switch_session_model(
                config,
                session,
                selector,
                task=task,
                role=str(parsed.get("role") or "session"),
                fallback_selectors=parsed.get("fallback") or [],
                source="slash_command_tool",
            )
            return json.dumps(result.to_dict(), indent=2), False
        if parsed["kind"] == "subagent_chain":
            started = await start_subagent_chain(
                session,
                task,
                str(parsed.get("instruction") or ""),
                config,
                get_run_agent_loop_fn(),
                profiles=parsed.get("profiles") or None,
                chain_name=str(parsed.get("chain") or "code_change"),
            )
            return json.dumps(started, indent=2), False
        if parsed["kind"] == "subagent":
            spawned = await spawn_pi_dev_subagent(
                session,
                task,
                str(parsed.get("instruction") or ""),
                config,
                get_run_agent_loop_fn(),
                profile_key=str(parsed.get("profile") or "") or None,
            )
            child_session = spawned["session"]
            child_task = spawned["task"]
            return f"{spawned['message']} Child task: {child_task.id}. Child session: {child_session.id}.", False
        if parsed["kind"] == "tool":
            shell_tool = parsed.get("tool") or ""
            shell_args = [str(a) for a in (parsed.get("args") or [])]
            return await execute_tool_fn(session, task, "shell", {"command": shlex_join([shell_tool, *shell_args])}, config)

    if tool == "resume_task":
        target_task_id = str(inp.get("task_id") or "").strip()
        if not target_task_id:
            return "resume_task requires task_id", False

        resumed_task = store.get_task(target_task_id)
        if not resumed_task:
            return f"Task not found: {target_task_id}", False

        checkpoint = load_latest_checkpoint(resumed_task.session_id)
        if not checkpoint:
            return f"No checkpoint found for session {resumed_task.session_id}", False

        if checkpoint.task_id != target_task_id:
            return f"Checkpoint session mismatch: expected {target_task_id}, got {checkpoint.task_id}", False

        resumed_task.metadata["checkpoint_seq"] = checkpoint.checkpoint_seq
        resumed_task.metadata["checkpoint_step"] = checkpoint.step
        resumed_task.metadata["checkpoint_at"] = checkpoint.checkpoint_at
        resumed_task.metadata["resumed_from_checkpoint"] = True

        resumed_task.status = TaskStatus.running

        store.add_task(resumed_task)
        AgentEvents(session, resumed_task).emit(
            "task_resumed",
            f"Task resumed from checkpoint seq={checkpoint.checkpoint_seq} step={checkpoint.step}",
            {"task_id": target_task_id, "checkpoint_seq": checkpoint.checkpoint_seq, "checkpoint_step": checkpoint.step},
        )

        result = {
            "task_id": target_task_id,
            "resumed": True,
            "checkpoint_seq": checkpoint.checkpoint_seq,
            "checkpoint_step": checkpoint.step,
            "checkpoint_at": datetime.fromtimestamp(checkpoint.checkpoint_at, timezone.utc).isoformat().replace("+00:00", "Z"),
            "rolling_summary": checkpoint.rolling_summary[:500],
            "transcript_len": checkpoint.transcript_len,
            "prompt": checkpoint.prompt[:200],
        }
        return json.dumps(result, indent=2), False

    if tool == "list_task_checkpoints":
        target_task_id = str(inp.get("task_id") or "").strip()
        if not target_task_id:
            return "list_task_checkpoints requires task_id", False

        t = store.get_task(target_task_id)
        if not t:
            return f"Task not found: {target_task_id}", False

        checkpoints = list_checkpoints(t.session_id)

        return json.dumps({
            "task_id": target_task_id,
            "session_id": t.session_id,
            "checkpoints": checkpoints,
            "count": len(checkpoints),
        }, indent=2)[:8000], False

    if tool == "clear_checkpoints":
        target_session_id = str(inp.get("session_id") or "").strip()
        if not target_session_id:
            return "clear_checkpoints requires session_id", False
        from ..checkpoint import delete_checkpoints
        count = delete_checkpoints(target_session_id)
        return json.dumps({"session_id": target_session_id, "deleted": count}), False

    # ---- auto_approve: view or modify auto-approve rules ----

    if tool == "auto_approve":
        mode = str(inp.get("mode") or "list").strip().lower()
        if mode == "list":
            from ..auto_approve import get_approval_rules
            rules = get_approval_rules()
            return json.dumps({"rules": rules, "count": len(rules)}), False
        if mode == "add":
            rule = {
                "tool": str(inp.get("tool") or "").strip() or None,
                "command_pattern": str(inp.get("command_pattern") or "").strip() or None,
                "path_pattern": str(inp.get("path_pattern") or "").strip() or None,
                "mode": str(inp.get("mode_key") or "").strip() or None,
            }
            if not any(v for v in rule.values()):
                return "auto_approve add requires at least one pattern field", False
            from ..auto_approve import DEFAULT_RULES
            DEFAULT_RULES.append(rule)
            events.auto_approve_rule_added(rule)
            return json.dumps({"ok": True, "rule": rule, "total_rules": len(DEFAULT_RULES)}), False
        return f"auto_approve: unknown mode {mode}", False

    # ---- PTY shell tools ----

    return None
