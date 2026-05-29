from __future__ import annotations

from typing import Any

from ..config import AppConfig
from ..models import Session, Task, TaskStatus
from ..agent_events import AgentEvents
from ..store import store
from ..web_tools import as_json_text, fetch_page_text, search_web_text
from .permission_guard import PermissionGuard
from .pipeline_approval import is_pipeline_approved


async def try_execute_web_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
    allowed: set[str],
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "web_fetch":
        if "web_fetch" not in allowed and "internet" not in allowed:
            return "DENIED: web_fetch/internet tool is not enabled for this session", False
        if denied := permission_guard.require("network"):
            return denied
        if permission_guard.level("network") == "ask" and session.permission_profile != "full-control" and not is_pipeline_approved(inp):
            from ..auto_approve import should_auto_approve
            approved, reason = should_auto_approve("web_fetch", inp)
            if approved:
                events.auto_approved(reason=reason, data={"tool": "web_fetch", "url": inp.get("url")})
            else:
                task.status = TaskStatus.approval_required
                task.metadata["agent_loop"] = True
                task.metadata["pending_tool"] = {"tool": "web_fetch", "input": inp}
                store.add_task(task)
                events.approval_required(message=f"Agent wants to fetch URL: {inp.get('url')}", data={"url": inp.get("url")})
                return "APPROVAL_REQUIRED", True
        url = str(inp.get("url") or "")
        max_chars = int(inp.get("max_chars") or 20000)
        try:
            result = fetch_page_text(url, max_chars=max_chars)
            events.web_fetch(url=url, source=result.get("source"), title=result.get("title"))
            return as_json_text(result), False
        except Exception as exc:
            return f"WEB_FETCH_FAILED: {exc}", False

    if tool == "web_search":
        if "web_search" not in allowed and "internet" not in allowed:
            return "DENIED: web_search/internet tool is not enabled for this session", False
        if denied := permission_guard.require("network"):
            return denied
        if permission_guard.level("network") == "ask" and session.permission_profile != "full-control" and not is_pipeline_approved(inp):
            from ..auto_approve import should_auto_approve
            approved, reason = should_auto_approve("web_search", inp)
            if approved:
                events.auto_approved(reason=reason, data={"tool": "web_search", "query": inp.get("query")})
            else:
                task.status = TaskStatus.approval_required
                task.metadata["agent_loop"] = True
                task.metadata["pending_tool"] = {"tool": "web_search", "input": inp}
                store.add_task(task)
                events.approval_required(message=f"Agent wants to search web: {inp.get('query')}", data={"query": inp.get("query")})
                return "APPROVAL_REQUIRED", True
        query = str(inp.get("query") or "")
        max_results = int(inp.get("max_results") or 5)
        try:
            result = search_web_text(query, max_results=max_results)
            events.web_search(query=query, result_count=len(result.get("results", [])))
            return as_json_text(result), False
        except Exception as exc:
            return f"WEB_SEARCH_FAILED: {exc}", False

    return None
