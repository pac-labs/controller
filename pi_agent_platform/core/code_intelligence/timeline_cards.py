from __future__ import annotations

from typing import Any


def lsp_card(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact timeline card for code intelligence tool output.

    The raw tool output remains available in the expandable event details; this
    card gives the session timeline a readable summary for definitions,
    references, hierarchy, rename previews, and endpoint/server readiness.
    """

    if tool == "code_lsp_status":
        servers = result.get("servers", {}) if isinstance(result.get("servers"), dict) else {}
        active = result.get("active_clients", []) if isinstance(result.get("active_clients"), list) else []
        ready = [name for name, row in servers.items() if isinstance(row, dict) and row.get("ready")]
        detected = [name for name, row in servers.items() if isinstance(row, dict) and row.get("detected")]
        return {
            "title": "Language servers",
            "summary": f"{len(ready)} ready, {len(detected)} detected in this workspace.",
            "fields": {"ready": ", ".join(ready) or "none", "active clients": len(active)},
            "steps": [
                {"status": "ok" if name in ready else "warn", "label": name, "detail": _server_detail(servers.get(name, {}))}
                for name in sorted(servers.keys())
            ],
        }

    if tool == "code_lsp_endpoint_prepare":
        return {
            "title": "Endpoint LSP preparation",
            "summary": "Endpoint-side language server metadata was prepared for this workspace.",
            "fields": _simple_fields(result, ("mode", "path", "language")),
            "output": _truncate(str(result.get("output") or result.get("result") or ""), 3000),
        }

    if tool in {"code_lsp_definition", "code_lsp_references", "code_lsp_hover"}:
        payload = result.get("result")
        count = _count_items(payload)
        return {
            "title": _tool_title(tool),
            "summary": f"{result.get('file', 'file')} · {result.get('language', 'auto')} · {count} item{'' if count == 1 else 's'}.",
            "fields": _simple_fields(result, ("file", "language", "method", "mode")),
            "output": _truncate(_preview(payload), 5000),
        }

    if tool == "code_lsp_document_symbols":
        symbols = result.get("symbols", [])
        return {
            "title": "Document symbols",
            "summary": f"{_count_items(symbols)} symbols in {result.get('file', 'file')}.",
            "fields": _simple_fields(result, ("file", "language", "mode")),
            "steps": _symbol_steps(symbols),
        }

    if tool in {"code_lsp_call_hierarchy", "code_lsp_type_hierarchy"}:
        data = result.get("result", {}) if isinstance(result.get("result"), dict) else {}
        return {
            "title": _tool_title(tool),
            "summary": f"{result.get('file', 'file')} · {result.get('direction', 'both')}.",
            "fields": _simple_fields(result, ("file", "language", "direction", "mode")),
            "output": _truncate(_preview(data), 6000),
        }

    if tool == "code_lsp_rename_plan":
        preview = result.get("preview", {}) if isinstance(result.get("preview"), dict) else {}
        return {
            "title": "Rename preview",
            "summary": f"Rename to {result.get('new_name', '')}: {preview.get('changed_file_count', 0)} files would change.",
            "fields": {"file": result.get("file", ""), "language": result.get("language", ""), "changed files": preview.get("changed_file_count", 0)},
            "diff": _truncate(str(preview.get("diff") or ""), 12000),
        }

    if tool == "code_lsp_rename_apply":
        applied = result.get("applied", {}) if isinstance(result.get("applied"), dict) else {}
        return {
            "title": "Rename applied",
            "summary": f"Rename to {result.get('new_name', '')}: {applied.get('changed_file_count', 0)} files changed.",
            "fields": {"file": result.get("file", ""), "language": result.get("language", ""), "changed files": applied.get("changed_file_count", 0)},
        }

    if tool == "code_roslyn_analysis":
        return {
            "title": "C# semantic readiness",
            "summary": result.get("summary") or "C# project and analyzer readiness checked.",
            "fields": _simple_fields(result, ("mode", "project_count", "solution_count", "dotnet_available")),
            "steps": _roslyn_steps(result),
            "output": _truncate(str(result.get("diagnostics_preview") or ""), 5000),
        }

    return {"title": _tool_title(tool), "summary": "Code intelligence result is available in event details."}


def _server_detail(row: Any) -> str:
    if not isinstance(row, dict):
        return "unknown"
    command = row.get("preferred_command") or []
    if command:
        return " ".join(str(part) for part in command)
    probes = row.get("probes") or []
    missing = [" ".join(item.get("command") or []) for item in probes if isinstance(item, dict) and not item.get("available")]
    return "missing: " + ", ".join(missing[:3]) if missing else "not detected"


def _simple_fields(result: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key.replace("_", " "): result.get(key) for key in keys if result.get(key) not in (None, "", [])}


def _count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(_count_items(item) for item in value.values()) or 1
    return 1 if value else 0


def _symbol_steps(symbols: Any) -> list[dict[str, str]]:
    if not isinstance(symbols, list):
        return []
    rows: list[dict[str, str]] = []
    for item in symbols[:12]:
        if not isinstance(item, dict):
            continue
        rows.append({"status": "info", "label": str(item.get("name") or "symbol"), "detail": str(item.get("detail") or item.get("kind") or "")})
    return rows


def _roslyn_steps(result: dict[str, Any]) -> list[dict[str, str]]:
    steps = []
    for project in result.get("projects", [])[:12]:
        if not isinstance(project, dict):
            continue
        steps.append({"status": "ok", "label": project.get("name") or project.get("path") or "project", "detail": project.get("target_framework") or project.get("path") or ""})
    return steps


def _tool_title(tool: str) -> str:
    return tool.replace("code_lsp_", "LSP ").replace("_", " ").title()


def _preview(value: Any) -> str:
    import json

    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def _truncate(value: str, limit: int) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "\n… truncated …"
