from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


INSPECTION_TOOLS = {"workspace_manifest", "find_code_paths", "ripgrep", "fd", "list_files"}
READ_TOOLS = {"read_file", "read_file_chunk", "batch_analyze_file"}
MUTATING_TOOLS = {"write_file", "edit_file"}
VALIDATION_TOOLS = {"shell", "git_diff", "git_status"}


@dataclass(frozen=True, slots=True)
class ContractDecision:
    allow: bool
    replacement_action: dict[str, Any] | None = None
    corrective_prompt: str = ""
    reason: str = "allowed"
    event_message: str = ""
    event_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContractState:
    applies: bool
    has_manifest: bool
    has_locator_or_search: bool
    has_source_read: bool
    has_mutation: bool
    has_validation_after_mutation: bool
    best_path: str | None
    query: str


def is_code_change_contract_request(prompt: str) -> bool:
    compact = " ".join(str(prompt or "").lower().split())
    if not compact:
        return False
    prefixes = (
        "add ",
        "please add ",
        "can you add ",
        "could you add ",
        "implement ",
        "please implement ",
        "fix ",
        "please fix ",
        "change ",
        "please change ",
        "update ",
        "please update ",
        "wire ",
        "persist ",
        "store ",
        "save ",
        "make it ",
        "make the ",
        "allow ",
        "enable ",
    )
    if compact.startswith(prefixes):
        return True
    verbs = ("add ", "implement ", "fix ", "change ", "update ", "persist ", "store ", "save ", "wire ")
    targets = (
        " so we can ",
        " in there",
        " code",
        " file",
        " route",
        " api",
        " ui",
        " event",
        " events",
        " session",
        " component",
        " function",
        " class",
        " json",
    )
    return any(verb in compact for verb in verbs) and any(target in compact for target in targets)


def evaluate_tool_action(prompt: str, transcript: list[dict[str, Any]], action: dict[str, Any]) -> ContractDecision:
    """Gate PAC code-change actions through an inspect -> locate -> read -> mutate flow.

    This is intentionally small and deterministic. It does not try to decide how
    to implement a feature; it only prevents the loop from skipping grounding
    steps that protect PAC/core from guessed paths and shallow edits.
    """
    state = inspect_contract_state(prompt, transcript)
    if not state.applies:
        return ContractDecision(allow=True)

    tool = str((action or {}).get("tool") or "")
    inp = (action or {}).get("input") if isinstance((action or {}).get("input"), dict) else {}

    if not state.has_manifest and tool != "workspace_manifest":
        return _replace(
            {"type": "tool_call", "tool": "workspace_manifest", "input": {"max_files": 300}},
            reason="contract_requires_manifest_first",
            message="Code-change contract forced an initial workspace manifest before other work.",
            state=state,
        )

    if state.has_manifest and not state.has_locator_or_search and tool not in {"find_code_paths", "ripgrep", "fd"}:
        return _replace(
            {"type": "tool_call", "tool": "find_code_paths", "input": {"query": state.query, "max_results": 12}},
            reason="contract_requires_code_locator",
            message="Code-change contract forced code-location search before opening or editing files.",
            state=state,
        )

    if _is_mutating_tool(tool, inp) and not state.has_source_read:
        if state.best_path:
            return _replace(
                {"type": "tool_call", "tool": "read_file", "input": {"path": state.best_path}},
                reason="contract_requires_read_before_mutation",
                message="Code-change contract forced reading a verified source file before mutation.",
                state=state,
            )
        return _reject(
            "Read at least one relevant source file from the verified search results before editing. "
            "Return one read_file tool_call for the most relevant matched path.",
            reason="contract_requires_verified_read_before_mutation",
            message="Code-change contract rejected mutation before a verified source file was read.",
            state=state,
        )

    return ContractDecision(allow=True)


def evaluate_final(prompt: str, transcript: list[dict[str, Any]]) -> ContractDecision:
    state = inspect_contract_state(prompt, transcript)
    if not state.applies:
        return ContractDecision(allow=True)
    if not state.has_manifest:
        return _replace(
            {"type": "tool_call", "tool": "workspace_manifest", "input": {"max_files": 300}},
            reason="contract_final_requires_manifest",
            message="Final answer blocked until the workspace manifest has grounded the code-change request.",
            state=state,
        )
    if not state.has_locator_or_search:
        return _replace(
            {"type": "tool_call", "tool": "find_code_paths", "input": {"query": state.query, "max_results": 12}},
            reason="contract_final_requires_locator",
            message="Final answer blocked until relevant code paths have been located.",
            state=state,
        )
    if not state.has_source_read:
        if state.best_path:
            return _replace(
                {"type": "tool_call", "tool": "read_file", "input": {"path": state.best_path}},
                reason="contract_final_requires_source_read",
                message="Final answer blocked until a verified source file has been read.",
                state=state,
            )
        return _reject(
            "Read at least one matched source file before finalizing this PAC code-change request.",
            reason="contract_final_requires_verified_source_read",
            message="Final answer rejected because no verified source file has been read.",
            state=state,
        )
    if not state.has_mutation:
        return _reject(
            "This is a code-change request. Perform the implementation with write_file, edit_file, or a scoped shell edit before finalizing.",
            reason="contract_final_requires_mutation",
            message="Final answer rejected because no mutation has been performed.",
            state=state,
        )
    if not state.has_validation_after_mutation:
        return _replace(
            {"type": "tool_call", "tool": "git_diff", "input": {}},
            reason="contract_final_requires_validation",
            message="Final answer blocked until the change has been validated or at least inspected with git diff.",
            state=state,
        )
    return ContractDecision(allow=True)


def inspect_contract_state(prompt: str, transcript: list[dict[str, Any]]) -> ContractState:
    applies = is_code_change_contract_request(prompt)
    has_manifest = False
    has_locator_or_search = False
    has_source_read = False
    has_mutation = False
    mutation_index: int | None = None
    validation_after_mutation = False
    best_path: str | None = None

    for idx, entry in enumerate(transcript or []):
        if not isinstance(entry, dict):
            continue
        tool = str(entry.get("tool") or "")
        inp = entry.get("input") if isinstance(entry.get("input"), dict) else {}
        observation = str(entry.get("observation") or "")

        if tool == "workspace_manifest":
            has_manifest = True
        if tool in {"find_code_paths", "ripgrep", "fd"}:
            has_locator_or_search = True
            best_path = best_path or _best_path_from_observation(tool, observation)
        if tool in READ_TOOLS and _read_path(inp):
            has_source_read = True
            best_path = best_path or _read_path(inp)
        if _is_mutating_tool(tool, inp):
            has_mutation = True
            mutation_index = idx if mutation_index is None else mutation_index
        if mutation_index is not None and idx > mutation_index and _is_validation_tool(tool, inp):
            validation_after_mutation = True

    return ContractState(
        applies=applies,
        has_manifest=has_manifest,
        has_locator_or_search=has_locator_or_search,
        has_source_read=has_source_read,
        has_mutation=has_mutation,
        has_validation_after_mutation=validation_after_mutation,
        best_path=best_path,
        query=_query_from_prompt(prompt),
    )


def _replace(action: dict[str, Any], *, reason: str, message: str, state: ContractState) -> ContractDecision:
    return ContractDecision(
        allow=False,
        replacement_action=action,
        reason=reason,
        event_message=message,
        event_data={"contract_state": _state_data(state), "action": action},
    )


def _reject(prompt: str, *, reason: str, message: str, state: ContractState) -> ContractDecision:
    return ContractDecision(
        allow=False,
        corrective_prompt=prompt,
        reason=reason,
        event_message=message,
        event_data={"contract_state": _state_data(state)},
    )


def _state_data(state: ContractState) -> dict[str, Any]:
    return {
        "has_manifest": state.has_manifest,
        "has_locator_or_search": state.has_locator_or_search,
        "has_source_read": state.has_source_read,
        "has_mutation": state.has_mutation,
        "has_validation_after_mutation": state.has_validation_after_mutation,
        "best_path": state.best_path,
        "query": state.query,
    }


def _query_from_prompt(prompt: str) -> str:
    text = " ".join(str(prompt or "").strip().split())
    if not text:
        return "PAC code change"
    text = re.sub(r"^(please\s+|can you\s+|could you\s+)?(add|implement|fix|change|update|wire|persist|store|save|make|allow|enable)\s+", "", text, flags=re.IGNORECASE)
    return text[:160] or "PAC code change"


def _best_path_from_observation(tool: str, observation: str) -> str | None:
    try:
        payload = json.loads(observation)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        if tool == "find_code_paths":
            matches = payload.get("matches")
            if isinstance(matches, list):
                for item in matches:
                    if isinstance(item, dict) and item.get("path"):
                        return str(item.get("path"))
        if tool == "ripgrep":
            matches = payload.get("matches")
            base = str(payload.get("path") or ".").strip("/.")
            if isinstance(matches, list):
                for item in matches:
                    if isinstance(item, dict) and item.get("file"):
                        file_path = str(item.get("file"))
                        return f"{base}/{file_path}" if base else file_path
        if tool == "fd":
            results = payload.get("results")
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and item.get("type") == "file" and item.get("name"):
                        return str(item.get("name"))
    return None


def _read_path(inp: dict[str, Any]) -> str | None:
    path = str((inp or {}).get("path") or "").strip()
    return path or None


def _is_mutating_tool(tool: str, inp: dict[str, Any]) -> bool:
    if tool in MUTATING_TOOLS:
        return True
    if tool != "shell":
        return False
    command = str((inp or {}).get("command") or "").strip().lower()
    return command.startswith(("python ", "python3 ", "perl ", "sed -i", "cat >", "tee ", "git apply"))


def _is_validation_tool(tool: str, inp: dict[str, Any]) -> bool:
    if tool in {"git_diff", "git_status"}:
        return True
    if tool != "shell":
        return False
    command = str((inp or {}).get("command") or "").strip().lower()
    validation_markers = ("pytest", "ruff", "mypy", "npm test", "npm run", "python -m py_compile", "python3 -m py_compile", "git diff", "git status")
    return any(marker in command for marker in validation_markers)
