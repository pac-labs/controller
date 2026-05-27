"""Auto-approve rules for safe operations — avoids blocking pauses for known-safe actions."""
from __future__ import annotations
import fnmatch
import re
from typing import Any

# Rules format: list of {"tool": "...", "path_pattern": "...", "command_pattern": "..."}
# All fields except one are None — match is OR across provided fields
DEFAULT_RULES: list[dict[str, Any]] = [
    # Safe git operations
    {"tool": "shell", "command_pattern": "git add *"},
    {"tool": "shell", "command_pattern": "git commit *"},
    {"tool": "shell", "command_pattern": "git status*"},
    {"tool": "shell", "command_pattern": "git diff*"},
    {"tool": "shell", "command_pattern": "git log*"},
    {"tool": "shell", "command_pattern": "git push*"},
    {"tool": "shell", "command_pattern": "git pull*"},
    {"tool": "shell", "command_pattern": "git stash*"},
    {"tool": "shell", "command_pattern": "git branch*"},
    {"tool": "shell", "command_pattern": "git checkout*"},
    # Safe read operations
    {"tool": "shell", "command_pattern": "cat *"},
    {"tool": "shell", "command_pattern": "head *"},
    {"tool": "shell", "command_pattern": "tail *"},
    {"tool": "shell", "command_pattern": "ls *"},
    {"tool": "shell", "command_pattern": "find *"},
    {"tool": "shell", "command_pattern": "grep *"},
    {"tool": "shell", "command_pattern": "rg *"},
    {"tool": "shell", "command_pattern": "fd *"},
    # Safe cargo/nix build operations
    {"tool": "shell", "command_pattern": "cargo *"},
    {"tool": "shell", "command_pattern": "nix *"},
    {"tool": "shell", "command_pattern": "podman *"},
    # Safe file reads
    {"tool": "read_file"},
    {"tool": "read_file_chunk"},
    {"tool": "ripgrep"},
    {"tool": "fd"},
    # Safe workspace ops
    {"tool": "workspace_manifest"},
    {"tool": "query_workspace_index"},
    {"tool": "find_code_paths"},
    {"tool": "git_status"},
    {"tool": "git_diff"},
    {"tool": "log_tail"},
    {"tool": "podman_ps"},
    {"tool": "wait_for"},
    {"tool": "shell_bg"},
    {"tool": "shell_bg_result"},
    {"tool": "shell_bg_stop"},
    # Safe save/artifact ops
    {"tool": "save_artifact"},
    {"tool": "list_artifacts"},
    # Safe consult/search
    {"tool": "consult_model"},
    {"tool": "lessons"},
    # Safe memory
    {"tool": "remote_memory", "mode": "get"},
    {"tool": "remote_memory", "mode": "search"},
    {"tool": "remote_memory", "mode": "bundle"},
]

DENY_RULES: list[dict[str, Any]] = [
    # Explicitly deny dangerous operations even if they'd match allow rules
    {"tool": "shell", "command_pattern": "*rm -rf /*"},
    {"tool": "shell", "command_pattern": "*dd if=*"},
    {"tool": "shell", "command_pattern": "*mkfs*"},
    {"tool": "shell", "command_pattern": ":(){:|:&};:*"},  # fork bomb
]


def _matches_rule(tool: str, inp: dict[str, Any], rule: dict[str, Any]) -> bool:
    """Check if a tool+input matches a rule. All non-None fields must match."""
    # Tool match
    if rule.get("tool") and rule["tool"] != tool:
        return False
    # Path pattern match
    if rule.get("path_pattern"):
        path = str(inp.get("path") or "")
        if not fnmatch.fnmatch(path, rule["path_pattern"]):
            return False
    # Command pattern match
    if rule.get("command_pattern"):
        command = str(inp.get("command") or "")
        if not fnmatch.fnmatch(command, rule["command_pattern"]):
            return False
    # Mode/key match
    if rule.get("mode"):
        mode = str(inp.get("mode") or "")
        if rule["mode"] != mode:
            return False
    return True


def should_auto_approve(tool: str, inp: dict[str, Any], extra_rules: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
    """
    Check if a pending tool call should be auto-approved.
    Returns (True, reason) if auto-approved, (False, "") if not.
    """
    all_rules = (extra_rules or []) + DEFAULT_RULES
    
    # Check deny rules first (they override allow rules)
    for rule in DENY_RULES:
        if _matches_rule(tool, inp, rule):
            return False, f"denied by rule: {rule}"
    
    # Check allow rules
    for rule in all_rules:
        if _matches_rule(tool, inp, rule):
            reason = f"auto-approved by rule: tool={rule.get('tool') or '*'}, command={rule.get('command_pattern') or '*'}"
            return True, reason
    
    return False, ""


def get_approval_rules() -> list[dict[str, Any]]:
    """Return current allow rules for inspection."""
    return DEFAULT_RULES.copy()
