from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from .permission_guard import PermissionGuard


async def try_execute_pty_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "pty_shell":
        if denied := permission_guard.require("shell"):
            return denied
        command = str(inp.get("command") or "bash")
        cwd = str(inp.get("cwd") or session.workspace_path or "/tmp")
        rows = max(1, min(int(inp.get("rows") or 24), 200))
        cols = max(1, min(int(inp.get("cols") or 80), 300))
        pty_session_id_new = str(uuid4())[:12]
        try:
            from ..pty_shell import open_pty_session
            ps = open_pty_session(pty_session_id_new, command, cwd=cwd, rows=rows, cols=cols)
            events.pty_opened(pty_session=pty_session_id_new, command=command, pid=ps.pid)
            return json.dumps({"pty_session": pty_session_id_new, "pid": ps.pid, "status": ps.status, "command": command, "rows": rows, "cols": cols}), False
        except Exception as exc:
            return f"pty_shell failed: {exc}", False

    if tool == "pty_read":
        pty_session_id = str(inp.get("pty_session") or "").strip()
        if not pty_session_id:
            return "pty_read requires pty_session", False
        max_bytes = max(1, min(int(inp.get("max_bytes") or 4096), 8000))
        from ..pty_shell import read_pty
        output = read_pty(pty_session_id, max_bytes=max_bytes)
        events.pty_read(pty_session=pty_session_id, bytes_read=len(output))
        return output[-8000:], False

    if tool == "pty_write":
        pty_session_id = str(inp.get("pty_session") or "").strip()
        if not pty_session_id:
            return "pty_write requires pty_session", False
        data = str(inp.get("data") or "")
        from ..pty_shell import write_pty
        written = write_pty(pty_session_id, data)
        return json.dumps({"pty_session": pty_session_id, "bytes_written": written}), False

    if tool == "pty_resize":
        pty_session_id = str(inp.get("pty_session") or "").strip()
        if not pty_session_id:
            return "pty_resize requires pty_session", False
        rows = max(1, min(int(inp.get("rows") or 24), 200))
        cols = max(1, min(int(inp.get("cols") or 80), 300))
        from ..pty_shell import resize_pty
        ok = resize_pty(pty_session_id, rows, cols)
        return json.dumps({"pty_session": pty_session_id, "resized": ok, "rows": rows, "cols": cols}), False

    if tool == "pty_close":
        pty_session_id = str(inp.get("pty_session") or "").strip()
        if not pty_session_id:
            return "pty_close requires pty_session", False
        from ..pty_shell import close_pty_session
        result = close_pty_session(pty_session_id)
        events.pty_closed(pty_session=pty_session_id, result=result)
        return json.dumps(result), False

    return None
