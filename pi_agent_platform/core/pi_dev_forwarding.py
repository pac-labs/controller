from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .models import Event, Session
from .platform_home import pacp_path


def _controller_forward_file(config: AppConfig) -> Path:
    rel = str(config.controller_harness.forward_file or "pi-agent-artifacts/agent-forwarding.jsonl").strip()
    if not rel:
        rel = "pi-agent-artifacts/agent-forwarding.jsonl"
    path = Path(rel)
    if path.is_absolute():
        return path
    return pacp_path("app") / path


def _session_forward_file(session: Session, config: AppConfig) -> Path:
    workspace = Path(str(session.workspace_path or "")).expanduser()
    if workspace.exists() and workspace.is_dir():
        return workspace / "pi-agent-artifacts" / "agent-forwarding.jsonl"
    return _controller_forward_file(config)


def _session_matches_scope(session: Session, scope: str) -> bool:
    meta = session.metadata or {}
    execution_mode = str(meta.get("execution_mode") or "").strip().lower()
    preferred_execution_mode = str(meta.get("preferred_execution_mode") or "").strip().lower()
    controller_session = bool(
        meta.get("controller_harness")
        or meta.get("system_context")
        or str(meta.get("agent_context_name") or "").strip() == "PAC/core"
    )
    pi_dev_backed = controller_session or execution_mode == "pi.dev" or preferred_execution_mode == "pi.dev" or bool(meta.get("pi_dev_backed"))
    if scope == "all_sessions":
        return True
    if scope == "pi_dev_sessions":
        return pi_dev_backed
    return controller_session


def _forward_payload(event: Event, session: Session) -> dict[str, Any]:
    session_meta = session.metadata or {}
    return {
        "created_at": event.created_at.isoformat(),
        "session_id": event.session_id,
        "session_name": session.name,
        "task_id": event.task_id,
        "event_type": event.type,
        "message": event.message,
        "data": event.data or {},
        "session": {
            "model": session.model,
            "agent_profile": session.agent_profile,
            "permission_profile": session.permission_profile,
            "context_mode": session.context_mode,
            "workspace_path": session.workspace_path,
            "agent_context_id": session_meta.get("agent_context_id"),
            "agent_context_name": session_meta.get("agent_context_name"),
            "execution_mode": session_meta.get("execution_mode"),
            "preferred_endpoint": session_meta.get("preferred_endpoint"),
        },
    }


def create_pi_dev_event_forwarder(
    config: AppConfig,
    store: Any,
) -> Callable[[Event], None]:
    configured_types = {str(item).strip() for item in (config.controller_harness.forward_event_types or []) if str(item).strip()}

    def _forward(event: Event) -> None:
        settings = config.controller_harness
        if not getattr(settings, "forward_events_enabled", False):
            return
        if str(getattr(settings, "forward_events_sink", "none") or "none").strip().lower() != "pi.dev":
            return
        if event.session_id == "system":
            return
        if configured_types and event.type not in configured_types:
            return
        session = store.get_session(event.session_id)
        if not session:
            return
        if not _session_matches_scope(session, str(getattr(settings, "forward_scope", "controller") or "controller").strip().lower()):
            return
        payload = _forward_payload(event, session)
        target = _session_forward_file(session, config)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    setattr(_forward, "_pac_hook_id", "pi_dev_event_forwarder")
    return _forward
