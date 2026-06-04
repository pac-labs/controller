from __future__ import annotations

from typing import Any

from .agent_loop import run_agent_loop
from .config import AppConfig
from .models import Event, Session, SessionStatus, Task, TaskStatus
from .store import store


async def run_agent_loop_safely(session: Session, task: Task, config: AppConfig) -> Task:
    """Run the agent loop and convert unexpected crashes into task failures.

    Background-task execution otherwise leaves the task stuck in `running` when
    an unhandled exception escapes the loop before lifecycle cleanup can run.
    """

    try:
        return await run_agent_loop(session, task, config)
    except Exception as exc:
        latest_task = store.get_task(task.id) or task
        latest_session = store.get_session(session.id) or session
        latest_task.status = TaskStatus.failed
        latest_task.error = f"Agent loop crashed unexpectedly: {exc}"
        latest_task.metadata["unexpected_agent_error"] = repr(exc)
        latest_task.metadata["unexpected_agent_error_type"] = exc.__class__.__name__
        latest_session.status = SessionStatus.failed
        store.add_task(latest_task)
        store.add_session(latest_session)
        store.add_event(
            Event(
                session_id=latest_session.id,
                task_id=latest_task.id,
                type="task_failed",
                message=latest_task.error,
                data={
                    "role": "system",
                    "internal": True,
                    "visibility": "internal",
                    "error_type": exc.__class__.__name__,
                },
            )
        )
        return latest_task
