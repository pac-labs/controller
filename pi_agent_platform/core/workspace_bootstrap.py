from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .models import Session


class WorkspaceBootstrapError(RuntimeError):
    """Raised when a session workspace cannot be prepared safely."""


def ensure_workspace_materialized(session: Session) -> dict[str, Any]:
    """Create or clone the workspace backing a session.

    Session creation paths and tool execution both use this helper so a git
    workspace created by the controller agent is immediately usable by the
    resulting programming session, even when the session was created outside
    the public HTTP route.
    """

    path = Path(session.workspace_path).expanduser()
    workspace = session.workspace
    url = str(getattr(workspace, "url", None) or "").strip()
    branch = str(getattr(workspace, "branch", None) or "").strip()
    workspace_type = str(getattr(workspace, "type", "local") or "local").strip().lower()

    if not _requires_git_materialization(workspace_type, url):
        path.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "action": "mkdir", "path": str(path), "workspace_type": workspace_type}

    return _ensure_git_clone(path=path, url=url, branch=branch or None, workspace_type=workspace_type)


def _requires_git_materialization(workspace_type: str, url: str) -> bool:
    if not url:
        return False
    return workspace_type in {"git", "profile"}


def _ensure_git_clone(*, path: Path, url: str, branch: str | None, workspace_type: str) -> dict[str, Any]:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    if (path / ".git").exists():
        return {"ok": True, "action": "already_cloned", "path": str(path), "url": url, "workspace_type": workspace_type}

    if path.exists() and any(path.iterdir()):
        raise WorkspaceBootstrapError(
            f"Workspace path is not empty and is not a git checkout: {path}. "
            "Choose an empty path or remove the existing contents before cloning."
        )

    path.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone"]
    if branch:
        command += ["--branch", branch]
    command += [url, str(path)]

    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=180)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git clone failed").strip()
        raise WorkspaceBootstrapError(detail)

    return {
        "ok": True,
        "action": "git_clone",
        "path": str(path),
        "url": url,
        "branch": branch,
        "workspace_type": workspace_type,
        "stdout": (result.stdout or "")[-4000:],
        "stderr": (result.stderr or "")[-4000:],
    }
