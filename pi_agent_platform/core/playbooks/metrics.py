from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .state import list_runs

_TERMINAL = {"completed", "failed", "cancelled"}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _duration_seconds(start: Any, end: Any) -> float | None:
    start_ts = _parse_ts(start)
    end_ts = _parse_ts(end)
    if not start_ts or not end_ts:
        return None
    return max(0.0, (end_ts - start_ts).total_seconds())


def playbook_metrics_snapshot(limit: int = 200) -> dict[str, Any]:
    """Return a compact metrics summary for Observe and dashboards."""
    runs = list_runs(limit=max(1, min(int(limit or 200), 1000)))
    status_counts: Counter[str] = Counter()
    playbook_counts: Counter[str] = Counter()
    step_counts: Counter[str] = Counter()
    active: list[dict[str, Any]] = []
    durations: list[float] = []

    for run in runs:
        status_counts[str(run.status)] += 1
        playbook_counts[str(run.playbook_id)] += 1
        if run.status not in _TERMINAL:
            active.append({
                "id": run.id,
                "playbook_id": run.playbook_id,
                "title": run.title,
                "status": run.status,
                "waiting_step_id": run.waiting_step_id,
                "updated_at": run.updated_at.isoformat(),
            })
        if run.status in _TERMINAL:
            duration = _duration_seconds(run.created_at, run.cancelled_at or run.updated_at)
            if duration is not None:
                durations.append(duration)
        for step in run.steps:
            step_counts[str(step.status)] += 1

    avg_duration = sum(durations) / len(durations) if durations else 0.0
    return {
        "runs_total": len(runs),
        "status": dict(sorted(status_counts.items())),
        "steps": dict(sorted(step_counts.items())),
        "top_playbooks": [
            {"playbook_id": playbook_id, "runs": count}
            for playbook_id, count in playbook_counts.most_common(8)
        ],
        "active_runs": active[:12],
        "completed_duration_avg_seconds": round(avg_duration, 3),
        "terminal_runs_with_duration": len(durations),
    }
