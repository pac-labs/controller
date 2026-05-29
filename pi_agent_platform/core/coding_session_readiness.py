from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import Event, Runner, RunnerExecutionMode, RunnerJob, RunnerJobStatus, RunnerStatus, Session, Task
from .store import store as default_store
from .workspace_bootstrap import WorkspaceBootstrapError, ensure_workspace_materialized


class CodingSessionReadinessError(RuntimeError):
    """Raised when a coding session cannot be made executable."""


READY_VERSION = 1


def is_coding_session(session: Session) -> bool:
    meta = session.metadata or {}
    return bool(meta.get("coding_session") or meta.get("ide_mode"))


def prepare_coding_session(
    session: Session,
    config: AppConfig,
    *,
    task: Task | None = None,
    store: Any = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Materialize and bind a coding session before agent/tool execution.

    A PAC coding session is usable only when three boundaries agree: the
    controller session record, the selected endpoint, and the workspace source
    checkout.  This helper turns that into an explicit readiness contract rather
    than letting the agent discover an empty workspace after the user opens the
    session.
    """

    active_store = store or default_store
    if not is_coding_session(session):
        materialization = ensure_workspace_materialized(session)
        session.metadata["workspace_materialization"] = materialization
        active_store.add_session(session)
        return _set_readiness(session, active_store, "ready", "local_workspace_ready", materialization=materialization)

    previous = session.metadata.get("coding_readiness") if isinstance(session.metadata.get("coding_readiness"), dict) else {}
    if _is_still_ready(session, previous, active_store):
        return previous

    readiness = _set_readiness(session, active_store, "preparing", "resolving_endpoint")
    runner = _resolve_runner(session, active_store)
    _require_container_runner(runner)

    session.metadata["preferred_endpoint"] = runner.id
    session.metadata["runner_id"] = runner.id
    session.metadata["endpoint_name"] = runner.name
    session.metadata["endpoint_locked"] = True
    session.metadata["agent_enabled"] = True
    session.metadata["execution_mode"] = "container"
    session.metadata["preferred_execution_mode"] = "container"
    container_image = str(session.metadata.get("container_image") or _default_container_image(session) or "").strip()
    if not container_image:
        raise CodingSessionReadinessError("Coding session has no container image configured.")
    session.metadata["container_image"] = container_image
    active_store.add_session(session)

    _emit(active_store, session, task, "endpoint_selected", {"endpoint": runner.id, "endpoint_name": runner.name})

    try:
        controller_materialization = ensure_workspace_materialized(session)
    except WorkspaceBootstrapError as exc:
        _fail_readiness(session, active_store, "source_clone_failed", str(exc), task=task)
        raise CodingSessionReadinessError(str(exc)) from exc
    session.metadata["workspace_materialization"] = controller_materialization
    active_store.add_session(session)
    _emit(active_store, session, task, "controller_workspace_prepared", controller_materialization)

    endpoint_materialization = _prepare_endpoint_workspace(
        session,
        runner,
        active_store,
        timeout_seconds=timeout_seconds,
    )
    readiness = _set_readiness(
        session,
        active_store,
        "ready",
        "agent_attached",
        materialization=controller_materialization,
        endpoint_materialization=endpoint_materialization,
        runner=runner,
    )
    _emit(active_store, session, task, "ready", readiness)
    return readiness


def _resolve_runner(session: Session, active_store: Any) -> Runner:
    endpoint_id = str(session.metadata.get("preferred_endpoint") or session.metadata.get("runner_id") or "").strip()
    if not endpoint_id:
        raise CodingSessionReadinessError("Coding session has no preferred endpoint.")
    runner = active_store.get_runner(endpoint_id) if hasattr(active_store, "get_runner") else None
    if not runner:
        raise CodingSessionReadinessError(f"Coding session endpoint not found: {endpoint_id}")
    return runner


def _require_container_runner(runner: Runner) -> None:
    if runner.status != RunnerStatus.online:
        raise CodingSessionReadinessError(f"Endpoint is not online: {runner.name} ({runner.id})")
    if not runner.allow_container_execution:
        raise CodingSessionReadinessError(f"Endpoint does not allow container execution: {runner.name} ({runner.id})")


def _prepare_endpoint_workspace(
    session: Session,
    runner: Runner,
    active_store: Any,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    if runner.metadata.get("local_control_plane"):
        return {"ok": True, "action": "local_control_plane", "path": session.workspace_path, "runner_id": runner.id}

    command = _endpoint_materialization_command(session)
    if not command:
        return {"ok": True, "action": "no_source", "path": session.workspace_path, "runner_id": runner.id}

    execution_mode = RunnerExecutionMode.host if runner.allow_host_execution else RunnerExecutionMode.container
    job = RunnerJob(
        runner_id=runner.id,
        prompt="Prepare PAC coding workspace",
        command=command,
        execution_mode=execution_mode,
        container_image=session.metadata.get("container_image") if execution_mode == RunnerExecutionMode.container else None,
        container_runtime=session.metadata.get("container_runtime", "auto"),
        workspace_path=session.workspace_path,
        session_id=session.id,
        metadata={"source": "coding_session_readiness", "workspace_url": session.workspace.url},
    )
    active_store.add_runner_job(job)
    _emit(active_store, session, None, "endpoint_workspace_prepare_queued", {"runner_job_id": job.id, "runner_id": runner.id, "execution_mode": str(execution_mode)})

    deadline = time.monotonic() + max(15, timeout_seconds)
    while time.monotonic() < deadline:
        current = active_store.get_runner_job(job.id)
        if not current:
            time.sleep(0.25)
            continue
        if current.status == RunnerJobStatus.completed:
            return {
                "ok": True,
                "action": "endpoint_git_materialized",
                "runner_id": runner.id,
                "runner_job_id": job.id,
                "path": session.workspace_path,
                "output": str(current.output or "")[-3000:],
            }
        if current.status in {RunnerJobStatus.failed, RunnerJobStatus.cancelled}:
            detail = str(current.error or current.output or "endpoint workspace preparation failed")[-3000:]
            raise CodingSessionReadinessError(detail)
        time.sleep(0.5)
    raise CodingSessionReadinessError(f"Endpoint workspace preparation timed out after {timeout_seconds}s")


def _endpoint_materialization_command(session: Session) -> str:
    url = str(session.workspace.url or "").strip()
    if not url:
        return "pwd && test -d . && find . -maxdepth 2 -mindepth 1 | head -40"
    branch = str(session.workspace.branch or "").strip()
    quoted_url = shlex.quote(url)
    branch_args = f" --branch {shlex.quote(branch)}" if branch else ""
    return "\n".join([
        "set -eu",
        "pwd",
        "if [ -d .git ]; then",
        "  git status --short --branch",
        "else",
        "  if find . -mindepth 1 -maxdepth 1 | grep -q .; then",
        "    echo \"Workspace path exists but is not an empty git checkout: $(pwd)\" >&2",
        "    exit 2",
        "  fi",
        f"  git clone{branch_args} {quoted_url} .",
        "fi",
        "test -d .git",
        "find . -maxdepth 2 -mindepth 1 | sed 's#^./##' | sort | head -80",
    ])

def _is_still_ready(session: Session, readiness: dict[str, Any], active_store: Any) -> bool:
    if readiness.get("version") != READY_VERSION or readiness.get("status") != "ready":
        return False
    if readiness.get("workspace_path") != session.workspace_path:
        return False
    if readiness.get("url") != (session.workspace.url or None):
        return False
    runner_id = str(readiness.get("runner_id") or "")
    runner = active_store.get_runner(runner_id) if runner_id and hasattr(active_store, "get_runner") else None
    return bool(runner and runner.status == RunnerStatus.online and runner.allow_container_execution)


def _set_readiness(session: Session, active_store: Any, status: str, stage: str, **extra: Any) -> dict[str, Any]:
    readiness = {
        "version": READY_VERSION,
        "status": status,
        "stage": stage,
        "workspace_path": session.workspace_path,
        "url": session.workspace.url or None,
        "branch": session.workspace.branch or None,
        **extra,
    }
    runner = extra.get("runner")
    if runner:
        readiness["runner_id"] = runner.id
        readiness["endpoint_name"] = runner.name
    elif session.metadata.get("preferred_endpoint"):
        readiness["runner_id"] = session.metadata.get("preferred_endpoint")
    session.metadata["coding_readiness"] = readiness
    active_store.add_session(session)
    return readiness


def _fail_readiness(session: Session, active_store: Any, stage: str, error: str, *, task: Task | None = None) -> dict[str, Any]:
    readiness = _set_readiness(session, active_store, "failed", stage, error=error[-3000:])
    _emit(active_store, session, task, "failed", readiness)
    return readiness


def _emit(active_store: Any, session: Session, task: Task | None, stage: str, data: dict[str, Any]) -> None:
    active_store.add_event(Event(
        session_id=session.id,
        task_id=task.id if task else None,
        type="coding_session_readiness",
        message=f"Coding session readiness: {stage}",
        data={"stage": stage, **data},
    ))


def _default_container_image(session: Session) -> str | None:
    url = str(session.workspace.url or "").lower()
    if "rust" in url or any(Path(session.workspace_path).glob("Cargo.toml")):
        return "rust:latest"
    return None
