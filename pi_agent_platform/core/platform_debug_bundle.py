from __future__ import annotations

import io
import json
import os
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .diagnostics_bundle import build_session_diagnostics
from .models import Session

_SECRET_WORDS = ("api_key", "apikey", "authorization", "bearer", "cookie", "password", "passwd", "secret", "token", "credential", "private_key")
_LOG_NAMES = ("*.log", "*.jsonl", "events.json", "events.jsonl", "*session*.json", "*session*.jsonl")
_SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "binaries", "release-binaries"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_text(text: str, *, limit: int | None = None) -> str:
    value = text
    for word in _SECRET_WORDS:
        value = _redact_assignments(value, word)
    value = value.replace("Bearer ", "Bearer <redacted> ")
    if limit is not None and len(value) > limit:
        return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"
    return value


def _redact_assignments(text: str, key: str) -> str:
    lowered = text.lower()
    out: list[str] = []
    cursor = 0
    while True:
        index = lowered.find(key.lower(), cursor)
        if index < 0:
            out.append(text[cursor:])
            return "".join(out)
        out.append(text[cursor:index])
        end = index + len(key)
        out.append(text[index:end])
        if end < len(text) and text[end] in ":=":
            out.append(text[end] + "<redacted>")
            end += 1
            while end < len(text) and text[end] not in "\n\r,; ":
                end += 1
        cursor = end


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in _SECRET_WORDS):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = _redact_json(item)
        return result
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value, limit=50000)
    return value


def _json_bytes(value: Any) -> str:
    return json.dumps(_redact_json(value), indent=2, ensure_ascii=False, default=str)


def _unique_existing_roots(candidates: list[Path]) -> list[Path]:
    roots: list[Path] = []
    for raw in candidates:
        if not raw:
            continue
        root = raw.expanduser().resolve() if raw.exists() else raw.expanduser()
        if root.exists() and root not in roots:
            roots.append(root)
    return roots


def _candidate_roots(config: AppConfig, session: Session) -> list[Path]:
    candidates = [Path.cwd(), Path(config.server.data_dir).expanduser()]
    if session.workspace_path:
        candidates.append(Path(session.workspace_path).expanduser())
    app = Path.cwd()
    if app.name == "app":
        candidates.append(app.parent)
    return _unique_existing_roots(candidates)


def _candidate_environment_roots(config: AppConfig) -> list[Path]:
    candidates = [Path.cwd(), Path(config.server.data_dir).expanduser()]
    app = Path.cwd()
    if app.name == "app":
        candidates.append(app.parent)
    return _unique_existing_roots(candidates)


def _safe_name(path: Path) -> str:
    return str(path).strip("/").replace("/", "__").replace(" ", "_") or "root"


def _tail_file(path: Path, *, max_bytes: int = 250_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(max(0, size - max_bytes))
            data = fh.read(max_bytes)
        return _redact_text(data.decode("utf-8", errors="replace"), limit=max_bytes)
    except Exception as exc:
        return f"Unable to read {path}: {exc}"


def _iter_recent_logs(roots: list[Path], *, limit: int = 80) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for root in roots:
        try:
            for pattern in _LOG_NAMES:
                for path in root.rglob(pattern):
                    if any(part in _SKIP_PARTS for part in path.parts):
                        continue
                    if not path.is_file() or path in seen:
                        continue
                    seen.add(path)
                    files.append(path)
        except Exception:
            continue
    files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return files[:limit]


def _run_command(args: list[str], *, timeout: int = 5) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return f"{args[0]} not found"
    except Exception as exc:
        return f"{args!r} failed: {exc}"
    output = ""
    if proc.stdout:
        output += proc.stdout
    if proc.stderr:
        output += "\n--- stderr ---\n" + proc.stderr
    return _redact_text(output.strip() or f"exit={proc.returncode}", limit=120000)


def _runtime_snapshot(config: AppConfig, session: Session) -> dict[str, Any]:
    return {
        "generated_at": _now(),
        "python": sys.version,
        "platform": platform.platform(),
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "data_dir": config.server.data_dir,
        "session_id": session.id,
        "session_name": session.name,
        "workspace_path": session.workspace_path,
        "environment_names": sorted([key for key in os.environ if key.startswith(("PAC", "PI_", "OPENAI", "ANTHROPIC", "GOOGLE", "MODEL", "PROVIDER"))]),
    }



def build_platform_debug_zip(
    *,
    store: Any,
    config: AppConfig,
    session: Session,
    include_events: int = 3000,
    include_full: bool = True,
    active_task_id: str | None = None,
) -> bytes:
    diagnostics = build_session_diagnostics(
        store=store,
        config=config,
        session=session,
        include_events=include_events,
        include_full=include_full,
        include_workspace_state=True,
    )
    roots = _candidate_roots(config, session)
    recent_logs = _iter_recent_logs(roots)
    tasks = diagnostics.get("tasks", [])
    active_tasks = [task for task in tasks if str(task.get("status", "")).lower() in {"running", "approval_required", "queued"}]
    if active_task_id:
        active_tasks = [task for task in tasks if task.get("id") == active_task_id] or active_tasks

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", _debug_readme(session.id))
        zf.writestr("support-summary.md", _support_summary(session, diagnostics, recent_logs, active_tasks))
        zf.writestr("session/diagnostics.json", _json_bytes(diagnostics))
        zf.writestr("session/summary.json", _json_bytes(diagnostics.get("summary", {})))
        zf.writestr("session/events.json", _json_bytes(diagnostics.get("events", [])))
        zf.writestr("session/tasks.json", _json_bytes(tasks))
        zf.writestr("session/active-tasks.json", _json_bytes(active_tasks))
        zf.writestr("session/config-redacted.json", _json_bytes(diagnostics.get("config", {})))
        zf.writestr("session/workspace.json", _json_bytes(diagnostics.get("workspace", {})))
        zf.writestr("platform/runtime.json", _json_bytes(_runtime_snapshot(config, session)))
        zf.writestr("platform/processes.txt", _run_command(["ps", "auxww"]))
        zf.writestr("platform/ports.txt", _run_command(["sh", "-lc", "ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true"]))
        zf.writestr("platform/containers.txt", _run_command(["sh", "-lc", "podman ps -a 2>/dev/null || docker ps -a 2>/dev/null || true"]))
        zf.writestr("platform/systemd-user.txt", _run_command(["sh", "-lc", "systemctl --user --no-pager status pacp.service 2>/dev/null || true"]))
        zf.writestr("platform/systemd-system.txt", _run_command(["sh", "-lc", "systemctl --no-pager status pacp.service 2>/dev/null || true"]))
        zf.writestr("logs/log-index.json", _json_bytes([{"path": str(path), "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()} for path in recent_logs if path.exists()]))
        for path in recent_logs[:40]:
            zf.writestr(f"logs/{_safe_name(path)}.tail.txt", _tail_file(path))
    return buf.getvalue()


def _support_summary(session: Session, diagnostics: dict[str, Any], logs: list[Path], active_tasks: list[dict[str, Any]]) -> str:
    summary = diagnostics.get("summary", {}) if isinstance(diagnostics.get("summary"), dict) else {}
    lines = [
        "# PAC debug support summary",
        "",
        f"Generated: {_now()}",
        f"Session: {session.name or session.id} (`{session.id}`)",
        f"Workspace: `{session.workspace_path or '-'}`",
        f"Active tasks: {len(active_tasks)}",
        "",
        "## Key counters",
        f"- Model calls: {summary.get('model_call_count', 0)}",
        f"- Tool calls: {summary.get('tool_call_count', 0)}",
        f"- Empty model responses: {summary.get('empty_model_response_count', 0)}",
        f"- Routing issues: {summary.get('routing_issue_count', 0)}",
        f"- Parse failures: {summary.get('tool_call_parse_failure_count', 0)}",
        "",
        "## Recent logs included",
    ]
    lines.extend(f"- `{path}`" for path in logs[:20])
    lines.append("")
    lines.append("Upload this zip to the PAC troubleshooting conversation. It contains redacted session events, task metadata, workspace state, process/container state, and recent PAC log tails.")
    return "\n".join(lines)


def _debug_readme(session_id: str) -> str:
    return f"""# PAC platform debug bundle

Session: `{session_id}`

This bundle is intended for troubleshooting PAC platform behavior: stuck sessions, provider streams, endpoint/coding-session readiness, tool pipeline failures, playbooks, updates, and UI/runtime event mismatches.

Important files:

- `support-summary.md` — quick overview to paste/read first.
- `session/events.json` — sanitized session timeline.
- `session/tasks.json` — task metadata and transcript state.
- `session/active-tasks.json` — running/queued/approval task details.
- `session/workspace.json` — workspace existence, git status, and file sample.
- `platform/runtime.json` — runtime and process context.
- `platform/*.txt` — process, port, container, and service snapshots.
- `logs/*.tail.txt` — redacted tails from recent PAC logs.

Obvious tokens, API keys, cookies, bearer values, passwords, and secrets are redacted automatically. Review before posting publicly.
"""
