from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from .platform_home import pacp_path


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_text_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Cheap, deterministic estimate used when a provider does not return usage.
    return max(1, int(len(text) / 4))


def estimate_messages_tokens(messages: list[dict[str, Any]] | None) -> int:
    if not messages:
        return 0
    total = 0
    for message in messages:
        total += 4
        total += estimate_text_tokens(str(message.get("role") or ""))
        total += estimate_text_tokens(str(message.get("content") or ""))
    return total


class ModelMetricsStore:
    """Small local metrics database for PAC model-call usage.

    The normal event timeline is optimized for UI/session debugging. This store is
    optimized for aggregate counters and longer-lived usage analysis. It stores no
    prompts or completions, only usage metadata and estimates.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else pacp_path("metrics.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("pragma journal_mode=WAL")
            conn.execute(
                """
                create table if not exists model_usage (
                    id text primary key,
                    created_at text not null,
                    session_id text,
                    task_id text,
                    call_type text not null,
                    model_name text not null,
                    provider_name text,
                    provider_type text,
                    provider_model text,
                    endpoint text,
                    prompt_tokens integer,
                    completion_tokens integer,
                    total_tokens integer,
                    prompt_tokens_estimated integer not null,
                    completion_tokens_estimated integer not null,
                    total_tokens_estimated integer not null,
                    max_tokens integer,
                    duration_ms integer not null,
                    success integer not null,
                    error text,
                    metadata text not null
                )
                """
            )
            conn.execute("create index if not exists idx_model_usage_created on model_usage(created_at)")
            conn.execute("create index if not exists idx_model_usage_session_created on model_usage(session_id, created_at)")
            conn.execute("create index if not exists idx_model_usage_model_created on model_usage(model_name, created_at)")
            conn.execute("create index if not exists idx_model_usage_provider_created on model_usage(provider_name, created_at)")

    def record(self, record: dict[str, Any]) -> dict[str, Any]:
        item = dict(record)
        item.setdefault("id", f"musg_{uuid4().hex[:12]}")
        item.setdefault("created_at", now_utc_iso())
        item.setdefault("call_type", "unknown")
        item.setdefault("metadata", {})
        item["prompt_tokens_estimated"] = int(item.get("prompt_tokens_estimated") or 0)
        item["completion_tokens_estimated"] = int(item.get("completion_tokens_estimated") or 0)
        item["total_tokens_estimated"] = int(item.get("total_tokens_estimated") or (item["prompt_tokens_estimated"] + item["completion_tokens_estimated"]))
        item["duration_ms"] = int(item.get("duration_ms") or 0)
        item["success"] = 1 if item.get("success", True) else 0
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert or replace into model_usage(
                    id, created_at, session_id, task_id, call_type, model_name,
                    provider_name, provider_type, provider_model, endpoint,
                    prompt_tokens, completion_tokens, total_tokens,
                    prompt_tokens_estimated, completion_tokens_estimated, total_tokens_estimated,
                    max_tokens, duration_ms, success, error, metadata
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["created_at"],
                    item.get("session_id"),
                    item.get("task_id"),
                    item["call_type"],
                    item.get("model_name") or "unknown",
                    item.get("provider_name"),
                    item.get("provider_type"),
                    item.get("provider_model"),
                    item.get("endpoint"),
                    item.get("prompt_tokens"),
                    item.get("completion_tokens"),
                    item.get("total_tokens"),
                    item["prompt_tokens_estimated"],
                    item["completion_tokens_estimated"],
                    item["total_tokens_estimated"],
                    item.get("max_tokens"),
                    item["duration_ms"],
                    item["success"],
                    str(item.get("error") or "")[:2000] or None,
                    json.dumps(item.get("metadata") or {}, ensure_ascii=False, default=str),
                ),
            )
        return item

    def list_usage(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        model_name: str | None = None,
        since_hours: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        args: list[Any] = []
        if session_id:
            where.append("session_id = ?")
            args.append(session_id)
        if task_id:
            where.append("task_id = ?")
            args.append(task_id)
        if model_name:
            where.append("model_name = ?")
            args.append(model_name)
        if since_hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))
            where.append("created_at >= ?")
            args.append(cutoff.isoformat())
        clause = " where " + " and ".join(where) if where else ""
        args.append(max(1, min(int(limit), 10000)))
        with self._connect() as conn:
            rows = conn.execute(f"select * from model_usage{clause} order by created_at desc limit ?", args).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def summarize_usage(
        self,
        *,
        session_id: str | None = None,
        since_hours: int | None = 24,
        limit: int = 10000,
    ) -> dict[str, Any]:
        rows = self.list_usage(session_id=session_id, since_hours=since_hours, limit=limit)
        summary: dict[str, Any] = {
            "database": str(self.db_path),
            "session_id": session_id,
            "since_hours": since_hours,
            "call_count": len(rows),
            "success_count": 0,
            "failure_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_tokens_estimated": 0,
            "completion_tokens_estimated": 0,
            "total_tokens_estimated": 0,
            "duration_ms": 0,
            "by_model": {},
            "by_provider": {},
            "by_call_type": {},
            "recent": rows[:50],
        }
        buckets: dict[str, dict[str, dict[str, Any]]] = {
            "by_model": defaultdict(lambda: self._empty_bucket()),
            "by_provider": defaultdict(lambda: self._empty_bucket()),
            "by_call_type": defaultdict(lambda: self._empty_bucket()),
        }
        for row in rows:
            success = bool(row.get("success"))
            summary["success_count" if success else "failure_count"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_tokens_estimated", "completion_tokens_estimated", "total_tokens_estimated", "duration_ms"):
                summary[key] += int(row.get(key) or 0)
            for bucket_name, value in (
                ("by_model", row.get("model_name") or "unknown"),
                ("by_provider", row.get("provider_name") or row.get("provider_type") or "unknown"),
                ("by_call_type", row.get("call_type") or "unknown"),
            ):
                bucket = buckets[bucket_name][str(value)]
                self._add_to_bucket(bucket, row)
        for bucket_name, bucket_map in buckets.items():
            summary[bucket_name] = dict(sorted(bucket_map.items(), key=lambda item: item[1]["total_tokens_estimated"], reverse=True))
        return summary

    @staticmethod
    def _empty_bucket() -> dict[str, Any]:
        return {
            "call_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_tokens_estimated": 0,
            "completion_tokens_estimated": 0,
            "total_tokens_estimated": 0,
            "duration_ms": 0,
        }

    @staticmethod
    def _add_to_bucket(bucket: dict[str, Any], row: dict[str, Any]) -> None:
        bucket["call_count"] += 1
        bucket["success_count" if row.get("success") else "failure_count"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_tokens_estimated", "completion_tokens_estimated", "total_tokens_estimated", "duration_ms"):
            bucket[key] += int(row.get(key) or 0)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["success"] = bool(item.get("success"))
        try:
            item["metadata"] = json.loads(item.get("metadata") or "{}")
        except Exception:
            item["metadata"] = {}
        return item


model_metrics = ModelMetricsStore()
