from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from ..models import Session, Task
from .pipeline_schema import required_fields

_READ_ONLY_TOOLS = {
    "workspace_manifest",
    "query_workspace_index",
    "list_files",
    "read_file",
    "read_file_chunk",
    "ripgrep",
    "fd",
    "batch_analyze_text",
    "batch_analyze_file",
    "find_code_paths",
    "git_status",
    "git_diff",
    "git_changes",
    "list_artifacts",
    "pac_list_components",
    "web_search",
    "web_fetch",
    "remote_memory",
    "consult_model",
    "lessons",
    "list_task_checkpoints",
    "podman_ps",
    "log_tail",
    "shell_bg_result",
    "batch_tools",
    "playbook_list",
    "playbook_status",
    "playbook_export",
    "code_intelligence_report",
    "code_symbol_search",
    "code_definition",
    "code_references",
    "code_diagnostics",
    "code_language_servers",
    "code_project_metadata",
    "code_call_hierarchy",
    "code_type_hierarchy",
    "code_module_index",
    "code_blast_radius",
    "code_lsp_status",
    "code_lsp_document_symbols",
    "code_lsp_definition",
    "code_lsp_references",
    "code_lsp_hover",
    "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy",
    "code_lsp_shutdown",
    "code_lsp_rename_plan",
    "code_lsp_endpoint_prepare", "code_roslyn_analysis",
    "local_inference_discover",
    "local_inference_health",
}

_MUTATING_TOOLS = {
    "write_file",
    "edit_file",
    "save_artifact",
    "shell",
    "shell_bg",
    "shell_bg_stop",
    "auto_commit",
    "pac_create_provider",
    "pac_create_model",
    "pac_create_endpoint",
    "pac_create_workspace_profile",
    "pac_create_session",
    "spawn_subagent",
    "run_subagent_chain",
    "import_subagent_summary",
    "playbook_start",
    "playbook_resume",
    "playbook_approve",
    "playbook_cancel",
    "playbook_import",
    "local_inference_register",
    "slash_command",
    "code_lsp_rename_apply",
    "resume_task",
    "clear_checkpoints",
    "auto_approve",
    "pty_shell",
    "pty_write",
    "pty_resize",
    "pty_close",
}

_PATH_KEYS = {"path", "old_path", "new_path", "file", "filename", "cwd"}
_CORE_VIRTUAL_TOOLS = {
    "workspace_manifest",
    "query_workspace_index",
    "list_files",
    "read_file",
    "read_file_chunk",
    "batch_analyze_text",
    "batch_analyze_file",
    "write_file",
    "edit_file",
}

_PATH_SCOPED_TOOLS = {
    "list_files",
    "read_file",
    "read_file_chunk",
    "write_file",
    "edit_file",
    "ripgrep",
    "fd",
    "batch_analyze_file",
    "code_intelligence_report",
    "code_symbol_search",
    "code_definition",
    "code_references",
    "code_diagnostics",
    "code_language_servers",
    "code_project_metadata",
    "code_call_hierarchy",
    "code_type_hierarchy",
    "code_module_index",
    "code_blast_radius",
    "code_lsp_status",
    "code_lsp_document_symbols",
    "code_lsp_definition",
    "code_lsp_references",
    "code_lsp_hover",
    "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy",
    "code_lsp_shutdown",
    "code_lsp_rename_plan",
    "code_lsp_rename_apply",
    "code_lsp_endpoint_prepare", "code_roslyn_analysis",
    "log_tail",
    "shell",
    "shell_bg",
}

_GROUP_ALIASES: dict[str, set[str]] = {
    "artifacts": {"save_artifact", "list_artifacts"},
    "git": {"git_status", "git_diff", "git_changes", "auto_commit"},
    "web": {"web_search", "web_fetch"},
    "workspace": {"workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk", "ripgrep", "fd", "batch_tools", "code_intelligence_report", "code_symbol_search", "code_definition", "code_references", "code_diagnostics", "code_language_servers", "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index", "code_blast_radius", "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition", "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy", "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_rename_apply", "code_lsp_endpoint_prepare", "code_roslyn_analysis"},
    "files": {"list_files", "read_file", "read_file_chunk", "write_file", "edit_file", "ripgrep", "fd", "batch_analyze_file"},
    "file_read": {"workspace_manifest", "query_workspace_index", "list_files", "read_file", "read_file_chunk", "ripgrep", "fd", "batch_analyze_file", "find_code_paths", "batch_tools", "code_intelligence_report", "code_symbol_search", "code_definition", "code_references", "code_diagnostics", "code_language_servers", "code_project_metadata", "code_call_hierarchy", "code_type_hierarchy", "code_module_index", "code_blast_radius", "code_lsp_status", "code_lsp_document_symbols", "code_lsp_definition", "code_lsp_references", "code_lsp_hover", "code_lsp_call_hierarchy", "code_lsp_type_hierarchy", "code_lsp_shutdown", "code_lsp_rename_plan", "code_lsp_endpoint_prepare", "code_roslyn_analysis"},
    "file_write": {"write_file", "edit_file", "code_lsp_rename_apply"},
    "pac-control-plane": {"pac_list_components", "pac_create_provider", "pac_create_model", "pac_create_endpoint", "pac_create_workspace_profile", "pac_create_session", "playbook_list", "playbook_start", "playbook_status", "playbook_resume", "playbook_approve", "playbook_cancel", "playbook_export", "playbook_import", "local_inference_discover", "local_inference_health", "local_inference_register"},
    "subagents": {"spawn_subagent", "run_subagent_chain", "import_subagent_summary", "playbook_start", "playbook_resume", "playbook_approve", "playbook_cancel", "playbook_export", "playbook_import"},
    "session-control": {"slash_command"},
}

_PERMISSION_CLASS_BY_TOOL = {
    "web_search": "network",
    "web_fetch": "network",
    "write_file": "file_write",
    "edit_file": "file_write",
    "code_lsp_rename_apply": "file_write",
    "save_artifact": "file_write",
    "shell": "shell",
    "shell_bg": "shell",
    "shell_bg_stop": "shell",
    "pty_shell": "shell",
    "pty_write": "shell",
    "pty_resize": "shell",
    "pty_close": "shell",
    "auto_commit": "git_write",
    "pac_create_provider": "pac_control_plane_write",
    "pac_create_model": "pac_control_plane_write",
    "pac_create_endpoint": "pac_control_plane_write",
    "pac_create_workspace_profile": "pac_control_plane_write",
    "pac_create_session": "pac_control_plane_write",
    "playbook_start": "pac_control_plane_write",
    "playbook_resume": "pac_control_plane_write",
    "playbook_approve": "pac_control_plane_write",
    "playbook_cancel": "pac_control_plane_write",
    "playbook_import": "pac_control_plane_write",
    "local_inference_register": "pac_control_plane_write",
}


def _tool_config(tool: str, config: Any | None) -> Any | None:
    if config is None:
        return None
    return getattr(config, "tools", {}).get(tool) if getattr(config, "tools", None) else None


def is_read_only_tool(tool: str, config: Any | None = None) -> bool:
    cfg = _tool_config(tool, config)
    if cfg is not None and getattr(cfg, "read_only", None) is not None:
        return bool(getattr(cfg, "read_only"))
    if cfg is not None and getattr(cfg, "mutating", None) is not None:
        return not bool(getattr(cfg, "mutating"))
    return tool in _READ_ONLY_TOOLS


def is_mutating_tool(tool: str, config: Any | None = None) -> bool:
    cfg = _tool_config(tool, config)
    if cfg is not None and getattr(cfg, "mutating", None) is not None:
        return bool(getattr(cfg, "mutating"))
    if cfg is not None and getattr(cfg, "read_only", None) is not None:
        return not bool(getattr(cfg, "read_only"))
    return tool in _MUTATING_TOOLS


def is_path_scoped_tool(tool: str, config: Any | None = None) -> bool:
    cfg = _tool_config(tool, config)
    if cfg is not None and getattr(cfg, "path_scoped", None) is not None:
        return bool(getattr(cfg, "path_scoped"))
    return tool in _PATH_SCOPED_TOOLS


def path_keys_for_tool(tool: str, config: Any | None = None) -> set[str]:
    cfg = _tool_config(tool, config)
    custom = set(getattr(cfg, "path_fields", []) or []) if cfg is not None else set()
    return _PATH_KEYS | custom


def is_path_key(key: str) -> bool:
    return key in _PATH_KEYS


def is_enabled_in_session(tool: str, enabled_tools: set[str]) -> bool:
    if not enabled_tools:
        return True
    if tool in _CORE_VIRTUAL_TOOLS:
        return True
    if tool in enabled_tools:
        return True
    return any(group in enabled_tools and tool in members for group, members in _GROUP_ALIASES.items())


def permission_class_for_tool(tool: str, config: Any | None = None) -> str | None:
    cfg = _tool_config(tool, config)
    if cfg is not None and getattr(cfg, "permission_class", None):
        return str(getattr(cfg, "permission_class"))
    return _PERMISSION_CLASS_BY_TOOL.get(tool)


def cache_enabled_for_tool(tool: str, config: Any | None = None) -> bool:
    cfg = _tool_config(tool, config)
    policy = str(getattr(cfg, "cache_policy", "auto") if cfg is not None else "auto")
    if policy == "disabled":
        return False
    if policy == "read_only":
        return True
    return is_read_only_tool(tool, config)


def _looks_like_domain_path(value: str) -> bool:
    if "/" not in value and "\\" not in value:
        return False
    first = value.replace("\\", "/").split("/", 1)[0]
    return "." in first and not first.startswith(".") and first not in {".."}


def path_problem(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text == ".":
        return None
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "ssh://", "git@")):
        return "repository or URL values are not valid workspace paths"
    if text.startswith(("/", "\\")) or (len(text) > 2 and text[1] == ":"):
        return "absolute paths are not allowed; use a workspace-relative path"
    parts = PurePosixPath(text.replace("\\", "/")).parts
    if ".." in parts:
        return "parent-relative paths are not allowed"
    if _looks_like_domain_path(text):
        return "domain-like values are not valid workspace paths"
    return None


def is_plan_mode(session: Session, task: Task) -> bool:
    meta = {**(session.metadata or {}), **(task.metadata or {})}
    raw = str(meta.get("plan_mode") or meta.get("mode") or "").strip().lower()
    return raw in {"plan", "planning", "dry-run", "dry_run", "read-only", "readonly"}
