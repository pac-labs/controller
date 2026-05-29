from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


READ_ONLY_RECOVERY_TOOLS = {"workspace_manifest", "find_code_paths", "list_files", "ripgrep", "fd"}
MISSING_FILE_PREFIXES = (
    "file not found:",
    "path not found:",
    "no such file or directory",
    "not a file:",
)


@dataclass(slots=True)
class DoomLoopDecision:
    detected: bool = False
    reason: str = ""
    message: str = ""
    corrective_prompt: str = ""
    replacement_action: dict[str, Any] | None = None
    data: dict[str, Any] | None = None


def _stable_jsonish(value: Any, *, max_len: int = 600) -> str:
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            item = value.get(key)
            if isinstance(item, (dict, list, tuple)):
                item_text = _stable_jsonish(item, max_len=max_len)
            else:
                item_text = str(item)
            parts.append(f"{key}={item_text}")
        text = "|".join(parts)
    elif isinstance(value, (list, tuple)):
        text = ",".join(_stable_jsonish(item, max_len=max_len) for item in value)
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text.strip())
    return text[:max_len]


def _hash_input(inp: dict[str, Any]) -> str:
    text = _stable_jsonish(inp)
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _tool_family(tool: str) -> str:
    name = str(tool or "").strip()
    if name in {"read_file", "read_file_chunk", "batch_analyze_file"}:
        return "file_read"
    if name in {"workspace_manifest", "list_files", "find_code_paths", "ripgrep", "fd"}:
        return "discovery"
    if name in {"web_search", "web_fetch"}:
        return "web"
    if name in {"shell", "shell_bg", "pty_shell"}:
        return "shell"
    return name


def _missing_file_outcome(tool: str, observation: str) -> bool:
    if tool not in {"read_file", "read_file_chunk", "batch_analyze_file"}:
        return False
    text = str(observation or "").strip().lower()
    return any(text.startswith(prefix) or prefix in text[:500] for prefix in MISSING_FILE_PREFIXES)


def _outcome_class(tool: str, observation: str) -> str:
    text = str(observation or "").strip().lower()
    if _missing_file_outcome(tool, observation):
        return "missing_path"
    if not text:
        return "empty_result"
    if text.startswith("denied:") or "permission denied" in text[:500]:
        return "denied"
    if '"ok": false' in text[:1000] or text.startswith("error:") or text.startswith("failed:"):
        return "error"
    return "ok"


def _path_or_query(inp: dict[str, Any]) -> str:
    for key in ("path", "query", "pattern", "url", "command", "name"):
        value = str((inp or {}).get(key) or "").strip()
        if value:
            return value[:240]
    return ""


def record_tool_result(task: Any, *, step: int, tool: str, inp: dict[str, Any], observation: str) -> dict[str, Any]:
    """Append a compact tool/outcome fingerprint to task metadata."""

    metadata = task.metadata if isinstance(getattr(task, "metadata", None), dict) else {}
    history = list(metadata.get("doom_loop_history") or [])
    outcome = _outcome_class(tool, observation)
    family = _tool_family(tool)
    entry = {
        "step": step,
        "tool": str(tool or ""),
        "family": family,
        "outcome": outcome,
        "target": _path_or_query(inp),
        "input_hash": _hash_input(inp or {}),
        "fingerprint": f"{family}:{outcome}:{_hash_input(inp or {})}",
        "pattern_fingerprint": f"{family}:{outcome}",
    }
    history.append(entry)
    metadata["doom_loop_history"] = history[-24:]
    task.metadata = metadata
    return entry


def _prompt_query(prompt: str, fallback: str = "code paths") -> str:
    text = str(prompt or "").strip()
    if not text:
        return fallback
    text = re.sub(r"https?://\S+", " ", text)
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_\-]{2,}", text)
    stop = {
        "please", "could", "would", "should", "about", "check", "find", "what", "where", "with",
        "from", "this", "that", "into", "there", "using", "make", "create", "workspace", "session",
        "code", "repo", "repository", "source", "files", "project", "inspect", "read", "look",
    }
    picked = [word for word in words if word.lower() not in stop][:6]
    return " ".join(picked) if picked else fallback


def _recovery_action(prompt: str, history: list[dict[str, Any]], task: Any) -> dict[str, Any]:
    metadata = task.metadata if isinstance(getattr(task, "metadata", None), dict) else {}
    count = int(metadata.get("doom_loop_recovery_count") or 0)
    metadata["doom_loop_recovery_count"] = count + 1
    task.metadata = metadata
    if count % 3 == 0:
        return {"type": "tool_call", "tool": "workspace_manifest", "input": {}}
    if count % 3 == 1:
        return {"type": "tool_call", "tool": "find_code_paths", "input": {"query": _prompt_query(prompt)}}
    return {"type": "tool_call", "tool": "list_files", "input": {"path": ".", "max_depth": 3}}


def _same_pattern_triplet(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recent = history[-3:]
    if len(recent) < 3:
        return []
    patterns = [str(item.get("pattern_fingerprint") or "") for item in recent]
    if patterns[0] and patterns.count(patterns[0]) == 3:
        # OK reads can repeat legitimately across different files; focus on loops that stall.
        if str(recent[-1].get("outcome") or "") != "ok":
            return recent
    return []


def _same_exact_sequence(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(history) < 6:
        return []
    for size in (3, 2):
        tail = history[-(size * 3):]
        if len(tail) != size * 3:
            continue
        chunks = [tail[i * size:(i + 1) * size] for i in range(3)]
        signatures = [[str(item.get("pattern_fingerprint") or "") for item in chunk] for chunk in chunks]
        if signatures[0] and signatures[0] == signatures[1] == signatures[2]:
            return tail
    return []


def _missing_path_guess_loop(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recent = [item for item in history[-6:] if item.get("family") == "file_read" and item.get("outcome") == "missing_path"]
    if len(recent) < 3:
        return []
    targets = {str(item.get("target") or "") for item in recent[-3:]}
    return recent[-3:] if len(targets) >= 2 else []


def evaluate_after_tool_result(task: Any, *, prompt: str, step: int, tool: str, inp: dict[str, Any], observation: str) -> DoomLoopDecision:
    entry = record_tool_result(task, step=step, tool=tool, inp=inp or {}, observation=observation)
    history = list((task.metadata or {}).get("doom_loop_history") or [])
    matched = _missing_path_guess_loop(history)
    reason = "missing_path_guess_loop" if matched else ""
    if not matched:
        matched = _same_pattern_triplet(history)
        reason = "same_tool_outcome_triplet" if matched else ""
    if not matched:
        matched = _same_exact_sequence(history)
        reason = "repeated_tool_sequence" if matched else ""
    if not matched:
        return DoomLoopDecision(data={"entry": entry})

    replacement = _recovery_action(prompt, history, task)
    recovery_tool = replacement.get("tool") if isinstance(replacement, dict) else None
    data = {
        "reason": reason,
        "matched": matched,
        "last_tool": tool,
        "last_outcome": entry.get("outcome"),
        "recovery_tool": recovery_tool,
        "recovery_action": replacement,
        "timeline": {
            "title": "Doom loop detected",
            "summary": _reason_summary(reason),
            "fields": {
                "Reason": reason,
                "Last tool": tool,
                "Recovery": str(recovery_tool or "strategy change"),
            },
            "steps": [
                {"status": "warn", "label": item.get("tool"), "detail": f"{item.get('outcome')} · {item.get('target') or item.get('family')}"}
                for item in matched[-6:]
            ],
        },
    }
    return DoomLoopDecision(
        detected=True,
        reason=reason,
        message=_reason_summary(reason),
        corrective_prompt=_corrective_prompt(reason, replacement),
        replacement_action=replacement,
        data=data,
    )


def evaluate_before_tool_action(task: Any, *, prompt: str, action: dict[str, Any]) -> DoomLoopDecision:
    if not isinstance(action, dict) or action.get("type") != "tool_call":
        return DoomLoopDecision()
    tool = str(action.get("tool") or "")
    if tool in READ_ONLY_RECOVERY_TOOLS:
        return DoomLoopDecision()
    history = list((getattr(task, "metadata", {}) or {}).get("doom_loop_history") or [])
    if not history:
        return DoomLoopDecision()
    last = history[-1]
    # If a loop was just detected and the model tries to continue the same failing family,
    # override it with discovery instead of allowing another guessed path or repeated command.
    if int((task.metadata or {}).get("doom_loop_recovery_count") or 0) <= 0:
        return DoomLoopDecision()
    if _tool_family(tool) != str(last.get("family") or ""):
        return DoomLoopDecision()
    if str(last.get("outcome") or "") == "ok":
        return DoomLoopDecision()
    replacement = _recovery_action(prompt, history, task)
    return DoomLoopDecision(
        detected=True,
        reason="continued_after_doom_loop",
        message="The model tried to continue a repeated failing tool pattern, so PAC forced a discovery step.",
        corrective_prompt=_corrective_prompt("continued_after_doom_loop", replacement),
        replacement_action=replacement,
        data={
            "reason": "continued_after_doom_loop",
            "blocked_tool": tool,
            "last_outcome": last.get("outcome"),
            "recovery_action": replacement,
            "timeline": {
                "title": "Doom loop recovery enforced",
                "summary": "PAC blocked another repeated failing action and switched to a discovery tool.",
                "fields": {"Blocked tool": tool, "Recovery": str(replacement.get("tool") or "")},
            },
        },
    )


def _reason_summary(reason: str) -> str:
    if reason == "missing_path_guess_loop":
        return "The agent repeatedly tried missing guessed file paths. PAC is switching to workspace discovery."
    if reason == "same_tool_outcome_triplet":
        return "The same tool outcome repeated three times. PAC is forcing a different strategy."
    if reason == "repeated_tool_sequence":
        return "The same tool sequence repeated three times. PAC is forcing a different strategy."
    if reason == "continued_after_doom_loop":
        return "The agent tried to continue a known failing pattern. PAC is forcing recovery."
    return "PAC detected a repeated unproductive tool loop and is forcing recovery."


def _corrective_prompt(reason: str, replacement: dict[str, Any] | None) -> str:
    tool = str((replacement or {}).get("tool") or "workspace_manifest")
    return (
        f"Doom-loop recovery is active because {reason}. Do not repeat the failing action. "
        f"Use the recovery result from {tool}, then continue from verified evidence only. "
        "If file paths were missing, do not guess more paths; use workspace_manifest, find_code_paths, list_files, ripgrep, or fd first."
    )
