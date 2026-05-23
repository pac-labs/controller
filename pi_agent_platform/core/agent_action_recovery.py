from __future__ import annotations

import re
from typing import Any

from .config import AppConfig
from .models import Session, Task

def _summarize_tool_intent(tool: str, inp: dict[str, Any]) -> str:
    tool = str(tool or "")
    inp = inp or {}
    if tool == "shell":
        return f"Preparing command: {str(inp.get('command') or '').strip() or 'shell'}"
    if tool == "read_file":
        return f"Reading {inp.get('path') or 'file'}"
    if tool == "read_file_chunk":
        return f"Reading chunk from {inp.get('path') or 'file'}"
    if tool == "list_files":
        return f"Listing {inp.get('path') or '.'}"
    if tool == "write_file":
        return f"Writing {inp.get('path') or 'file'}"
    if tool == "workspace_manifest":
        return "Scanning workspace structure"
    if tool == "printing_press":
        return f"Running Printing Press on {inp.get('path') or 'workspace'}"
    if tool == "batch_analyze_text":
        return f"Analyzing text: {str(inp.get('instruction') or 'batch analysis')[:120]}"
    if tool == "batch_analyze_file":
        return f"Analyzing {inp.get('path') or 'file'}"
    if tool == "web_search":
        return f"Searching the web for {inp.get('query') or 'results'}"
    if tool == "web_fetch":
        return f"Fetching {inp.get('url') or 'page'}"
    if tool == "save_artifact":
        return f"Saving artifact {inp.get('name') or ''}".strip()
    if tool == "list_artifacts":
        return "Checking saved artifacts"
    if tool == "slash_command":
        return f"Running {inp.get('command') or 'slash command'}"
    if tool == "git_status":
        return "Checking git status"
    if tool == "git_diff":
        return "Checking git diff"
    return f"Using {tool}"


def _summarize_model_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    action = action or {}
    kind = str(action.get("type") or "")
    if kind == "tool_call":
        tool = str(action.get("tool") or "")
        inp = action.get("input") or {}
        return _summarize_tool_intent(tool, inp), {"action_type": kind, "tool": tool, "input": inp}
    if kind == "final":
        # The visible session timeline already renders the final answer as its own
        # assistant message. Keep the intent row as process metadata so the UI
        # does not show the same answer twice as both a status update and a reply.
        return "Prepared a final answer", {"action_type": kind}
    return "Re-evaluating next step", {"action_type": kind or "unknown"}


def _looks_like_unexecuted_consult_request(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return (
        "consult_model" in raw
        or "consult model" in raw
        or "use the consult" in raw
        or "using consult" in raw
        or "ask another model" in raw
        or "second opinion" in raw
    ) and (
        "generate" in raw
        or "plan" in raw
        or "review" in raw
        or "continue" in raw
        or "next step" in raw
        or "extensive" in raw
    )


def _consult_prompt_from_final_message(task_prompt: str, final_message: str) -> str:
    original = str(task_prompt or "").strip()
    final = str(final_message or "").strip()
    pieces = []
    if original:
        pieces.append("Original user request:\n" + original)
    if final:
        pieces.append("The primary model requested consultation instead of completing the work:\n" + final)
    pieces.append(
        "Provide concise, actionable guidance that the primary PAC agent can use immediately. "
        "If approval is needed, say so directly. Do not return tool-call JSON."
    )
    return "\n\n".join(pieces)


def _infer_tool_call_from_action_narration(text: str, session: Session, task: Task, config: AppConfig) -> dict[str, Any] | None:
    """Best-effort conversion of obvious action prose into an executable PAC tool call.

    Some local models keep returning natural language such as "I will inspect the
    workspace" even after being told to emit tool_call JSON. That should not stop
    the loop. For clearly actionable controller/workspace phrasing, choose the
    safest read-only first step and let the normal loop continue from the result.
    """
    raw_text = str(text or "").strip()
    raw = raw_text.lower()
    if not raw:
        return None

    configured_tools = getattr(session, "tools", None) or list(getattr(config, "tools", {}).keys())
    allowed = {str(tool) for tool in configured_tools if str(tool or "").strip()}

    def can(tool: str) -> bool:
        return not allowed or tool in allowed

    if _looks_like_unexecuted_consult_request(raw_text) and can("consult_model"):
        return {
            "type": "tool_call",
            "tool": "consult_model",
            "input": {
                "prompt": _consult_prompt_from_final_message(task.prompt or "", raw_text),
                "include_recent_context": True,
                "max_tokens": 1400,
            },
        }

    workspace_words = (
        "workspace", "codebase", "project", "source", "files", "relevant files",
        "current pac", "pac workspace", "integration files", "ldap", "ad/ldap",
    )
    inspect_words = (
        "inspect", "re-examine", "examine", "check", "scan", "look at", "review",
        "list", "find", "read", "open",
    )
    if any(word in raw for word in workspace_words) and any(word in raw for word in inspect_words):
        if can("workspace_manifest"):
            return {"type": "tool_call", "tool": "workspace_manifest", "input": {"max_files": 300}}
        if can("list_files"):
            return {"type": "tool_call", "tool": "list_files", "input": {"path": "."}}

    search_match = re.search(
        r"\b(?:search|find|grep|ripgrep|look\s+for)\s+(?:for\s+)?[\"'`]?([^\"'`\n.]{2,80})",
        raw_text,
        re.IGNORECASE,
    )
    if search_match and can("ripgrep"):
        query = search_match.group(1).strip()
        query = re.sub(r"\s+(?:in|under|inside|across)\s+(?:the\s+)?(?:workspace|codebase|project|source|files?)$", "", query, flags=re.IGNORECASE).strip()
        if query:
            return {"type": "tool_call", "tool": "ripgrep", "input": {"query": query, "path": ".", "max_results": 200}}

    list_match = re.search(r"\b(?:list|show)\s+(?:the\s+)?(?:files|tree|directory|workspace)", raw, re.IGNORECASE)
    if list_match and can("list_files"):
        return {"type": "tool_call", "tool": "list_files", "input": {"path": "."}}

    if "git status" in raw and can("git_status"):
        return {"type": "tool_call", "tool": "git_status", "input": {}}
    if "git diff" in raw and can("git_diff"):
        return {"type": "tool_call", "tool": "git_diff", "input": {}}

    file_match = re.search(r"\b(?:read|open|inspect|check|review)\s+([A-Za-z0-9_./\\-]+\.(?:py|js|ts|json|ya?ml|toml|md|adoc|txt|css|html))\b", raw_text, re.IGNORECASE)
    if file_match and can("read_file"):
        return {"type": "tool_call", "tool": "read_file", "input": {"path": file_match.group(1)}}

    task_text = str(task.prompt or "").lower()
    actionable_task_words = (
        "investigate", "debug", "fix", "patch", "change", "update", "implement",
        "inspect", "look at", "analyze", "why", "slow", "stuck", "broken", "not doing",
    )
    if session.workspace_path and (
        any(word in raw for word in ("plan", "patch", "modify", "update", "implement", "fix", "configure", "do this", "do that", "handle this"))
        or any(word in task_text for word in actionable_task_words)
    ):
        if can("workspace_manifest"):
            return {"type": "tool_call", "tool": "workspace_manifest", "input": {"max_files": 300}}
        if can("list_files"):
            return {"type": "tool_call", "tool": "list_files", "input": {"path": "."}}

    return None


def _default_consult_models(config: AppConfig, session_model: str | None, limit: int = 2) -> list[str]:
    configured = config.models or {}
    preferred: list[str] = []
    fallback: list[str] = []
    session_model = str(session_model or "").strip()
    for name, model in configured.items():
        if not name or name == session_model:
            continue
        caps = getattr(model, "capabilities", None)
        reasoning = str(getattr(caps, "reasoning", "none") or "none")
        if reasoning in {"medium", "high"} or any(marker in name.lower() for marker in ("think", "reason", "planner", "consult")):
            preferred.append(name)
        else:
            fallback.append(name)
    chosen = (preferred + fallback)[:max(0, limit)]
    if chosen:
        return chosen
    if session_model and session_model in configured:
        return [session_model]
    return list(configured.keys())[:1]


def _looks_like_action_narration(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    signals = (
        "i will ",
        "i'll ",
        "i am going to ",
        "i'm going to ",
        "i am running ",
        "i'm running ",
        "i will use ",
        "i will perform ",
        "i will search ",
        "i will inspect ",
        "i will scan ",
        "i will list ",
        "i will read ",
        "i will do ",
        "i'll do ",
        "i need to ",
        "i should ",
        "i can start by ",
        "i would start by ",
        "i would inspect ",
        "let me ",
        "next i will ",
        "we need to ",
        "we should ",
    )
    if not any(signal in raw for signal in signals):
        return False
    action_verbs = (
        "inspect", "read", "list", "open", "search", "scan", "run", "execute",
        "modify", "update", "write", "patch", "create", "apply", "check",
        "plan", "prepare", "implement", "fix", "adjust", "change", "configure",
        "do", "handle", "proceed", "start", "continue",
        "use consult_model", "consult", "call", "investigate", "review", "look at",
    )
    if any(verb in raw for verb in action_verbs):
        return True
    # Catch natural-language planning statements such as
    # "I need to plan a patch for ..." even when the exact implementation verb
    # is not near the initial action signal.
    return re.search(r"\b(i|we)\s+(need|should|will|would|can)\s+to\s+[^.]{0,160}\b(plan|patch|fix|modify|update|implement|inspect|check|review|configure)\b", raw) is not None


def _should_reject_unformatted_action(session: Session, task: Task, text: str, transcript: list[dict[str, Any]]) -> bool:
    """Return True when model prose is clearly an intended action, not an answer.

    Local/controller sessions should act through structured tool calls. If a model says
    it will inspect, patch, run, consult, or configure something but does not emit the
    tool_call JSON, treating that prose as a final answer creates dead-end sessions.
    """
    return _looks_like_action_narration(text)

