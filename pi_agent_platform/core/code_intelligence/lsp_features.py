from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .lsp_client import (
    LspError,
    SERVER_SPECS,
    active_clients,
    client_for,
    detect_language_for_file,
    preferred_command,
    shutdown_clients,
    uri_path,
)
from .scanner import detect_projects, safe_root
from .lsp_workspace_edit import apply_workspace_edit, preview_workspace_edit


def status(root: Path) -> dict[str, Any]:
    projects = detect_projects(root)
    languages = set(projects.get("languages", {}).keys())
    servers: dict[str, Any] = {}
    for language, spec in SERVER_SPECS.items():
        probes = []
        for command in spec.binaries:
            probes.append({"command": list(command), "available": bool(shutil.which(command[0])), "path": shutil.which(command[0])})
        servers[language] = {
            "detected": language in languages,
            "ready": preferred_command(language) is not None,
            "preferred_command": list(preferred_command(language) or ()),
            "probes": probes,
        }
    return {"projects": projects, "servers": servers, "active_clients": active_clients(), "mode": "persistent-jsonrpc-lsp"}


def document_symbols(root: Path, file: str, *, language: str | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        result = client.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}}, timeout=20)
        return {"file": file, "language": lang, "symbols": _compact(result), "mode": "lsp-document-symbol"}
    except LspError as exc:
        return _error(file, language or "auto", exc, "textDocument/documentSymbol")


def definition(root: Path, file: str, line: int, character: int, *, language: str | None = None) -> dict[str, Any]:
    return _position_request(root, file, line, character, "textDocument/definition", language=language)


def references(root: Path, file: str, line: int, character: int, *, include_declaration: bool = True, language: str | None = None) -> dict[str, Any]:
    extra = {"context": {"includeDeclaration": include_declaration}}
    return _position_request(root, file, line, character, "textDocument/references", language=language, extra=extra)


def hover(root: Path, file: str, line: int, character: int, *, language: str | None = None) -> dict[str, Any]:
    return _position_request(root, file, line, character, "textDocument/hover", language=language)


def call_hierarchy(root: Path, file: str, line: int, character: int, *, direction: str = "incoming", language: str | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        params = _text_position(uri, line, character)
        items = client.request("textDocument/prepareCallHierarchy", params, timeout=20) or []
        results: dict[str, Any] = {"prepare": _compact(items)}
        if direction in {"incoming", "both"}:
            results["incoming"] = [_compact(client.request("callHierarchy/incomingCalls", {"item": item}, timeout=20)) for item in items[:5]]
        if direction in {"outgoing", "both"}:
            results["outgoing"] = [_compact(client.request("callHierarchy/outgoingCalls", {"item": item}, timeout=20)) for item in items[:5]]
        return {"file": file, "language": lang, "direction": direction, "result": results, "mode": "lsp-call-hierarchy"}
    except LspError as exc:
        return _error(file, language or "auto", exc, "callHierarchy")


def type_hierarchy(root: Path, file: str, line: int, character: int, *, direction: str = "both", language: str | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        params = _text_position(uri, line, character)
        items = client.request("textDocument/prepareTypeHierarchy", params, timeout=20) or []
        results: dict[str, Any] = {"prepare": _compact(items)}
        if direction in {"supertypes", "both"}:
            results["supertypes"] = [_compact(client.request("typeHierarchy/supertypes", {"item": item}, timeout=20)) for item in items[:5]]
        if direction in {"subtypes", "both"}:
            results["subtypes"] = [_compact(client.request("typeHierarchy/subtypes", {"item": item}, timeout=20)) for item in items[:5]]
        return {"file": file, "language": lang, "direction": direction, "result": results, "mode": "lsp-type-hierarchy"}
    except LspError as exc:
        return _error(file, language or "auto", exc, "typeHierarchy")



def rename_plan(root: Path, file: str, line: int, character: int, new_name: str, *, language: str | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        params = _text_position(uri, line, character)
        params["newName"] = new_name
        workspace_edit = client.request("textDocument/rename", params, timeout=30) or {}
        preview = preview_workspace_edit(root, workspace_edit).as_dict()
        return {
            "file": file,
            "language": lang,
            "new_name": new_name,
            "workspace_edit": _compact(workspace_edit),
            "preview": preview,
            "mode": "lsp-rename-plan",
        }
    except Exception as exc:
        return _error(file, language or "auto", exc, "textDocument/rename")


def rename_apply(root: Path, file: str, line: int, character: int, new_name: str, *, language: str | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        params = _text_position(uri, line, character)
        params["newName"] = new_name
        workspace_edit = client.request("textDocument/rename", params, timeout=30) or {}
        applied = apply_workspace_edit(root, workspace_edit).as_dict()
        return {
            "file": file,
            "language": lang,
            "new_name": new_name,
            "applied": applied,
            "mode": "lsp-rename-apply",
        }
    except Exception as exc:
        return _error(file, language or "auto", exc, "textDocument/rename")

def shutdown(root: Path, *, language: str | None = None) -> dict[str, Any]:
    stopped = shutdown_clients(root=root, language=language if language != "auto" else None)
    return {"stopped": stopped, "language": language or "all", "mode": "persistent-jsonrpc-lsp"}


def _position_request(root: Path, file: str, line: int, character: int, method: str, *, language: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        target, lang = _target(root, file, language)
        client = client_for(root, lang)
        uri = client.open_document(target)
        params = _text_position(uri, line, character)
        if extra:
            params.update(extra)
        result = client.request(method, params, timeout=20)
        return {"file": file, "language": lang, "method": method, "result": _compact(result), "mode": "persistent-jsonrpc-lsp"}
    except LspError as exc:
        return _error(file, language or "auto", exc, method)


def _target(root: Path, file: str, language: str | None) -> tuple[Path, str]:
    target = safe_root(root, file)
    if not target.is_file():
        raise LspError(f"not a file: {file}")
    lang = detect_language_for_file(target, language)
    if not lang:
        raise LspError(f"could not detect language for {file}")
    if lang not in SERVER_SPECS:
        raise LspError(f"unsupported LSP language: {lang}")
    return target, lang


def _text_position(uri: str, line: int, character: int) -> dict[str, Any]:
    return {
        "textDocument": {"uri": uri},
        "position": {"line": max(0, int(line) - 1), "character": max(0, int(character))},
    }


def _compact(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "..."
    if isinstance(value, list):
        return [_compact(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            if key == "uri" and isinstance(item, str):
                compacted[key] = uri_path(item)
            elif key in {"data", "selectionRange"}:
                compacted[key] = _compact(item, depth=depth + 1)
            elif key in {"name", "kind", "detail", "range", "targetUri", "targetRange", "targetSelectionRange", "contents", "message"}:
                compacted[key] = _compact(item, depth=depth + 1)
            elif depth < 2:
                compacted[key] = _compact(item, depth=depth + 1)
        return compacted
    return value


def _error(file: str, language: str, exc: Exception, method: str) -> dict[str, Any]:
    return {"file": file, "language": language, "method": method, "error": str(exc), "mode": "lsp-error"}
