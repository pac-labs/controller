from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from shlex import join as shlex_join
from uuid import uuid4
from typing import Any

from .config import AppConfig
from .models import Event, Session, SessionStatus, Task, TaskStatus, RunnerJob, RunnerJobStatus, RunnerExecutionMode
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
from .workspace_index import build_workspace_index
from .workspace_lessons import save_lesson, load_lessons, search_lessons, get_project_memory
from .background_jobs import start_job
from .checkpoint import save_checkpoint, load_latest_checkpoint, list_checkpoints


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
{"type":"tool_call","tool":"remote_memory","input":{"mode":"bundle","profile":"doc-reader","user":"dorbian","workspace":"customer-a"}}
{"type":"tool_call","tool":"remote_memory","input":{"mode":"search","query":"git author email","kind":"user","limit":5}}
{"type":"tool_call","tool":"save_artifact","input":{"name":"notes/result.txt","content":"..."}}
{"type":"tool_call","tool":"list_artifacts","input":{}}
{"type":"tool_call","tool":"slash_command","input":{"command":"/rg TODO src"}}

Rules:
- Prefer inspecting files before editing.
- Use shell only when needed.
- Keep commands scoped to the workspace.
- If blocked by policy, explain what approval or permission is needed.
- Do not narrate future actions like "I will now search" or "I am going to run...". If a tool should run, return a tool_call immediately.
- Do not print tool-call markup or pseudo-code examples in the final answer. Execute the tool call instead.
- If approval is needed, ask for that approval directly and briefly instead of saying the action has already started.
- For small-context models, prefer workspace_manifest, read_file_chunk, web_fetch max_chars, and batch_analyze_file over loading many large files at once.
- Use web_search before web_fetch when you do not know the exact URL.
- Use consult_model when you want a second opinion from another configured PAC model or want to fan out a planning question to multiple models.
- Use remote_memory when profile/user/workspace memory may contain relevant prior preferences, customer context, or durable notes.
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


def _extract_wrapped_tool_call(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    match = re.search(r"<\|tool_call\>\s*call:((?:tool_call:)?[A-Za-z0-9_:-]+)\s*(.*?)\s*<tool_call\|>", raw, re.DOTALL)
    if not match:
        return None
    tool = str(match.group(1) or "").strip()
    if tool.startswith("tool_call:"):
        tool = tool.split("tool_call:", 1)[1].strip()
    if not tool:
        return None
    raw_input = _extract_balanced_jsonish(str(match.group(2) or "").strip())
    try:
        parsed_input = _load_loose_json_object(raw_input)
    except Exception:
        parsed_input = None
    if not isinstance(parsed_input, dict):
        return None
    inp = parsed_input.get("input") if isinstance(parsed_input.get("input"), dict) else parsed_input
    return {"type": "tool_call", "tool": tool, "input": inp}


def _extract_balanced_jsonish(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    start = -1
    opener = ""
    for idx, ch in enumerate(raw):
        if ch in "{[":
            start = idx
            opener = ch
            break
    if start < 0:
        return raw
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    return raw[start:]


def _load_loose_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    normalized = raw
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = "{" + normalized[1:-1].strip() + "}"
    normalized = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)', r'\1"\2"\3', normalized)
    normalized = normalized.replace("'", '"')
    normalized = re.sub(r':\s*True\b', ': true', normalized)
    normalized = re.sub(r':\s*False\b', ': false', normalized)
    normalized = re.sub(r':\s*None\b', ': null', normalized)
    def _quote_bare_value(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_value = str(match.group(2) or "")
        stripped = raw_value.strip()
        if not stripped:
            return prefix + raw_value
        if stripped[0] in '"{[':
            return prefix + raw_value
        if stripped in {"true", "false", "null"}:
            return prefix + stripped
        if re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
            return prefix + stripped
        return prefix + json.dumps(stripped)

    normalized = re.sub(r'(:\s*)([^"\{\[\],][^,\}\]]*)', _quote_bare_value, normalized)
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start >= 0 and end > start:
        candidate = normalized[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None

def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    wrapped = _extract_wrapped_tool_call(text)
    if wrapped:
        return wrapped
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
        loose = _load_loose_json_object(text)
        if loose:
            return loose
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            loose = _load_loose_json_object(text[start : end + 1])
            if loose:
                return loose
            return json.loads(text[start : end + 1])
        raise


def _looks_like_wrapped_tool_markup(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return (
        "<|tool_call>" in raw
        or "<tool_call|>" in raw
        or '"type":"tool_call"' in raw
        or '"type": "tool_call"' in raw
        or "call:tool_call:" in raw
        or re.search(r"\bcall:[a-z0-9_:-]+\s*[\[{]", raw) is not None
    )


def _looks_like_action_narration(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    signals = (
        "i will ",
        "i'll ",
        "i am going to ",
        "i'm going to ",
        "i am running ",
        "i'm running ",
        "i will use ",
        "i will perform ",
        "i will search ",
        "i will inspect ",
        "i will scan ",
        "i will list ",
        "i will read ",
    )
    return any(signal in raw for signal in signals)


def _controller_session_guidance(session: Session) -> str | None:
    if not session.metadata.get("controller_harness"):
        return None
    workspace = str(session.workspace_path or "").strip() or "the PAC controller workspace"
    return (
        "You are operating as PAC's built-in controller session.\n"
        f"Primary local source of truth: {workspace}\n"
        "For PAC-domain questions about code, sessions, wrappers, providers, profiles, endpoints, settings, updates, logs, or configuration, inspect the local PAC workspace/configuration first.\n"
        "Prefer local tools like workspace_manifest, list_files, read_file, read_file_chunk, rg/shell, git_status, and git_diff before web_search or web_fetch.\n"
        "Only use the web when the user explicitly asks for external information or the local PAC workspace clearly cannot answer the question.\n"
        "If the user asks to update PAC behavior or configuration, you are allowed to rewrite PAC application files and PAC configuration directly. Do the work instead of only describing it.\n"
        "Assume PAC-specific terms like PAC RAM, plugins, sessions, wrappers, endpoints, and profiles refer to this PAC installation unless the user explicitly broadens the scope.\n"
        "For broad PAC requests, inspect first and answer from local evidence instead of asking generic clarifying questions."
    )


def _controller_session_runtime_context(session: Session, config: AppConfig) -> str | None:
    if not session.metadata.get("controller_harness"):
        return None
    workspace = str(session.workspace_path or "").strip() or "-"
    data_dir = str(config.server.data_dir or "").strip() or "-"
    config_path = f"{data_dir.rstrip('/')}/config/config.yaml" if data_dir not in {"-", ""} else "-"
    public_url = str(config.server.public_url or "").strip() or "-"
    endpoint_id = str(session.metadata.get("preferred_endpoint") or "local-PAC")
    tool_names = []
    agent = config.agent_profiles.get(session.agent_profile or "")
    if agent:
        tool_names = list(agent.tools or [])
    if not tool_names:
        tool_names = list(config.tools.keys())
    top_level_hints = ["pi_agent_platform/", "binaries/", "containers/", "plugins/", "docs/", "config/"]
    return (
        "PAC controller runtime snapshot:\n"
        f"- controller workspace: {workspace}\n"
        f"- PAC data dir: {data_dir}\n"
        f"- PAC config path: {config_path}\n"
        f"- public URL: {public_url}\n"
        f"- preferred local endpoint: {endpoint_id}\n"
        f"- common top-level source paths: {', '.join(top_level_hints)}\n"
        f"- available tools in this session: {', '.join(tool_names[:20]) or '-'}\n"
        "Use this snapshot as background context; verify details in files or runtime state before making precise claims."
    )


def _save_task_lesson(session: Session, task: Task, transcript: list[dict], config: AppConfig) -> None:
    """
    Save a lesson to workspace memory on task completion.
    Called from both completed and failed task exits.
    """
    if not session.workspace_path:
        return

    # Determine category and title from task
    category = "task_result"
    title = task.prompt[:80] if task.prompt else "untitled task"

    # Extract files touched
    files_touched = []
    for entry in transcript:
        inp = entry.get("input", {})
        if isinstance(inp, dict):
            path = inp.get("path") or inp.get("file") or ""
            if path and path not in files_touched:
                files_touched.append(path)
        elif isinstance(inp, str) and inp not in files_touched:
            files_touched.append(inp[:200])

    # Extract tool calls
    tool_calls = [{"tool": e.get("tool"), "input": e.get("input", {}), "observation": e.get("observation", "")[:500]} for e in transcript[-12:]]

    # Body: what was the task, what was the outcome
    body_parts = []
    if task.output:
        body_parts.append(f"Outcome: {task.output[:1000]}")
    if task.error:
        body_parts.append(f"Error: {task.error[:500]}")

    # Add workspace index info if available
    idx = task.metadata.get("workspace_index", {})
    if idx:
        pt = idx.get("project_type", "unknown")
        fc = idx.get("tree", {}).get("file_count", 0)
        body_parts.append(f"Workspace: {pt} project, {fc} files indexed")
        proj = idx.get("projects", [])
        if proj:
            body_parts.append(f"Projects: {', '.join(p.get('type', '') for p in proj)}")

    body = "\n".join(body_parts) or title

    try:
        save_lesson(
            workspace_path=session.workspace_path,
            category=category,
            title=title,
            body=body,
            tags=["task", session.agent_profile or "pi-dev"],
            tool_calls=tool_calls,
            files_touched=files_touched[:20],
        )
    except Exception:
        pass  # Don't let lesson saving failures break task completion


def _format_workspace_index_briefing(idx: dict) -> str:
    """Format the workspace index as a compact system-message briefing."""
    if idx.get("error"):
        return ""
    lines = ["=== WORKSPACE PROJECT CONTEXT ==="]
    pt = idx.get("project_type", "unknown")
    projects = idx.get("projects", [])
    if projects:
        proj_types = ', '.join(p['type'] for p in projects)
        lines.append(f"Project: {proj_types}")
    else:
        lines.append(f"Project type: {pt}")

    tree = idx.get("tree", {})
    fc = tree.get("file_count", 0)
    tb = tree.get("total_bytes", 0)
    if fc:
        mb = tb / (1024 * 1024)
        lines.append(f"Files: {fc} (~{mb:.1f} MB)")

    syms = idx.get("python_symbols", [])
    if syms:
        top_files = sorted(syms, key=lambda s: len(s.get("defs", [])) + len(s.get("classes", [])), reverse=True)[:8]
        lines.append(f"Python top files: {', '.join(s['file'] for s in top_files)}")

    git = idx.get("git_summary", {})
    if git.get("branch"):
        lines.append(f"Git branch: {git['branch']}, {git.get('total_commits', 0)} commits")
        recent = git.get("recent_commits", [])
        if recent:
            lines.append(f"Recent: {recent[0].get('message', '')} ({recent[0].get('hash', '')})")

    key_files = idx.get("key_files", [])
    if key_files:
        roles = {}
        for kf in key_files:
            role = kf.get("role", "other")
            if role not in roles:
                roles[role] = []
            roles[role].append(kf["path"])
        lines.append(f"Key files: {', '.join(roles.get('documentation', [])[:2])}")

    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


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
    controller_session = bool(session.metadata.get("controller_harness"))
    def _looks_like_raw_tool_call(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        if "<|tool_call>" in text and "<tool_call|>" in text:
            return True
        if text.startswith('{"type":"tool_call"') or text.startswith("{'type':'tool_call'"):
            return True
        return False
    def _looks_like_low_value_controller_history(content: str) -> bool:
        text = str(content or "").strip().lower()
        if not text:
            return True
        markers = (
            "understood. i will",
            "understood. all future responses",
            "the provided context details",
            "i am ready to operate",
            "please provide the specific task",
            "i maintain full context",
        )
        return any(marker in text for marker in markers)
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
        if role == "assistant" and _looks_like_raw_tool_call(content):
            continue
        if controller_session and role == "assistant" and _looks_like_low_value_controller_history(content):
            continue
        signature = (role, event.task_id or "", content)
        if signature in seen_pairs:
            continue
        seen_pairs.add(signature)
        messages.append({"role": role, "content": content})
    effective_max = 6 if controller_session else max_messages
    if effective_max > 0 and len(messages) > effective_max:
        messages = messages[-effective_max:]
    return messages


def _prompt_requests_codebase_inspection(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    keywords = [
        "codebase",
        "repo",
        "repository",
        "workspace",
        "source",
        "entrypoint",
        "entry point",
        "look at the code",
        "find the code",
        "inspect the code",
        "main app",
        "where is",
        "how does",
        "what file",
        "which file",
    ]
    return any(k in text for k in keywords)


def _has_meaningful_codebase_inspection(transcript: list[dict[str, Any]]) -> bool:
    deep_tools = {"workspace_manifest", "read_file", "read_file_chunk", "batch_analyze_file", "git_diff", "git_status", "shell"}
    shallow_tools = {"list_files"}
    used = [str(item.get("tool") or "") for item in transcript if item.get("tool")]
    if any(tool in deep_tools for tool in used):
        return True
    # A bare top-level listing is not enough for architecture / entrypoint answers.
    if used.count("list_files") >= 2:
        return True
    return False


def _looks_like_generic_ready_response(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    markers = (
        "i am ready to proceed",
        "please provide the specific task",
        "please provide the next task",
        "ready to operate",
        "the provided context details",
        "the platform capabilities",
        "i maintain full context",
    )
    return any(marker in raw for marker in markers)


def _is_broad_codebase_request(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    broad_signals = [
        "look at the code",
        "look at the codebase",
        "look at pac",
        "scan the workspace",
        "inspect the workspace",
        "what is in",
        "what does this repo",
        "understand the codebase",
        "find the source",
        "where stuff is",
    ]
    return any(signal in text for signal in broad_signals)


def _inspection_depth_score(transcript: list[dict[str, Any]]) -> float:
    score = 0.0
    for item in transcript:
        tool = str(item.get("tool") or "")
        if tool == "workspace_manifest":
            score += 2.0
        elif tool in {"git_status", "git_diff", "batch_analyze_file", "batch_analyze_text"}:
            score += 1.5
        elif tool == "shell":
            command = str((item.get("input") or {}).get("command") or "")
            if any(term in command for term in ("rg ", "grep ", "find ", "fd ")):
                score += 2.0
            else:
                score += 1.0
        elif tool == "read_file":
            path = str((item.get("input") or {}).get("path") or "").lower()
            if path.endswith(("readme.md", "readme", ".md", ".adoc")):
                score += 0.5
            else:
                score += 1.25
        elif tool == "read_file_chunk":
            score += 1.0
        elif tool == "list_files":
            score += 0.5
    return score


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
    store.add_event(Event(session_id=session.id, task_id=task.id, type="runner_job_queued", message=f"Queued {tool} on runner {runner.name}", data={"runner_id": runner.id, "runner_job_id": job.id, "execution_mode": job.execution_mode, "command": command, "container_image": container_image}))
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
    runner_result = await _run_tool_via_runner(session, task, tool, inp, config)
    if runner_result is not None:
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"{tool} executed in workspace container", data={"tool": tool, "endpoint_id": task.metadata.get("runner_id") or session.metadata.get("preferred_endpoint"), "execution_mode": "container"}))
        return runner_result

    if tool == "list_files":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or ".")
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        if target.is_file():
            result = json.dumps({"path": path, "type": "file", "size": target.stat().st_size})
            store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"listed file {path}", data={"tool": "list_files", "path": path, "result_preview": result[:1200]}))
            return result, False
        items = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
            if item.name in {".git", "node_modules", "__pycache__", ".venv"}:
                continue
            items.append({"name": item.name, "type": "dir" if item.is_dir() else "file"})
        result = json.dumps({"path": path, "items": items}, indent=2)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"listed {path}", data={"tool": "list_files", "path": path, "count": len(items), "result_preview": result[:1200]}))
        return result, False

    if tool == "read_file":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        path = str(inp.get("path") or "")
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        result = target.read_text(errors="replace")[:20000]
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"read {path}", data={"tool": "read_file", "path": path, "chars": len(result)}))
        return result, False


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
        result = json.dumps({"path": path, "chunk_index": chunk_index, "chunk_count": len(chunks), "start": c["start"], "end": c["end"], "content": c["content"]}, indent=2)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"read chunk {chunk_index} from {path}", data={"tool": "read_file_chunk", "path": path, "chunk_index": chunk_index, "chunk_count": len(chunks)}))
        return result, False

    if tool == "edit_file":
        if perm.file_write == "deny":
            return "DENIED: file writes are denied", False
        path = str(inp.get("path") or "")
        old_text = str(inp.get("old_text") or "")
        new_text = str(inp.get("new_text") or "")
        if not path or not old_text:
            return "edit_file requires path and old_text", False
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        content = target.read_text(errors="replace")
        if old_text not in content:
            return f"old_text not found in {path} — no changes made", False
        backup_path = target.with_suffix(target.suffix + ".bak")
        target.write_text(content, encoding="utf-8")  # overwrite backup with original
        new_content = content.replace(old_text, new_text, 1)  # replace first occurrence only
        target.write_text(new_content, encoding="utf-8")
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"edited {path}", data={"tool": "edit_file", "path": path}))
        return f"EDITED {path}: replaced 1 occurrence", False

    if tool == "ripgrep":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        query = str(inp.get("query") or "")
        path = str(inp.get("path") or session.workspace_path)
        file_filter = str(inp.get("file_filter") or "")
        context = max(0, min(int(inp.get("context") or 0), 5))
        max_results = max(1, min(int(inp.get("max_results") or 200), 2000))
        if not query:
            return "ripgrep requires query", False
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        import re
        try:
            pattern = re.compile(query)
        except Exception:
            pattern = re.compile(re.escape(query))
        matches = []
        try:
            files = list(target.rglob(file_filter or "*"))
        except Exception:
            files = []
        for f in files:
            if f.is_dir() or "/.git/" in str(f) or "/node_modules/" in str(f) or "/__pycache__/" in str(f):
                continue
            try:
                lines = f.read_text(errors="replace").split("\n")
            except Exception:
                continue
            for i, line in enumerate(lines):
                if pattern.search(line):
                    ctx_before = lines[max(0, i - context):i]
                    ctx_after = lines[i + 1:i + 1 + context]
                    matches.append({
                        "file": str(f.relative_to(target)),
                        "line": i + 1,
                        "text": line.strip(),
                        "context_before": ctx_before,
                        "context_after": ctx_after,
                    })
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        result = json.dumps({"query": query, "path": str(path), "count": len(matches), "matches": matches[:max_results]}, indent=2)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"ripgrep: {query} → {len(matches)} matches", data={"tool": "ripgrep", "query": query, "count": len(matches)}))
        return result[:15000], False

    if tool == "fd":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        pattern = str(inp.get("pattern") or "*")
        path = str(inp.get("path") or session.workspace_path)
        max_results = max(1, min(int(inp.get("max_results") or 200), 2000))
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        results = []
        try:
            for f in target.rglob(pattern):
                if "/.git/" in str(f) or "/node_modules/" in str(f) or "/__pycache__/" in str(f):
                    continue
                rel = str(f.relative_to(target))
                results.append({"name": rel, "type": "dir" if f.is_dir() else "file", "size": f.stat().st_size if f.is_file() else 0})
                if len(results) >= max_results:
                    break
        except Exception as e:
            return f"fd error: {e}", False
        return json.dumps({"pattern": pattern, "count": len(results), "results": results}, indent=2)[:15000], False

    if tool == "workspace_manifest":
        if perm.file_read == "deny":
            return "DENIED: file reads are denied", False
        max_files = int(inp.get("max_files") or 200)
        import re
        _ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
        _ignored_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".tar", ".sqlite", ".db", ".pyc"}
        _project_markers = {
            "package.json": "Node",
            "pyproject.toml": "Python",
            "setup.py": "Python",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "requirements.txt": "Python",
            "Gemfile": "Ruby",
            "pom.xml": "Java",
            "build.gradle": "Java",
        }
        _key_files = ["README.md", "README", "readme.md", "README.rst", "config.yaml", "config.yml", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile", "Dockerfile", ".dockerignore", ".gitignore", "pyproject.toml", "setup.py", "setup.cfg"]

        root = Path(session.workspace_path)
        files_tree: dict = {}
        flat_files: list[dict] = []
        projects: list[dict] = []
        total_size = 0
        file_count = 0
        detected_project_types: set[str] = set()
        key_files_found: dict[str, str] = {}

        def _tree_get(tree: dict, parts: list[str]) -> dict:
            node = tree
            for part in parts:
                if part not in node:
                    node[part] = {"__files": [], "__dirs": {}}
                node = node[part]
            return node

        def _add_to_tree(tree: dict, rel_path: Path) -> None:
            parts = list(rel_path.parts[:-1])
            if not parts:
                tree.setdefault("__files", []).append(rel_path.name)
                return
            node = _tree_get(tree, parts)
            node.setdefault("__files", []).append(rel_path.name)

        def _build_readme_snippet(p: Path) -> str:
            try:
                text = p.read_text(errors="replace")
                lines = [l.strip() for l in text.splitlines() if l.strip()][:10]
                return "\n".join(lines[:5])
            except Exception:
                return ""

        try:
            for p in root.rglob("*"):
                if file_count >= max_files:
                    break
                if any(part in _ignored for part in p.parts):
                    continue
                if p.is_file():
                    ext = p.suffix.lower()
                    if ext in _ignored_ext:
                        continue
                    try:
                        size = p.stat().st_size
                        total_size += size
                        file_count += 1
                    except OSError:
                        continue
                    rel = p.relative_to(root)
                    _add_to_tree(files_tree, rel)
                    flat_files.append({"path": str(rel), "size": size})
                    fname = p.name
                    fname_lower = fname.lower()
                    for marker, ptype in _project_markers.items():
                        if fname == marker:
                            detected_project_types.add(ptype)
                            project_root = str(p.parent.relative_to(root))
                            readme_p = None
                            for rf in ["README.md", "README.rst", "README", "readme.md"]:
                                candidate = p.parent / rf
                                if candidate.is_file():
                                    readme_p = candidate
                                    break
                            readme_snippet = _build_readme_snippet(readme_p) if readme_p else ""
                            projects.append({"type": ptype, "root": project_root or ".", "readme": readme_snippet[:200]})
                    for kf in _key_files:
                        if fname_lower == kf.lower():
                            key_files_found[fname] = str(rel)
                elif p.is_dir():
                    rel = p.relative_to(root)
                    parts = list(rel.parts)
                    node = _tree_get(files_tree, parts)
        except Exception:
            pass

        result = {
            "path": str(root),
            "summary": {"files": file_count, "total_bytes": total_size},
            "projects": list(detected_project_types),
            "project_details": projects,
            "key_files": key_files_found,
            "tree": files_tree,
            "flat_files": flat_files[:100],
        }
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message="scanned workspace manifest", data={"tool": "workspace_manifest", "files": file_count, "projects": list(detected_project_types)}))
        return json.dumps(result, indent=2, default=str)[:15000], False

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

    if tool == "query_workspace_index":
        # Let agent query the pre-built workspace index without re-scanning
        idx = task.metadata.get("workspace_index") or {}
        if not idx or idx.get("error"):
            return "No workspace index available", False
        query = str(inp.get("query") or "").lower()
        result_type = str(inp.get("type") or "summary").lower()

        if result_type == "symbols" or "symbol" in query or "function" in query or "class" in query:
            syms = idx.get("python_symbols", [])
            if not syms:
                return json.dumps({"note": "no Python symbols indexed"}), False
            return json.dumps({"type": "python_symbols", "count": len(syms), "files": syms[:50]}, indent=2)[:12000], False

        if result_type == "tree" or "tree" in query or "structure" in query or "files" in query:
            tree = idx.get("tree", {}).get("root", {})

            def _truncate_tree(t: dict, depth: int = 4) -> dict:
                if depth <= 0:
                    return {"type": "dir", "truncated": True}
                result = {}
                for k, v in list(t.items())[:40]:
                    if isinstance(v, dict) and v.get("type") == "dir":
                        result[k] = {"type": "dir", "children": _truncate_tree(v.get("children", {}), depth - 1)}
                    else:
                        result[k] = v
                return result

            return json.dumps({"type": "file_tree", "tree": _truncate_tree(tree, depth=4)}, indent=2)[:12000], False

        if result_type == "git" or "commit" in query or "history" in query or "change" in query:
            git = idx.get("git_summary", {})
            if git.get("error"):
                return f"No git info: {git.get('error', 'unknown')}", False
            return json.dumps({"type": "git_summary", **git}, indent=2)[:12000], False

        if result_type == "key_files" or "config" in query or "readme" in query:
            kf = idx.get("key_files", [])
            return json.dumps({"type": "key_files", "count": len(kf), "files": kf}, indent=2)[:12000], False

        # Default: return project summary
        summary = {
            "project_type": idx.get("project_type"),
            "projects": idx.get("projects", []),
            "file_count": idx.get("tree", {}).get("file_count", 0),
            "total_bytes": idx.get("tree", {}).get("total_bytes", 0),
            "python_files": len(idx.get("python_symbols", [])),
            "git_branch": idx.get("git_summary", {}).get("branch"),
            "git_total_commits": idx.get("git_summary", {}).get("total_commits", 0),
            "recent_commit": idx.get("git_summary", {}).get("recent_commits", [{}])[0] if idx.get("git_summary", {}).get("recent_commits") else None,
        }
        return json.dumps({"type": "workspace_summary", **summary}, indent=2)[:8000], False

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

    # --- Stage 4: ops + runtime tools ---

    if tool == "shell_bg":
        if perm.shell == "deny":
            return "DENIED: shell access is denied", False
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
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"shell_bg started job {job_id}: {command[:100]}", data={"tool": "shell_bg", "job_id": job_id, "command": command}))
        return json.dumps({"job_id": job_id, "status": "running", "command": command}), False

    if tool == "shell_bg_result":
        job_id = str(inp.get("job_id") or "").strip()
        if not job_id:
            return "shell_bg_result requires job_id", False
        from .background_jobs import get_job
        job = get_job(job_id)
        if not job:
            return json.dumps({"job_id": job_id, "status": "unknown", "error": "job not found"}), False
        return json.dumps(job.to_dict(), indent=2)[:12000], False

    if tool == "shell_bg_stop":
        job_id = str(inp.get("job_id") or "").strip()
        if not job_id:
            return "shell_bg_stop requires job_id", False
        from .background_jobs import stop_job
        ok = stop_job(job_id)
        return json.dumps({"job_id": job_id, "stopped": ok}), False

    if tool == "log_tail":
        if perm.file_read == "deny" and perm.shell == "deny":
            return "DENIED: no read or shell access", False
        path = str(inp.get("path") or "")
        container = str(inp.get("container") or "")
        lines = max(1, min(int(inp.get("lines") or 50), 500))
        filter_pattern = str(inp.get("grep") or "")
        follow = bool(inp.get("follow"))

        if container:
            # podman logs
            if perm.shell == "deny":
                return "DENIED: shell access required for container logs", False
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
            store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"log_tail container={container} lines={lines}", data={"tool": "log_tail", "container": container, "lines": lines}))
            return combined or "no logs found", False
        elif path:
            if perm.file_read == "deny":
                return "DENIED: file read access denied", False
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
            store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"log_tail path={path} lines={lines}", data={"tool": "log_tail", "path": path, "lines": lines}))
            return result[-8000:], False
        else:
            return "log_tail requires either path or container", False

    if tool == "podman_ps":
        if perm.shell == "deny":
            return "DENIED: shell access is denied", False
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
        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"podman_ps host={host} count={len(rows)}", data={"tool": "podman_ps", "host": host, "count": len(rows)}))
        return json.dumps(result, indent=2)[:10000], False

    if tool == "wait_for":
        if perm.network == "deny":
            return "DENIED: network access is denied", False
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

        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_started", message=f"wait_for {target} (timeout={timeout}s)", data={"tool": "wait_for", "target": target, "timeout": timeout}))

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = await asyncio.wait_for(check_fn(), timeout=poll_interval + 2)
                if result:
                    elapsed = round(time.time() - (deadline - timeout), 1)
                    store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"wait_for {target} ready after {elapsed}s", data={"tool": "wait_for", "target": target, "elapsed": elapsed}))
                    return json.dumps({"target": target, "ready": True, "elapsed_seconds": elapsed}), False
            except Exception:
                pass
            await asyncio.sleep(poll_interval)

        store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_result", message=f"wait_for {target} timed out", data={"tool": "wait_for", "target": target, "timeout": timeout}))
        return json.dumps({"target": target, "ready": False, "error": f"timed out after {timeout}s"}), False

    if tool == "resume_task":
        target_task_id = str(inp.get("task_id") or "").strip()
        if not target_task_id:
            return "resume_task requires task_id", False

        resumed_task = store.get_task(target_task_id)
        if not resumed_task:
            return f"Task not found: {target_task_id}", False

        checkpoint = load_latest_checkpoint(resumed_task.session_id)
        if not checkpoint:
            return f"No checkpoint found for session {resumed_task.session_id}", False

        if checkpoint.task_id != target_task_id:
            return f"Checkpoint session mismatch: expected {target_task_id}, got {checkpoint.task_id}", False

        resumed_task.metadata["checkpoint_seq"] = checkpoint.checkpoint_seq
        resumed_task.metadata["checkpoint_step"] = checkpoint.step
        resumed_task.metadata["checkpoint_at"] = checkpoint.checkpoint_at
        resumed_task.metadata["resumed_from_checkpoint"] = True

        resumed_task.status = TaskStatus.running

        store.add_task(resumed_task)
        store.add_event(Event(
            session_id=resumed_task.session_id, task_id=resumed_task.id,
            type="task_resumed", message=f"Task resumed from checkpoint seq={checkpoint.checkpoint_seq} step={checkpoint.step}",
            data={"task_id": target_task_id, "checkpoint_seq": checkpoint.checkpoint_seq, "checkpoint_step": checkpoint.step}
        ))

        result = {
            "task_id": target_task_id,
            "resumed": True,
            "checkpoint_seq": checkpoint.checkpoint_seq,
            "checkpoint_step": checkpoint.step,
            "checkpoint_at": datetime.fromtimestamp(checkpoint.checkpoint_at, timezone.utc).isoformat().replace("+00:00", "Z"),
            "rolling_summary": checkpoint.rolling_summary[:500],
            "transcript_len": checkpoint.transcript_len,
            "prompt": checkpoint.prompt[:200],
        }
        return json.dumps(result, indent=2), False

    if tool == "list_task_checkpoints":
        target_task_id = str(inp.get("task_id") or "").strip()
        if not target_task_id:
            return "list_task_checkpoints requires task_id", False

        t = store.get_task(target_task_id)
        if not t:
            return f"Task not found: {target_task_id}", False

        checkpoints = list_checkpoints(t.session_id)

        return json.dumps({
            "task_id": target_task_id,
            "session_id": t.session_id,
            "checkpoints": checkpoints,
            "count": len(checkpoints),
        }, indent=2)[:8000], False

    if tool == "clear_checkpoints":
        target_session_id = str(inp.get("session_id") or "").strip()
        if not target_session_id:
            return "clear_checkpoints requires session_id", False
        from .checkpoint import delete_checkpoints
        count = delete_checkpoints(target_session_id)
        return json.dumps({"session_id": target_session_id, "deleted": count}), False

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
    decision_model = task.metadata.get('model') or (agent.planner_model if agent and agent.planner_model else session.model)
    decision_context_name = agent.planner_context_profile if agent and agent.planner_context_profile else context_name
    ctx = effective_context(config, decision_model, decision_context_name)
    budget = get_context_budget(config, decision_model, decision_context_name)
    full_control = session.permission_profile == "full-control"
    store.add_event(Event(session_id=session.id, task_id=task.id, type="agent_loop_started", message="Agent loop started", data={"model": session.model, "decision_model": decision_model, "planner_model": agent.planner_model if agent else None, "permission_profile": session.permission_profile, "full_control": full_control, "effective_context": ctx, "endpoint_id": task.metadata.get("runner_id"), "endpoint_locked": task.metadata.get("endpoint_locked"), "agent_enabled": task.metadata.get("agent_enabled", True), "requested_command": task.metadata.get("requested_command"), "routing": task.metadata.get("routing", "agent")}))
    if full_control:
        store.add_event(Event(session_id=session.id, task_id=task.id, type="full_control_enabled", message="FULL CONTROL MODE ENABLED: approvals are bypassed, but every tool action is logged."))

    system_prompt = (agent.system_prompt if agent else "You are a remote coding agent.") + "\n\n" + TOOL_HELP
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    controller_guidance = _controller_session_guidance(session)
    if controller_guidance:
        messages.append({"role": "system", "content": controller_guidance})
    controller_context = _controller_session_runtime_context(session, config)
    if controller_context:
        messages.append({"role": "system", "content": controller_context})
    # Build workspace index on session start
    workspace_index = build_workspace_index(Path(session.workspace_path), max_files=600)
    task.metadata["workspace_index"] = workspace_index
    index_briefing = _format_workspace_index_briefing(workspace_index)
    if index_briefing:
        messages.append({"role": "system", "content": index_briefing})
    store.add_event(Event(session_id=session.id, task_id=task.id, type="workspace_indexed", message="Workspace indexed", data={"project_type": workspace_index.get("project_type"), "file_count": workspace_index.get("tree", {}).get("file_count", 0), "projects": [p.get("type") for p in workspace_index.get("projects", [])]}))
    # Inject accumulated project memory (cross-session lessons)
    project_memory = get_project_memory(session.workspace_path)
    if project_memory.get("has_memory"):
        memory_brief = (
            f"\nNote: this workspace has {project_memory['count']} prior lesson(s) in memory.\n"
            f"Summary:\n{project_memory['summary']}\n"
            "To recall specific lessons: use `lessons(mode=\"search\", query=\"...\")` tool.\n"
        )
        messages.append({"role": "system", "content": memory_brief})
    messages.extend(_session_history_messages(session, current_task_id=task.id, max_messages=12))
    messages.append({"role": "user", "content": "Current user request (answer this now; earlier conversation is context only):\n" + task.prompt})

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
    empty_model_retries = 0
    step = 0
    while True:
        step += 1
        # Auto-checkpoint every 10 steps
        if step % 10 == 0:
            try:
                cp_path = save_checkpoint(
                    session_id=session.id,
                    task_id=task.id,
                    step=step,
                    rolling_summary=rolling_summary or "",
                    messages=messages[-20:],
                    transcript=transcript[-20:],
                    workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "",
                    model=session.model or "",
                    prompt=task.prompt or "",
                    output=task.output or "",
                    task_status=str(task.status.value) if hasattr(task.status, "value") else str(task.status),
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
                store.add_event(Event(session_id=session.id, task_id=task.id, type="checkpoint_saved", message=f"Checkpoint {step} steps", data={"step": step, "path": cp_path}))
            except Exception:
                pass  # Never let checkpoint failures break the loop
        latest_task = store.get_task(task.id) or task
        stop_requested = bool((latest_task.metadata or {}).get("stop_requested"))
        if stop_requested:
            _save_task_lesson(session, task, transcript, config)
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
            try:
                save_checkpoint(
                    session_id=session.id, task_id=task.id, step=step,
                    rolling_summary=rolling_summary or "", messages=messages[-20:],
                    transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "", model=session.model or "",
                    prompt=task.prompt or "", output=task.output or "", task_status="completed",
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
            except Exception:
                pass
            _save_task_lesson(session, task, transcript, config)
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
            try:
                save_checkpoint(
                    session_id=session.id, task_id=task.id, step=step,
                    rolling_summary=rolling_summary or "", messages=messages[-20:],
                    transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "", model=session.model or "",
                    prompt=task.prompt or "", output="", task_status="failed",
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
            except Exception:
                pass
            _save_task_lesson(session, task, transcript, config)
            task.status = TaskStatus.failed
            task.error = f"Model call failed: {exc}"
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="task_failed", message=task.error))
            return task

        transcript.append({"step": step, "model": raw})
        if not str(raw or "").strip():
            empty_model_retries += 1
            store.add_event(Event(session_id=session.id, task_id=task.id, type="model_response_empty", message="Model returned an empty response", data={"role": "assistant", "model": decision_model, "session_model": session.model, "endpoint_id": task.metadata.get("runner_id"), "step": step, "retry": empty_model_retries}))
            if empty_model_retries <= 2:
                messages.append({"role": "user", "content": "Your previous response was empty. Based on the latest tool result or context, return either ONE final answer or ONE valid tool_call JSON object now."})
                continue
            try:
                save_checkpoint(
                    session_id=session.id, task_id=task.id, step=step,
                    rolling_summary=rolling_summary or "", messages=messages[-20:],
                    transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "", model=session.model or "",
                    prompt=task.prompt or "", output="", task_status="failed",
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
            except Exception:
                pass
            _save_task_lesson(session, task, transcript, config)
            task.status = TaskStatus.failed
            task.error = "Model returned an empty response repeatedly."
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="task_failed", message=task.error))
            return task
        empty_model_retries = 0
        store.add_event(Event(session_id=session.id, task_id=task.id, type="model_response", message=raw[-4000:], data={"role": "assistant", "model": decision_model, "session_model": session.model, "endpoint_id": task.metadata.get("runner_id"), "step": step}))
        try:
            action = _extract_json(raw)
        except Exception:
            if _looks_like_wrapped_tool_markup(raw):
                store.add_event(Event(session_id=session.id, task_id=task.id, type="tool_call_parse_failed", message="Model returned malformed tool-call markup; requesting a corrected tool call.", data={"role": "assistant", "model": decision_model, "raw": raw[-4000:]}))
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": 'Your previous reply contained malformed tool-call markup. Return ONE valid JSON object only. If you intend to act, return {"type":"tool_call","tool":"...","input":{...}}. Do not include wrapper markers, pseudo-code, or explanatory narration.'})
                continue
            if _prompt_requests_codebase_inspection(task.prompt) and _looks_like_action_narration(raw):
                store.add_event(Event(session_id=session.id, task_id=task.id, type="action_narration_rejected", message="Model narrated an action instead of taking one; requesting a real tool call.", data={"role": "assistant", "model": decision_model, "raw": raw[-4000:]}))
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Do not narrate future actions for this code/workspace task. "
                        "If inspection is needed, return exactly ONE valid tool_call JSON object now. "
                        "Only return a final answer after you have actually inspected the workspace."
                    ),
                })
                continue
            try:
                save_checkpoint(
                    session_id=session.id, task_id=task.id, step=step,
                    rolling_summary=rolling_summary or "", messages=messages[-20:],
                    transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "", model=session.model or "",
                    prompt=task.prompt or "", output=raw[:2000], task_status="completed",
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
            except Exception:
                pass
            _save_task_lesson(session, task, transcript, config)
            task.status = TaskStatus.completed
            task.output = raw
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            store.add_event(Event(session_id=session.id, task_id=task.id, type="result", message=raw[-4000:], data={"role": "assistant", "model": session.model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile}))
            return task

        thought_summary, thought_meta = _summarize_model_action(action)
        store.add_event(Event(session_id=session.id, task_id=task.id, type="agent_intent", message=thought_summary, data={"role": "assistant", "model": decision_model, "session_model": session.model, "endpoint_id": task.metadata.get("runner_id"), "step": step, **thought_meta}))

        if action.get("type") == "final":
            depth_score = _inspection_depth_score(transcript)
            broad_request = _is_broad_codebase_request(task.prompt)
            final_message = str(action.get("message") or "")
            if _prompt_requests_codebase_inspection(task.prompt) and not _has_meaningful_codebase_inspection(transcript):
                messages.append({
                    "role": "user",
                    "content": (
                        "Before answering this codebase/workspace question, inspect the workspace more deeply. "
                        "A shallow response is not acceptable. Use one or more of workspace_manifest, read_file, "
                        "read_file_chunk, batch_analyze_file, git_diff, git_status, or shell/rg to gather concrete evidence first."
                    ),
                })
                continue
            if broad_request and depth_score < 2.5:
                messages.append({
                    "role": "user",
                    "content": (
                        "This request is still too broad to answer from a shallow scan. "
                        "Inspect more deeply before answering: use workspace_manifest or a focused shell search (rg/find), "
                        "then read concrete source files that are likely to implement the relevant behavior. "
                        "Do not stop after a README or top-level listing."
                    ),
                })
                continue
            if session.metadata.get("controller_harness") and _looks_like_generic_ready_response(final_message):
                messages.append({
                    "role": "user",
                    "content": (
                        "Do not give a generic readiness or acknowledgement reply. "
                        "Answer the current PAC question directly from the local evidence you already gathered, "
                        "or keep inspecting with a concrete tool call if the answer is still incomplete."
                    ),
                })
                continue
            try:
                save_checkpoint(
                    session_id=session.id, task_id=task.id, step=step,
                    rolling_summary=rolling_summary or "", messages=messages[-20:],
                    transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                    agent_profile=session.agent_profile or "", model=session.model or "",
                    prompt=task.prompt or "", output=final_message[:2000], task_status="completed",
                    session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                    metadata=task.metadata or {},
                )
            except Exception:
                pass
            _save_task_lesson(session, task, transcript, config)
            task.status = TaskStatus.completed
            task.output = final_message
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
                try:
                    save_checkpoint(
                        session_id=session.id, task_id=task.id, step=step,
                        rolling_summary=rolling_summary or "", messages=messages[-20:],
                        transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                        agent_profile=session.agent_profile or "", model=session.model or "",
                        prompt=task.prompt or "", output="", task_status="approval_required",
                        session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                        metadata=task.metadata or {},
                    )
                except Exception:
                    pass
                return task
            latest_task = store.get_task(task.id) or task
            if (latest_task.metadata or {}).get("stop_requested"):
                try:
                    save_checkpoint(
                        session_id=session.id, task_id=task.id, step=step,
                        rolling_summary=rolling_summary or "", messages=messages[-20:],
                        transcript=transcript[-20:], workspace_path=session.workspace_path or "",
                        agent_profile=session.agent_profile or "", model=session.model or "",
                        prompt=task.prompt or "", output="Agent stopped by user.", task_status="completed",
                        session_status=str(session.status.value) if hasattr(session.status, "value") else str(session.status),
                        metadata=task.metadata or {},
                    )
                except Exception:
                    pass
                _save_task_lesson(session, task, transcript, config)
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
