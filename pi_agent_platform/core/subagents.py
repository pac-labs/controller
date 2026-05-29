from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .config import AppConfig
from .models import Event, Session, Task
from .providers import effective_context
from .store import store
from .subagent_profiles import (
    SubAgentProfile,
    available_subagent_tools,
    select_subagent_profile,
    subagent_prompt,
    resolve_subagent_model,
)


async def spawn_pi_dev_subagent(
    parent_session: Session,
    parent_task: Task,
    instruction: str,
    config: AppConfig,
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
    *,
    profile_key: str | None = None,
    auto_start: bool = True,
) -> dict[str, Any]:
    specialist = select_subagent_profile(instruction, profile_key)
    prompt = subagent_prompt(specialist, instruction)
    root_session_id = (
        str(parent_session.metadata.get("root_session_id") or "").strip()
        or str(parent_session.metadata.get("parent_session_id") or "").strip()
        or parent_session.id
    )
    preferred_endpoint = (
        parent_task.metadata.get("runner_id")
        or parent_session.metadata.get("preferred_endpoint")
        or parent_task.metadata.get("target_runner_id")
    )
    task_execution_mode = (
        parent_task.metadata.get("execution_mode")
        or parent_session.metadata.get("preferred_execution_mode")
        or "pi_container"
    )
    locked_tools = available_subagent_tools(config, specialist, parent_session.tools)
    child_model = resolve_subagent_model(config, parent_session, parent_task, specialist)
    base_metadata = {
        **(parent_session.metadata or {}),
        "subagent": True,
        "subagent_profile": specialist.key,
        "subagent_display_name": specialist.display_name,
        "subagent_turn_budget": specialist.turn_budget,
        "subagent_read_only": specialist.read_only,
        "subagent_plan_only": specialist.plan_only,
        "parent_session_id": parent_session.id,
        "parent_task_id": parent_task.id,
        "root_session_id": root_session_id,
        "agent_enabled": True,
        "execution_mode": "pi.dev",
        "preferred_execution_mode": task_execution_mode,
        "preferred_endpoint": preferred_endpoint,
        "endpoint_locked": bool(preferred_endpoint),
        "pi_dev_backed": True,
        "locked_tools": locked_tools,
        "max_agent_steps": specialist.turn_budget,
        "plan_mode": "read-only" if (specialist.read_only or specialist.plan_only) else None,
        "preferred_model_role": specialist.preferred_model_role,
        "parent_importable_summary": True,
    }
    child_session = Session(
        name=f"{parent_session.name or parent_session.id} / {specialist.display_name}",
        agent_profile=parent_task.metadata.get("agent_profile") or parent_session.agent_profile,
        permission_profile=parent_session.permission_profile,
        context_mode=parent_session.context_mode,
        workspace=parent_session.workspace.model_copy(deep=True),
        workspace_path=parent_session.workspace_path,
        model=child_model,
        tools=locked_tools,
        metadata=base_metadata,
    )
    child_task = Task(
        session_id=child_session.id,
        prompt=prompt,
        metadata={
            "agent_loop": True,
            "agent_enabled": True,
            "routing": "subagent",
            "parent_session_id": parent_session.id,
            "parent_task_id": parent_task.id,
            "root_session_id": root_session_id,
            "runner_id": preferred_endpoint,
            "endpoint_locked": bool(preferred_endpoint),
            "execution_mode": task_execution_mode,
            "spawned_by": parent_task.metadata.get("slash_command") or "subagent",
            "pi_dev_backed": True,
            "subagent_instruction": instruction,
            "subagent_profile": specialist.key,
            "subagent_display_name": specialist.display_name,
            "subagent_turn_budget": specialist.turn_budget,
            "subagent_read_only": specialist.read_only,
            "subagent_plan_only": specialist.plan_only,
            "locked_tools": locked_tools,
            "max_agent_steps": specialist.turn_budget,
            "plan_mode": "read-only" if (specialist.read_only or specialist.plan_only) else None,
            "model": child_model,
            "preferred_model_role": specialist.preferred_model_role,
        },
    )
    store.add_session(child_session)
    agent_profile = config.agent_profiles.get(child_session.agent_profile or "")
    store.add_event(
        Event(
            session_id=child_session.id,
            type="session_created",
            message=f"{specialist.display_name} subagent session created",
            data={
                "workspace_path": child_session.workspace_path,
                "agent_profile": child_session.agent_profile,
                "permission_profile": child_session.permission_profile,
                "context_mode": child_session.context_mode,
                "endpoint": child_session.metadata.get("preferred_endpoint"),
                "endpoint_locked": child_session.metadata.get("endpoint_locked"),
                "agent_enabled": True,
                "execution_mode": child_session.metadata.get("execution_mode", "pi.dev"),
                "effective_context": effective_context(
                    config,
                    child_session.model,
                    agent_profile.context_profile if agent_profile else child_session.context_mode,
                ),
                "subagent": True,
                "subagent_profile": specialist.key,
                "subagent_display_name": specialist.display_name,
                "turn_budget": specialist.turn_budget,
                "locked_tools": locked_tools,
                "parent_session_id": parent_session.id,
                "parent_task_id": parent_task.id,
            },
        )
    )
    store.add_task(child_task)
    _emit_child_event(child_session, child_task, "user_message", prompt, specialist, preferred_endpoint, task_execution_mode, parent_session, parent_task)
    _emit_child_event(child_session, child_task, "task_queued", "Subagent task queued", specialist, preferred_endpoint, task_execution_mode, parent_session, parent_task, internal=True)
    store.add_event(
        Event(
            session_id=child_session.id,
            task_id=child_task.id,
            type="agent_routing",
            message=f"Routed to {specialist.display_name} subagent",
            data={
                "agent_profile": child_session.agent_profile,
                "model": child_model,
                "endpoint_id": preferred_endpoint,
                "requested_command": None,
                "subagent": True,
                "subagent_profile": specialist.key,
                "subagent_display_name": specialist.display_name,
                "parent_session_id": parent_session.id,
                "parent_task_id": parent_task.id,
            },
        )
    )
    store.add_event(
        Event(
            session_id=parent_session.id,
            task_id=parent_task.id,
            type="subagent_started",
            message=f"Spawned {specialist.display_name} subagent: {child_session.name}",
            data={
                "subagent_session_id": child_session.id,
                "subagent_task_id": child_task.id,
                "subagent_profile": specialist.key,
                "subagent_display_name": specialist.display_name,
                "instruction": prompt,
                "model": child_model,
                "agent_profile": child_session.agent_profile,
                "endpoint_id": preferred_endpoint,
                "execution_mode": task_execution_mode,
                "turn_budget": specialist.turn_budget,
                "locked_tools": locked_tools,
                "timeline": {
                    "title": f"{specialist.display_name} subagent started",
                    "summary": str(instruction or prompt)[:500],
                    "fields": {
                        "Session": child_session.id,
                        "Task": child_task.id,
                        "Model": child_model,
                        "Profile": child_session.agent_profile or "-",
                        "Endpoint": preferred_endpoint or "-",
                        "Mode": f"{specialist.display_name} / pi.dev",
                        "Turn budget": str(specialist.turn_budget),
                    },
                },
            },
        )
    )
    if auto_start:
        run_task = asyncio.create_task(
            _run_child_and_report(run_agent_loop_fn, child_session, child_task, config, parent_session, parent_task, specialist)
        )
        child_task.metadata["asyncio_task"] = str(id(run_task))
        store.add_task(child_task)
    return {
        "session": child_session,
        "task": child_task,
        "profile": specialist,
        "model": child_model,
        "message": f"Spawned {specialist.display_name} subagent session {child_session.id} on {preferred_endpoint or 'the session default endpoint'}.",
    }


def _emit_child_event(
    child_session: Session,
    child_task: Task,
    event_type: str,
    message: str,
    specialist: SubAgentProfile,
    preferred_endpoint: str | None,
    execution_mode: str | None,
    parent_session: Session,
    parent_task: Task,
    *,
    internal: bool = False,
) -> None:
    store.add_event(
        Event(
            session_id=child_session.id,
            task_id=child_task.id,
            type=event_type,
            message=message,
            data={
                "role": "user",
                "model": child_session.model,
                "session_model": child_session.model,
                "endpoint_id": preferred_endpoint,
                "command": None,
                "execution_mode": execution_mode,
                "stored": True,
                "internal": internal,
                "agent_enabled": True,
                "subagent": True,
                "subagent_profile": specialist.key,
                "subagent_display_name": specialist.display_name,
                "turn_budget": specialist.turn_budget,
                "locked_tools": list(child_session.tools or []),
                "parent_session_id": parent_session.id,
                "parent_task_id": parent_task.id,
            },
        )
    )


async def _run_child_and_report(
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
    child_session: Session,
    child_task: Task,
    config: AppConfig,
    parent_session: Session,
    parent_task: Task,
    specialist: SubAgentProfile,
) -> None:
    try:
        completed = await run_agent_loop_fn(child_session, child_task, config)
        summary = str(completed.output or completed.error or "").strip()
        status = getattr(completed.status, "value", str(completed.status))
        imported = list(parent_task.metadata.get("subagent_summaries") or [])
        entry = {
            "profile": specialist.key,
            "display_name": specialist.display_name,
            "session_id": child_session.id,
            "task_id": child_task.id,
            "status": status,
            "summary": summary[:4000],
        }
        imported.append(entry)
        parent_task.metadata["subagent_summaries"] = imported[-20:]
        store.add_task(parent_task)
        store.add_event(
            Event(
                session_id=parent_session.id,
                task_id=parent_task.id,
                type="subagent_completed",
                message=f"{specialist.display_name} subagent {status}: {summary[:300]}",
                data={
                    "subagent_session_id": child_session.id,
                    "subagent_task_id": child_task.id,
                    "subagent_profile": specialist.key,
                    "subagent_display_name": specialist.display_name,
                    "status": status,
                    "summary": summary[:4000],
                    "importable": True,
                    "timeline": {
                        "title": f"{specialist.display_name} subagent completed",
                        "summary": summary[:500],
                        "fields": {
                            "Session": child_session.id,
                            "Task": child_task.id,
                            "Status": status,
                            "Turn budget": str(specialist.turn_budget),
                        },
                    },
                },
            )
        )
    except Exception as exc:
        store.add_event(
            Event(
                session_id=parent_session.id,
                task_id=parent_task.id,
                type="subagent_failed",
                message=f"{specialist.display_name} subagent failed: {exc}",
                data={
                    "subagent_session_id": child_session.id,
                    "subagent_task_id": child_task.id,
                    "subagent_profile": specialist.key,
                    "subagent_display_name": specialist.display_name,
                    "error": str(exc),
                },
            )
        )


async def run_spawned_subagent_and_report(
    spawned: dict[str, Any],
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
    config: AppConfig,
    parent_session: Session,
    parent_task: Task,
) -> None:
    profile = spawned.get("profile")
    if not isinstance(profile, SubAgentProfile):
        raise ValueError("spawned subagent has no profile")
    await _run_child_and_report(
        run_agent_loop_fn,
        spawned["session"],
        spawned["task"],
        config,
        parent_session,
        parent_task,
        profile,
    )
