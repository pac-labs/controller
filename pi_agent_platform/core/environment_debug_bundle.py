from __future__ import annotations

import io
import os
import platform
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .diagnostics_bundle import build_session_diagnostics
from .models import Session
from .platform_debug_bundle import (
    _candidate_environment_roots,
    _iter_recent_logs,
    _json_bytes,
    _redact_json,
    _redact_text,
    _run_command,
    _safe_name,
    _tail_file,
    _now,
)


def _session_digest(session: Session) -> dict[str, Any]:
    metadata = getattr(session, "metadata", {}) or {}
    active_model = metadata.get("active_model") if isinstance(metadata, dict) else None
    provider = getattr(session, "provider", None)
    endpoint = getattr(session, "endpoint", None)
    profile = getattr(session, "profile", None) or getattr(session, "agent_profile", None)
    if isinstance(metadata, dict):
        provider = provider or metadata.get("provider")
        endpoint = endpoint or metadata.get("preferred_endpoint")
        profile = profile or metadata.get("agent_profile")
    return {
        "id": getattr(session, "id", ""),
        "name": getattr(session, "name", None),
        "workspace_path": getattr(session, "workspace_path", None),
        "model": active_model or getattr(session, "model", None),
        "provider": provider,
        "endpoint": endpoint,
        "profile": profile,
        "agent_profile": getattr(session, "agent_profile", None),
        "permission_profile": getattr(session, "permission_profile", None),
        "context_mode": getattr(session, "context_mode", None),
        "status": getattr(getattr(session, "status", None), "value", None) or str(getattr(session, "status", "")),
        "metadata": _redact_json(metadata),
        "created_at": getattr(session, "created_at", None),
        "updated_at": getattr(session, "updated_at", None),
    }


def _task_digest(task: Any) -> dict[str, Any]:
    return _redact_json({
        "id": getattr(task, "id", ""),
        "session_id": getattr(task, "session_id", ""),
        "status": getattr(getattr(task, "status", None), "value", None) or str(getattr(task, "status", "")),
        "prompt": getattr(task, "prompt", ""),
        "metadata": getattr(task, "metadata", {}) or {},
        "created_at": getattr(task, "created_at", None),
        "updated_at": getattr(task, "updated_at", None),
    })


def _event_digest(event: Any) -> dict[str, Any]:
    return _redact_json({
        "id": getattr(event, "id", ""),
        "session_id": getattr(event, "session_id", ""),
        "task_id": getattr(event, "task_id", None),
        "type": getattr(event, "type", ""),
        "message": getattr(event, "message", ""),
        "data": getattr(event, "data", {}) or {},
        "created_at": getattr(event, "created_at", None),
    })


def _capture_errors(errors: list[dict[str, Any]], section: str, exc: BaseException) -> None:
    errors.append({
        "section": section,
        "error": _redact_text(str(exc), limit=4000),
        "traceback": _redact_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), limit=12000),
    })


def _safe_collect(section: str, errors: list[dict[str, Any]], fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        _capture_errors(errors, section, exc)
        return default


def _safe_digest_many(section: str, items: list[Any], digest: Callable[[Any], dict[str, Any]], errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        try:
            rows.append(digest(item))
        except Exception as exc:
            _capture_errors(errors, f"{section}:{index}", exc)
            rows.append({
                "digest_error": _redact_text(str(exc), limit=1000),
                "item_type": type(item).__name__,
                "id": getattr(item, "id", ""),
            })
    return rows


def _safe_writestr(zf: zipfile.ZipFile, name: str, data: Any, errors: list[dict[str, Any]]) -> None:
    try:
        if isinstance(data, bytes):
            zf.writestr(name, data)
        elif isinstance(data, str):
            zf.writestr(name, data)
        else:
            zf.writestr(name, _json_bytes(data))
    except Exception as exc:
        _capture_errors(errors, f"write:{name}", exc)
        try:
            zf.writestr(f"generation/write-errors/{_safe_name(Path(name))}.txt", _redact_text(str(exc), limit=4000))
        except Exception:
            pass


def _safe_recent_logs(roots: list[Path], errors: list[dict[str, Any]]) -> list[Path]:
    logs = _safe_collect("recent_logs", errors, lambda: _iter_recent_logs(roots), [])
    safe_logs: list[Path] = []
    for path in logs:
        try:
            if Path(path).exists() and Path(path).is_file():
                safe_logs.append(Path(path))
        except Exception as exc:
            _capture_errors(errors, f"log_probe:{path}", exc)
    return safe_logs


def build_environment_debug_zip(
    *,
    store: Any,
    config: AppConfig,
    include_events: int = 2000,
    include_sessions: int = 30,
) -> bytes:
    errors: list[dict[str, Any]] = []
    sessions = _safe_collect("sessions", errors, lambda: list(store.list_sessions())[:max(1, min(include_sessions, 200))], [])
    tasks = _safe_collect("tasks", errors, lambda: list(store.list_tasks())[:2000] if hasattr(store, "list_tasks") else [], [])
    recent_events = _safe_collect(
        "recent_events",
        errors,
        lambda: list(store.list_recent_events(limit=max(1, min(include_events, 10000)))) if hasattr(store, "list_recent_events") else [],
        [],
    )
    roots = _safe_collect("environment_roots", errors, lambda: _candidate_environment_roots(config), [])
    recent_logs = _safe_recent_logs(roots, errors)
    active_tasks = [
        task for task in tasks
        if str(getattr(getattr(task, "status", None), "value", None) or getattr(task, "status", "")).lower()
        in {"running", "approval_required", "queued"}
    ]
    latest_session = sessions[0] if sessions else None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _safe_writestr(zf, "README.md", _environment_debug_readme(), errors)
        _safe_writestr(zf, "support-summary.md", _environment_support_summary(sessions, active_tasks, recent_events, recent_logs, errors), errors)
        _safe_writestr(zf, "environment/runtime.json", _environment_runtime_snapshot(config, errors), errors)
        _safe_writestr(zf, "environment/sessions.json", _safe_digest_many("session_digest", sessions, _session_digest, errors), errors)
        _safe_writestr(zf, "environment/tasks.json", _safe_digest_many("task_digest", tasks, _task_digest, errors), errors)
        _safe_writestr(zf, "environment/active-tasks.json", _safe_digest_many("active_task_digest", active_tasks, _task_digest, errors), errors)
        _safe_writestr(zf, "environment/recent-events.json", _safe_digest_many("event_digest", recent_events, _event_digest, errors), errors)
        _safe_writestr(zf, "environment/config-redacted.json", _safe_config_snapshot(config, errors), errors)
        if latest_session:
            diagnostics = _safe_collect(
                "latest_session_diagnostics",
                errors,
                lambda: build_session_diagnostics(
                    store=store,
                    config=config,
                    session=latest_session,
                    include_events=1000,
                    include_full=False,
                    include_workspace_state=True,
                ),
                None,
            )
            if diagnostics is not None:
                _safe_writestr(zf, "latest-session/diagnostics.json", diagnostics, errors)
        _safe_writestr(zf, "platform/processes.txt", _run_command(["ps", "auxww"]), errors)
        _safe_writestr(zf, "platform/ports.txt", _run_command(["sh", "-lc", "ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true"]), errors)
        _safe_writestr(zf, "platform/containers.txt", _run_command(["sh", "-lc", "podman ps -a 2>/dev/null || docker ps -a 2>/dev/null || true"]), errors)
        _safe_writestr(zf, "platform/systemd-user.txt", _run_command(["sh", "-lc", "systemctl --user --no-pager status pacp.service 2>/dev/null || true"]), errors)
        _safe_writestr(zf, "platform/systemd-system.txt", _run_command(["sh", "-lc", "systemctl --no-pager status pacp.service 2>/dev/null || true"]), errors)
        log_index: list[dict[str, Any]] = []
        for path in recent_logs:
            try:
                stat = path.stat()
                log_index.append({"path": str(path), "size": stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
            except Exception as exc:
                _capture_errors(errors, f"log_index:{path}", exc)
        _safe_writestr(zf, "logs/log-index.json", log_index, errors)
        for path in recent_logs[:60]:
            _safe_writestr(zf, f"logs/{_safe_name(path)}.tail.txt", _tail_file(path), errors)
        _safe_writestr(zf, "generation/errors.json", errors, errors)
    return buf.getvalue()


def _safe_config_snapshot(config: AppConfig, errors: list[dict[str, Any]]) -> dict[str, Any]:
    return _safe_collect(
        "config_snapshot",
        errors,
        lambda: config.model_dump(mode="json") if hasattr(config, "model_dump") else {},
        {},
    )


def _environment_runtime_snapshot(config: AppConfig, errors: list[dict[str, Any]]) -> dict[str, Any]:
    data_dir = _safe_collect("runtime_data_dir", errors, lambda: config.server.data_dir, "")
    return {
        "generated_at": _now(),
        "python": sys.version,
        "platform": platform.platform(),
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "data_dir": data_dir,
        "environment_names": sorted([key for key in os.environ if key.startswith(("PAC", "PI_", "OPENAI", "ANTHROPIC", "GOOGLE", "MODEL", "PROVIDER"))]),
        "generation_error_count": len(errors),
    }


def _environment_support_summary(sessions: list[Session], active_tasks: list[Any], events: list[Any], logs: list[Path], errors: list[dict[str, Any]]) -> str:
    lines = [
        "# PAC environment debug support summary",
        "",
        f"Generated: {_now()}",
        f"Sessions included: {len(sessions)}",
        f"Active tasks: {len(active_tasks)}",
        f"Recent events: {len(events)}",
        f"Generation warnings/errors: {len(errors)}",
        "",
        "## Active tasks",
    ]
    if active_tasks:
        lines.extend(f"- `{getattr(task, 'id', '-')}` session `{getattr(task, 'session_id', '-')}` status `{getattr(getattr(task, 'status', None), 'value', None) or getattr(task, 'status', '-')}`" for task in active_tasks[:20])
    else:
        lines.append("- None recorded")
    lines.extend(["", "## Recent sessions"])
    if sessions:
        lines.extend(f"- `{session.id}` — {session.name or 'unnamed'} — `{session.workspace_path or '-'}`" for session in sessions[:15])
    else:
        lines.append("- None recorded")
    lines.extend(["", "## Recent logs included"])
    if logs:
        lines.extend(f"- `{path}`" for path in logs[:25])
    else:
        lines.append("- None found")
    if errors:
        lines.extend(["", "## Generation warnings/errors"])
        lines.extend(f"- `{item.get('section')}` — {item.get('error')}" for item in errors[:20])
    lines.append("")
    lines.append("Upload this zip to the PAC troubleshooting conversation. It contains redacted platform state, current sessions/tasks, recent events, and recent PAC log tails.")
    return "\n".join(lines)


def _environment_debug_readme() -> str:
    return """# PAC environment debug bundle

This bundle is generated from the global Downloads area and is intended for troubleshooting PAC platform functionality, not just one session.

Important files:

- `support-summary.md` — quick overview to inspect first.
- `generation/errors.json` — bundle-generation warnings if a collector failed.
- `environment/sessions.json` — recent session metadata, redacted.
- `environment/tasks.json` — recent task metadata, redacted.
- `environment/active-tasks.json` — currently active/queued/approval tasks.
- `environment/recent-events.json` — recent platform/session events.
- `latest-session/diagnostics.json` — focused diagnostics for the latest session when available.
- `platform/*.txt` — process, port, container, and service snapshots.
- `logs/*.tail.txt` — redacted tails from recent PAC logs.

Obvious tokens, API keys, cookies, bearer values, passwords, and secrets are redacted automatically. Review before posting publicly.
"""
