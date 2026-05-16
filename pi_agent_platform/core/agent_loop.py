from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from shlex import join as shlex_join
from typing import Any

from .config import AppConfig
from .models import Event, Session, SessionStatus, Task, TaskStatus
from .providers import chat_complete, effective_context
from .session_commands import parse_session_slash_command, slash_help_text
from .subagents import spawn_pi_dev_subagent
from .context_manager import (
    batch_reduce_text,
    chunk_text,
    compact_messages_basic,
    estimate_tokens,
    file_manifest,
    get_context_budget,
    message_tokens,
    truncate_middle,
)
from .runtime import command_policy, ensure_workspace
from .store import store
from .web_tools import fetch_page_text, search_web_text, as_json_text
from .artifacts import write_artifact, list_artifacts


TOOL_HELP = """
Available response formats. Return ONE JSON object only.

Final answer:
{"type":"final","message":"..."}

Tool call:
{"type":"tool_call","tool":"list_files","input":{"path":"."}}
{"type":"tool_call","tool":"read_file","input":{"path":"README.md"}}
{"type":"tool_call","tool":"read_file_chunk","input":{"path":"large.log","chunk_index":0,"chunk_tokens":1200}}
{"type":"tool_call","tool":"workspace_manifest","input":{"max_files":200}}
{"type":"tool_call","tool":"batch_analyze_text","input":{"instruction":"find likely bugs","text":"...","chunk_tokens":1000}}
{"type":"tool_call","tool":"batch_analyze_file","input":{"path":"large-file.txt","instruction":"summarize important parts","chunk_tokens":1000}}
{"type":"tool_call","tool":"write_file","input":{"path":"file.txt","content":"..."}}
{"type":"tool_call","tool":"shell","input":{"command":"git status --short"}}
{"type":"tool_call","tool":"git_status","input":{}}
{"type":"tool_call","tool":"git_diff","input":{}}
{"type":"tool_call","tool":"web_fetch","input":{"url":"https://example.com","max_chars":12000}}
{"type":"tool_call","tool":"web_search","input":{"query":"search terms","max_results":5}}
{"type":"tool_call","tool":"consult_model","input":{"models":["deep-thinker","fast-coder"],"prompt":"Review this plan and suggest the next 3 steps.","max_tokens":1200}}
{"type":"tool_call","tool":"save_artifact","input":{"name":"notes/result.txt","content":"..."}}
{"type":"tool_call","tool":"list_artifacts","input":{}}
{"type":"tool_call","tool":"slash_command","input":{"command":"/rg TODO src"}}

Rules:
- Prefer inspecting files before editing.
- Use shell only when needed.
- Keep commands scoped to the workspace.
- If blocked by policy, explain what approval or permission is needed.
- For small-context models, prefer workspace_manifest, read_file_chunk, web_fetch max_chars, and batch_analyze_file over loading many large files at once.
- Use web_search before web_fetch when you do not know the exact URL.
- Use consult_model when you want a second opinion from another configured PAC model or want to fan out a planning question to multiple models.
- Save important generated files/results with save_artifact when the user may want to download them.
""".strip()


def _summarize_tool_intent(tool: str, inp: dict[str, Any]) -> str:
    tool = str(tool or "")
    inp = inp or {}
    if tool == "shell":
        return f"Preparing command: {str(inp.get('command') or '').strip() or 'shell'}"
    if tool == "read_file":
        return f"Reading {inp.get('path') or 'file'}"
    if tool == "read_file_chunk":
        return f"Reading chunk from {inp.get('path') or 'file'}"
    if tool == "list_files":
        return f"Listing {inp.get('path') or '.'}"
    if tool == "write_file":
        return f"Writing {inp.get('path') or 'file'}"
    if tool == "workspace_manifest":
        return "Scanning workspace structure"
    if tool == "batch_analyze_text":
        return f"Analyzing text: {str(inp.get('instruction') or 'batch analysis')[:120]}"
    if tool == "batch_analyze_file":
        return f"Analyzing {inp.get('path') or 'file'}"
    if tool == "web_search":
        return f"Searching the web for {inp.get('query') or 'results'}"
    if tool == "web_fetch":
        return f"Fetching {inp.get('url') or 'page'}"
    if tool == "save_artifact":
        return f"Saving artifact {inp.get('name') or ''}".strip()
    if tool == "list_artifacts":
        return "Checking saved artifacts"
    if tool == "slash_command":
        return f"Running {inp.get('command') or 'slash command'}"
    if tool == "git_status":
        return "Checking git status"
    if tool == "git_diff":
        return "Checking git diff"
    return f"Using {tool}"


def _summarize_model_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    action = action or {}
    kind = str(action.get("type") or "")
    if kind == "tool_call":
        tool = str(action.get("tool") or "")
        inp = action.get("input") or {}
        return _summarize_tool_intent(tool, inp), {"action_type": kind, "tool": tool, "input": inp}
    if kind == "final":
        message = str(action.get("message") or "").strip()
        concise = message.splitlines()[0][:180] if message else "Preparing final response"
        return concise or "Preparing final response", {"action_type": kind}
    return "Re-evaluating next step", {"action_type": kind or "unknown"}

def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    decoder = json.JSONDecoder()
    actions: list[dict[str, Any]] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        if text[idx] != "{":
            idx += 1
            continue
        try:
            parsed, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(parsed, dict):
            actions.append(parsed)
        idx = end
    if actions:
        tool_action = next((action for action in actions if str(action.get("type") or "") == "tool_call"), None)
        if tool_action:
            return tool_action
        final_action = next((action for action in actions if str(action.get("type") or "") == "final"), None)
        if final_action:
            return final_action
        return actions[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _safe_path(session: Session, rel_path: str) -> Path:
    root = Path(session.workspace_path).resolve()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes workspace")
    return target


def _permission(session: Session, config: AppConfig):
    return config.permission_profiles.get(session.permission_profile)


def _session_history_messages(session: Session, current_task_id: str | None = None, max_messages: int = 24) -> list[dict[str, str]]:
    """Rebuild user/assistant chat history from prior session events."""
    events = store.get_events(session.id, limit=800, latest=True)
    messages: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for event in events:
        if current_task_id and event.task_id == current_task_id:
            continue
        event_type = str(event.type or "").lower()
        if event_type not in {"user_message", "result", "final", "assistant_message"}:
            continue
        data = event.data if isinstance(event.data, dict) else {}
        role = str(data.get("role") or ("user" if event_type == "user_message" else "assistant")).lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(event.message or "").strip()
        if not content:
            continue
        signature = (role, event.task_id or "", content)
        if signature in seen_pairs:
            continue
        seen_pairs.add(signature)
        messages.append({"role": role, "content": content})
    if max_messages > 0 and len(messages) > max_messages:
        messages = messages[-max_messages:]
    return messages


async def _run_shell(session: Session, task: Task, command: str, config: AppConfig) -> tuple[str, bool]:
    decision, reason = command_policy(command, session, config)
    if decision == "deny":
        return f"DENIED: {reason}", False
    if decision == "ask" and session.permission_profile != "full-control":
        task.status = TaskStatus.approval_required
        task.metadata["agent_loop"] = True
        task.metadata["pending_tool"] = {"tool": "shell", "input": {"command": command}}
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="approval_required", message=f"Agent wants to run: {command}", data={"command": command, "reason": reason}))
        return "APPROVAL_REQUIRED", True

    store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_started", message=f"shell: {command}", data={"tool":"shell", "command": command}))
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
    store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"shell exited {proc.returncode}", data={"exit_code": proc.returncode, "output": combined[-4000:]}))
    return combined or f"Command exited {proc.returncode} with no output", False


async def execute_tool(session: Session, task: Task, tool: str, inp: dict[str, Any], config: AppConfig) -> tuple[str, bool]:
    ensure_workspace(session)
    allowed = set(session.tools)
    perm = _permission(session, config)
    if not perm:
        return f"DENIED: unknown permission profile {session.permission_profile}", False

    if tool == "list_files":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or ".")
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        if target.is_file():
            return json.dumps({"path": path, "type": "file", "size": target.stat().st_size}), False
        items = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
            if item.name in {".git", "node_modules", "__pycache__", ".venv"}:
                continue
            items.append({"name": item.name, "type": "dir" if item.is_dir() else "file"})
        return json.dumps({"path": path, "items": items}, indent=2), False

    if tool == "read_file":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or "")
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        return target.read_text(errors="replace")[:20000], False


    if tool == "read_file_chunk":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or "")
        chunk_index = int(inp.get("chunk_index") or 0)
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        text = target.read_text(errors="replace")
        chunks = chunk_text(text, max_tokens=chunk_tokens)
        if chunk_index < 0 or chunk_index >= len(chunks):
            return json.dumps({"path": path, "chunk_count": len(chunks), "error": "chunk_index out of range"}), False
        c = chunks[chunk_index]
        return json.dumps({"path": path, "chunk_index": chunk_index, "chunk_count": len(chunks), "start": c["start"], "end": c["end"], "content": c["content"]}, indent=2), False

    if tool == "workspace_manifest":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        max_files = int(inp.get("max_files") or 200)
        return file_manifest(Path(session.workspace_path), max_files=max_files) or "No files found", False

    if tool == "batch_analyze_text":
        instruction = str(inp.get("instruction") or "Summarize this text")
        text = str(inp.get("text") or "")
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        result = batch_reduce_text(config, session.model, instruction, text, chunk_tokens=chunk_tokens)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="batch_result", message=f"Batched analysis completed over {result['chunk_count']} chunks", data={"chunk_count": result["chunk_count"]}))
        return json.dumps({"chunk_count": result["chunk_count"], "summary": result["summary"]}, indent=2), False

    if tool == "batch_analyze_file":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or "")
        instruction = str(inp.get("instruction") or f"Analyze {path}")
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        text = target.read_text(errors="replace")
        result = batch_reduce_text(config, session.model, instruction, text, chunk_tokens=chunk_tokens)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="batch_result", message=f"Batched file analysis completed for {path} over {result['chunk_count']} chunks", data={"path": path, "chunk_count": result["chunk_count"]}))
        return json.dumps({"path": path, "chunk_count": result["chunk_count"], "summary": result["summary"]}, indent=2), False

    if tool == "write_file":
        if perm.file_write == "deny":
            return "DENIED: file writes are denied", False
        if perm.file_write == "ask" and session.permission_profile != "full-control":
            task.status = TaskStatus.approval_required
            task.metadata["agent_loop"] = True
            task.metadata["pending_tool"] = {"tool": "write_file", "input": inp}
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="approval_required", message=f"Agent wants to write file: {inp.get('path')}", data={"path": inp.get("path")}))
            return "APPROVAL_REQUIRED", True
        path = str(inp.get("path") or "")
        content = str(inp.get("content") or "")
        target = _safe_path(session, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"wrote {path}", data={"tool":"write_file", "path": path}))
        return f"WROTE {path} ({len(content)} bytes)", False

    if tool == "shell":
        if "shell" not in allowed:
            return "DENIED: shell tool is not enabled for this session", False
        return await _run_shell(session, task, str(inp.get("command") or ""), config)

    if tool == "slash_command":
        parsed = parse_session_slash_command(str(inp.get("command") or ""))
        if not parsed:
            return "Invalid slash command input", False
        if parsed.get("error"):
            return parsed["error"], False
        if parsed["kind"] == "help":
            return slash_help_text(), False
        if parsed["kind"] == "compact":
            task.metadata["_compact_now"] = True
            return "Context compaction requested.", False
        if parsed["kind"] == "subagent":
            spawned = await spawn_pi_dev_subagent(session, task, str(parsed.get("instruction") or ""), config, run_agent_loop)
            child_session = spawned["session"]
            child_task = spawned["task"]
            return f"{spawned['message']} Child task: {child_task.id}. Child session: {child_session.id}.", False
        if parsed["kind"] == "tool":
            shell_tool = parsed.get("tool") or ""
            shell_args = [str(a) for a in (parsed.get("args") or [])]
            return await execute_tool(session, task, "shell", {"command": shlex_join([shell_tool, *shell_args])}, config)

    if tool == "consult_model":
        if "consult_model" not in allowed:
            return "DENIED: consult_model is not enabled for this session", False
        requested_models = inp.get("models")
        if isinstance(requested_models, list):
            target_models = [str(model).strip() for model in requested_models if str(model).strip()]
        else:
            single = str(inp.get("model") or "").strip()
            target_models = [single] if single else []
        if not target_models:
            return "CONSULT_MODEL_FAILED: specify model or models", False
        unknown = [model for model in target_models if model not in config.models]
        if unknown:
            return f"CONSULT_MODEL_FAILED: unknown configured model(s): {', '.join(unknown)}", False
        prompt = str(inp.get("prompt") or inp.get("question") or "").strip()
        if not prompt:
            return "CONSULT_MODEL_FAILED: prompt is required", False
        max_tokens = int(inp.get("max_tokens") or 1200)
        include_recent = bool(inp.get("include_recent_context", True))
        recent_context = ""
        if include_recent:
            transcript = list(task.metadata.get("agent_transcript") or [])[-6:]
            if transcript:
                recent_context = "\n\nRecent agent context:\n" + json.dumps(transcript, indent=2)
        consult_messages = [
            {
                "role": "system",
                "content": "You are an internal PAC planning consultant. Be concise, actionable, and explicit about risks or missing information.",
            },
            {"role": "user", "content": prompt + recent_context},
        ]

        async def _consult(target_model: str) -> dict[str, Any]:
            try:
                response = await asyncio.to_thread(chat_complete, config, target_model, consult_messages, max_tokens=max_tokens)
                return {"model": target_model, "ok": True, "response": response}
            except Exception as exc:
                return {"model": target_model, "ok": False, "error": str(exc)}

        results = await asyncio.gather(*[_consult(model_name) for model_name in target_models])
        store.add_event(Event(session_id=session.id, task_id=task.id, type="model_consult", message=f"Consulted {len(target_models)} model(s)", data={"models": target_models, "ok": sum(1 for item in results if item.get('ok')), "failed": sum(1 for item in results if not item.get('ok'))}))
        return as_json_text({"results": results}), False

    if tool == "web_fetch":
        if "web_fetch" not in allowed and "internet" not in allowed:
            return "DENIED: web_fetch/internet tool is not enabled for this session", False
        if perm.network == "deny":
            return "DENIED: network access is denied", False
        if perm.network == "ask" and session.permission_profile != "full-control":
            task.status = TaskStatus.approval_required
            task.metadata["agent_loop"] = True
            task.metadata["pending_tool"] = {"tool": "web_fetch", "input": inp}
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="approval_required", message=f"Agent wants to fetch URL: {inp.get('url')}", data={"url": inp.get("url")}))
            return "APPROVAL_REQUIRED", True
        url = str(inp.get("url") or "")
        max_chars = int(inp.get("max_chars") or 20000)
        try:
            result = fetch_page_text(url, max_chars=max_chars)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="web_fetch", message=f"Fetched {url}", data={"url": url, "source": result.get("source"), "title": result.get("title")}))
            return as_json_text(result), False
        except Exception as exc:
            return f"WEB_FETCH_FAILED: {exc}", False

    if tool == "web_search":
        if "web_search" not in allowed and "internet" not in allowed:
            return "DENIED: web_search/internet tool is not enabled for this session", False
        if perm.network == "deny":
            return "DENIED: network access is denied", False
        if perm.network == "ask" and session.permission_profile != "full-control":
            task.status = TaskStatus.approval_required
            task.metadata["agent_loop"] = True
            task.metadata["pending_tool"] = {"tool": "web_search", "input": inp}
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="approval_required", message=f"Agent wants to search web: {inp.get('query')}", data={"query": inp.get("query")}))
            return "APPROVAL_REQUIRED", True
        query = str(inp.get("query") or "")
        max_results = int(inp.get("max_results") or 5)
        try:
            result = search_web_text(query, max_results=max_results)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="web_search", message=f"Searched web: {query}", data={"query": query, "results": len(result.get("results", []))}))
            return as_json_text(result), False
        except Exception as exc:
            return f"WEB_SEARCH_FAILED: {exc}", False

    if tool == "save_artifact":
        name = str(inp.get("name") or "artifact.txt")
        content = str(inp.get("content") or "")
        meta = write_artifact(config.server.data_dir, session.id, task.id, name, content.encode("utf-8"))
        store.add_event(Event(session_id=session.id, task_id=task.id, type="artifact_saved", message=f"Saved artifact {name}", data=meta))
        return as_json_text(meta), False

    if tool == "list_artifacts":
        return as_json_text({"artifacts": list_artifacts(config.server.data_dir, session.id, task.id)}), False

    if tool == "git_status":
        result = subprocess.run(["git", "status", "--short", "--branch"], cwd=session.workspace_path, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr or "No git status output", False

    if tool == "git_diff":
        result = subprocess.run(["git", "diff", "--"], cwd=session.workspace_path, capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr or "No diff", False

    return f"Unknown tool: {tool}", False


async def run_agent_loop(session: Session, task: Task, config: AppConfig) -> Task:
    ensure_workspace(session)
    task.metadata["agent_loop"] = True
    task.status = TaskStatus.running
    session.status = SessionStatus.running
    store.add_session(session)
    store.add_task(task)

    agent = config.agent_profiles.get(session.agent_profile or "")
    context_name = (agent.context_profile if agent and agent.context_profile else session.context_mode)
    decision_model = agent.planner_model if agent and agent.planner_model else session.model
    decision_context_name = agent.planner_context_profile if agent and agent.planner_context_profile else context_name
    ctx = effective_context(config, decision_model, decision_context_name)
    budget = get_context_budget(config, decision_model, decision_context_name)
    full_control = session.permission_profile == "full-control"
    store.add_event(Event(session_id=session.id, task_id=task.id, type="agent_loop_started", message="Agent loop started", data={"model": session.model, "decision_model": decision_model, "planner_model": agent.planner_model if agent else None, "permission_profile": session.permission_profile, "full_control": full_control, "effective_context": ctx, "endpoint_id": task.metadata.get("runner_id"), "endpoint_locked": task.metadata.get("endpoint_locked"), "agent_enabled": task.metadata.get("agent_enabled", True), "requested_command": task.metadata.get("requested_command"), "routing": task.metadata.get("routing", "agent")}))
    if full_control:
        store.add_event(Event(session_id=session.id, task_id=task.id, type="full_control_enabled", message="FULL CONTROL MODE ENABLED: approvals are bypassed, but every tool action is logged."))

    messages: list[dict[str, str]] = [
        {"role": "system", "content": (agent.system_prompt if agent else "You are a remote coding agent.") + "\n\n" + TOOL_HELP},
    ]
    messages.extend(_session_history_messages(session, current_task_id=task.id, max_messages=24))
    messages.append({"role": "user", "content": task.prompt})

    pending = task.metadata.pop("pending_tool", None)
    if pending:
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_resumed", message=f"Resuming approved tool: {pending.get('tool')}", data=pending))
        observation, paused = await execute_tool(session, task, pending.get("tool", ""), pending.get("input", {}), config)
        if paused:
            return task
        messages.append({"role": "assistant", "content": json.dumps(pending)})
        messages.append({"role": "user", "content": "Tool result:\n" + observation})
    max_runtime_minutes = max(1, int(task.metadata.get("max_runtime_minutes") or (getattr(agent, "max_runtime_minutes", 60) if agent else 60)))
    deadline = time.monotonic() + (max_runtime_minutes * 60)
    transcript: list[dict[str, Any]] = task.metadata.get("agent_transcript") or []
    rolling_summary = task.metadata.get("rolling_context_summary")
    step = 0
    while True:
        step += 1
        latest_task = store.get_task(task.id) or task
        stop_requested = bool((latest_task.metadata or {}).get("stop_requested"))
        if stop_requested:
            task = latest_task
            task.status = TaskStatus.completed
            task.output = "Agent stopped by user."
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=task.output, data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile, "stop_reason": "user_stop"}))
            session.status = SessionStatus.created
            store.add_session(session)
            return task
        if time.monotonic() >= deadline:
            task.status = TaskStatus.completed
            task.output = f"Agent stopped after reaching the runtime limit of {max_runtime_minutes} minute(s). Check the timeline and diff for partial work."
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=task.output, data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile, "stop_reason": "runtime_limit"}))
            session.status = SessionStatus.created
            store.add_session(session)
            return task
        current_tokens = message_tokens(messages)
        threshold = int(budget.input_budget_tokens * 0.82)
        if current_tokens > threshold:
            messages, rolling_summary, did_compact = compact_messages_basic(messages, budget, rolling_summary)
            if did_compact:
                task.metadata["rolling_context_summary"] = rolling_summary
                task.metadata["context_tokens_estimate"] = message_tokens(messages)
                store.add_task(task)
                store.add_event(Event(session_id=session.id, task_id=task.id, type="context_compacted", message=f"Compacted context from ~{current_tokens} tokens to ~{message_tokens(messages)} tokens", data={"before_tokens": current_tokens, "after_tokens": message_tokens(messages), "budget_tokens": budget.budget_tokens}))

        remaining_seconds = max(0, int(deadline - time.monotonic()))
        store.add_event(Event(session_id=session.id, task_id=task.id, type="agent_thinking", message=f"Agent step {step} (~{message_tokens(messages)}/{budget.input_budget_tokens} input tokens, ~{remaining_seconds}s left)"))
        try:
            raw = await asyncio.to_thread(chat_complete, config, decision_model, messages, max_tokens=min(ctx["reserve_output_tokens"], 4096))
        except Exception as exc:
            task.status = TaskStatus.failed
            task.error = f"Model call failed: {exc}"
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="task_failed", message=task.error))
            return task

        transcript.append({"step": step, "model": raw})
        store.add_event(Event(session_id=session.id, task_id=task.id, type="model_response", message=raw[-4000:], data={"role": "assistant", "model": decision_model, "session_model": session.model, "endpoint_id": task.metadata.get("runner_id"), "step": step}))
        try:
            action = _extract_json(raw)
        except Exception:
            task.status = TaskStatus.completed
            task.output = raw
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=raw[-4000:], data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile}))
            return task

        thought_summary, thought_meta = _summarize_model_action(action)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="agent_intent", message=thought_summary, data={"role": "assistant", "model": decision_model, "session_model": session.model, "endpoint_id": task.metadata.get("runner_id"), "step": step, **thought_meta}))

        if action.get("type") == "final":
            task.status = TaskStatus.completed
            task.output = str(action.get("message") or "")
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=task.output[-4000:], data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile}))
            session.status = SessionStatus.created
            store.add_session(session)
            return task

        if action.get("type") == "tool_call":
            tool = str(action.get("tool") or "")
            inp = action.get("input") or {}
            store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_call", message=tool, data={"tool": tool, "input": inp}))
            observation, paused = await execute_tool(session, task, tool, inp, config)
            transcript.append({"step": step, "tool": tool, "input": inp, "observation": observation[-4000:]})
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            if paused:
                return task
            latest_task = store.get_task(task.id) or task
            if (latest_task.metadata or {}).get("stop_requested"):
                task = latest_task
                task.status = TaskStatus.completed
                task.output = "Agent stopped by user."
                task.metadata["agent_transcript"] = transcript[-20:]
                store.add_task(task)
                store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=task.output, data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile, "stop_reason": "user_stop"}))
                session.status = SessionStatus.created
                store.add_session(session)
                return task
            if task.metadata.pop("_compact_now", False):
                before_tokens = message_tokens(messages)
                messages, rolling_summary, did_compact = compact_messages_basic(messages, budget, rolling_summary)
                if did_compact:
                    task.metadata["rolling_context_summary"] = rolling_summary
                    task.metadata["context_tokens_estimate"] = message_tokens(messages)
                    store.add_task(task)
                    store.add_event(Event(session_id=session.id, task_id=task.id, type="context_compacted", message=f"Compacted context from ~{before_tokens} tokens to ~{message_tokens(messages)} tokens", data={"before_tokens": before_tokens, "after_tokens": message_tokens(messages), "budget_tokens": budget.budget_tokens, "source": "agent_slash_command"}))
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": "Tool result:\n" + observation})
            # crude context trim: keep system, original prompt, and recent tool turns
            if len(messages) > 14:
                messages = messages[:2] + messages[-12:]
            continue

        messages.append({"role": "user", "content": "Invalid action. Return either a final answer or a valid tool_call JSON object."})
