from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...core.models import Event, Runner, RunnerStatus

_VOLATILE_KEYS = {
    "last_seen",
    "last_seen_at",
    "observed_at",
    "checked_at",
    "timestamp",
    "time",
    "uptime",
    "uptime_seconds",
    "pid",
    "memory",
    "memory_bytes",
    "cpu_percent",
}


def _normalise_for_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalise_for_signature(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).lower() not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_normalise_for_signature(item) for item in value]
    return value


def stable_capability_signature(capabilities: dict[str, Any] | None) -> str:
    """Return a heartbeat capability signature without high-churn counters.

    Endpoint heartbeats may include process metrics or probe timestamps. Those
    values are useful on the endpoint card, but they should not generate a new
    global "status changed" event every few seconds.
    """
    return json.dumps(_normalise_for_signature(capabilities or {}), sort_keys=True, default=str)


def _status_value(status: RunnerStatus | str) -> str:
    return status.value if isinstance(status, RunnerStatus) else str(status)


def emit_heartbeat_events(
    store: Any,
    *,
    runner: Runner,
    previous_status: RunnerStatus | str,
    previous_labels: list[str],
    previous_version: str,
    previous_capability_signature: str,
    current_version: str,
    current_capability_signature: str,
) -> None:
    status_changed = previous_status != runner.status
    identity_changed = previous_labels != list(runner.labels or []) or previous_version != current_version
    if status_changed or identity_changed:
        store.add_event(
            Event(
                session_id="system",
                type="runner_status_changed",
                message=f"Endpoint {runner.name} changed to {_status_value(runner.status)}",
                data={
                    "runner_id": runner.id,
                    "status": _status_value(runner.status),
                    "labels": runner.labels,
                    "version": current_version,
                    "containers": len(runner.containers),
                },
            )
        )
        return

    if previous_capability_signature == current_capability_signature:
        return

    last_signature = str(runner.metadata.get("_last_capability_event_signature") or "")
    last_at_raw = str(runner.metadata.get("_last_capability_event_at") or "")
    if last_signature == current_capability_signature:
        return
    try:
        last_at = datetime.fromisoformat(last_at_raw)
    except Exception:
        last_at = None
    now = datetime.now(timezone.utc)
    if last_at and (now - last_at).total_seconds() < 300:
        runner.metadata["_last_capability_event_signature"] = current_capability_signature
        runner.metadata["_last_capability_event_at"] = now.isoformat()
        store.add_runner(runner)
        return
    runner.metadata["_last_capability_event_signature"] = current_capability_signature
    runner.metadata["_last_capability_event_at"] = now.isoformat()
    store.add_runner(runner)
    store.add_event(
        Event(
            session_id="system",
            type="runner_capabilities_changed",
            message=f"Endpoint {runner.name} capabilities changed",
            data={
                "runner_id": runner.id,
                "status": _status_value(runner.status),
                "version": current_version,
                "containers": len(runner.containers),
            },
        )
    )
