from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .platform_home import pacp_path

_DB_PATH = pacp_path("observability.db")
_SCHEMA_READY = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _json(data: dict[str, Any] | None) -> str:
    return json.dumps(data or {}, sort_keys=True, separators=(",", ":"), default=str)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except Exception:
        return default


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY and conn is not None:
        return
    owns_conn = conn is None
    if conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                value REAL NOT NULL,
                component TEXT NOT NULL DEFAULT '',
                labels_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_metric_samples_ts ON metric_samples(ts);
            CREATE INDEX IF NOT EXISTS idx_metric_samples_name_ts ON metric_samples(name, ts);

            CREATE TABLE IF NOT EXISTS metric_rollups_1m (
                bucket TEXT NOT NULL,
                name TEXT NOT NULL,
                component TEXT NOT NULL DEFAULT '',
                labels_hash TEXT NOT NULL DEFAULT '',
                labels_json TEXT NOT NULL DEFAULT '{}',
                count INTEGER NOT NULL,
                min_value REAL NOT NULL,
                max_value REAL NOT NULL,
                sum_value REAL NOT NULL,
                avg_value REAL NOT NULL,
                PRIMARY KEY(bucket, name, component, labels_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_metric_rollups_1m_name_bucket ON metric_rollups_1m(name, bucket);

            CREATE TABLE IF NOT EXISTS trace_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                parent_span_id TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                component TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                start_ts TEXT NOT NULL,
                end_ts TEXT,
                duration_ms REAL,
                attributes_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_trace_spans_start ON trace_spans(start_ts);
            CREATE INDEX IF NOT EXISTS idx_trace_spans_operation_start ON trace_spans(operation, start_ts);
            """
        )
        if owns_conn:
            conn.commit()
        _SCHEMA_READY = True
    finally:
        if owns_conn:
            conn.close()


def _minute_bucket(ts: str) -> str:
    # ISO strings sort lexicographically; the first 16 chars are YYYY-MM-DDTHH:MM.
    return ts[:16] + ":00+00:00"


def _labels_hash(labels_json: str) -> str:
    import hashlib

    return hashlib.sha256(labels_json.encode("utf-8")).hexdigest()[:16]


def record_metric(name: str, value: float = 1.0, *, kind: str = "counter", component: str = "", labels: dict[str, Any] | None = None) -> None:
    ts = _iso()
    labels_json = _json(labels)
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO metric_samples(ts, name, kind, value, component, labels_json) VALUES(?,?,?,?,?,?)",
                (ts, str(name), str(kind), _float(value), str(component or ""), labels_json),
            )
            bucket = _minute_bucket(ts)
            label_hash = _labels_hash(labels_json)
            row = conn.execute(
                "SELECT count, min_value, max_value, sum_value FROM metric_rollups_1m WHERE bucket=? AND name=? AND component=? AND labels_hash=?",
                (bucket, str(name), str(component or ""), label_hash),
            ).fetchone()
            if row:
                count = int(row["count"]) + 1
                min_value = min(_float(row["min_value"]), _float(value))
                max_value = max(_float(row["max_value"]), _float(value))
                sum_value = _float(row["sum_value"]) + _float(value)
                conn.execute(
                    "UPDATE metric_rollups_1m SET count=?, min_value=?, max_value=?, sum_value=?, avg_value=? WHERE bucket=? AND name=? AND component=? AND labels_hash=?",
                    (count, min_value, max_value, sum_value, sum_value / max(count, 1), bucket, str(name), str(component or ""), label_hash),
                )
            else:
                conn.execute(
                    "INSERT INTO metric_rollups_1m(bucket, name, component, labels_hash, labels_json, count, min_value, max_value, sum_value, avg_value) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (bucket, str(name), str(component or ""), label_hash, labels_json, 1, _float(value), _float(value), _float(value), _float(value)),
                )
    except Exception:
        # Observability must never break controller behavior.
        return


def start_span(operation: str, *, component: str = "", trace_id: str | None = None, parent_span_id: str | None = None, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "trace_id": trace_id or uuid.uuid4().hex,
        "span_id": uuid.uuid4().hex[:16],
        "parent_span_id": parent_span_id or "",
        "operation": str(operation),
        "component": str(component or ""),
        "start_ts": _iso(),
        "started_monotonic": time.perf_counter(),
        "attributes": attributes or {},
    }


def finish_span(span: dict[str, Any], *, status: str = "ok", attributes: dict[str, Any] | None = None) -> None:
    try:
        started = _float(span.get("started_monotonic"), time.perf_counter())
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        merged = dict(span.get("attributes") or {})
        merged.update(attributes or {})
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_spans(trace_id, span_id, parent_span_id, operation, component, status, start_ts, end_ts, duration_ms, attributes_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(span.get("trace_id") or uuid.uuid4().hex),
                    str(span.get("span_id") or uuid.uuid4().hex[:16]),
                    str(span.get("parent_span_id") or ""),
                    str(span.get("operation") or "unknown"),
                    str(span.get("component") or ""),
                    str(status or "ok"),
                    str(span.get("start_ts") or _iso()),
                    _iso(),
                    duration_ms,
                    _json(merged),
                ),
            )
    except Exception:
        return


@contextmanager
def span(operation: str, *, component: str = "", trace_id: str | None = None, parent_span_id: str | None = None, attributes: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    item = start_span(operation, component=component, trace_id=trace_id, parent_span_id=parent_span_id, attributes=attributes)
    try:
        yield item
    except Exception as exc:
        finish_span(item, status="error", attributes={"error": str(exc)})
        raise
    else:
        finish_span(item, status="ok")


def record_http_request(path: str, method: str, status_code: int, duration_ms: float) -> None:
    labels = {"path": str(path or ""), "method": str(method or "GET"), "status": str(status_code)}
    record_metric("http.requests", 1, kind="counter", component="api", labels=labels)
    record_metric("http.duration_ms", duration_ms, kind="timer", component="api", labels=labels)
    trace = start_span("http.request", component="api", attributes={**labels, "duration_ms": round(duration_ms, 3)})
    finish_span(trace, status="error" if int(status_code) >= 500 else "ok")


def observability_store_status() -> dict[str, Any]:
    try:
        ensure_schema()
        stat = _DB_PATH.stat() if _DB_PATH.exists() else None
        with _connect() as conn:
            metric_count = int(conn.execute("SELECT COUNT(*) AS c FROM metric_samples").fetchone()["c"])
            rollup_count = int(conn.execute("SELECT COUNT(*) AS c FROM metric_rollups_1m").fetchone()["c"])
            span_count = int(conn.execute("SELECT COUNT(*) AS c FROM trace_spans").fetchone()["c"])
        return {
            "backend": "sqlite-local-observability",
            "path": str(_DB_PATH),
            "exists": _DB_PATH.exists(),
            "size_bytes": stat.st_size if stat else 0,
            "metrics": {"samples": metric_count, "rollups_1m": rollup_count},
            "traces": {"spans": span_count},
            "retention": {
                "raw_metric_hours": _int_env("PAC_OBSERVABILITY_RAW_METRIC_HOURS", 24),
                "trace_days": _int_env("PAC_OBSERVABILITY_TRACE_DAYS", 7),
                "rollup_days": _int_env("PAC_OBSERVABILITY_ROLLUP_DAYS", 30),
            },
        }
    except Exception as exc:
        return {"backend": "sqlite-local-observability", "path": str(_DB_PATH), "error": str(exc)}


def query_metrics(*, since_hours: int = 24, limit: int = 200) -> dict[str, Any]:
    since_hours = max(1, min(int(since_hours or 24), 24 * 90))
    limit = max(1, min(int(limit or 200), 1000))
    since = (_now() - timedelta(hours=since_hours)).isoformat()
    try:
        with _connect() as conn:
            summary_rows = conn.execute(
                """
                SELECT name, component, COUNT(*) AS samples, SUM(value) AS sum_value, AVG(value) AS avg_value, MIN(value) AS min_value, MAX(value) AS max_value
                FROM metric_samples WHERE ts >= ? GROUP BY name, component ORDER BY name LIMIT ?
                """,
                (since, limit),
            ).fetchall()
            series_rows = conn.execute(
                """
                SELECT bucket, name, component, SUM(count) AS count, SUM(sum_value) AS sum_value, AVG(avg_value) AS avg_value, MIN(min_value) AS min_value, MAX(max_value) AS max_value
                FROM metric_rollups_1m WHERE bucket >= ? GROUP BY bucket, name, component ORDER BY bucket DESC, name LIMIT ?
                """,
                (since[:16] + ":00+00:00", limit),
            ).fetchall()
        return {
            "since_hours": since_hours,
            "summary": [dict(row) for row in summary_rows],
            "series": [dict(row) for row in series_rows],
        }
    except Exception as exc:
        return {"since_hours": since_hours, "summary": [], "series": [], "error": str(exc)}


def query_traces(*, since_hours: int = 24, limit: int = 80, trace_id: str | None = None) -> dict[str, Any]:
    since_hours = max(1, min(int(since_hours or 24), 24 * 90))
    limit = max(1, min(int(limit or 80), 500))
    since = (_now() - timedelta(hours=since_hours)).isoformat()
    try:
        with _connect() as conn:
            if trace_id:
                rows = conn.execute(
                    "SELECT * FROM trace_spans WHERE trace_id=? ORDER BY start_ts ASC, id ASC LIMIT ?",
                    (trace_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trace_spans WHERE start_ts >= ? ORDER BY start_ts DESC, id DESC LIMIT ?",
                    (since, limit),
                ).fetchall()
        spans = []
        for row in rows:
            item = dict(row)
            try:
                item["attributes"] = json.loads(item.pop("attributes_json") or "{}")
            except Exception:
                item["attributes"] = {}
            spans.append(item)
        return {"since_hours": since_hours, "trace_id": trace_id, "spans": spans}
    except Exception as exc:
        return {"since_hours": since_hours, "trace_id": trace_id, "spans": [], "error": str(exc)}


def prune_observability_store() -> dict[str, Any]:
    raw_hours = _int_env("PAC_OBSERVABILITY_RAW_METRIC_HOURS", 24)
    trace_days = _int_env("PAC_OBSERVABILITY_TRACE_DAYS", 7)
    rollup_days = _int_env("PAC_OBSERVABILITY_ROLLUP_DAYS", 30)
    raw_before = (_now() - timedelta(hours=raw_hours)).isoformat()
    trace_before = (_now() - timedelta(days=trace_days)).isoformat()
    rollup_before = (_now() - timedelta(days=rollup_days)).isoformat()
    try:
        with _connect() as conn:
            metric_deleted = conn.execute("DELETE FROM metric_samples WHERE ts < ?", (raw_before,)).rowcount
            span_deleted = conn.execute("DELETE FROM trace_spans WHERE start_ts < ?", (trace_before,)).rowcount
            rollup_deleted = conn.execute("DELETE FROM metric_rollups_1m WHERE bucket < ?", (rollup_before,)).rowcount
        return {"metric_samples_deleted": metric_deleted, "trace_spans_deleted": span_deleted, "rollups_deleted": rollup_deleted}
    except Exception as exc:
        return {"error": str(exc)}
