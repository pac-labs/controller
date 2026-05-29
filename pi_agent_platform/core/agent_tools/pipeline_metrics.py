from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

from ..observability_store import finish_span, record_metric, start_span

_LOCK = Lock()
_STAGE_COUNTS: dict[str, int] = defaultdict(int)
_STAGE_ERRORS: dict[str, int] = defaultdict(int)
_STAGE_TOTAL_MS: dict[str, float] = defaultdict(float)
_RECENT: deque[dict[str, Any]] = deque(maxlen=120)


def _key(tool: str, stage: str, status: str) -> str:
    return f"{tool}:{stage}:{status}"


def record_pipeline_stage(tool: str, stage: str, duration_ms: float, *, status: str = "ok", labels: dict[str, Any] | None = None) -> None:
    status = status or "ok"
    metric_labels = {"tool": tool, "stage": stage, "status": status, **(labels or {})}
    try:
        record_metric("tool_pipeline.stage.count", 1, kind="counter", component="agent_tools", labels=metric_labels)
        record_metric("tool_pipeline.stage.duration_ms", duration_ms, kind="timer", component="agent_tools", labels=metric_labels)
    except Exception:
        pass
    with _LOCK:
        key = _key(tool, stage, status)
        _STAGE_COUNTS[key] += 1
        if status != "ok":
            _STAGE_ERRORS[key] += 1
        _STAGE_TOTAL_MS[key] += float(duration_ms or 0.0)
        _RECENT.append({"tool": tool, "stage": stage, "status": status, "duration_ms": round(float(duration_ms or 0.0), 3), "at": time.time()})


@contextmanager
def pipeline_stage(tool: str, stage: str, *, labels: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    span = start_span(f"tool_pipeline.{stage}", component="agent_tools", attributes={"tool": tool, **(labels or {})})
    status = "ok"
    extra: dict[str, Any] = {}
    try:
        yield extra
    except Exception as exc:
        status = "error"
        extra["error"] = str(exc)
        raise
    finally:
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        record_pipeline_stage(tool, stage, duration_ms, status=status, labels=labels)
        finish_span(span, status=status, attributes={"duration_ms": round(duration_ms, 3), **extra})


def pipeline_metrics_snapshot() -> dict[str, Any]:
    with _LOCK:
        rows = []
        for key, count in _STAGE_COUNTS.items():
            tool, stage, status = key.split(":", 2)
            total = _STAGE_TOTAL_MS.get(key, 0.0)
            rows.append({
                "tool": tool,
                "stage": stage,
                "status": status,
                "count": count,
                "error_count": _STAGE_ERRORS.get(key, 0),
                "avg_duration_ms": round(total / max(count, 1), 3),
            })
        rows.sort(key=lambda item: (-int(item["count"]), str(item["tool"]), str(item["stage"])))
        return {"summary": rows[:80], "recent": list(_RECENT)[-40:]}
