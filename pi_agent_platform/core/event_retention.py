from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_EVENT_RETENTION_POLICY: dict[str, Any] = {
    "retention_enabled": True,
    "retain_days": 30,
    "emergency_retain_days": 180,
    "max_events": 20000,
    "prune_on_startup": True,
}

EMERGENCY_EVENT_HINTS = (
    "failed",
    "error",
    "warning",
    "warn",
    "danger",
    "critical",
    "alert",
    "approval",
    "security",
    "denied",
    "rejected",
    "unavailable",
)


def normalize_event_retention_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(DEFAULT_EVENT_RETENTION_POLICY)
    raw.update(policy or {})
    return {
        "retention_enabled": bool(raw.get("retention_enabled", True)),
        "retain_days": max(1, min(int(raw.get("retain_days") or 30), 3650)),
        "emergency_retain_days": max(1, min(int(raw.get("emergency_retain_days") or 180), 3650)),
        "max_events": max(100, min(int(raw.get("max_events") or 20000), 1_000_000)),
        "prune_on_startup": bool(raw.get("prune_on_startup", True)),
    }


def is_emergency_event(event_type: str | None, data: dict[str, Any] | None = None) -> bool:
    lowered = str(event_type or "").strip().lower()
    severity = str((data or {}).get("severity") or (data or {}).get("level") or "").strip().lower()
    if severity in {"critical", "error", "warning", "warn", "danger", "alert"}:
        return True
    return any(hint in lowered for hint in EMERGENCY_EVENT_HINTS)


def retention_cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(1, int(days or 1)))
