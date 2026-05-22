from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import Session, Task
from .profiles import profile_instructions
from .store import store
from .workspace_index import build_workspace_index
from .workspace_lessons import get_project_memory


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
{"type":"tool_call","tool":"printing_press","input":{"path":".","mode":"optimize"}}
{"type":"tool_call","tool":"slash_command","input":{"command":"/rg TODO src"}}

Rules:
- Prefer inspecting files before editing.
- Use shell only when needed.
- Keep commands scoped to the workspace.
- If blocked by policy, explain what approval or permission is needed.
- Do not narrate future actions like "I will now search" or "I am going to run...". If a tool should run, return a tool_call immediately.
- Do not print tool-call markup or pseudo-code examples in the final answer. Execute the tool call instead.
- If approval is needed, ask for that approval directly and briefly instead of saying the action has already started.
- Prefer read_file for normal source files. Use read_file_chunk or batch_analyze_file only when a file is too large for the current effective context budget.
- Use web_search before web_fetch when you do not know the exact URL.
- Use consult_model when you want a second opinion from another configured PAC model or want to fan out a planning question to multiple models. If you do not know a configured consult model name, omit the models field and PAC will choose an available consult/fallback model. Never return a final answer that merely says to use consult_model; call the tool or continue with the available session model.
- Use remote_memory when profile/user/workspace memory may contain relevant prior preferences, customer context, or durable notes.
- Save important generated files/results with save_artifact when the user may want to download them.
""".strip()


@dataclass(slots=True)
class AgentPromptContext:
    messages: list[dict[str, str]]
    controller_guidance: str | None
    controller_runtime_context: str | None
    workspace_index: dict[str, Any]
    workspace_index_briefing: str
    workspace_index_event_data: dict[str, Any]


def controller_session_guidance(session: Session) -> str | None:
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


def controller_session_runtime_context(session: Session, config: AppConfig) -> str | None:
    if not session.metadata.get("controller_harness"):
        return None
    workspace = str(session.workspace_path or "").strip() or "-"
    data_dir = str(config.server.data_dir or "").strip() or "-"
    config_path = f"{data_dir.rstrip('/')}/config/config.yaml" if data_dir not in {"-", ""} else "-"
    public_url = str(config.server.public_url or "").strip() or "-"
    endpoint_id = str(session.metadata.get("preferred_endpoint") or "local-PAC")
    tool_names = list(session.tools or []) or list(config.tools.keys())
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


def format_workspace_index_briefing(idx: dict[str, Any]) -> str:
    """Format the workspace index as a compact system-message briefing."""
    if idx.get("error"):
        return ""
    lines = ["=== WORKSPACE PROJECT CONTEXT ==="]
    project_type = idx.get("project_type", "unknown")
    projects = idx.get("projects", [])
    if projects:
        proj_types = ", ".join(str(project.get("type") or "unknown") for project in projects)
        lines.append(f"Project: {proj_types}")
    else:
        lines.append(f"Project type: {project_type}")

    tree = idx.get("tree", {})
    file_count = int(tree.get("file_count", 0) or 0)
    total_bytes = int(tree.get("total_bytes", 0) or 0)
    if file_count:
        mb = total_bytes / (1024 * 1024)
        lines.append(f"Files: {file_count} (~{mb:.1f} MB)")

    symbols = idx.get("python_symbols", [])
    if symbols:
        top_files = sorted(
            symbols,
            key=lambda symbol: len(symbol.get("defs", [])) + len(symbol.get("classes", [])),
            reverse=True,
        )[:8]
        lines.append(f"Python top files: {', '.join(str(symbol.get('file') or '') for symbol in top_files)}")

    git = idx.get("git_summary", {})
    if git.get("branch"):
        lines.append(f"Git branch: {git['branch']}, {git.get('total_commits', 0)} commits")
        recent = git.get("recent_commits", [])
        if recent:
            lines.append(f"Recent: {recent[0].get('message', '')} ({recent[0].get('hash', '')})")

    key_files = idx.get("key_files", [])
    if key_files:
        roles: dict[str, list[str]] = {}
        for key_file in key_files:
            role = str(key_file.get("role") or "other")
            roles.setdefault(role, []).append(str(key_file.get("path") or ""))
        documentation = [path for path in roles.get("documentation", []) if path]
        if documentation:
            lines.append(f"Key files: {', '.join(documentation[:2])}")

    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


def session_history_messages(session: Session, current_task_id: str | None = None, max_messages: int = 24) -> list[dict[str, str]]:
    """Rebuild compact user/assistant chat history from prior session events."""
    events = store.get_events(session.id, limit=800, latest=True)
    messages: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    controller_session = bool(session.metadata.get("controller_harness"))

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


def build_agent_prompt_context(session: Session, task: Task, config: AppConfig, *, agent: Any | None = None) -> AgentPromptContext:
    system_prompt = profile_instructions(agent) if agent else "You are a remote coding agent."
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt + "\n\n" + TOOL_HELP}]

    guidance = controller_session_guidance(session)
    if guidance:
        messages.append({"role": "system", "content": guidance})

    runtime_context = controller_session_runtime_context(session, config)
    if runtime_context:
        messages.append({"role": "system", "content": runtime_context})

    workspace_index = build_workspace_index(Path(session.workspace_path), max_files=600)
    index_briefing = format_workspace_index_briefing(workspace_index)
    if index_briefing:
        messages.append({"role": "system", "content": index_briefing})

    memory_brief = project_memory_brief(session.workspace_path)
    if memory_brief:
        messages.append({"role": "system", "content": memory_brief})

    messages.extend(session_history_messages(session, current_task_id=task.id, max_messages=12))
    messages.append({"role": "user", "content": "Current user request (answer this now; earlier conversation is context only):\n" + task.prompt})

    return AgentPromptContext(
        messages=messages,
        controller_guidance=guidance,
        controller_runtime_context=runtime_context,
        workspace_index=workspace_index,
        workspace_index_briefing=index_briefing,
        workspace_index_event_data=workspace_index_event_data(workspace_index),
    )


def project_memory_brief(workspace_path: str | None) -> str:
    project_memory = get_project_memory(workspace_path)
    if not project_memory.get("has_memory"):
        return ""
    return (
        f"\nNote: this workspace has {project_memory['count']} prior lesson(s) in memory.\n"
        f"Summary:\n{project_memory['summary']}\n"
        "To recall specific lessons: use `lessons(mode=\"search\", query=\"...\")` tool.\n"
    )


def workspace_index_event_data(workspace_index: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_type": workspace_index.get("project_type"),
        "file_count": workspace_index.get("tree", {}).get("file_count", 0),
        "projects": [project.get("type") for project in workspace_index.get("projects", [])],
    }


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
