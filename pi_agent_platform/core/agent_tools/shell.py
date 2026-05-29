from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from ..config import AppConfig
from ..models import Session, Task, TaskStatus, RunnerJob, RunnerJobStatus, RunnerExecutionMode
from ..agent_events import AgentEvents
from ..runtime import command_policy
from ..code_intelligence.language_servers import endpoint_script
from ..store import store

def _shell_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def _runner_tool_command(tool: str, inp: dict[str, Any]) -> str | None:
    inp = inp or {}
    if tool == "shell":
        return str(inp.get("command") or "").strip() or None
    if tool == "git_status":
        return "git status --short"
    if tool == "git_diff":
        return "git diff --"
    if tool == "workspace_manifest":
        max_files = max(1, min(int(inp.get("max_files") or 200), 400))
        return (
            "find . "
            "\\( -path './.git' -o -path './node_modules' -o -path './__pycache__' -o -path './.venv' \\) -prune "
            f"-o -type f -printf '%P\\n' | sort | head -n {max_files}"
        )
    if tool == "list_files":
        path = str(inp.get("path") or ".").strip() or "."
        quoted = _shell_single_quote(path)
        return (
            f"if [ -f {quoted} ]; then "
            f"printf 'file %s\\n' {quoted}; "
            f"wc -c < {quoted}; "
            "else "
            f"cd {quoted} 2>/dev/null || exit 2; "
            "find . -maxdepth 3 "
            "\\( -path './.git' -o -path './node_modules' -o -path './__pycache__' -o -path './.venv' \\) -prune "
            "-o -printf '%y %P\\n' | sed '/^d $/d' | sort | head -n 200; "
            "fi"
        )
    if tool == "read_file":
        path = str(inp.get("path") or "").strip()
        if not path:
            return None
        quoted = _shell_single_quote(path)
        return f"sed -n '1,260p' -- {quoted}"
    if tool == "read_file_chunk":
        path = str(inp.get("path") or "").strip()
        if not path:
            return None
        chunk_index = max(0, int(inp.get("chunk_index") or 0))
        chunk_lines = max(80, min(int(inp.get("chunk_lines") or 220), 600))
        start = (chunk_index * chunk_lines) + 1
        end = start + chunk_lines - 1
        quoted = _shell_single_quote(path)
        return f"sed -n '{start},{end}p' -- {quoted}"
    if tool == "write_file":
        path = str(inp.get("path") or "").strip()
        if not path:
            return None
        content = str(inp.get("content") or "")
        marker = f"__PAC_EOF_{uuid4().hex}__"
        quoted = _shell_single_quote(path)
        return (
            f"mkdir -p -- $(dirname {quoted}) && "
            f"cat > {quoted} <<'{marker}'\n{content}\n{marker}\n"
        )
    if tool == "edit_file":
        return None  # runner doesn't support edit_file directly
    if tool == "ripgrep":
        return None  # runner doesn't support ripgrep directly
    if tool == "fd":
        return None  # runner doesn't support fd directly
    if tool in {"code_language_servers", "code_project_metadata", "code_lsp_status", "code_lsp_endpoint_prepare", "code_roslyn_analysis"}:
        return endpoint_script(tool, inp)

    if tool == "code_diagnostics":
        path = str(inp.get("path") or ".").strip() or "."
        language = str(inp.get("language") or "auto").strip().lower() or "auto"
        run = "1" if bool(inp.get("run") or False) else "0"
        timeout = max(5, min(int(inp.get("timeout") or 30), 120))
        quoted = _shell_single_quote(path)
        script_lines = [
            "set -eu",
            f"LANGUAGE={_shell_single_quote(language)}",
            f"RUN={run}",
            f"TIMEOUT={timeout}",
            "echo '== code diagnostics environment =='",
            "echo language=$LANGUAGE run=$RUN timeout=$TIMEOUT",
            "echo '== tool availability =='",
            "for binary in cargo python go npx dotnet rust-analyzer pyright-langserver pylsp gopls typescript-language-server tsserver csharp-ls omnisharp; do if command -v $binary >/dev/null 2>&1; then echo $binary=available; else echo $binary=missing; fi; done",
            "echo '== project markers =='",
            "find . -maxdepth 4 \\( -name Cargo.toml -o -name pyproject.toml -o -name requirements.txt -o -name package.json -o -name tsconfig.json -o -name go.mod -o -name '*.csproj' -o -name '*.sln' \\) | sed 's#^./##' | sort | head -80",
            "if [ \"$RUN\" = \"1\" ]; then",
            "  echo '== diagnostics output =='",
            "  if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = rust ]; } && [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then timeout \"$TIMEOUT\" cargo check --message-format=json || true; fi",
            "  if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = python ]; } && command -v python >/dev/null 2>&1; then timeout \"$TIMEOUT\" python -m compileall -q . || true; fi",
            "  if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = go ]; } && [ -f go.mod ] && command -v go >/dev/null 2>&1; then timeout \"$TIMEOUT\" go test ./... || true; fi",
            "  if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = typescript ]; } && [ -f package.json ] && command -v npx >/dev/null 2>&1; then timeout \"$TIMEOUT\" npx tsc --noEmit || true; fi",
            "  if { [ \"$LANGUAGE\" = auto ] || [ \"$LANGUAGE\" = csharp ]; } && command -v dotnet >/dev/null 2>&1; then timeout \"$TIMEOUT\" dotnet build --no-restore || true; fi",
            "fi",
        ]
        script = "\n".join(script_lines)
        return f"cd {quoted} 2>/dev/null || exit 2; sh -lc {_shell_single_quote(script)}"
    return None


async def _run_tool_via_runner(session: Session, task: Task, tool: str, inp: dict[str, Any], config: AppConfig) -> tuple[str, bool] | None:
    meta = session.metadata or {}
    if not (
        meta.get("coding_session")
        and str(meta.get("preferred_execution_mode") or meta.get("execution_mode") or "").strip().lower() == "container"
    ):
        return None
    runner_id = str(task.metadata.get("runner_id") or meta.get("preferred_endpoint") or "").strip()
    if not runner_id:
        return None
    runner = store.get_runner(runner_id)
    if not runner or runner.metadata.get("local_control_plane"):
        return None
    command = _runner_tool_command(tool, inp)
    if not command:
        return None
    execution_mode = RunnerExecutionMode.container
    container_image = str(task.metadata.get("container_image") or meta.get("container_image") or "").strip()
    if not container_image:
        return ("DENIED: coding session has no container image configured", False)
    job = RunnerJob(
        runner_id=runner.id,
        prompt=f"Tool execution: {tool}",
        command=command,
        execution_mode=execution_mode,
        container_image=container_image,
        workspace_path=session.workspace_path,
        session_id=session.id,
        task_id=task.id,
        metadata={
            "tool_name": tool,
            "tool_input": inp,
            "coding_session": True,
            "source": "agent_loop_tool_bridge",
            "permission_profile": session.permission_profile,
            "model": session.model,
        },
    )
    store.add_runner_job(job)
    AgentEvents(session, task).runner_job_queued(tool=tool, runner_name=runner.name, data={"runner_id": runner.id, "runner_job_id": job.id, "execution_mode": job.execution_mode, "command": command, "container_image": container_image})
    deadline = time.monotonic() + max(30, int(config.runtime.command_timeout_seconds))
    while time.monotonic() < deadline:
        current = store.get_runner_job(job.id)
        if not current:
            await asyncio.sleep(0.25)
            continue
        if current.status == RunnerJobStatus.completed:
            output = str(current.output or "").strip()
            return (output or f"{tool} completed with no output", False)
        if current.status in {RunnerJobStatus.failed, RunnerJobStatus.cancelled}:
            detail = str(current.error or current.output or f"{tool} failed").strip()
            return (detail or f"{tool} failed", False)
        await asyncio.sleep(0.4)
    return (f"{tool} timed out waiting for endpoint runner completion", False)


async def _run_shell(session: Session, task: Task, command: str, config: AppConfig, *, pipeline_approved: bool = False) -> tuple[str, bool]:
    events = AgentEvents(session, task)
    decision, reason = command_policy(command, session, config)
    if decision == "deny":
        return f"DENIED: {reason}", False
    if decision == "ask" and session.permission_profile != "full-control" and not pipeline_approved:
        # Check auto-approve rules first
        from ..auto_approve import should_auto_approve
        approved, reason = should_auto_approve("shell", {"command": command})
        if approved:
            events.auto_approved(reason=reason, data={"tool": "shell", "command": command})
        else:
            task.status = TaskStatus.approval_required
            task.metadata["agent_loop"] = True
            task.metadata["pending_tool"] = {"tool": "shell", "input": {"command": command}}
            store.add_task(task)
            events.approval_required(message=f"Agent wants to run: {command}", data={"command": command, "reason": reason})
            return "APPROVAL_REQUIRED", True

    events.tool_started(tool="shell", message=f"shell: {command}", data={"command": command})
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=session.workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=config.runtime.command_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        return "Command timed out", False
    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    combined = (out + ("\nSTDERR:\n" + err if err else ""))[-12000:]
    events.tool_result(tool="shell", message=f"shell exited {proc.returncode}", data={"exit_code": proc.returncode, "output": combined[-4000:]})
    return combined or f"Command exited {proc.returncode} with no output", False

