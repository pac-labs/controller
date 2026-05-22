from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..context_manager import batch_reduce_text, chunk_text, file_manifest, should_chunk_text
from ..models import Session, Task, TaskStatus
from ..agent_events import AgentEvents
from ..store import store
from .permission_guard import PermissionGuard


def _safe_path(session: Session, rel_path: str) -> Path:
    root = Path(session.workspace_path).resolve()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes workspace")
    return target


async def try_execute_file_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "list_files":
        if denied := permission_guard.require("file_read"):
            return denied
        path = str(inp.get("path") or ".")
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        if target.is_file():
            result = json.dumps({"path": path, "type": "file", "size": target.stat().st_size})
            events.tool_result(tool="list_files", message=f"listed file {path}", data={"path": path, "result_preview": result[:1200]})
            return result, False
        items = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
            if item.name in {".git", "node_modules", "__pycache__", ".venv"}:
                continue
            items.append({"name": item.name, "type": "dir" if item.is_dir() else "file"})
        result = json.dumps({"path": path, "items": items}, indent=2)
        events.tool_result(tool="list_files", message=f"listed {path}", data={"path": path, "count": len(items), "result_preview": result[:1200]})
        return result, False

    if tool == "read_file":
        if denied := permission_guard.require("file_read"):
            return denied
        path = str(inp.get("path") or "")
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        result = target.read_text(errors="replace")[:20000]
        events.tool_result(tool="read_file", message=f"read {path}", data={"path": path, "chars": len(result)})
        return result, False


    if tool == "read_file_chunk":
        if denied := permission_guard.require("file_read"):
            return denied
        path = str(inp.get("path") or "")
        chunk_index = int(inp.get("chunk_index") or 0)
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        text = target.read_text(errors="replace")
        should_chunk, suggested_tokens = should_chunk_text(config, session.model, session.context_mode, text)
        if not should_chunk:
            result = json.dumps({"path": path, "chunk_index": 0, "chunk_count": 1, "start": 0, "end": len(text), "content": text}, indent=2)
            events.tool_result(tool="read_file", message=f"read {path}", data={"path": path, "chars": len(text), "promoted_from": "read_file_chunk"})
            return result[:22000], False
        chunk_tokens = max(chunk_tokens, suggested_tokens)
        chunks = chunk_text(text, max_tokens=chunk_tokens)
        if chunk_index < 0 or chunk_index >= len(chunks):
            return json.dumps({"path": path, "chunk_count": len(chunks), "error": "chunk_index out of range"}), False
        c = chunks[chunk_index]
        result = json.dumps({"path": path, "chunk_index": chunk_index, "chunk_count": len(chunks), "start": c["start"], "end": c["end"], "content": c["content"]}, indent=2)
        events.tool_result(tool="read_file_chunk", message=f"read chunk {chunk_index} from {path}", data={"path": path, "chunk_index": chunk_index, "chunk_count": len(chunks)})
        return result, False

    if tool == "edit_file":
        if denied := permission_guard.require("file_write"):
            return denied
        path = str(inp.get("path") or "")
        old_text = str(inp.get("old_text") or "")
        new_text = str(inp.get("new_text") or "")
        if not path or not old_text:
            return "edit_file requires path and old_text", False
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        content = target.read_text(errors="replace")
        if old_text not in content:
            return f"old_text not found in {path} — no changes made", False
        backup_path = target.with_suffix(target.suffix + ".bak")
        target.write_text(content, encoding="utf-8")  # overwrite backup with original
        new_content = content.replace(old_text, new_text, 1)  # replace first occurrence only
        target.write_text(new_content, encoding="utf-8")
        events.tool_result(tool="edit_file", message=f"edited {path}", data={"path": path})
        return f"EDITED {path}: replaced 1 occurrence", False

    if tool == "ripgrep":
        if denied := permission_guard.require("file_read"):
            return denied
        query = str(inp.get("query") or "")
        path = str(inp.get("path") or session.workspace_path)
        file_filter = str(inp.get("file_filter") or "")
        context = max(0, min(int(inp.get("context") or 0), 5))
        max_results = max(1, min(int(inp.get("max_results") or 200), 2000))
        if not query:
            return "ripgrep requires query", False
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        import re
        try:
            pattern = re.compile(query)
        except Exception:
            pattern = re.compile(re.escape(query))
        matches = []
        try:
            files = list(target.rglob(file_filter or "*"))
        except Exception:
            files = []
        for f in files:
            if f.is_dir() or "/.git/" in str(f) or "/node_modules/" in str(f) or "/__pycache__/" in str(f):
                continue
            try:
                lines = f.read_text(errors="replace").split("\n")
            except Exception:
                continue
            for i, line in enumerate(lines):
                if pattern.search(line):
                    ctx_before = lines[max(0, i - context):i]
                    ctx_after = lines[i + 1:i + 1 + context]
                    matches.append({
                        "file": str(f.relative_to(target)),
                        "line": i + 1,
                        "text": line.strip(),
                        "context_before": ctx_before,
                        "context_after": ctx_after,
                    })
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        result = json.dumps({"query": query, "path": str(path), "count": len(matches), "matches": matches[:max_results]}, indent=2)
        events.tool_result(tool="ripgrep", message=f"ripgrep: {query} → {len(matches)} matches", data={"query": query, "count": len(matches)})
        return result[:15000], False

    if tool == "fd":
        if denied := permission_guard.require("file_read"):
            return denied
        pattern = str(inp.get("pattern") or "*")
        path = str(inp.get("path") or session.workspace_path)
        max_results = max(1, min(int(inp.get("max_results") or 200), 2000))
        target = _safe_path(session, path)
        if not target.exists():
            return f"Path not found: {path}", False
        results = []
        try:
            for f in target.rglob(pattern):
                if "/.git/" in str(f) or "/node_modules/" in str(f) or "/__pycache__/" in str(f):
                    continue
                rel = str(f.relative_to(target))
                results.append({"name": rel, "type": "dir" if f.is_dir() else "file", "size": f.stat().st_size if f.is_file() else 0})
                if len(results) >= max_results:
                    break
        except Exception as e:
            return f"fd error: {e}", False
        return json.dumps({"pattern": pattern, "count": len(results), "results": results}, indent=2)[:15000], False

    if tool == "batch_analyze_text":
        instruction = str(inp.get("instruction") or "Summarize this text")
        text = str(inp.get("text") or "")
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        should_chunk, suggested_tokens = should_chunk_text(config, session.model, session.context_mode, text)
        chunk_tokens = max(chunk_tokens, suggested_tokens)
        result = batch_reduce_text(config, session.model, instruction, text, chunk_tokens=chunk_tokens)
        events.batch_result(message=f"Batched analysis completed over {result['chunk_count']} chunks", data={"chunk_count": result["chunk_count"]})
        return json.dumps({"chunk_count": result["chunk_count"], "summary": result["summary"]}, indent=2), False

    if tool == "batch_analyze_file":
        if denied := permission_guard.require("file_read"):
            return denied
        path = str(inp.get("path") or "")
        instruction = str(inp.get("instruction") or f"Analyze {path}")
        chunk_tokens = int(inp.get("chunk_tokens") or 1200)
        target = _safe_path(session, path)
        if not target.is_file():
            return f"File not found: {path}", False
        text = target.read_text(errors="replace")
        should_chunk, suggested_tokens = should_chunk_text(config, session.model, session.context_mode, text)
        chunk_tokens = max(chunk_tokens, suggested_tokens)
        result = batch_reduce_text(config, session.model, instruction, text, chunk_tokens=chunk_tokens)
        events.batch_result(message=f"Batched file analysis completed for {path} over {result['chunk_count']} chunks", data={"path": path, "chunk_count": result["chunk_count"]})
        return json.dumps({"path": path, "chunk_count": result["chunk_count"], "summary": result["summary"]}, indent=2), False

    if tool == "write_file":
        if denied := permission_guard.require("file_write"):
            return denied
        if permission_guard.level("file_write") == "ask" and session.permission_profile != "full-control":
            from ..auto_approve import should_auto_approve
            approved, reason = should_auto_approve("write_file", inp)
            if approved:
                events.auto_approved(reason=reason, data={"tool": "write_file", "path": inp.get("path")})
            else:
                task.status = TaskStatus.approval_required
                task.metadata["agent_loop"] = True
                task.metadata["pending_tool"] = {"tool": "write_file", "input": inp}
                store.add_task(task)
                events.approval_required(message=f"Agent wants to write file: {inp.get('path')}", data={"path": inp.get("path")})
                return "APPROVAL_REQUIRED", True
        path = str(inp.get("path") or "")
        content = str(inp.get("content") or "")
        target = _safe_path(session, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        events.tool_result(tool="write_file", message=f"wrote {path}", data={"path": path})
        return f"WROTE {path} ({len(content)} bytes)", False

    return None
