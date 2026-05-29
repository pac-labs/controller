from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


JsonKind = Literal["string", "integer", "number", "boolean", "object", "array"]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Small runtime schema for agent tool arguments.

    The model is intentionally dependency-free so it can run before handler
    dispatch and before any tool-specific import side effects. It is not a full
    JSON Schema implementation; it covers the constraints that prevent most bad
    tool calls from reaching handlers: missing fields, wrong types, ranges,
    enums, and mutually exclusive input groups.
    """

    kind: JsonKind | tuple[JsonKind, ...]
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    allowed_values: tuple[Any, ...] = ()
    item_kind: JsonKind | tuple[JsonKind, ...] | None = None
    allow_empty: bool = True


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    allow_extra: bool = True
    any_of: tuple[tuple[str, ...], ...] = ()
    one_of: tuple[tuple[str, ...], ...] = ()

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.required)


def _str(required: bool = False, *, max_length: int | None = 32_000, allow_empty: bool = False) -> FieldSpec:
    return FieldSpec("string", required=required, max_length=max_length, allow_empty=allow_empty)


def _int(required: bool = False, *, min_value: int | None = None, max_value: int | None = None) -> FieldSpec:
    return FieldSpec("integer", required=required, min_value=min_value, max_value=max_value)


def _bool(required: bool = False) -> FieldSpec:
    return FieldSpec("boolean", required=required)


def _str_list(required: bool = False, *, max_length: int | None = 200) -> FieldSpec:
    return FieldSpec("array", required=required, item_kind="string", max_length=max_length)


def _obj(required: bool = False) -> FieldSpec:
    return FieldSpec("object", required=required)


def _enum(*values: str, required: bool = False) -> FieldSpec:
    return FieldSpec("string", required=required, allowed_values=tuple(values), allow_empty=False)


TOOL_SPECS: dict[str, ToolSpec] = {
    "batch_tools": ToolSpec("batch_tools", {"calls": FieldSpec("array", required=True, item_kind="object", min_length=1, max_length=8)}),
    "workspace_manifest": ToolSpec("workspace_manifest", {"max_files": _int(min_value=1, max_value=5000)}),
    "query_workspace_index": ToolSpec("query_workspace_index", {"query": _str(max_length=500), "type": _str(max_length=80)}),
    "list_files": ToolSpec("list_files", {"path": _str(max_length=4096, allow_empty=True)}),
    "read_file": ToolSpec("read_file", {"path": _str(True, max_length=4096)}),
    "read_file_chunk": ToolSpec(
        "read_file_chunk",
        {
            "path": _str(True, max_length=4096),
            "chunk_index": _int(min_value=0, max_value=100_000),
            "chunk_tokens": _int(min_value=100, max_value=20_000),
        },
    ),
    "write_file": ToolSpec("write_file", {"path": _str(True, max_length=4096), "content": _str(True, max_length=None, allow_empty=True)}),
    "edit_file": ToolSpec(
        "edit_file",
        {
            "path": _str(True, max_length=4096),
            "old_text": _str(True, max_length=None),
            "new_text": _str(True, max_length=None, allow_empty=True),
        },
    ),
    "ripgrep": ToolSpec(
        "ripgrep",
        {
            "query": _str(True, max_length=2000),
            "path": _str(max_length=4096, allow_empty=True),
            "file_filter": _str(max_length=256, allow_empty=True),
            "context": _int(min_value=0, max_value=20),
            "max_results": _int(min_value=1, max_value=5000),
        },
    ),
    "fd": ToolSpec(
        "fd",
        {
            "pattern": _str(max_length=512, allow_empty=True),
            "path": _str(max_length=4096, allow_empty=True),
            "max_results": _int(min_value=1, max_value=5000),
        },
    ),
    "batch_analyze_text": ToolSpec(
        "batch_analyze_text",
        {"instruction": _str(max_length=4000, allow_empty=True), "text": _str(max_length=None, allow_empty=True), "chunk_tokens": _int(min_value=100, max_value=20_000)},
    ),
    "batch_analyze_file": ToolSpec(
        "batch_analyze_file",
        {"path": _str(True, max_length=4096), "instruction": _str(max_length=4000, allow_empty=True), "chunk_tokens": _int(min_value=100, max_value=20_000)},
    ),
    "find_code_paths": ToolSpec(
        "find_code_paths",
        {"query": _str(True, max_length=1000), "roots": _str_list(max_length=50), "max_results": _int(min_value=1, max_value=100), "max_files": _int(min_value=50, max_value=10_000)},
    ),
    "save_artifact": ToolSpec("save_artifact", {"name": _str(True, max_length=4096), "content": _str(True, max_length=None, allow_empty=True), "mime_type": _str(max_length=200)}),
    "list_artifacts": ToolSpec("list_artifacts", {"limit": _int(min_value=1, max_value=500)}),
    "consult_model": ToolSpec("consult_model", {"prompt": _str(True, max_length=None), "model": _str(max_length=300), "system": _str(max_length=8000)}),
    "slash_command": ToolSpec("slash_command", {"command": _str(True, max_length=4096)}),
    "remote_memory": ToolSpec("remote_memory", {"query": _str(max_length=2000), "content": _str(max_length=None, allow_empty=True), "action": _enum("search", "save", "append", required=False)}),
    "lessons": ToolSpec("lessons", {"query": _str(max_length=2000), "content": _str(max_length=None, allow_empty=True), "action": _enum("search", "save", "append", required=False)}),
    "web_search": ToolSpec("web_search", {"query": _str(True, max_length=2000), "max_results": _int(min_value=1, max_value=20)}),
    "web_fetch": ToolSpec("web_fetch", {"url": _str(True, max_length=4096), "max_chars": _int(min_value=100, max_value=200_000)}),
    "git_status": ToolSpec("git_status"),
    "git_diff": ToolSpec("git_diff", {"path": _str(max_length=4096, allow_empty=True), "staged": _bool()}),
    "git_changes": ToolSpec("git_changes", {"max_files": _int(min_value=1, max_value=1000)}),
    "auto_commit": ToolSpec("auto_commit", {"message": _str(True, max_length=500)}),
    "shell": ToolSpec("shell", {"command": _str(True, max_length=20_000), "cwd": _str(max_length=4096, allow_empty=True), "timeout_seconds": _int(min_value=1, max_value=3600)}),
    "shell_bg": ToolSpec("shell_bg", {"command": _str(True, max_length=20_000), "cwd": _str(max_length=4096, allow_empty=True), "name": _str(max_length=200), "timeout_seconds": _int(min_value=1, max_value=86_400)}),
    "shell_bg_result": ToolSpec("shell_bg_result", {"job_id": _str(max_length=200), "name": _str(max_length=200)}, any_of=(("job_id", "name"),)),
    "shell_bg_stop": ToolSpec("shell_bg_stop", {"job_id": _str(max_length=200), "name": _str(max_length=200)}, any_of=(("job_id", "name"),)),
    "log_tail": ToolSpec("log_tail", {"path": _str(True, max_length=4096), "lines": _int(min_value=1, max_value=5000)}),
    "podman_ps": ToolSpec("podman_ps", {"all": _bool()}),
    "wait_for": ToolSpec("wait_for", {"seconds": _int(min_value=1, max_value=3600), "reason": _str(max_length=1000)}),
    "code_intelligence_report": ToolSpec(
        "code_intelligence_report",
        {"path": _str(max_length=4096, allow_empty=True), "max_files": _int(min_value=50, max_value=5000)},
    ),
    "code_symbol_search": ToolSpec(
        "code_symbol_search",
        {
            "query": _str(True, max_length=500),
            "path": _str(max_length=4096, allow_empty=True),
            "language": _enum("python", "typescript", "go", "rust", "csharp", required=False),
            "kind": _str(max_length=100),
            "max_results": _int(min_value=1, max_value=500),
        },
    ),
    "code_definition": ToolSpec(
        "code_definition",
        {
            "symbol": _str(max_length=500),
            "query": _str(max_length=500),
            "path": _str(max_length=4096, allow_empty=True),
            "language": _enum("python", "typescript", "go", "rust", "csharp", required=False),
        },
        any_of=(("symbol", "query"),),
    ),
    "code_references": ToolSpec(
        "code_references",
        {"symbol": _str(True, max_length=500), "path": _str(max_length=4096, allow_empty=True), "max_results": _int(min_value=1, max_value=1000)},
    ),
    "code_diagnostics": ToolSpec(
        "code_diagnostics",
        {
            "path": _str(max_length=4096, allow_empty=True),
            "language": _enum("auto", "python", "typescript", "go", "rust", "csharp", required=False),
            "run": _bool(),
            "timeout": _int(min_value=5, max_value=120),
        },
    ),
    "code_language_servers": ToolSpec(
        "code_language_servers",
        {"path": _str(max_length=4096, allow_empty=True)},
    ),
    "code_project_metadata": ToolSpec(
        "code_project_metadata",
        {
            "path": _str(max_length=4096, allow_empty=True),
            "language": _enum("auto", "python", "typescript", "go", "rust", "csharp", required=False),
            "run": _bool(),
            "timeout": _int(min_value=5, max_value=180),
        },
    ),
    "code_call_hierarchy": ToolSpec(
        "code_call_hierarchy",
        {"symbol": _str(True, max_length=500), "path": _str(max_length=4096, allow_empty=True), "max_results": _int(min_value=1, max_value=500)},
    ),
    "code_type_hierarchy": ToolSpec(
        "code_type_hierarchy",
        {"symbol": _str(max_length=500), "path": _str(max_length=4096, allow_empty=True), "max_results": _int(min_value=1, max_value=500)},
    ),
    "code_module_index": ToolSpec(
        "code_module_index",
        {"path": _str(max_length=4096, allow_empty=True), "language": _enum("auto", "python", "typescript", "go", "rust", "csharp", required=False), "max_files": _int(min_value=50, max_value=5000)},
    ),
    "code_blast_radius": ToolSpec(
        "code_blast_radius",
        {"symbol": _str(True, max_length=500), "path": _str(max_length=4096, allow_empty=True), "max_results": _int(min_value=1, max_value=1000)},
    ),
    "code_lsp_status": ToolSpec(
        "code_lsp_status",
        {"path": _str(max_length=4096, allow_empty=True)},
    ),
    "code_lsp_document_symbols": ToolSpec(
        "code_lsp_document_symbols",
        {"file": _str(True, max_length=4096), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_definition": ToolSpec(
        "code_lsp_definition",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_references": ToolSpec(
        "code_lsp_references",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "include_declaration": _bool(), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_hover": ToolSpec(
        "code_lsp_hover",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_call_hierarchy": ToolSpec(
        "code_lsp_call_hierarchy",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "direction": _enum("incoming", "outgoing", "both", required=False), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_type_hierarchy": ToolSpec(
        "code_lsp_type_hierarchy",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "direction": _enum("supertypes", "subtypes", "both", required=False), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_shutdown": ToolSpec(
        "code_lsp_shutdown",
        {"path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),

    "code_lsp_rename_plan": ToolSpec(
        "code_lsp_rename_plan",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "new_name": _str(True, max_length=500), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_rename_apply": ToolSpec(
        "code_lsp_rename_apply",
        {"file": _str(True, max_length=4096), "line": _int(min_value=1, max_value=2_000_000), "character": _int(min_value=0, max_value=200_000), "new_name": _str(True, max_length=500), "path": _str(max_length=4096, allow_empty=True), "language": _enum("python", "typescript", "go", "rust", "csharp", required=False)},
    ),
    "code_lsp_endpoint_prepare": ToolSpec(
        "code_lsp_endpoint_prepare",
        {"path": _str(max_length=4096, allow_empty=True), "language": _enum("auto", "python", "typescript", "go", "rust", "csharp", required=False), "timeout": _int(min_value=5, max_value=180)},
    ),
    "code_roslyn_analysis": ToolSpec(
        "code_roslyn_analysis",
        {"path": _str(max_length=4096, allow_empty=True), "run": _bool(), "timeout": _int(min_value=10, max_value=600)},
    ),
    "spawn_subagent": ToolSpec(
        "spawn_subagent",
        {
            "instruction": _str(True, max_length=8000),
            "profile": _enum("explore", "plan", "coder", "verify", "general", required=False),
        },
    ),
    "run_subagent_chain": ToolSpec(
        "run_subagent_chain",
        {
            "instruction": _str(True, max_length=12000),
            "chain": _enum("code_change", "auto_code_change", required=False),
            "profiles": FieldSpec("array", required=False, item_kind="string"),
        },
    ),
    "import_subagent_summary": ToolSpec(
        "import_subagent_summary",
        {
            "task_id": _str(max_length=200),
            "parent_task_id": _str(max_length=200),
        },
    ),
    "playbook_list": ToolSpec("playbook_list", {"tag": _str(max_length=100), "query": _str(max_length=500)}),
    "playbook_start": ToolSpec("playbook_start", {"playbook_id": _str(True, max_length=200), "parameters": _obj(), "wait": _bool()}),
    "playbook_status": ToolSpec("playbook_status", {"run_id": _str(max_length=200), "limit": _int(min_value=1, max_value=200)}),
    "playbook_resume": ToolSpec("playbook_resume", {"run_id": _str(True, max_length=200)}),
    "playbook_approve": ToolSpec("playbook_approve", {"run_id": _str(True, max_length=200), "note": _str(max_length=4000, allow_empty=True)}),
    "playbook_cancel": ToolSpec("playbook_cancel", {"run_id": _str(True, max_length=200), "note": _str(max_length=4000, allow_empty=True)}),
    "playbook_export": ToolSpec("playbook_export", {"playbook_id": _str(True, max_length=200)}),
    "playbook_import": ToolSpec("playbook_import", {"yaml": _str(True, max_length=100000), "overwrite": _bool()}),
    "resume_task": ToolSpec("resume_task", {"task_id": _str(max_length=200)}),
    "list_task_checkpoints": ToolSpec("list_task_checkpoints", {"task_id": _str(max_length=200)}),
    "clear_checkpoints": ToolSpec("clear_checkpoints", {"task_id": _str(max_length=200)}),
    "auto_approve": ToolSpec("auto_approve", {"tool": _str(max_length=200), "path": _str(max_length=4096), "command": _str(max_length=20_000), "url": _str(max_length=4096)}),
    "pac_list_components": ToolSpec("pac_list_components", {"kind": _str(max_length=80), "query": _str(max_length=2000)}),
    "local_inference_discover": ToolSpec("local_inference_discover", {"url": _str(max_length=4096), "urls": FieldSpec("array", required=False, item_kind="string"), "timeout_seconds": _int(min_value=1, max_value=10)}),
    "local_inference_health": ToolSpec("local_inference_health", {"base_url": _str(True, max_length=4096), "chat_test": _bool(), "model": _str(max_length=500), "timeout_seconds": _int(min_value=1, max_value=30)}),
    "local_inference_register": ToolSpec("local_inference_register", {"name": _str(max_length=200), "base_url": _str(True, max_length=4096), "enabled": _bool(), "overwrite": _bool(), "create_models": _bool(), "model_limit": _int(min_value=0, max_value=100), "force": _bool()}),
    "pac_create_provider": ToolSpec("pac_create_provider", {"name": _str(True, max_length=200), "type": _str(max_length=80), "base_url": _str(max_length=4096), "api_key_env": _str(max_length=200)}),
    "pac_create_model": ToolSpec("pac_create_model", {"name": _str(True, max_length=200), "provider": _str(max_length=200), "model": _str(max_length=300), "context_window": _int(min_value=1_000, max_value=2_000_000)}),
    "pac_create_endpoint": ToolSpec("pac_create_endpoint", {"name": _str(True, max_length=200), "url": _str(max_length=4096), "kind": _str(max_length=80)}),
    "pac_create_workspace_profile": ToolSpec(
        "pac_create_workspace_profile",
        {
            "name": _str(True, max_length=200),
            "source_type": _enum("empty", "git", "local", "template", required=False),
            "source_url": _str(max_length=4096),
            "container_image": _str(max_length=500),
            "description": _str(max_length=4000, allow_empty=True),
        },
    ),
    "pac_create_session": ToolSpec(
        "pac_create_session",
        {
            "name": _str(True, max_length=200),
            "workspace_profile": _str(max_length=200),
            "workspace_profile_id": _str(max_length=200),
            "container_image": _str(max_length=500),
            "execution_mode": _enum("host", "container", "auto", required=False),
            "tools": _str_list(max_length=200),
        },
    ),
    "pty_shell": ToolSpec("pty_shell", {"command": _str(max_length=20_000), "cwd": _str(max_length=4096, allow_empty=True), "cols": _int(min_value=20, max_value=300), "rows": _int(min_value=5, max_value=120)}),
    "pty_read": ToolSpec("pty_read", {"pty_id": _str(True, max_length=200), "max_chars": _int(min_value=100, max_value=200_000)}),
    "pty_write": ToolSpec("pty_write", {"pty_id": _str(True, max_length=200), "data": _str(True, max_length=20_000, allow_empty=True)}),
    "pty_resize": ToolSpec("pty_resize", {"pty_id": _str(True, max_length=200), "cols": _int(min_value=20, max_value=300), "rows": _int(min_value=5, max_value=120)}),
    "pty_close": ToolSpec("pty_close", {"pty_id": _str(True, max_length=200)}),
}


def get_tool_spec(tool: str, config: Any | None = None) -> ToolSpec | None:
    if config is not None:
        from .pipeline_dynamic_schema import dynamic_tool_spec

        dynamic = dynamic_tool_spec(tool, config)
        if dynamic is not None:
            return dynamic
    return TOOL_SPECS.get(tool)


def required_fields(tool: str, config: Any | None = None) -> tuple[str, ...]:
    spec = get_tool_spec(tool, config)
    return spec.required_fields if spec else ()



def describe_tool_schema(tool: str, config: Any | None = None) -> dict[str, Any]:
    spec = get_tool_spec(tool, config)
    if spec is None:
        return {"tool": tool, "known": False, "required": [], "fields": {}}
    fields: dict[str, Any] = {}
    for name, field in spec.fields.items():
        field_info: dict[str, Any] = {"kind": _kind_name(field.kind), "required": field.required}
        if field.min_value is not None:
            field_info["minimum"] = field.min_value
        if field.max_value is not None:
            field_info["maximum"] = field.max_value
        if field.min_length is not None:
            field_info["min_length"] = field.min_length
        if field.max_length is not None:
            field_info["max_length"] = field.max_length
        if field.allowed_values:
            field_info["enum"] = list(field.allowed_values)
        if field.item_kind:
            field_info["item_kind"] = _kind_name(field.item_kind)
        fields[name] = field_info
    return {
        "tool": tool,
        "known": True,
        "required": list(spec.required_fields),
        "allow_extra": spec.allow_extra,
        "any_of": [list(group) for group in spec.any_of],
        "one_of": [list(group) for group in spec.one_of],
        "fields": fields,
    }

def _kind_matches(value: Any, kind: JsonKind) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    return False


def _matches_any_kind(value: Any, kinds: JsonKind | tuple[JsonKind, ...]) -> bool:
    if isinstance(kinds, tuple):
        return any(_kind_matches(value, kind) for kind in kinds)
    return _kind_matches(value, kinds)


def _kind_name(kinds: JsonKind | tuple[JsonKind, ...]) -> str:
    return " or ".join(kinds) if isinstance(kinds, tuple) else kinds


def _present(inp: dict[str, Any], field_name: str) -> bool:
    value = inp.get(field_name)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, list) and not value:
        return False
    return True


def _validate_field(name: str, value: Any, spec: FieldSpec) -> str | None:
    if not _matches_any_kind(value, spec.kind):
        return f"{name} must be {_kind_name(spec.kind)}"
    if isinstance(value, str):
        if not spec.allow_empty and not value.strip():
            return f"{name} cannot be empty"
        if spec.min_length is not None and len(value) < spec.min_length:
            return f"{name} must be at least {spec.min_length} characters"
        if spec.max_length is not None and len(value) > spec.max_length:
            return f"{name} must be at most {spec.max_length} characters"
    if isinstance(value, list):
        if spec.min_length is not None and len(value) < spec.min_length:
            return f"{name} must contain at least {spec.min_length} item(s)"
        if spec.max_length is not None and len(value) > spec.max_length:
            return f"{name} must contain at most {spec.max_length} item(s)"
        if spec.item_kind is not None:
            for index, item in enumerate(value):
                if not _matches_any_kind(item, spec.item_kind):
                    return f"{name}[{index}] must be {_kind_name(spec.item_kind)}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if spec.min_value is not None and value < spec.min_value:
            return f"{name} must be >= {spec.min_value:g}"
        if spec.max_value is not None and value > spec.max_value:
            return f"{name} must be <= {spec.max_value:g}"
    if spec.allowed_values and value not in spec.allowed_values:
        allowed = ", ".join(str(item) for item in spec.allowed_values)
        return f"{name} must be one of: {allowed}"
    return None


def validate_tool_input(tool: str, inp: dict[str, Any], config: Any | None = None) -> list[str]:
    spec = get_tool_spec(tool, config)
    if spec is None:
        return []
    errors: list[str] = []
    for field_name, field_spec in spec.fields.items():
        if field_spec.required and field_name not in inp:
            errors.append(f"missing required input field: {field_name}")
            continue
        if field_name not in inp or inp.get(field_name) is None:
            continue
        if problem := _validate_field(field_name, inp[field_name], field_spec):
            errors.append(problem)
    if not spec.allow_extra:
        for field_name in inp:
            if field_name not in spec.fields:
                errors.append(f"unknown input field: {field_name}")
    for group in spec.any_of:
        if not any(_present(inp, field_name) for field_name in group):
            errors.append("one of these fields is required: " + " or ".join(group))
    for group in spec.one_of:
        count = sum(1 for field_name in group if _present(inp, field_name))
        if count != 1:
            errors.append("exactly one of these fields is required: " + " or ".join(group))
    return errors
