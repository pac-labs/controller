from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from uuid import uuid4

from ..background_jobs import start_job
from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from ..runtime import command_policy
from .file_ops import _safe_path
from .permission_guard import PermissionGuard


async def try_execute_diagnostics_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "shell_bg":
        if denied := permission_guard.require("shell"):
            return denied
        command = str(inp.get("command") or "")
        if not command:
            return "shell_bg requires command", False
        decision, reason = command_policy(command, session, config)
        if decision == "deny":
            return f"DENIED: {reason}", False
        job_id = str(uuid4())[:8]
        cwd = str(inp.get("cwd") or session.workspace_path or "/tmp")
        # Fire-and-forget: start the job
        asyncio.create_task(start_job(job_id, command, cwd))
        events.tool_result(tool="shell_bg", message=f"shell_bg started job {job_id}: {command[:100]}", data={"job_id": job_id, "command": command})
        return json.dumps({"job_id": job_id, "status": "running", "command": command}), False

    if tool == "shell_bg_result":
        job_id = str(inp.get("job_id") or "").strip()
        if not job_id:
            return "shell_bg_result requires job_id", False
        from ..background_jobs import get_job
        job = get_job(job_id)
        if not job:
            return json.dumps({"job_id": job_id, "status": "unknown", "error": "job not found"}), False
        return json.dumps(job.to_dict(), indent=2)[:12000], False

    if tool == "shell_bg_stop":
        job_id = str(inp.get("job_id") or "").strip()
        if not job_id:
            return "shell_bg_stop requires job_id", False
        from ..background_jobs import stop_job
        ok = stop_job(job_id)
        return json.dumps({"job_id": job_id, "stopped": ok}), False

    if tool == "log_tail":
        if denied := permission_guard.require_any(("file_read", "shell"), "DENIED: no read or shell access"):
            return denied
        path = str(inp.get("path") or "")
        container = str(inp.get("container") or "")
        lines = max(1, min(int(inp.get("lines") or 50), 500))
        filter_pattern = str(inp.get("grep") or "")
        follow = bool(inp.get("follow"))

        if container:
            # podman logs
            if denied := permission_guard.require("shell", "DENIED: shell access required for container logs"):
                return denied
            cmd = f"podman logs --tail {lines} {container}"
            if filter_pattern:
                cmd = f"podman logs --tail {lines} {container} 2>&1 | grep -i {filter_pattern} | tail -{lines}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                out = stdout.decode(errors="replace")
                err = stderr.decode(errors="replace")
                combined = (out + ("\nSTDERR:\n" + err if err else ""))[-8000:]
            except asyncio.TimeoutError:
                proc.kill()
                combined = "log_tail timed out after 15s"
            events.tool_result(tool="log_tail", message=f"log_tail container={container} lines={lines}", data={"container": container, "lines": lines})
            return combined or "no logs found", False
        elif path:
            if denied := permission_guard.require("file_read", "DENIED: file read access denied"):
                return denied
            p = _safe_path(session, path)
            if not p.exists():
                return f"log_tail: file not found: {path}", False
            try:
                all_lines = p.read_text(errors="replace").splitlines()
            except Exception as e:
                return f"log_tail read error: {e}", False
            if filter_pattern:
                import re
                pattern = re.compile(filter_pattern, re.IGNORECASE)
                filtered = [l for l in all_lines if pattern.search(l)]
                result_lines = filtered[-lines:]
            else:
                result_lines = all_lines[-lines:]
            result = "\n".join(result_lines)
            events.tool_result(tool="log_tail", message=f"log_tail path={path} lines={lines}", data={"path": path, "lines": lines})
            return result[-8000:], False
        else:
            return "log_tail requires either path or container", False

    if tool == "podman_ps":
        if denied := permission_guard.require("shell"):
            return denied
        host = str(inp.get("host") or "localhost").strip()
        all_containers = bool(inp.get("all") or False)

        if host == "localhost":
            cmd = "podman ps" + (" -a" if all_containers else "")
        else:
            cmd = f"ssh {host} podman ps" + (" -a" if all_containers else "")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            return "podman_ps timed out", False

        if err and not out:
            return f"podman_ps error: {err[:500]}", False

        # Parse the output into structured rows
        lines = out.strip().split("\n")
        if len(lines) < 2:
            return out or "no containers running", False

        headers = lines[0].split()
        rows = []
        for raw_line in lines[1:]:
            parts = raw_line.split(None, len(headers) - 1)
            if len(parts) >= len(headers):
                row = dict(zip(headers, parts))
                rows.append(row)

        result = {"host": host, "count": len(rows), "containers": rows}
        events.tool_result(tool="podman_ps", message=f"podman_ps host={host} count={len(rows)}", data={"host": host, "count": len(rows)})
        return json.dumps(result, indent=2)[:10000], False

    if tool == "wait_for":
        if denied := permission_guard.require("network"):
            return denied
        target = str(inp.get("target") or "").strip()
        timeout = max(1, min(int(inp.get("timeout") or 30), 120))
        poll_interval = max(0.5, min(float(inp.get("interval") or 1.0), 5.0))

        if not target:
            return "wait_for requires target (URL or host:port)", False

        async def check_tcp(host_port: str) -> bool:
            try:
                host, port = host_port.rsplit(":", 1)
                port = int(port)
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                return False

        # Determine check type: TCP only (host:port)
        if ":" in target:
            check_fn = lambda: check_tcp(target)
        else:
            return f"wait_for: target must be host:port, got: {target}", False

        events.tool_started(tool="wait_for", message=f"wait_for {target} (timeout={timeout}s)", data={"target": target, "timeout": timeout})

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = await asyncio.wait_for(check_fn(), timeout=poll_interval + 2)
                if result:
                    elapsed = round(time.time() - (deadline - timeout), 1)
                    events.tool_result(tool="wait_for", message=f"wait_for {target} ready after {elapsed}s", data={"target": target, "elapsed": elapsed})
                    return json.dumps({"target": target, "ready": True, "elapsed_seconds": elapsed}), False
            except Exception:
                pass
            await asyncio.sleep(poll_interval)

        events.tool_result(tool="wait_for", message=f"wait_for {target} timed out", data={"target": target, "timeout": timeout})
        return json.dumps({"target": target, "ready": False, "error": f"timed out after {timeout}s"}), False

    return None
