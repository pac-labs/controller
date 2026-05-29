from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..models import Event, Session, Task, TaskStatus, now_utc
from ..observability_store import finish_span, record_metric, start_span
from .catalog import get_playbook
from .conditions import step_condition_passes
from .schema import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from .state import load_run, save_run

RunAgentLoop = Callable[[Session, Task, Any], Awaitable[None]]


def _coerce_parameters(playbook: Playbook, raw: dict[str, Any]) -> dict[str, Any]:
    values = dict(raw or {})
    result: dict[str, Any] = {}
    for param in playbook.parameters:
        value = values.get(param.name, param.default)
        if value is None and param.required:
            raise ValueError(f"Missing required playbook parameter: {param.name}")
        if value is None:
            continue
        if param.enum and value not in param.enum:
            raise ValueError(f"Invalid value for {param.name}; expected one of {param.enum}")
        if param.type == "integer":
            value = int(value)
        elif param.type == "number":
            value = float(value)
        elif param.type == "boolean":
            value = bool(value) if not isinstance(value, str) else value.lower() in {"1", "true", "yes", "on"}
        elif param.type == "array" and not isinstance(value, list):
            raise ValueError(f"Parameter {param.name} must be an array")
        elif param.type == "object" and not isinstance(value, dict):
            raise ValueError(f"Parameter {param.name} must be an object")
        elif param.type == "string":
            value = str(value)
        result[param.name] = value
    for key, value in values.items():
        result.setdefault(key, value)
    return result


def _format_value(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        try:
            return value.format(**params)
        except Exception:
            return value
    if isinstance(value, dict):
        return {k: _format_value(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_format_value(v, params) for v in value]
    return value


def _dependencies_done(step: PlaybookStep, run: PlaybookRun) -> bool:
    statuses = {item.id: item.status for item in run.steps}
    return all(statuses.get(dep) in {"completed", "skipped"} for dep in step.depends_on)


def _run_step(run: PlaybookRun, step_id: str) -> PlaybookRunStep:
    for item in run.steps:
        if item.id == step_id:
            return item
    raise KeyError(step_id)


def _metric(name: str, value: float = 1.0, **labels: Any) -> None:
    record_metric(f"playbook.{name}", value, kind="counter", component="playbooks", labels={k: str(v) for k, v in labels.items() if v is not None})


def _emit(store: Any, run: PlaybookRun, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    session_id = run.session_id or "system"
    store.add_event(Event(session_id=session_id, task_id=run.task_id, type=event_type, message=message, data={"playbook_run_id": run.id, "playbook_id": run.playbook_id, **(data or {})}))


def _nested_value(data: Any, path: str) -> Any:
    current = data
    for part in path.split('.'):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
    return current


def _json_payload(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {"text": value}


def _record_exports(run: PlaybookRun, step: PlaybookStep, state: PlaybookRunStep, value: Any) -> None:
    payload = _json_payload(value)
    run.outputs[step.id] = payload
    if state.task_id:
        run.outputs[f"{step.id}.task_id"] = state.task_id
    for name, source_path in step.export.items():
        exported = _nested_value(payload, source_path)
        run.outputs[name] = exported
        run.parameters.setdefault(name, exported)


def _target_session_for_step(step: PlaybookStep, run: PlaybookRun, default: Session | None, store: Any) -> Session | None:
    if not step.target_session_from:
        return default
    raw = run.outputs.get(step.target_session_from) or _nested_value(run.outputs, step.target_session_from)
    session_id = str(raw or "").strip()
    return store.get_session(session_id) if session_id else default


def create_run(playbook: Playbook, parameters: dict[str, Any], *, session: Session | None = None, task: Task | None = None) -> PlaybookRun:
    params = _coerce_parameters(playbook, parameters)
    run = PlaybookRun(
        playbook_id=playbook.id,
        title=playbook.title,
        session_id=session.id if session else None,
        task_id=task.id if task else None,
        parameters=params,
        steps=[PlaybookRunStep(id=step.id, title=step.title or step.id) for step in playbook.steps],
    )
    _metric("run_created", playbook_id=playbook.id)
    return save_run(run)


async def advance_run(run: PlaybookRun, config: Any, store: Any, run_agent_loop: RunAgentLoop | None = None) -> PlaybookRun:
    if run.status == "cancelled":
        return run
    playbook = get_playbook(config, run.playbook_id)
    session = store.get_session(run.session_id) if run.session_id else None
    parent_task = store.get_task(run.task_id) if run.task_id else None
    run.status = "running"
    run_span = start_span("playbook.run", component="playbooks", attributes={"playbook_id": run.playbook_id, "run_id": run.id})
    _metric("run_started", playbook_id=run.playbook_id)
    _emit(store, run, "playbook_run_started", f"Playbook running: {run.title}")

    progressed = True
    while progressed and run.status != "cancelled":
        progressed = False
        for step in playbook.steps:
            state = _run_step(run, step.id)
            if state.status != "pending" or not _dependencies_done(step, run):
                continue
            if not step_condition_passes(step, run):
                state.status = "skipped"
                state.completed_at = state.completed_at or now_utc()
                state.message = "Condition did not match"
                _emit(store, run, "playbook_step_skipped", f"Skipped playbook step: {step.id}", {"step_id": step.id})
                progressed = True
                save_run(run)
                continue
            if step.gate:
                state.status = "waiting"
                state.message = step.gate.message or f"Waiting for {step.gate.type}"
                run.status = "waiting"
                run.waiting_step_id = step.id
                run.waiting_gate = step.gate
                _emit(store, run, "playbook_gate_waiting", state.message, {"step_id": step.id, "gate": step.gate.model_dump(mode="json")})
                return save_run(run)
            await _execute_step(run, step, state, config, store, session, parent_task, run_agent_loop)
            progressed = True
            save_run(run)
            if state.status == "failed":
                run.status = "failed"
                run.error = state.message
                _emit(store, run, "playbook_run_failed", state.message or "Playbook failed", {"step_id": step.id})
                finish_span(run_span, status="error", attributes={"status": "failed", "step_id": step.id})
                return save_run(run)
    if run.status != "cancelled" and all(item.status in {"completed", "skipped"} for item in run.steps):
        run.status = "completed"
        run.waiting_step_id = None
        run.waiting_gate = None
        _metric("run_completed", playbook_id=run.playbook_id)
        _emit(store, run, "playbook_run_completed", f"Playbook completed: {run.title}")
    finish_span(run_span, status="ok" if run.status == "completed" else str(run.status), attributes={"status": run.status})
    return save_run(run)


async def _execute_step(run: PlaybookRun, step: PlaybookStep, state: PlaybookRunStep, config: Any, store: Any, session: Session | None, parent_task: Task | None, run_agent_loop: RunAgentLoop | None) -> None:
    state.status = "running"
    state.started_at = state.started_at or now_utc()
    step_span = start_span("playbook.step", component="playbooks", attributes={"playbook_id": run.playbook_id, "run_id": run.id, "step_id": step.id, "action": step.action})
    _metric("step_started", playbook_id=run.playbook_id, step_id=step.id, action=step.action)
    _emit(store, run, "playbook_step_started", f"Playbook step started: {step.title or step.id}", {"step_id": step.id, "action": step.action})
    try:
        target_session = _target_session_for_step(step, run, session, store)
        if step.action == "note" or step.action == "checkpoint":
            state.output = step.prompt or step.title or step.id
        elif step.action == "tool":
            if not target_session or not parent_task:
                raise ValueError("Tool playbook steps require a parent session and task")
            inp = _format_value(step.input, run.parameters)
            from ..agent_tools.registry import execute_tool
            output, paused = await execute_tool(target_session, parent_task, step.tool or "", inp, config)
            if paused:
                state.status = "waiting"
                state.message = f"Tool {step.tool} is waiting for approval"
                run.status = "waiting"
                run.waiting_step_id = step.id
                run.checkpoint[step.id] = {"tool": step.tool, "input": inp, "paused": True}
                _emit(store, run, "playbook_step_waiting", state.message, {"step_id": step.id, "tool": step.tool})
                return
            state.output = output[-6000:] if isinstance(output, str) else str(output)
            _record_exports(run, step, state, output)
        elif step.action in {"agent_task", "subagent_chain"}:
            if not target_session or not run_agent_loop:
                raise ValueError(f"{step.action} playbook steps require an agent session")
            prompt = str(_format_value(step.prompt or "", run.parameters))
            meta = {"playbook_run_id": run.id, "playbook_step_id": step.id}
            if step.action == "subagent_chain":
                meta.update({"subagent_chain": "code_change", "subagent_instruction": prompt})
            task = Task(session_id=target_session.id, prompt=prompt, metadata=meta)
            task.status = TaskStatus.running
            store.add_task(task)
            state.task_id = task.id
            if run.status == "cancelled":
                task.metadata["stop_requested"] = True
                task.metadata["playbook_cancel_requested"] = True
                store.add_task(task)
                raise ValueError("Playbook was cancelled before the agent task started")
            await run_agent_loop(target_session, task, config)
            done = store.get_task(task.id) or task
            state.output = (done.output or done.error or "")[-6000:]
            _record_exports(run, step, state, {"task_id": task.id, "status": done.status.value, "output": state.output})
            if done.status == TaskStatus.failed:
                raise ValueError(done.error or "Agent task failed")
        state.status = "completed"
        state.completed_at = now_utc()
        state.message = "Completed"
        _metric("step_completed", playbook_id=run.playbook_id, step_id=step.id, action=step.action)
        finish_span(step_span, status="ok", attributes={"status": "completed"})
        _emit(store, run, "playbook_step_completed", f"Playbook step completed: {step.title or step.id}", {"step_id": step.id, "exports": step.export})
    except Exception as exc:
        state.status = "failed"
        state.message = str(exc)
        state.output = state.output or str(exc)
        _metric("step_failed", playbook_id=run.playbook_id, step_id=step.id, action=step.action)
        finish_span(step_span, status="error", attributes={"status": "failed", "error": str(exc)})


async def approve_run(run_id: str, config: Any, store: Any, run_agent_loop: RunAgentLoop | None = None, note: str | None = None) -> PlaybookRun:
    run = load_run(run_id)
    if not run:
        raise KeyError(f"Unknown playbook run: {run_id}")
    if run.status != "waiting" or not run.waiting_step_id:
        return run
    state = _run_step(run, run.waiting_step_id)
    state.status = "completed"
    state.message = note or "Gate approved"
    state.completed_at = now_utc()
    run.checkpoint[run.waiting_step_id] = {"approved": True, "note": note}
    run.waiting_step_id = None
    run.waiting_gate = None
    run.status = "running"
    save_run(run)
    _emit(store, run, "playbook_gate_approved", state.message or "Playbook gate approved", {"step_id": state.id})
    return await advance_run(run, config, store, run_agent_loop)


def cancel_run(run_id: str, store: Any, note: str | None = None) -> PlaybookRun:
    run = load_run(run_id)
    if not run:
        raise KeyError(f"Unknown playbook run: {run_id}")
    if run.status in {"completed", "failed", "cancelled"}:
        return run
    run.status = "cancelled"
    run.cancelled_at = now_utc()
    _metric("run_cancelled", playbook_id=run.playbook_id)
    run.waiting_step_id = None
    run.waiting_gate = None
    for step in run.steps:
        if step.status in {"pending", "running", "waiting"}:
            step.status = "skipped" if step.status == "pending" else "failed"
            step.message = note or "Cancelled"
    for task_id in [step.task_id for step in run.steps if step.task_id]:
        task = store.get_task(task_id)
        if task and task.status in {TaskStatus.queued, TaskStatus.running, TaskStatus.approval_required}:
            task.metadata["cancel_requested"] = True
            task.metadata["stop_requested"] = True
            task.metadata["stop_reason"] = "playbook_cancelled"
            task.error = note or "Cancelled by playbook run cancellation"
            store.add_task(task)
    save_run(run)
    _emit(store, run, "playbook_run_cancelled", note or f"Playbook cancelled: {run.title}", {"active_task_ids": [step.task_id for step in run.steps if step.task_id]})
    return run


def run_summary(run: PlaybookRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "playbook_id": run.playbook_id,
        "title": run.title,
        "status": run.status,
        "waiting_step_id": run.waiting_step_id,
        "waiting_gate": run.waiting_gate.model_dump(mode="json") if run.waiting_gate else None,
        "steps": [item.model_dump(mode="json") for item in run.steps],
        "parameters": run.parameters,
        "outputs": run.outputs,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
    }


def run_summary_json(run: PlaybookRun) -> str:
    return json.dumps(run_summary(run), indent=2, default=str)[:20000]
