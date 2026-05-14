from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .platform_home import pacp_path

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_key(value: str, label: str) -> str:
    key = _SAFE_KEY.sub("-", str(value or "").strip()).strip(".-")
    if not key:
        raise ValueError(f"{label} is required")
    return key


def _template(kind: str, key: str) -> str:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if kind == "profile":
        return (
            "=== PAC-RAM-PROFILE v2 ===\n"
            f"# Profile: {key}\n"
            f"timestamp: {now}\n"
            f"profile_mode: {key}\n\n"
            "## Purpose\n"
            "[Describe how this profile should operate and what it is optimized for]\n\n"
            "## Operating Rules\n"
            "[Constraints, approval expectations, escalation rules, quality bar]\n\n"
            "## Preferences\n"
            "[Stable preferences or defaults this profile should carry into new sessions]\n\n"
            "## Notes\n"
            "[Anything the control plane or IDE integrations should remember]\n\n"
            "---\n"
        )
    if kind == "user":
        return (
            "=== PAC-RAM-USER v2 ===\n"
            f"# User: {key}\n"
            f"timestamp: {now}\n\n"
            "## Preferences\n"
            "[How this user likes PAC to communicate and structure work]\n\n"
            "## Working Style\n"
            "[Known habits, project defaults, and review expectations]\n\n"
            "## Durable Notes\n"
            "[Information worth preserving across sessions]\n\n"
            "---\n"
        )
    return (
        "=== PAC-RAM-WORKSPACE v2 ===\n"
        f"# Workspace: {key}\n"
        f"timestamp: {now}\n\n"
        "## State\n"
        "[Current customer, branch, task stream, or bootstrap context]\n\n"
        "## Notes\n"
        "[Workspace-specific knowledge to carry between sessions]\n\n"
        "## Risks\n"
        "[Known hazards, limitations, or pending decisions]\n\n"
        "---\n"
    )


def _ram_path(kind: str, key: str) -> Path:
    clean = _clean_key(key, kind)
    if kind == "profile":
        return pacp_path("profile-memory", clean, "pac-ram-profile.md")
    if kind == "user":
        return pacp_path("users", clean, "pac-ram-user.md")
    if kind == "workspace":
        return pacp_path("workspaces", clean, "pac-ram-workspace.md")
    raise ValueError(f"Unsupported PAC RAM kind: {kind}")


def ensure_ram(kind: str, key: str) -> Path:
    path = _ram_path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_template(kind, _clean_key(key, kind)), encoding="utf-8")
    return path


def read_ram(kind: str, key: str) -> dict[str, Any]:
    path = ensure_ram(kind, key)
    content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return {
        "kind": kind,
        "key": _clean_key(key, kind),
        "path": str(path),
        "exists": path.exists(),
        "content": content,
        "size": len(content.encode("utf-8")),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_ram(kind: str, key: str, content: str) -> dict[str, Any]:
    path = ensure_ram(kind, key)
    body = str(content or "")
    path.write_text(body, encoding="utf-8")
    result = read_ram(kind, key)
    result["ok"] = True
    return result


def list_ram() -> dict[str, list[str]]:
    def _children(path: Path) -> list[str]:
        if not path.exists():
            return []
        return sorted(item.name for item in path.iterdir() if item.is_dir())

    return {
        "profiles": _children(pacp_path("profile-memory")),
        "users": _children(pacp_path("users")),
        "workspaces": _children(pacp_path("workspaces")),
    }


def all_ram() -> dict[str, list[dict[str, Any]]]:
    listing = list_ram()
    return {
        "profiles": [read_ram("profile", name) for name in listing["profiles"]],
        "users": [read_ram("user", name) for name in listing["users"]],
        "workspaces": [read_ram("workspace", name) for name in listing["workspaces"]],
    }
