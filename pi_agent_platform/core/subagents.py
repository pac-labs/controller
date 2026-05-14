from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .config import AppConfig
from .models import Event, Session, Task
from .providers import effective_context
from .store import store


async def spawn_pi_dev_subagent(
    parent_session: Session,
    parent_task: Task,
    instruction: str,
    config: AppConfig,
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
) -> dict[str, Any]:
    prompt = (instruction or "").strip() or "Carry out one narrowly scoped subtask that supports the parent session."
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
    child_session = Session(
        name=f"{parent_session.name or parent_session.id} / subagent",
        agent_profile=parent_task.metadata.get("agent_profile") or parent_session.agent_profile,
        permission_profile=parent_session.permission_profile,
        context_mode=parent_session.context_mode,
        workspace=parent_session.workspace.model_copy(deep=True),
        workspace_path=parent_session.workspace_path,
        model=parent_task.metadata.get("model") or parent_session.model,
        tools=list(parent_session.tools),
        metadata={
            **(parent_session.metadata or {}),
            "subagent": True,
            "parent_session_id": parent_session.id,
            "parent_task_id": parent_task.id,
            "root_session_id": root_session_id,
            "agent_enabled": True,
            "execution_mode": "pi.dev",
            "preferred_execution_mode": task_execution_mode,
            "preferred_endpoint": preferred_endpoint,
            "endpoint_locked": bool(preferred_endpoint),
            "pi_dev_backed": True,
        },
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
        },
    )
    store.add_session(child_session)
    profile = config.agent_profiles.get(child_session.agent_profile or "")
    store.add_event(
        Event(
            session_id=child_session.id,
            type="session_created",
            message="Subagent session created",
            data={
                "workspace_path": child_session.workspace_path,
                "agent_profile": child_session.agent_profile,
                "permission_profile": child_session.permission_profile,
                "context_mode": child_session.context_mode,
                "endpoint": child_session.metadata.get("preferred_endpoint"),
                "endpoint_locked": child_session.metadata.get("endpoint_locked"),
                "agent_enabled": True,
                "execution_mode": child_session.metadata.get("execution_mode", "pi.dev"),
                "effective_context": effective_context(config, child_session.model, profile.context_profile if profile else child_session.context_mode),
                "subagent": True,
                "parent_session_id": parent_session.id,
                "parent_task_id": parent_task.id,
            },
        )
    )
    store.add_task(child_task)
    store.add_event(
        Event(
            session_id=child_session.id,
            task_id=child_task.id,
            type="user_message",
            message=prompt,
            data={
                "role": "user",
                "model": child_session.model,
                "session_model": child_session.model,
                "endpoint_id": preferred_endpoint,
                "command": None,
                "execution_mode": task_execution_mode,
                "stored": True,
                "subagent": True,
                "parent_session_id": parent_session.id,
                "parent_task_id": parent_task.id,
            },
        )
    )
    store.add_event(
        Event(
            session_id=child_session.id,
            task_id=child_task.id,
            type="task_queued",
            message="Subagent task queued",
            data={
                "role": "user",
                "model": child_session.model,
                "session_model": child_session.model,
                "endpoint_id": preferred_endpoint,
                "execution_mode": task_execution_mode,
                "stored": True,
                "internal": True,
                "agent_enabled": True,
                "subagent": True,
            },
        )
    )
    store.add_event(
        Event(
            session_id=child_session.id,
            task_id=child_task.id,
            type="agent_routing",
            message="Routed to subagent",
            data={
                "agent_profile": child_session.agent_profile,
                "model": child_session.model,
                "endpoint_id": preferred_endpoint,
                "requested_command": None,
                "subagent": True,
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
            message=f"Spawned pi.dev subagent: {child_session.name}",
            data={
                "subagent_session_id": child_session.id,
                "subagent_task_id": child_task.id,
                "instruction": prompt,
                "model": child_session.model,
                "agent_profile": child_session.agent_profile,
                "endpoint_id": preferred_endpoint,
                "execution_mode": task_execution_mode,
                "timeline": {
                    "title": "Subagent started",
                    "summary": prompt,
                    "fields": {
                        "Session": child_session.id,
                        "Task": child_task.id,
                        "Model": child_session.model,
                        "Profile": child_session.agent_profile or "-",
                        "Endpoint": preferred_endpoint or "-",
                        "Mode": "pi.dev",
                    },
                },
            },
        )
    )
    asyncio.create_task(run_agent_loop_fn(child_session, child_task, config))
    return {
        "session": child_session,
        "task": child_task,
        "message": f"Spawned pi.dev subagent session {child_session.id} on {preferred_endpoint or 'the session default endpoint'}.",
    }
