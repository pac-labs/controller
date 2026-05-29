from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_DISCOVERY_TOOLS: tuple[str, ...] = (
    "workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk",
    "ripgrep", "fd", "find_code_paths", "code_intelligence_report", "code_symbol_search",
    "code_definition", "code_references", "code_diagnostics", "code_language_servers",
    "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index",
    "code_blast_radius",
    "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition",
    "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "batch_analyze_text", "batch_analyze_file",
    "git_status", "git_diff", "git_changes", "web_search", "web_fetch", "remote_memory",
    "lessons", "consult_model", "batch_tools",
)

PLAN_TOOLS: tuple[str, ...] = (
    "workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk",
    "ripgrep", "fd", "find_code_paths", "code_intelligence_report", "code_symbol_search",
    "code_definition", "code_references", "code_diagnostics", "code_language_servers",
    "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index",
    "code_blast_radius",
    "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition",
    "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "git_status", "git_diff", "git_changes",
    "web_search", "web_fetch", "remote_memory", "lessons", "consult_model", "batch_tools",
)

CODER_TOOLS: tuple[str, ...] = (
    "workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk",
    "ripgrep", "fd", "find_code_paths", "code_intelligence_report", "code_symbol_search",
    "code_definition", "code_references", "code_diagnostics", "code_language_servers",
    "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index",
    "code_blast_radius",
    "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition",
    "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "batch_analyze_text", "batch_analyze_file",
    "write_file", "edit_file", "code_lsp_rename_apply", "shell", "shell_bg", "shell_bg_result", "shell_bg_stop",
    "git_status", "git_diff", "git_changes", "auto_commit", "save_artifact", "list_artifacts",
    "web_search", "web_fetch", "remote_memory", "lessons", "consult_model", "batch_tools",
)

VERIFY_TOOLS: tuple[str, ...] = (
    "workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk",
    "ripgrep", "fd", "find_code_paths", "code_intelligence_report", "code_symbol_search",
    "code_definition", "code_references", "code_diagnostics", "code_language_servers",
    "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index",
    "code_blast_radius",
    "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition",
    "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "batch_analyze_text", "batch_analyze_file",
    "shell", "shell_bg", "shell_bg_result", "git_status", "git_diff", "git_changes",
    "save_artifact", "list_artifacts", "web_search", "web_fetch", "consult_model", "batch_tools",
)

GENERAL_TOOLS: tuple[str, ...] = (
    "workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk",
    "ripgrep", "fd", "find_code_paths", "code_intelligence_report", "code_symbol_search",
    "code_definition", "code_references", "code_diagnostics", "code_language_servers",
    "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index",
    "code_blast_radius",
    "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition",
    "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "batch_analyze_text", "batch_analyze_file",
    "write_file", "edit_file", "code_lsp_rename_apply", "shell", "shell_bg", "shell_bg_result", "git_status", "git_diff",
    "git_changes", "save_artifact", "list_artifacts", "web_search", "web_fetch", "remote_memory",
    "lessons", "consult_model", "batch_tools",
)


@dataclass(frozen=True, slots=True)
class SubAgentProfile:
    key: str
    display_name: str
    purpose: str
    turn_budget: int
    tools: tuple[str, ...]
    read_only: bool = False
    plan_only: bool = False
    preferred_model_role: str = "session"
    instructions: str = ""


SUBAGENT_PROFILES: dict[str, SubAgentProfile] = {
    "explore": SubAgentProfile(
        key="explore",
        display_name="Explore",
        purpose="Read-only workspace discovery and evidence gathering.",
        turn_budget=15,
        tools=READ_ONLY_DISCOVERY_TOOLS,
        read_only=True,
        preferred_model_role="cheap",
        instructions=(
            "You are the Explore specialist. Discover relevant workspace structure, files, symbols, and docs. "
            "Do not modify files or run mutating commands. Prefer workspace_manifest, find_code_paths, ripgrep, fd, and read_file. "
            "Return concise evidence with verified paths and open questions for the parent agent."
        ),
    ),
    "plan": SubAgentProfile(
        key="plan",
        display_name="Plan",
        purpose="Architecture and implementation planning without writes.",
        turn_budget=10,
        tools=PLAN_TOOLS,
        read_only=True,
        plan_only=True,
        preferred_model_role="planner",
        instructions=(
            "You are the Plan specialist. Produce an architecture-level plan from verified local evidence. "
            "Do not write files, edit code, or run mutating commands. Identify risks, file targets, sequencing, and validation steps."
        ),
    ),
    "coder": SubAgentProfile(
        key="coder",
        display_name="Coder",
        purpose="Scoped implementation with file writes and validation.",
        turn_budget=30,
        tools=CODER_TOOLS,
        preferred_model_role="coder",
        instructions=(
            "You are the Coder specialist. Implement the requested change with minimal, well-scoped edits. "
            "Search before reads, read before writes, validate after mutation, and summarize changed files and remaining work."
        ),
    ),
    "verify": SubAgentProfile(
        key="verify",
        display_name="Verify",
        purpose="Adversarial testing, review, and regression checks.",
        turn_budget=20,
        tools=VERIFY_TOOLS,
        preferred_model_role="verifier",
        instructions=(
            "You are the Verify specialist. Try to break the proposed or implemented work. "
            "Run safe tests/checks, inspect diffs, search for edge cases, and report pass/fail evidence. "
            "Do not commit or rewrite code unless the parent explicitly requested verification fixes."
        ),
    ),
    "general": SubAgentProfile(
        key="general",
        display_name="General-purpose",
        purpose="Balanced scoped assistance when no specialist clearly fits.",
        turn_budget=25,
        tools=GENERAL_TOOLS,
        preferred_model_role="session",
        instructions=(
            "You are the General-purpose specialist. Work on the narrow delegated objective, use tools when useful, "
            "and return a concise result summary for the parent session."
        ),
    ),
}

ALIASES: dict[str, str] = {
    "discovery": "explore", "inspect": "explore", "research": "explore",
    "architect": "plan", "architecture": "plan",
    "implement": "coder", "code": "coder", "coding": "coder",
    "test": "verify", "review": "verify", "validate": "verify", "verification": "verify",
    "default": "general",
}


def normalize_subagent_key(value: str | None) -> str | None:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return None
    raw = raw.removeprefix("/")
    raw = raw.replace("-agent", "").replace(" subagent", "")
    return SUBAGENT_PROFILES.get(raw, None).key if raw in SUBAGENT_PROFILES else ALIASES.get(raw)


def get_subagent_profile(value: str | None) -> SubAgentProfile:
    key = normalize_subagent_key(value) or "general"
    return SUBAGENT_PROFILES[key]


def select_subagent_profile(instruction: str, requested: str | None = None) -> SubAgentProfile:
    explicit = normalize_subagent_key(requested)
    if explicit:
        return SUBAGENT_PROFILES[explicit]
    text = f" {str(instruction or '').lower()} "
    if any(word in text for word in (" verify", " test", " check", " validate", " regression", " review", " audit")):
        return SUBAGENT_PROFILES["verify"]
    if any(word in text for word in (" plan", " design", " architecture", " approach", " strategy")):
        return SUBAGENT_PROFILES["plan"]
    if any(word in text for word in (" implement", " code", " write", " edit", " fix", " patch", " refactor", " add ", " change")):
        return SUBAGENT_PROFILES["coder"]
    if any(word in text for word in (" find", " inspect", " explore", " locate", " discover", " summarize", " entails", " overview")):
        return SUBAGENT_PROFILES["explore"]
    return SUBAGENT_PROFILES["general"]


def subagent_prompt(profile: SubAgentProfile, instruction: str) -> str:
    objective = str(instruction or "").strip() or "Carry out one narrowly scoped subtask that supports the parent session."
    return (
        f"Specialist: {profile.display_name}\n"
        f"Purpose: {profile.purpose}\n"
        f"Turn budget: {profile.turn_budget}\n"
        f"Preferred model role: {profile.preferred_model_role}\n"
        f"Locked tools: {', '.join(profile.tools)}\n\n"
        f"Specialist instructions:\n{profile.instructions}\n\n"
        f"Delegated objective:\n{objective}"
    )


def available_subagent_tools(config: Any, profile: SubAgentProfile, parent_tools: list[str] | tuple[str, ...] | None = None) -> list[str]:
    configured = set(getattr(config, "tools", {}) or {})
    parent_allowed = set(parent_tools or [])
    core_virtual = {"workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk", "write_file", "edit_file", "batch_analyze_text", "batch_analyze_file"}
    if not configured and not parent_allowed:
        return list(profile.tools)
    allowed: list[str] = []
    for tool in profile.tools:
        if tool in core_virtual or tool in configured or tool in parent_allowed:
            allowed.append(tool)
    return allowed


def resolve_subagent_model(config: Any, parent_session: Any, parent_task: Any, profile: SubAgentProfile) -> str:
    task_meta = getattr(parent_task, "metadata", {}) or {}
    session_meta = getattr(parent_session, "metadata", {}) or {}
    candidates: list[str | None] = []
    explicit_map = session_meta.get("subagent_model_preferences") or task_meta.get("subagent_model_preferences") or {}
    role_map = session_meta.get("model_role_preferences") or task_meta.get("model_role_preferences") or {}
    if isinstance(explicit_map, dict):
        candidates.extend([
            explicit_map.get(profile.key),
            explicit_map.get(profile.preferred_model_role),
            explicit_map.get("default"),
        ])
    if isinstance(role_map, dict):
        candidates.extend([
            role_map.get(profile.key),
            role_map.get(profile.preferred_model_role),
            role_map.get("default"),
        ])
    candidates.extend([
        task_meta.get(f"{profile.key}_model"),
        task_meta.get(f"subagent_{profile.key}_model"),
    ])
    agent_profile = getattr(config, "agent_profiles", {}).get(getattr(parent_session, "agent_profile", "") or "")
    if profile.preferred_model_role == "planner" and agent_profile is not None:
        candidates.append(getattr(agent_profile, "planner_model", None))
    if profile.key == "verify":
        candidates.append(task_meta.get("verify_model") or session_meta.get("verify_model"))
    if profile.key == "coder":
        candidates.append(task_meta.get("coder_model") or session_meta.get("coder_model"))
    candidates.extend([task_meta.get("model"), getattr(parent_session, "model", None)])
    configured = set(getattr(config, "models", {}) or {})
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and (not configured or value in configured):
            return value
    return str(getattr(parent_session, "model", "") or "")
