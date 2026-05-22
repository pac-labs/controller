from __future__ import annotations

from typing import Any


def prompt_requests_codebase_inspection(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    keywords = [
        "codebase",
        "repo",
        "repository",
        "workspace",
        "source",
        "entrypoint",
        "entry point",
        "look at the code",
        "find the code",
        "inspect the code",
        "main app",
        "where is",
        "how does",
        "what file",
        "which file",
    ]
    return any(keyword in text for keyword in keywords)


def has_meaningful_codebase_inspection(transcript: list[dict[str, Any]]) -> bool:
    deep_tools = {"workspace_manifest", "read_file", "read_file_chunk", "batch_analyze_file", "git_diff", "git_status", "shell"}
    used = [str(item.get("tool") or "") for item in transcript if item.get("tool")]
    if any(tool in deep_tools for tool in used):
        return True
    # A bare top-level listing is not enough for architecture / entrypoint answers.
    if used.count("list_files") >= 2:
        return True
    return False


def looks_like_generic_ready_response(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    markers = (
        "i am ready to proceed",
        "please provide the specific task",
        "please provide the next task",
        "ready to operate",
        "the provided context details",
        "the platform capabilities",
        "i maintain full context",
    )
    return any(marker in raw for marker in markers)


def is_broad_codebase_request(prompt: str) -> bool:
    text = str(prompt or "").lower()
    if not text:
        return False
    broad_signals = [
        "look at the code",
        "look at the codebase",
        "look at pac",
        "scan the workspace",
        "inspect the workspace",
        "what is in",
        "what does this repo",
        "understand the codebase",
        "find the source",
        "where stuff is",
    ]
    return any(signal in text for signal in broad_signals)


def inspection_depth_score(transcript: list[dict[str, Any]]) -> float:
    score = 0.0
    for item in transcript:
        tool = str(item.get("tool") or "")
        if tool == "workspace_manifest":
            score += 2.0
        elif tool in {"git_status", "git_diff", "batch_analyze_file", "batch_analyze_text"}:
            score += 1.5
        elif tool == "shell":
            command = str((item.get("input") or {}).get("command") or "")
            if any(term in command for term in ("rg ", "grep ", "find ", "fd ")):
                score += 2.0
            else:
                score += 1.0
        elif tool == "read_file":
            path = str((item.get("input") or {}).get("path") or "").lower()
            if path.endswith(("readme.md", "readme", ".md", ".adoc")):
                score += 0.5
            else:
                score += 1.25
        elif tool == "read_file_chunk":
            score += 1.0
        elif tool == "list_files":
            score += 0.5
    return score
