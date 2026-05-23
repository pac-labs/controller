from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from .workspace_index import build_workspace_index


@dataclass(slots=True)
class _CachedIndex:
    created_at: float
    root_mtime_ns: int
    max_files: int
    value: dict[str, Any]


_CACHE: dict[str, _CachedIndex] = {}
DEFAULT_TTL_SECONDS = 45.0


def get_workspace_index(root: Path, *, max_files: int = 600, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> tuple[dict[str, Any], bool]:
    """Return a short-lived workspace index cache to avoid slow loop startup scans."""
    key = str(root.resolve()) if root.exists() else str(root)
    try:
        root_mtime_ns = root.stat().st_mtime_ns if root.exists() else 0
    except Exception:
        root_mtime_ns = 0

    cached = _CACHE.get(key)
    now = monotonic()
    if (
        cached is not None
        and cached.max_files == max_files
        and cached.root_mtime_ns == root_mtime_ns
        and now - cached.created_at <= ttl_seconds
    ):
        return cached.value, True

    value = build_workspace_index(root, max_files=max_files)
    _CACHE[key] = _CachedIndex(created_at=now, root_mtime_ns=root_mtime_ns, max_files=max_files, value=value)
    return value, False


def clear_workspace_index(root: Path) -> None:
    key = str(root.resolve()) if root.exists() else str(root)
    _CACHE.pop(key, None)
