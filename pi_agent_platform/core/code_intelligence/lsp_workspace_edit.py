from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .lsp_client import uri_path


@dataclass(frozen=True, slots=True)
class WorkspaceEditPreview:
    changed_files: list[str]
    skipped: list[dict[str, Any]]
    diff: str
    edit_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "skipped": self.skipped,
            "diff": self.diff,
            "edit_count": self.edit_count,
        }


def preview_workspace_edit(root: Path, workspace_edit: dict[str, Any], *, max_diff_lines: int = 400) -> WorkspaceEditPreview:
    updated, skipped, edit_count = _render_updates(root, workspace_edit)
    diff_lines: list[str] = []
    for rel_path, before_after in sorted(updated.items()):
        before, after = before_after
        diff_lines.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
        )
        if len(diff_lines) >= max_diff_lines:
            diff_lines = diff_lines[:max_diff_lines]
            diff_lines.append("\n... diff truncated ...\n")
            break
    return WorkspaceEditPreview(
        changed_files=sorted(updated.keys()),
        skipped=skipped,
        diff="".join(diff_lines),
        edit_count=edit_count,
    )


def apply_workspace_edit(root: Path, workspace_edit: dict[str, Any]) -> WorkspaceEditPreview:
    updated, skipped, edit_count = _render_updates(root, workspace_edit)
    preview = preview_workspace_edit(root, workspace_edit)
    for rel_path, before_after in updated.items():
        _before, after = before_after
        target = _safe_path(root, rel_path)
        target.write_text(after, encoding="utf-8")
    return WorkspaceEditPreview(
        changed_files=preview.changed_files,
        skipped=skipped,
        diff=preview.diff,
        edit_count=edit_count,
    )


def _render_updates(root: Path, workspace_edit: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], list[dict[str, Any]], int]:
    changes, skipped = _collect_text_edits(root, workspace_edit)
    updated: dict[str, tuple[str, str]] = {}
    edit_count = 0
    for rel_path, edits in changes.items():
        target = _safe_path(root, rel_path)
        if not target.exists() or not target.is_file():
            skipped.append({"file": rel_path, "reason": "target is not a file"})
            continue
        before = target.read_text(errors="replace")
        after = _apply_text_edits(before, edits)
        if after != before:
            updated[rel_path] = (before, after)
            edit_count += len(edits)
    return updated, skipped, edit_count


def _collect_text_edits(root: Path, workspace_edit: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    changes: dict[str, list[dict[str, Any]]] = {}
    skipped: list[dict[str, Any]] = []
    for uri, edits in (workspace_edit.get("changes") or {}).items():
        rel_path = _rel_from_uri(root, uri)
        if rel_path:
            changes.setdefault(rel_path, []).extend([edit for edit in edits if isinstance(edit, dict)])
        else:
            skipped.append({"uri": uri, "reason": "unsupported non-file URI"})
    for entry in workspace_edit.get("documentChanges") or []:
        if not isinstance(entry, dict):
            continue
        text_document = entry.get("textDocument")
        if not text_document:
            skipped.append({"operation": entry.get("kind") or "resource", "reason": "resource operations are not applied"})
            continue
        rel_path = _rel_from_uri(root, str(text_document.get("uri") or ""))
        if not rel_path:
            skipped.append({"uri": text_document.get("uri"), "reason": "unsupported non-file URI"})
            continue
        changes.setdefault(rel_path, []).extend([edit for edit in entry.get("edits") or [] if isinstance(edit, dict)])
    return changes, skipped


def _apply_text_edits(text: str, edits: list[dict[str, Any]]) -> str:
    lines = text.splitlines(keepends=True)
    ordered = sorted(edits, key=lambda e: (_start(e)[0], _start(e)[1]), reverse=True)
    current = text
    for edit in ordered:
        start_line, start_char = _start(edit)
        end_line, end_char = _end(edit)
        start = _offset(current, start_line, start_char)
        end = _offset(current, end_line, end_char)
        current = current[:start] + str(edit.get("newText") or "") + current[end:]
    return current


def _offset(text: str, line: int, character: int) -> int:
    if line <= 0:
        return max(0, character)
    lines = text.splitlines(keepends=True)
    offset = sum(len(item) for item in lines[:line])
    return min(len(text), offset + max(0, character))


def _start(edit: dict[str, Any]) -> tuple[int, int]:
    pos = ((edit.get("range") or {}).get("start") or {})
    return int(pos.get("line") or 0), int(pos.get("character") or 0)


def _end(edit: dict[str, Any]) -> tuple[int, int]:
    pos = ((edit.get("range") or {}).get("end") or {})
    return int(pos.get("line") or 0), int(pos.get("character") or 0)


def _rel_from_uri(root: Path, uri: str) -> str | None:
    if not uri.startswith("file://"):
        return None
    target = Path(uri_path(uri)).resolve()
    root = root.resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"workspace edit target escapes workspace: {target}")
    return str(target.relative_to(root))


def _safe_path(root: Path, rel_or_abs: str) -> Path:
    root = root.resolve()
    candidate = Path(rel_or_abs)
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (root / candidate).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"workspace edit target escapes workspace: {rel_or_abs}")
    return target
