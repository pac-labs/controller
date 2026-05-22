from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from .permission_guard import PermissionGuard


async def try_execute_workspace_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    permission_guard = PermissionGuard(perm)
    if tool == "workspace_manifest":
        if denied := permission_guard.require("file_read"):
            return denied
        max_files = int(inp.get("max_files") or 200)
        import re
        _ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
        _ignored_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".tar", ".sqlite", ".db", ".pyc"}
        _project_markers = {
            "package.json": "Node",
            "pyproject.toml": "Python",
            "setup.py": "Python",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "requirements.txt": "Python",
            "Gemfile": "Ruby",
            "pom.xml": "Java",
            "build.gradle": "Java",
        }
        _key_files = ["README.md", "README", "readme.md", "README.rst", "config.yaml", "config.yml", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile", "Dockerfile", ".dockerignore", ".gitignore", "pyproject.toml", "setup.py", "setup.cfg"]

        root = Path(session.workspace_path)
        files_tree: dict = {}
        flat_files: list[dict] = []
        projects: list[dict] = []
        total_size = 0
        file_count = 0
        detected_project_types: set[str] = set()
        key_files_found: dict[str, str] = {}

        def _tree_get(tree: dict, parts: list[str]) -> dict:
            node = tree
            for part in parts:
                if part not in node:
                    node[part] = {"__files": [], "__dirs": {}}
                node = node[part]
            return node

        def _add_to_tree(tree: dict, rel_path: Path) -> None:
            parts = list(rel_path.parts[:-1])
            if not parts:
                tree.setdefault("__files", []).append(rel_path.name)
                return
            node = _tree_get(tree, parts)
            node.setdefault("__files", []).append(rel_path.name)

        def _build_readme_snippet(p: Path) -> str:
            try:
                text = p.read_text(errors="replace")
                lines = [l.strip() for l in text.splitlines() if l.strip()][:10]
                return "\n".join(lines[:5])
            except Exception:
                return ""

        try:
            for p in root.rglob("*"):
                if file_count >= max_files:
                    break
                if any(part in _ignored for part in p.parts):
                    continue
                if p.is_file():
                    ext = p.suffix.lower()
                    if ext in _ignored_ext:
                        continue
                    try:
                        size = p.stat().st_size
                        total_size += size
                        file_count += 1
                    except OSError:
                        continue
                    rel = p.relative_to(root)
                    _add_to_tree(files_tree, rel)
                    flat_files.append({"path": str(rel), "size": size})
                    fname = p.name
                    fname_lower = fname.lower()
                    for marker, ptype in _project_markers.items():
                        if fname == marker:
                            detected_project_types.add(ptype)
                            project_root = str(p.parent.relative_to(root))
                            readme_p = None
                            for rf in ["README.md", "README.rst", "README", "readme.md"]:
                                candidate = p.parent / rf
                                if candidate.is_file():
                                    readme_p = candidate
                                    break
                            readme_snippet = _build_readme_snippet(readme_p) if readme_p else ""
                            projects.append({"type": ptype, "root": project_root or ".", "readme": readme_snippet[:200]})
                    for kf in _key_files:
                        if fname_lower == kf.lower():
                            key_files_found[fname] = str(rel)
                elif p.is_dir():
                    rel = p.relative_to(root)
                    parts = list(rel.parts)
                    node = _tree_get(files_tree, parts)
        except Exception:
            pass

        result = {
            "path": str(root),
            "summary": {"files": file_count, "total_bytes": total_size},
            "projects": list(detected_project_types),
            "project_details": projects,
            "key_files": key_files_found,
            "tree": files_tree,
            "flat_files": flat_files[:100],
        }
        events.tool_result(tool="workspace_manifest", message="scanned workspace manifest", data={"files": file_count, "projects": list(detected_project_types)})
        return json.dumps(result, indent=2, default=str)[:15000], False

    if tool == "query_workspace_index":
        # Let agent query the pre-built workspace index without re-scanning
        idx = task.metadata.get("workspace_index") or {}
        if not idx or idx.get("error"):
            return "No workspace index available", False
        query = str(inp.get("query") or "").lower()
        result_type = str(inp.get("type") or "summary").lower()

        if result_type == "symbols" or "symbol" in query or "function" in query or "class" in query:
            syms = idx.get("python_symbols", [])
            if not syms:
                return json.dumps({"note": "no Python symbols indexed"}), False
            return json.dumps({"type": "python_symbols", "count": len(syms), "files": syms[:50]}, indent=2)[:12000], False

        if result_type == "tree" or "tree" in query or "structure" in query or "files" in query:
            tree = idx.get("tree", {}).get("root", {})

            def _truncate_tree(t: dict, depth: int = 4) -> dict:
                if depth <= 0:
                    return {"type": "dir", "truncated": True}
                result = {}
                for k, v in list(t.items())[:40]:
                    if isinstance(v, dict) and v.get("type") == "dir":
                        result[k] = {"type": "dir", "children": _truncate_tree(v.get("children", {}), depth - 1)}
                    else:
                        result[k] = v
                return result

            return json.dumps({"type": "file_tree", "tree": _truncate_tree(tree, depth=4)}, indent=2)[:12000], False

        if result_type == "git" or "commit" in query or "history" in query or "change" in query:
            git = idx.get("git_summary", {})
            if git.get("error"):
                return f"No git info: {git.get('error', 'unknown')}", False
            return json.dumps({"type": "git_summary", **git}, indent=2)[:12000], False

        if result_type == "key_files" or "config" in query or "readme" in query:
            kf = idx.get("key_files", [])
            return json.dumps({"type": "key_files", "count": len(kf), "files": kf}, indent=2)[:12000], False

        # Default: return project summary
        summary = {
            "project_type": idx.get("project_type"),
            "projects": idx.get("projects", []),
            "file_count": idx.get("tree", {}).get("file_count", 0),
            "total_bytes": idx.get("tree", {}).get("total_bytes", 0),
            "python_files": len(idx.get("python_symbols", [])),
            "git_branch": idx.get("git_summary", {}).get("branch"),
            "git_total_commits": idx.get("git_summary", {}).get("total_commits", 0),
            "recent_commit": idx.get("git_summary", {}).get("recent_commits", [{}])[0] if idx.get("git_summary", {}).get("recent_commits") else None,
        }
        return json.dumps({"type": "workspace_summary", **summary}, indent=2)[:8000], False

    return None
