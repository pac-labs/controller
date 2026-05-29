from __future__ import annotations

import io
import json
import os
import platform
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .context_manager import message_tokens
from .models import Event, Session, Task
from .model_metrics import model_metrics
from .runtime import git_diff, git_status

_SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|cookie|password|passwd|secret|token|credential|private[_-]?key)", re.IGNORECASE)
_SECRET_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s,'\"]+", re.IGNORECASE),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_text(value: str, *, max_length: int | None = None) -> str:
    text = value
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split(":", 1)[0].split("=", 1)[0] + "=<redacted>" if ":" in m.group(0) or "=" in m.group(0) else "Bearer <redacted>", text)
    if max_length is not None and len(text) > max_length:
        return text[:max_length] + f"\n...[truncated {len(text) - max_length} chars]"
    return text


def _redact(value: Any, *, text_limit: int | None = None) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if _SECRET_KEY_RE.search(key_s):
                redacted[key_s] = "<redacted>"
            else:
                redacted[key_s] = _redact(item, text_limit=text_limit)
        return redacted
    if isinstance(value, list):
        return [_redact(item, text_limit=text_limit) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, text_limit=text_limit) for item in value]
    if isinstance(value, str):
        return _redact_text(value, max_length=text_limit)
    return value


def _jsonable_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _event_payload(event: Event, *, full: bool) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    # Keep enough model text to debug routing/format drift, while protecting the bundle size.
    text_limit = None if full else 8000
    return _redact(payload, text_limit=text_limit)


def _task_payload(task: Task, *, full: bool) -> dict[str, Any]:
    payload = task.model_dump(mode="json")
    if not full and isinstance(payload.get("metadata"), dict):
        transcript = payload["metadata"].get("agent_transcript")
        if isinstance(transcript, list):
            payload["metadata"]["agent_transcript"] = transcript[-8:]
    return _redact(payload, text_limit=None if full else 12000)


def _session_payload(session: Session) -> dict[str, Any]:
    return _redact(session.model_dump(mode="json"), text_limit=12000)


def _config_diagnostics(config: AppConfig, session: Session) -> dict[str, Any]:
    model = config.models.get(session.model)
    provider = config.providers.get(model.provider) if model else None
    profile = config.context_profiles.get(session.context_mode) if getattr(config, "context_profiles", None) else None
    agent_profile = config.agent_profiles.get(session.agent_profile) if session.agent_profile else None
    return _redact(
        {
            "session_model": session.model,
            "session_context_mode": session.context_mode,
            "permission_profile": session.permission_profile,
            "model": _jsonable_model(model) if model else None,
            "provider": _jsonable_model(provider) if provider else None,
            "context_profile": _jsonable_model(profile) if profile else None,
            "agent_profile": _jsonable_model(agent_profile) if agent_profile else None,
            "tool_names": sorted(config.tools.keys()),
        },
        text_limit=12000,
    )


def _summarize_events(events: list[Event], tasks: list[Task]) -> dict[str, Any]:
    counts = Counter(event.type for event in events)
    tool_counts: Counter[str] = Counter()
    tool_sequence: list[dict[str, Any]] = []
    model_steps: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    routing_issues: list[dict[str, Any]] = []
    empty_responses: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    latest_context_estimate: int | None = None

    for event in events:
        data = event.data or {}
        if event.type == "tool_call":
            tool = str(data.get("tool") or event.message or "unknown")
            tool_counts[tool] += 1
            tool_sequence.append({"at": event.created_at.isoformat(), "task_id": event.task_id, "tool": tool, "input_keys": sorted((data.get("input") or {}).keys()) if isinstance(data.get("input"), dict) else []})
        elif event.type == "model_response":
            text = str(event.message or "")
            model_steps.append(
                {
                    "at": event.created_at.isoformat(),
                    "task_id": event.task_id,
                    "step": data.get("step"),
                    "model": data.get("model"),
                    "chars": len(text),
                    "estimated_tokens": max(1, len(text) // 4) if text else 0,
                    "looks_like_tool_call": '"type"' in text and '"tool_call"' in text,
                    "looks_like_final": '"type"' in text and '"final"' in text,
                }
            )
        elif event.type == "agent_thinking":
            latest_context_estimate = data.get("input_tokens") if isinstance(data.get("input_tokens"), int) else latest_context_estimate
        elif event.type == "context_compacted":
            compactions.append({"at": event.created_at.isoformat(), **_redact(data)})
        elif event.type == "model_routing_issue":
            routing_issues.append({"at": event.created_at.isoformat(), "message": event.message, "data": _redact(data)})
        elif event.type == "model_response_empty":
            empty_responses.append({"at": event.created_at.isoformat(), "data": _redact(data)})
        elif event.type == "tool_call_parse_failed":
            parse_failures.append({"at": event.created_at.isoformat(), "data": _redact(data, text_limit=4000)})

    task_status_counts = Counter(str(task.status.value if hasattr(task.status, "value") else task.status) for task in tasks)
    repeated_tools = {tool: count for tool, count in tool_counts.items() if count > 1}
    response_token_estimate = sum(item["estimated_tokens"] for item in model_steps)
    return {
        "event_counts": dict(counts),
        "task_status_counts": dict(task_status_counts),
        "model_call_count": len(model_steps),
        "model_response_token_estimate": response_token_estimate,
        "latest_context_token_estimate": latest_context_estimate,
        "tool_call_count": sum(tool_counts.values()),
        "tool_counts": dict(tool_counts),
        "repeated_tools": repeated_tools,
        "compaction_count": len(compactions),
        "empty_model_response_count": len(empty_responses),
        "tool_call_parse_failure_count": len(parse_failures),
        "routing_issue_count": len(routing_issues),
        "model_steps": model_steps[-50:],
        "tool_sequence": tool_sequence[-80:],
        "compactions": compactions[-20:],
        "routing_issues": routing_issues[-20:],
        "empty_model_responses": empty_responses[-20:],
        "parse_failures": parse_failures[-20:],
    }


def build_session_diagnostics(
    *,
    store: Any,
    config: AppConfig,
    session: Session,
    include_events: int = 1000,
    include_full: bool = False,
    include_workspace_state: bool = True,
) -> dict[str, Any]:
    tasks = store.list_tasks(session.id)
    events = store.get_events(session.id, limit=max(1, min(include_events, 10000)), latest=True)
    recent_events = store.list_recent_events(limit=200, exclude_types={"runner_heartbeat", "endpoint_heartbeat", "provider_heartbeat"})
    usage_summary = model_metrics.summarize_usage(session_id=session.id, since_hours=None, limit=10000)
    payload: dict[str, Any] = {
        "schema": "pac.session-diagnostics.v2",
        "generated_at": _now_iso(),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "session": _session_payload(session),
        "tasks": [_task_payload(task, full=include_full) for task in tasks],
        "summary": {**_summarize_events(events, tasks), "model_usage": usage_summary},
        "model_usage": usage_summary,
        "events": [_event_payload(event, full=include_full) for event in events],
        "recent_events": [_event_payload(event, full=False) for event in recent_events[:200]],
        "config": _config_diagnostics(config, session),
        "runners": [_redact(runner.model_dump(mode="json"), text_limit=12000) for runner in store.list_runners()],
    }
    if include_workspace_state:
        payload["workspace"] = _workspace_diagnostics(session)
    return payload


def _workspace_diagnostics(session: Session) -> dict[str, Any]:
    root = Path(session.workspace_path or "")
    info: dict[str, Any] = {"path": str(root), "exists": root.exists()}
    if not root.exists() or not root.is_dir():
        return info
    try:
        info["git_status"] = _redact_text(git_status(session), max_length=20000)
    except Exception as exc:
        info["git_status_error"] = str(exc)
    try:
        info["git_diff_stat"] = _redact_text(git_diff(session), max_length=50000)
    except Exception as exc:
        info["git_diff_error"] = str(exc)
    try:
        files: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if len(files) >= 500:
                break
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(part in {".git", "node_modules", "__pycache__", ".venv", "venv"} for part in path.parts):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append({"path": rel, "type": "dir" if path.is_dir() else "file", "size": stat.st_size if path.is_file() else None})
        info["files_sample"] = files
    except Exception as exc:
        info["files_error"] = str(exc)
    return info


def build_session_diagnostics_zip(**kwargs: Any) -> bytes:
    diagnostics = build_session_diagnostics(**kwargs)
    session_id = diagnostics.get("session", {}).get("id", "session")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", _diagnostics_readme(session_id))
        zf.writestr("diagnostics.json", json.dumps(diagnostics, indent=2, ensure_ascii=False))
        zf.writestr("summary.json", json.dumps(diagnostics.get("summary", {}), indent=2, ensure_ascii=False))
        zf.writestr("events.json", json.dumps(diagnostics.get("events", []), indent=2, ensure_ascii=False))
        zf.writestr("tasks.json", json.dumps(diagnostics.get("tasks", []), indent=2, ensure_ascii=False))
        zf.writestr("config-redacted.json", json.dumps(diagnostics.get("config", {}), indent=2, ensure_ascii=False))
        zf.writestr("model-usage.json", json.dumps(diagnostics.get("model_usage", {}), indent=2, ensure_ascii=False))
    return buf.getvalue()


def _diagnostics_readme(session_id: str) -> str:
    return f"""# PAC session diagnostics\n\nSession: `{session_id}`\n\nThis bundle is intended to be shared when the PAC agent loop appears inefficient, stalls after routing, repeats tool calls, or burns too much context.\n\nFiles:\n\n- `summary.json` — compact counts for model calls, context estimates, compactions, routing issues, parse failures, and repeated tools.\n- `events.json` — sanitized session timeline events.\n- `tasks.json` — sanitized task metadata and recent transcript state.\n- `config-redacted.json` — model/provider/context/profile information with secrets redacted.\n- `diagnostics.json` — all sections combined.\n\nObvious tokens, API keys, passwords, cookies, and bearer values are redacted automatically. Still review the bundle before posting it publicly.\n"""
