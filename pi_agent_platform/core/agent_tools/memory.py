from __future__ import annotations

import json
from typing import Any

from ..config import AppConfig
from ..models import Session, Task
from ..web_tools import as_json_text
from ..workspace_lessons import load_lessons, save_lesson, search_lessons


async def try_execute_memory_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    allowed: set[str],
) -> tuple[str, bool] | None:
    if tool == "remote_memory":
        if "remote_memory" not in allowed and "pac_memory" not in allowed:
            return "DENIED: remote_memory tool is not enabled for this session", False
        mode = str(inp.get("mode") or "get").strip().lower()
        if mode == "get":
            kind = str(inp.get("kind") or "workspace").strip().lower()
            key = str(inp.get("key") or "").strip()
            if not key:
                return "REMOTE_MEMORY_FAILED: key is required for get mode", False
            from .pac_ram import read_ram
            return as_json_text(read_ram(kind, key)), False
        if mode == "bundle":
            from .pac_ram import bundle_ram
            return as_json_text(bundle_ram(
                profile=str(inp.get("profile") or "").strip() or None,
                user=str(inp.get("user") or "").strip() or None,
                workspace=str(inp.get("workspace") or "").strip() or None,
            )), False
        if mode == "search":
            query = str(inp.get("query") or "").strip()
            if not query:
                return "REMOTE_MEMORY_FAILED: query is required for search mode", False
            from .pac_ram import search_ram
            return as_json_text(search_ram(query, kind=str(inp.get("kind") or "").strip() or None, limit=int(inp.get("limit") or 8))), False
        return f"REMOTE_MEMORY_FAILED: unsupported mode {mode}", False

    if tool == "lessons":
        # Cross-session memory: save/load/query lessons learned in this workspace
        mode = str(inp.get("mode") or "load").strip().lower()
        workspace = session.workspace_path

        if mode == "save":
            # Save a lesson explicitly (agent can call this mid-task)
            category = str(inp.get("category") or "implementation")
            title = str(inp.get("title") or task.prompt[:80] or "untitled")
            body = str(inp.get("body") or "")
            tags = inp.get("tags")
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            elif not isinstance(tags, list):
                tags = []
            files_touched = inp.get("files_touched") or []
            result = save_lesson(
                workspace_path=workspace,
                category=category,
                title=title,
                body=body,
                tags=tags,
                tool_calls=[],
                files_touched=files_touched if isinstance(files_touched, list) else [],
            )
            return json.dumps({"ok": True, "lesson_id": result.get("lesson_id")}), False

        if mode == "search":
            query = str(inp.get("query") or "").strip()
            if not query:
                return "lessons search requires query", False
            category = str(inp.get("category") or "").strip() or None
            limit = max(1, min(int(inp.get("limit") or 10), 30))
            result = search_lessons(workspace, query, category=category, limit=limit)
            return json.dumps(result, indent=2)[:12000], False

        # Default: load recent lessons
        category = str(inp.get("category") or "").strip() or None
        limit = max(1, min(int(inp.get("limit") or 20), 50))
        result = load_lessons(workspace, category=category, limit=limit)
        return json.dumps(result, indent=2)[:12000], False

    return None
