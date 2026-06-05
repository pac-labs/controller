from __future__ import annotations

from .config import AppConfig
from .agent_tools.pipeline_schema import TOOL_SPECS


CODING_SESSION_DEFAULT_TOOLS = (
    "workspace_manifest",
    "list_files",
    "read_file",
    "read_file_chunk",
    "find_code_paths",
    "write_file",
    "edit_file",
    "shell",
    "git_status",
    "git_diff",
    "batch_analyze_file",
    "batch_analyze_text",
    "printing_press",
    "save_artifact",
    "list_artifacts",
)

GENERAL_AGENT_DEFAULT_TOOLS = (
    "workspace_manifest",
    "list_files",
    "read_file",
    "read_file_chunk",
    "find_code_paths",
    "shell",
    "git_status",
    "git_diff",
    "printing_press",
)


def known_agent_tool_names(config: AppConfig) -> set[str]:
    return set(TOOL_SPECS.keys()) | set(getattr(config, "tools", {}).keys())


def is_known_agent_tool(config: AppConfig, tool: str) -> bool:
    return bool(tool) and tool in known_agent_tool_names(config)


def requires_endpoint_advertisement(config: AppConfig, tool: str) -> bool:
    return bool(tool) and tool in getattr(config, "tools", {})


def default_agent_session_tools(config: AppConfig, *, coding_session: bool) -> list[str]:
    preferred = CODING_SESSION_DEFAULT_TOOLS if coding_session else GENERAL_AGENT_DEFAULT_TOOLS
    known = known_agent_tool_names(config)
    return [tool for tool in preferred if tool in known]


def merge_agent_session_tools(config: AppConfig, selected: list[str], *, coding_session: bool) -> list[str]:
    merged: list[str] = []
    for tool in [*selected, *default_agent_session_tools(config, coding_session=coding_session)]:
        if tool and tool not in merged:
            merged.append(tool)
    return merged
