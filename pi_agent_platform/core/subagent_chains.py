from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .config import AppConfig
from .models import Event, Session, Task, TaskStatus
from .store import store
from .subagents import spawn_pi_dev_subagent, run_spawned_subagent_and_report

DEFAULT_CODE_CHANGE_CHAIN: tuple[str, ...] = ("explore", "plan", "coder", "verify")


def should_auto_start_code_chain(session: Session, task: Task, request_policy: Any | None = None) -> bool:
    meta = task.metadata or {}
    if meta.get("subagent") or meta.get("subagent_chain") or meta.get("disable_subagent_chain"):
        return False
    if (session.metadata or {}).get("subagent"):
        return False
    prompt = str(task.prompt or "").strip()
    text = f" {prompt.lower()} "
    if len(prompt) < 140 and not any(word in text for word in (" redesign ", " refactor ", " implement ", " architecture ")):
        return False
    workish = bool(getattr(request_policy, "needs_work_intent", False)) or any(
        word in text for word in (" implement ", " add ", " change ", " refactor ", " redesign ", " fix ", " build ", " wire ")
    )
    large = any(
        word in text for word in (
            " large ", " major ", " flow ", " architecture ", " pipeline ", " subsystem ",
            " across ", " several ", " multiple ", " finalize ", " end-to-end ", " full ",
        )
    )
    return workish and large


def chain_summary_from_events(session_id: str, task_id: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in store.get_events(session_id, limit=1000):
        if event.type not in {"subagent_completed", "subagent_failed", "subagent_chain_completed"}:
            continue
        if task_id and event.task_id != task_id:
            continue
        data = event.data or {}
        if event.type == "subagent_chain_completed":
            for step in data.get("summaries") or []:
                if isinstance(step, dict):
                    items.append(step)
            continue
        items.append({
            "profile": data.get("subagent_profile"),
            "display_name": data.get("subagent_display_name"),
            "session_id": data.get("subagent_session_id"),
            "task_id": data.get("subagent_task_id"),
            "status": data.get("status") or ("failed" if event.type.endswith("failed") else "completed"),
            "summary": data.get("summary") or data.get("error") or event.message,
        })
    return items[-20:]


def import_subagent_summaries(session: Session, task: Task, *, source_task_id: str | None = None) -> dict[str, Any]:
    summaries = chain_summary_from_events(session.id, source_task_id)
    existing = list(task.metadata.get("imported_subagent_summaries") or [])
    existing.extend(summaries)
    task.metadata["imported_subagent_summaries"] = existing[-30:]
    store.add_task(task)
    store.add_event(Event(
        session_id=session.id,
        task_id=task.id,
        type="subagent_summaries_imported",
        message=f"Imported {len(summaries)} subagent summaries into parent context.",
        data={
            "count": len(summaries),
            "source_task_id": source_task_id,
            "summaries": summaries,
            "timeline": {
                "title": "Subagent summaries imported",
                "summary": f"Imported {len(summaries)} child summaries for this parent task.",
                "fields": {"Imported": str(len(summaries)), "Source task": source_task_id or "current session"},
            },
        },
    ))
    return {"imported": len(summaries), "summaries": summaries}


async def start_subagent_chain(
    parent_session: Session,
    parent_task: Task,
    instruction: str,
    config: AppConfig,
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
    *,
    profiles: tuple[str, ...] | list[str] | None = None,
    chain_name: str = "code_change",
) -> dict[str, Any]:
    sequence = tuple(profiles or DEFAULT_CODE_CHANGE_CHAIN)
    parent_task.metadata["subagent_chain"] = chain_name
    parent_task.metadata["subagent_chain_profiles"] = list(sequence)
    store.add_task(parent_task)
    store.add_event(Event(
        session_id=parent_session.id,
        task_id=parent_task.id,
        type="subagent_chain_started",
        message=f"Started {chain_name} subagent chain: {' → '.join(sequence)}",
        data={
            "chain": chain_name,
            "profiles": list(sequence),
            "instruction": instruction,
            "timeline": {
                "title": "Specialist chain started",
                "summary": instruction[:500],
                "steps": [{"status": "queued", "label": profile, "detail": "Waiting to run"} for profile in sequence],
            },
        },
    ))
    run_task = asyncio.create_task(_run_chain(parent_session, parent_task, instruction, config, run_agent_loop_fn, sequence, chain_name))
    parent_task.metadata["subagent_chain_asyncio_task"] = str(id(run_task))
    store.add_task(parent_task)
    return {"ok": True, "chain": chain_name, "profiles": list(sequence), "message": f"Started {' → '.join(sequence)} specialist chain."}


async def _run_chain(
    parent_session: Session,
    parent_task: Task,
    instruction: str,
    config: AppConfig,
    run_agent_loop_fn: Callable[[Session, Task, AppConfig], Awaitable[Task]],
    sequence: tuple[str, ...],
    chain_name: str,
) -> None:
    summaries: list[dict[str, Any]] = []
    try:
        for profile in sequence:
            prior = "\n\nPrior specialist summaries:\n" + "\n\n".join(
                f"[{item.get('display_name') or item.get('profile')}] {item.get('summary', '')}" for item in summaries
            ) if summaries else ""
            delegated = f"{instruction}{prior}"
            spawned = await spawn_pi_dev_subagent(
                parent_session,
                parent_task,
                delegated,
                config,
                run_agent_loop_fn,
                profile_key=profile,
                auto_start=False,
            )
            await run_spawned_subagent_and_report(spawned, run_agent_loop_fn, config, parent_session, parent_task)
            child_task = store.get_task(spawned["task"].id) or spawned["task"]
            summary = str(child_task.output or child_task.error or "").strip()
            summaries.append({
                "profile": profile,
                "display_name": getattr(spawned.get("profile"), "display_name", profile),
                "session_id": spawned["session"].id,
                "task_id": child_task.id,
                "status": getattr(child_task.status, "value", str(child_task.status)),
                "summary": summary[:4000],
            })
        parent_task.metadata["subagent_chain_summaries"] = summaries[-20:]
        parent_task.status = TaskStatus.completed
        parent_task.output = _chain_output(chain_name, summaries)
        store.add_task(parent_task)
        store.add_event(Event(
            session_id=parent_session.id,
            task_id=parent_task.id,
            type="subagent_chain_completed",
            message=f"{chain_name} specialist chain completed.",
            data={
                "chain": chain_name,
                "summaries": summaries,
                "timeline": {
                    "title": "Specialist chain completed",
                    "summary": parent_task.output[:500] if parent_task.output else "Specialist chain completed.",
                    "steps": [
                        {"status": item.get("status") or "completed", "label": item.get("display_name") or item.get("profile"), "detail": str(item.get("summary") or "")[:300]}
                        for item in summaries
                    ],
                },
            },
        ))
        store.add_event(Event(session_id=parent_session.id, task_id=parent_task.id, type="result", message=parent_task.output or "Specialist chain completed.", data={"role": "assistant", "subagent_chain": chain_name}))
    except Exception as exc:
        parent_task.status = TaskStatus.failed
        parent_task.error = str(exc)
        store.add_task(parent_task)
        store.add_event(Event(session_id=parent_session.id, task_id=parent_task.id, type="subagent_chain_failed", message=str(exc), data={"chain": chain_name, "error": str(exc), "summaries": summaries}))


def _chain_output(chain_name: str, summaries: list[dict[str, Any]]) -> str:
    lines = [f"{chain_name} specialist chain completed."]
    for item in summaries:
        label = item.get("display_name") or item.get("profile") or "Subagent"
        status = item.get("status") or "completed"
        summary = str(item.get("summary") or "").strip().splitlines()
        lines.append(f"\n{label} ({status}):")
        lines.extend(summary[:8] or ["No summary returned."])
    return "\n".join(lines)[:8000]
