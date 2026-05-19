"""Auto-commit hook — commits changes when a task completes with modifications."""
from __future__ import annotations
import subprocess
import os
from pathlib import Path
from typing import Any


def get_git_changes(workspace_path: str | None) -> dict[str, Any]:
    """Get git status and diff stats for the workspace."""
    if not workspace_path:
        return {"has_changes": False, "error": "no workspace"}
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        staged = subprocess.run(
            ["git", "diff", "--staged", "--stat"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw_status = status.stdout or ""
        has_changes = bool(raw_status.strip())
        changed_files = [line.strip() for line in raw_status.strip().splitlines() if line.strip()]
        return {
            "has_changes": has_changes,
            "changed_files": changed_files,
            "changed_count": len(changed_files),
            "staged": staged.stdout.strip(),
            "unstaged": unstaged.stdout.strip(),
            "untracked": untracked.stdout.strip(),
            "raw": raw_status,
        }
    except Exception as e:
        return {"has_changes": False, "error": str(e)}


def get_task_commit_message(workspace_path: str, task_prompt: str, changed_files: list[str]) -> str:
    """Generate a reasonable commit message from task context."""
    # Grab the first sentence of the task prompt
    prompt_clean = task_prompt.strip().replace("\n", " ")[:200]
    files_desc = ", ".join(changed_files[:8])
    if len(changed_files) > 8:
        files_desc += f" and {len(changed_files) - 8} more"

    # Try to infer what changed from git diff --stat
    try:
        diff_stat = subprocess.run(
            ["git", "diff", "--stat", "--format=''"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stat_lines = [l.strip() for l in (diff_stat.stdout or "").splitlines() if l.strip() and "|" in l]
        if stat_lines:
            stat_desc = "; ".join(stat_lines[:5])
        else:
            stat_desc = files_desc
    except Exception:
        stat_desc = files_desc

    return f"Task: {prompt_clean}\n\nChanged: {stat_desc}"


def auto_commit(workspace_path: str | None, task_prompt: str, task_id: str, commit_message: str | None = None) -> dict[str, Any]:
    """
    Run git add -A + git commit if there are changes.
    Returns dict with commit info or error.
    """
    if not workspace_path:
        return {"committed": False, "error": "no workspace"}

    changes = get_git_changes(workspace_path)
    if not changes.get("has_changes"):
        return {"committed": False, "reason": "no changes"}

    changed_files = changes.get("changed_files", [])
    msg = commit_message or get_task_commit_message(workspace_path, task_prompt, changed_files)

    try:
        # git add -A
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if add_result.returncode != 0:
            return {"committed": False, "error": f"git add failed: {add_result.stderr}"}

        # git commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if commit_result.returncode != 0:
            return {"committed": False, "error": f"git commit failed: {commit_result.stderr}"}

        commit_output = commit_result.stdout.strip()
        # Extract commit SHA from output like "1 file changed, 2 insertions(+)"
        sha = ""
        try:
            log_result = subprocess.run(
                ["git", "log", "-1", "--format=%H %s"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if log_result.returncode == 0:
                parts = log_result.stdout.strip().split(" ", 1)
                if parts:
                    sha = parts[0][:12]
        except Exception:
            pass

        return {
            "committed": True,
            "message": msg,
            "sha": sha,
            "changed_files": changed_files,
            "output": commit_output,
        }
    except Exception as e:
        return {"committed": False, "error": str(e)}


def auto_push(workspace_path: str | None) -> dict[str, Any]:
    """Try to git push after auto-commit. Fails gracefully if no remote."""
    if not workspace_path:
        return {"pushed": False, "error": "no workspace"}
    try:
        push_result = subprocess.run(
            ["git", "push"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if push_result.returncode != 0:
            return {"pushed": False, "error": push_result.stderr.strip()}
        return {"pushed": True, "output": push_result.stdout.strip()}
    except Exception as e:
        return {"pushed": False, "error": str(e)}
