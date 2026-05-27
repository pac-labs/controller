from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agent_events import AgentEvents
from ..config import AppConfig
from ..models import Session, Task
from .permission_guard import PermissionGuard

_DEFAULT_ROOTS = (
    "pi_agent_platform/web/app/",
    "pi_agent_platform/web/styles/",
    "pi_agent_platform/api/routes/",
    "pi_agent_platform/core/",
)

_PAC_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("session", ("pi_agent_platform/web/app/session_", "pi_agent_platform/api/routes/sessions.py", "pi_agent_platform/core/session_commands.py")),
    ("composer", ("pi_agent_platform/web/app/session_composer_controls.js", "pi_agent_platform/web/app/composer_status.js")),
    ("timeline", ("pi_agent_platform/web/app/session_timeline_",)),
    ("atlas", ("pi_agent_platform/web/app/dashboard_atlas_", "pi_agent_platform/core/dashboard_component_atlas.py")),
    ("dashboard", ("pi_agent_platform/web/app/dashboard_",)),
    ("visualization", ("pi_agent_platform/web/app/dashboard_", "pi_agent_platform/web/app/session_timeline_")),
    ("provider", ("pi_agent_platform/web/app/provider_", "pi_agent_platform/api/routes/providers.py", "pi_agent_platform/core/providers.py")),
    ("endpoint", ("pi_agent_platform/web/app/endpoint_", "pi_agent_platform/api/routes/endpoints.py", "pi_agent_platform/core/runner_discovery.py")),
    ("workspace", ("pi_agent_platform/web/app/workspace_", "pi_agent_platform/api/routes/workspaces.py", "pi_agent_platform/core/workspace_")),
    ("profile", ("pi_agent_platform/web/app/profile_", "pi_agent_platform/api/routes/profiles.py", "pi_agent_platform/core/profiles.py")),
    ("style", ("pi_agent_platform/web/styles/",)),
)

_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
_IGNORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".tar", ".sqlite", ".db", ".pyc"}


@dataclass(slots=True)
class Candidate:
    path: str
    score: int
    reasons: list[str]
    lines: list[dict[str, Any]]

    def add_score(self, amount: int, reason: str) -> None:
        self.score += amount
        if reason not in self.reasons:
            self.reasons.append(reason)

    def add_line(self, line: int, text: str) -> None:
        if len(self.lines) >= 5:
            return
        self.lines.append({"line": line, "text": text.strip()[:240]})


def pac_code_location_hints() -> str:
    return (
        "PAC code location hints:\n"
        "- web UI modules: pi_agent_platform/web/app/\n"
        "- web styles/design tokens: pi_agent_platform/web/styles/\n"
        "- API routes: pi_agent_platform/api/routes/\n"
        "- runtime/core services: pi_agent_platform/core/\n"
        "- session UI: pi_agent_platform/web/app/session_*\n"
        "- dashboard/atlas UI: pi_agent_platform/web/app/dashboard_*\n"
        "- provider UI/API/core: pi_agent_platform/web/app/provider_*, pi_agent_platform/api/routes/providers.py, pi_agent_platform/core/providers.py\n"
        "- endpoint UI/API/core: pi_agent_platform/web/app/endpoint_*, pi_agent_platform/api/routes/endpoints.py, pi_agent_platform/core/runner_discovery.py"
    )


def _normalize_query_terms(query: str) -> list[str]:
    text = re.sub(r"[^A-Za-z0-9_./-]+", " ", str(query or "").lower())
    stop = {"the", "a", "an", "what", "where", "which", "file", "files", "handles", "handle", "find", "code", "for", "in", "pac", "core"}
    terms = [term for term in text.split() if len(term) >= 3 and term not in stop]
    phrase = str(query or "").strip().lower()
    if phrase and phrase not in terms:
        terms.insert(0, phrase)
    return terms[:12]


def _iter_files(workspace: Path, roots: list[str], max_files: int) -> list[Path]:
    files: list[Path] = []
    for rel_root in roots:
        root = (workspace / rel_root.strip("/.")).resolve() if rel_root not in {"", "."} else workspace
        if workspace != root and workspace not in root.parents:
            continue
        if not root.exists():
            continue
        search_root = root if root.is_dir() else root.parent
        for path in search_root.rglob("*"):
            if len(files) >= max_files:
                return files
            if not path.is_file():
                continue
            rel = path.relative_to(workspace)
            if any(part in _IGNORED_DIRS for part in rel.parts):
                continue
            if path.suffix.lower() in _IGNORED_SUFFIXES:
                continue
            files.append(path)
    return files


def _candidate_for(candidates: dict[str, Candidate], workspace: Path, path: Path) -> Candidate:
    rel = str(path.relative_to(workspace)).replace("\\", "/")
    if rel not in candidates:
        candidates[rel] = Candidate(path=rel, score=0, reasons=[], lines=[])
    return candidates[rel]


def _score_hints(candidates: dict[str, Candidate], workspace: Path, files: list[Path], terms: list[str]) -> None:
    lower_terms = " ".join(terms)
    for key, hinted_paths in _PAC_HINTS:
        if key not in lower_terms:
            continue
        for path in files:
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            if any(rel == hint.rstrip("/") or rel.startswith(hint) for hint in hinted_paths):
                _candidate_for(candidates, workspace, path).add_score(20, f"PAC hint: {key}")


def _score_names(candidates: dict[str, Candidate], workspace: Path, files: list[Path], terms: list[str]) -> None:
    plain_terms = [term for term in terms if " " not in term]
    for path in files:
        rel = str(path.relative_to(workspace)).replace("\\", "/").lower()
        name = path.name.lower()
        candidate = _candidate_for(candidates, workspace, path)
        for term in plain_terms:
            token = term.replace(" ", "_")
            if token in name:
                candidate.add_score(12, f"filename contains {term}")
            elif token in rel:
                candidate.add_score(6, f"path contains {term}")


def _score_contents(candidates: dict[str, Candidate], workspace: Path, files: list[Path], terms: list[str]) -> None:
    plain_terms = [term for term in terms if " " not in term]
    phrase_terms = [term for term in terms if " " in term]
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        lower_lines = [line.lower() for line in lines]
        candidate = _candidate_for(candidates, workspace, path)
        for idx, line in enumerate(lower_lines, start=1):
            matched = False
            for phrase in phrase_terms:
                if phrase in line:
                    candidate.add_score(16, f"content contains phrase {phrase}")
                    matched = True
            for term in plain_terms:
                if term in line:
                    candidate.add_score(3, f"content contains {term}")
                    matched = True
            if matched:
                candidate.add_line(idx, lines[idx - 1] if idx - 1 < len(lines) else line)


def find_code_paths(session: Session, query: str, roots: list[str] | None = None, max_results: int = 12, max_files: int = 900) -> dict[str, Any]:
    workspace = Path(session.workspace_path).resolve()
    requested_roots = [str(root).strip() for root in (roots or []) if str(root).strip()]
    search_roots = requested_roots or list(_DEFAULT_ROOTS)
    terms = _normalize_query_terms(query)
    files = _iter_files(workspace, search_roots, max(50, min(max_files, 2500)))
    candidates: dict[str, Candidate] = {}
    _score_hints(candidates, workspace, files, terms)
    _score_names(candidates, workspace, files, terms)
    _score_contents(candidates, workspace, files, terms)
    ranked = sorted(candidates.values(), key=lambda item: (item.score, -len(item.path)), reverse=True)
    ranked = [item for item in ranked if item.score > 0][: max(1, min(max_results, 50))]
    return {
        "query": query,
        "roots": search_roots,
        "terms": terms,
        "searched_files": len(files),
        "count": len(ranked),
        "matches": [
            {"path": item.path, "score": item.score, "reasons": item.reasons[:8], "lines": item.lines}
            for item in ranked
        ],
        "next_step": "Read the top verified paths before answering. If matches are weak, retry with narrower intent words.",
    }


async def try_execute_code_locator_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    perm: Any,
) -> tuple[str, bool] | None:
    del config
    if tool != "find_code_paths":
        return None
    permission_guard = PermissionGuard(perm)
    if denied := permission_guard.require("file_read"):
        return denied
    query = str(inp.get("query") or "").strip()
    if not query:
        return "find_code_paths requires query", False
    roots_value = inp.get("roots")
    roots = [str(root) for root in roots_value] if isinstance(roots_value, list) else None
    result = find_code_paths(
        session,
        query=query,
        roots=roots,
        max_results=int(inp.get("max_results") or 12),
        max_files=int(inp.get("max_files") or 900),
    )
    AgentEvents(session, task).tool_result(
        tool="find_code_paths",
        message=f"located code paths for {query}",
        data={"query": query, "count": result.get("count"), "roots": result.get("roots")},
    )
    return json.dumps(result, indent=2), False
