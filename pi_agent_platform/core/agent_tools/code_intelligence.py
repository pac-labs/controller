from __future__ import annotations

import json
from typing import Any

from ..agent_events import AgentEvents
from ..config import AppConfig
from ..models import Session, Task
from ..code_intelligence.scanner import diagnostics, find_references, report, safe_root, search_symbols
from ..code_intelligence.roslyn import analyze_csharp
from ..code_intelligence.timeline_cards import lsp_card
from ..code_intelligence.lsp_features import (
    call_hierarchy as lsp_call_hierarchy,
    definition as lsp_definition,
    document_symbols as lsp_document_symbols,
    hover as lsp_hover,
    references as lsp_references,
    shutdown as lsp_shutdown,
    status as lsp_status,
    type_hierarchy as lsp_type_hierarchy,
    rename_plan as lsp_rename_plan,
    rename_apply as lsp_rename_apply,
)
from ..code_intelligence.language_servers import (
    blast_radius,
    call_hierarchy,
    language_server_status,
    module_index,
    project_metadata,
    type_hierarchy,
)
from .permission_guard import PermissionGuard


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)[:50000]


async def try_execute_code_intelligence_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    del config
    if tool not in {
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
        "code_lsp_endpoint_prepare",
        "code_roslyn_analysis",
    }:
        return None
    if denied := PermissionGuard(perm).require("file_read"):
        return denied
    events = AgentEvents(session, task)
    root = safe_root(session.workspace_path, str(inp.get("path") or "."))

    if tool == "code_intelligence_report":
        result = report(root, max_files=max(50, min(int(inp.get("max_files") or 1200), 5000)))
        events.tool_result(tool=tool, message="code intelligence report built", data={"path": str(inp.get("path") or "."), "languages": result.get("projects", {}).get("languages", {})})
        return _json(result), False

    if tool == "code_symbol_search":
        result = search_symbols(
            root,
            str(inp.get("query") or ""),
            language=str(inp.get("language") or "") or None,
            kind=str(inp.get("kind") or "") or None,
            max_results=max(1, min(int(inp.get("max_results") or 80), 500)),
        )
        events.tool_result(tool=tool, message=f"symbol search returned {result['count']} matches", data={"query": inp.get("query"), "count": result["count"]})
        return _json(result), False

    if tool == "code_definition":
        query = str(inp.get("symbol") or inp.get("query") or "")
        result = search_symbols(root, query, language=str(inp.get("language") or "") or None, max_results=20)
        exact = [item for item in result.get("symbols", []) if item.get("name") == query]
        payload = {"symbol": query, "definitions": exact or result.get("symbols", [])[:10]}
        events.tool_result(tool=tool, message=f"definition lookup for {query}", data={"symbol": query, "count": len(payload["definitions"])})
        return _json(payload), False

    if tool == "code_references":
        symbol = str(inp.get("symbol") or "")
        result = find_references(root, symbol, max_results=max(1, min(int(inp.get("max_results") or 120), 1000)))
        events.tool_result(tool=tool, message=f"reference search for {symbol}: {result['count']}", data={"symbol": symbol, "count": result["count"]})
        return _json(result), False

    if tool == "code_diagnostics":
        result = diagnostics(
            root,
            language=str(inp.get("language") or "auto"),
            run=bool(inp.get("run") or False),
            timeout=max(5, min(int(inp.get("timeout") or 30), 120)),
        )
        events.tool_result(tool=tool, message="code diagnostics prepared", data={"language": result.get("language"), "run": result.get("run")})
        return _json(result), False

    if tool == "code_language_servers":
        result = language_server_status(root)
        events.tool_result(tool=tool, message="language server status checked", data={"path": str(inp.get("path") or ".")})
        return _json(result), False

    if tool == "code_project_metadata":
        result = project_metadata(
            root,
            language=str(inp.get("language") or "auto"),
            run=bool(inp.get("run") or False),
            timeout=max(5, min(int(inp.get("timeout") or 30), 180)),
        )
        events.tool_result(tool=tool, message="project metadata prepared", data={"language": result.get("language"), "run": bool(inp.get("run") or False)})
        return _json(result), False

    if tool == "code_call_hierarchy":
        symbol = str(inp.get("symbol") or "")
        result = call_hierarchy(root, symbol, max_results=max(1, min(int(inp.get("max_results") or 120), 500)))
        events.tool_result(tool=tool, message=f"call hierarchy for {symbol}: {result['count']}", data={"symbol": symbol, "count": result["count"]})
        return _json(result), False

    if tool == "code_type_hierarchy":
        symbol = str(inp.get("symbol") or "").strip() or None
        result = type_hierarchy(root, symbol, max_results=max(1, min(int(inp.get("max_results") or 120), 500)))
        events.tool_result(tool=tool, message="type hierarchy prepared", data={"symbol": symbol, "count": result["count"]})
        return _json(result), False

    if tool == "code_module_index":
        result = module_index(
            root,
            language=str(inp.get("language") or "auto"),
            max_files=max(50, min(int(inp.get("max_files") or 1200), 5000)),
        )
        events.tool_result(tool=tool, message=f"module index built: {result['count']} modules", data={"language": result.get("language"), "count": result["count"]})
        return _json(result), False

    if tool == "code_blast_radius":
        symbol = str(inp.get("symbol") or "")
        result = blast_radius(root, symbol, max_results=max(1, min(int(inp.get("max_results") or 200), 1000)))
        events.tool_result(tool=tool, message=f"blast radius for {symbol}: {result['affected_file_count']} files", data={"symbol": symbol, "affected_files": result["affected_file_count"]})
        return _json(result), False

    if tool == "code_lsp_status":
        result = lsp_status(root)
        events.tool_result(tool=tool, message="persistent LSP status checked", data={"active_clients": len(result.get("active_clients", [])), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_document_symbols":
        result = lsp_document_symbols(root, str(inp.get("file") or ""), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP document symbols requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_definition":
        result = lsp_definition(root, str(inp.get("file") or ""), int(inp.get("line") or 1), int(inp.get("character") or 0), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP definition requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_references":
        result = lsp_references(root, str(inp.get("file") or ""), int(inp.get("line") or 1), int(inp.get("character") or 0), include_declaration=bool(inp.get("include_declaration", True)), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP references requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_hover":
        result = lsp_hover(root, str(inp.get("file") or ""), int(inp.get("line") or 1), int(inp.get("character") or 0), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP hover requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_call_hierarchy":
        result = lsp_call_hierarchy(root, str(inp.get("file") or ""), int(inp.get("line") or 1), int(inp.get("character") or 0), direction=str(inp.get("direction") or "incoming"), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP call hierarchy requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_type_hierarchy":
        result = lsp_type_hierarchy(root, str(inp.get("file") or ""), int(inp.get("line") or 1), int(inp.get("character") or 0), direction=str(inp.get("direction") or "both"), language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="LSP type hierarchy requested", data={"file": inp.get("file"), "mode": result.get("mode"), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_shutdown":
        result = lsp_shutdown(root, language=str(inp.get("language") or "") or None)
        events.tool_result(tool=tool, message="persistent LSP clients stopped", data={"stopped": result.get("stopped")})
        return _json(result), False

    if tool == "code_lsp_rename_plan":
        result = lsp_rename_plan(
            root,
            str(inp.get("file") or ""),
            int(inp.get("line") or 1),
            int(inp.get("character") or 0),
            str(inp.get("new_name") or ""),
            language=str(inp.get("language") or "") or None,
        )
        events.tool_result(tool=tool, message="LSP rename plan requested", data={"file": inp.get("file"), "mode": result.get("mode"), "changed_files": (result.get("preview") or {}).get("changed_files", []), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_rename_apply":
        if denied := PermissionGuard(perm).require("file_write"):
            return denied
        result = lsp_rename_apply(
            root,
            str(inp.get("file") or ""),
            int(inp.get("line") or 1),
            int(inp.get("character") or 0),
            str(inp.get("new_name") or ""),
            language=str(inp.get("language") or "") or None,
        )
        events.tool_result(tool=tool, message="LSP rename applied", data={"file": inp.get("file"), "mode": result.get("mode"), "changed_files": (result.get("applied") or {}).get("changed_files", []), "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_lsp_endpoint_prepare":
        result = {"mode": "endpoint-runner-preferred", "message": "In container-backed sessions this tool is executed through the endpoint runner to prepare endpoint LSP metadata. Controller-side fallback has nothing to prepare."}
        events.tool_result(tool=tool, message="endpoint LSP preparation fallback", data={**result, "timeline": lsp_card(tool, result)})
        return _json(result), False

    if tool == "code_roslyn_analysis":
        result = analyze_csharp(
            root,
            path=str(inp.get("path") or "."),
            run=bool(inp.get("run") or False),
            timeout=max(10, min(int(inp.get("timeout") or 120), 600)),
        )
        events.tool_result(tool=tool, message="C# semantic readiness checked", data={"timeline": lsp_card(tool, result), "project_count": result.get("project_count"), "symbol_count": result.get("symbol_count")})
        return _json(result), False

    return None
