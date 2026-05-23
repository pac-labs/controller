from __future__ import annotations

from pathlib import Path
from typing import Any


MAX_ACTIVE_FILE_CHARS = 12000
MAX_SELECTION_CHARS = 4000
MAX_OPEN_FILES = 4
MAX_OPEN_FILE_CHARS = 2500


def session_editor_state(metadata: dict[str, Any] | None) -> dict[str, Any]:
    state = (metadata or {}).get("editor_state")
    return state if isinstance(state, dict) else {}


def editor_session_summary(metadata: dict[str, Any] | None) -> str:
    state = session_editor_state(metadata)
    origin = str((metadata or {}).get("session_origin") or "editor").strip() or "editor"
    active_file = str(state.get("active_file") or "").strip()
    if active_file:
        return f"{origin} attached: {active_file}"
    open_files = state.get("open_files")
    if isinstance(open_files, list) and open_files:
        return f"{origin} attached: {len(open_files)} open file(s)"
    return f"{origin} attached"


def build_editor_state_briefing(workspace_path: str | None, metadata: dict[str, Any] | None) -> str:
    state = session_editor_state(metadata)
    if not state:
        return ""
    root = Path(workspace_path or "").resolve() if workspace_path else None
    lines = ["=== EDITOR CONTEXT ==="]
    origin = str((metadata or {}).get("session_origin") or state.get("editor") or "editor").strip()
    if origin:
        lines.append(f"Editor client: {origin}")
    if workspace_root := str(state.get("workspace_root") or "").strip():
        lines.append(f"Editor workspace root: {workspace_root}")
    active_file = str(state.get("active_file") or "").strip()
    if active_file:
        lines.append(f"Active file: {active_file}")
    language = str(state.get("language_id") or "").strip()
    if language:
        lines.append(f"Language: {language}")
    if selection := _selection_block(state):
        lines.append("Selection:")
        lines.append(selection)
    active_contents = _file_preview(root, active_file, MAX_ACTIVE_FILE_CHARS) if active_file else ""
    if active_contents:
        lines.append(f"Active file contents ({active_file}):")
        lines.append(active_contents)
    open_files = state.get("open_files")
    if isinstance(open_files, list):
        previews: list[str] = []
        for rel_path in [str(item).strip() for item in open_files if str(item).strip()][:MAX_OPEN_FILES]:
            if rel_path == active_file:
                continue
            preview = _file_preview(root, rel_path, MAX_OPEN_FILE_CHARS)
            if preview:
                previews.append(f"{rel_path}:\n{preview}")
        if previews:
            lines.append("Other open files:")
            lines.extend(previews)
    diagnostics = state.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        lines.append("Diagnostics:")
        for item in diagnostics[:10]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "info").strip()
            path = str(item.get("path") or active_file or "").strip()
            message = str(item.get("message") or "").strip()
            if message:
                lines.append(f"- [{severity}] {path}: {message}")
    lines.append("=== END EDITOR CONTEXT ===")
    return "\n".join(lines)


def _selection_block(state: dict[str, Any]) -> str:
    selected_text = str(state.get("selected_text") or "").strip()
    if not selected_text:
        return ""
    if len(selected_text) > MAX_SELECTION_CHARS:
        selected_text = selected_text[:MAX_SELECTION_CHARS] + "\n...[selection truncated]"
    start_line = state.get("selection_start_line")
    end_line = state.get("selection_end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        return f"Lines {start_line}-{end_line}\n{selected_text}"
    return selected_text


def _file_preview(root: Path | None, rel_path: str, max_chars: int) -> str:
    try:
        target = _safe_editor_path(root, rel_path)
    except ValueError:
        return ""
    if not target or not target.is_file():
        return ""
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    content = content.strip()
    if not content:
        return ""
    if len(content) > max_chars:
        content = content[:max_chars] + "\n...[file preview truncated]"
    return content


def _safe_editor_path(root: Path | None, rel_path: str) -> Path | None:
    rel = str(rel_path or "").replace("\\", "/").strip().strip("/")
    if not root or not rel:
        return None
    resolved_root = root.resolve()
    target = (resolved_root / rel).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ValueError("Path escapes workspace root")
    return target
