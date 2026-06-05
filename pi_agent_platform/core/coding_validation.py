from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_FAILURE_MARKERS = (
    "traceback",
    "error:",
    "failed",
    "no tests ran",
    "no module named pytest",
    "command not found",
    "returned non-zero",
    "assertionerror",
)
_RESULT_MARKER = "__PAC_RESULT__="


@dataclass(frozen=True, slots=True)
class ValidationRequirement:
    mode: str
    command: str | None
    reason: str
    expected_output: str | None = None
    expected_expression: str | None = None
    expected_module: str | None = None

    @property
    def requires_runtime_check(self) -> bool:
        return self.mode in {"pytest", "python_call", "pytest_and_python_call"}


def infer_validation_requirement(prompt: str, transcript: list[dict[str, Any]] | None = None) -> ValidationRequirement:
    compact = " ".join(str(prompt or "").split())
    lowered = compact.lower()
    python_module = _best_python_module(compact, transcript or [])
    exact_call = _python_call_expectation(compact)

    if _requires_pytest(lowered):
        if exact_call and python_module:
            call_expr, expected_output = exact_call
            return ValidationRequirement(
                mode="pytest_and_python_call",
                command=_pytest_and_python_call_command(python_module, call_expr),
                reason="prompt_requires_pytest_and_exact_python_output",
                expected_output=expected_output,
                expected_expression=call_expr,
                expected_module=python_module,
            )
        return ValidationRequirement(
            mode="pytest",
            command="python3 -m pytest -q || python -m pytest -q",
            reason="prompt_requires_pytest_validation",
            expected_module=python_module,
        )

    if exact_call and python_module:
        call_expr, expected_output = exact_call
        return ValidationRequirement(
            mode="python_call",
            command=_python_call_command(python_module, call_expr),
            reason="prompt_requires_exact_python_output",
            expected_output=expected_output,
            expected_expression=call_expr,
            expected_module=python_module,
        )

    return ValidationRequirement(
        mode="inspection",
        command=None,
        reason="generic_change_request_can_fall_back_to_diff_inspection",
        expected_module=python_module,
    )


def is_validation_satisfied(
    *,
    tool: str,
    inp: dict[str, Any],
    observation: str,
    requirement: ValidationRequirement,
) -> bool:
    if requirement.mode == "inspection":
        if tool in {"git_diff", "git_status"}:
            return True
        return tool == "shell" and _shell_command_looks_like_validation(str((inp or {}).get("command") or ""), requirement)

    if tool != "shell":
        return False
    command = str((inp or {}).get("command") or "")
    if not _shell_command_looks_like_validation(command, requirement):
        return False
    if _looks_like_failed_validation(observation):
        return False
    if requirement.mode in {"python_call", "pytest_and_python_call"} and requirement.expected_output is not None:
        return _extract_marked_result(observation) == requirement.expected_output
    return True


def next_validation_action(requirement: ValidationRequirement) -> dict[str, Any]:
    if requirement.requires_runtime_check and requirement.command:
        return {
            "type": "tool_call",
            "tool": "shell",
            "input": {
                "command": requirement.command,
                "timeout_seconds": 120,
            },
        }
    return {"type": "tool_call", "tool": "git_diff", "input": {}}


def validation_metadata(requirement: ValidationRequirement) -> dict[str, Any]:
    return {
        "mode": requirement.mode,
        "reason": requirement.reason,
        "expected_module": requirement.expected_module,
        "expected_expression": requirement.expected_expression,
        "expected_output": requirement.expected_output,
        "command": requirement.command,
    }


def _requires_pytest(lowered_prompt: str) -> bool:
    return any(
        marker in lowered_prompt
        for marker in (
            "pytest",
            "test_",
            "make it pass",
            "make tests pass",
            "tests pass",
            "add test",
            "add tests",
        )
    )


def _python_call_expectation(prompt: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?P<call>[A-Za-z_][A-Za-z0-9_]*\([^)]*\))\s+returns?\s+exactly\s+(?P<quote>['\"])(?P<expected>.+?)(?P=quote)",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group("call"), repr(match.group("expected"))


def _best_python_module(prompt: str, transcript: list[dict[str, Any]]) -> str | None:
    paths = _python_paths(prompt, transcript)
    if not paths:
        return None
    best = sorted(paths, key=lambda item: ("/test_" in item or item.endswith("_test.py"), len(item)))[0]
    stem = best.rsplit("/", 1)[-1]
    if not stem.endswith(".py") or stem == "__init__.py":
        return None
    return stem[:-3]


def _python_paths(prompt: str, transcript: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(r"([A-Za-z0-9_./-]+\.py)\b", str(prompt or "")):
        found.add(match.group(1).replace("\\", "/"))
    for entry in transcript or []:
        if not isinstance(entry, dict):
            continue
        inp = entry.get("input") if isinstance(entry.get("input"), dict) else {}
        for key in ("path", "target", "file"):
            value = str(inp.get(key) or "").strip().replace("\\", "/")
            if value.endswith(".py"):
                found.add(value)
        observation = str(entry.get("observation") or "")
        for match in re.finditer(r"([A-Za-z0-9_./-]+\.py)\b", observation):
            found.add(match.group(1).replace("\\", "/"))
    return found


def _python_call_command(module_name: str, expression: str) -> str:
    func_name = expression.split("(", 1)[0].strip()
    return "\n".join(
        [
            "if command -v python3 >/dev/null 2>&1; then",
            "  PYTHON_BIN=python3",
            "else",
            "  PYTHON_BIN=python",
            "fi",
            '$PYTHON_BIN - <<\'PY\'',
            f"from {module_name} import {func_name}",
            f"print(\"{_RESULT_MARKER}\" + repr({expression}))",
            "PY",
        ]
    )


def _pytest_and_python_call_command(module_name: str, expression: str) -> str:
    func_name = expression.split("(", 1)[0].strip()
    return "\n".join(
        [
            "if command -v python3 >/dev/null 2>&1; then",
            "  PYTHON_BIN=python3",
            "else",
            "  PYTHON_BIN=python",
            "fi",
            "$PYTHON_BIN -m pytest -q",
            '$PYTHON_BIN - <<\'PY\'',
            f"from {module_name} import {func_name}",
            f"print(\"{_RESULT_MARKER}\" + repr({expression}))",
            "PY",
        ]
    )


def _shell_command_looks_like_validation(command: str, requirement: ValidationRequirement) -> bool:
    lowered = str(command or "").lower()
    if requirement.mode == "pytest":
        return "pytest" in lowered
    if requirement.mode in {"python_call", "pytest_and_python_call"}:
        if requirement.expected_expression and requirement.expected_expression.split("(", 1)[0].lower() in lowered:
            return True
        if requirement.expected_module and f"from {requirement.expected_module.lower()} import" in lowered:
            return True
        return "print(repr(" in lowered
    return any(marker in lowered for marker in ("git diff", "git status", "pytest", "py_compile", "ruff", "mypy"))


def _looks_like_failed_validation(observation: str) -> bool:
    lowered = str(observation or "").lower()
    return any(marker in lowered for marker in _FAILURE_MARKERS)


def _extract_marked_result(observation: str) -> str | None:
    for line in str(observation or "").splitlines():
        if line.startswith(_RESULT_MARKER):
            return line[len(_RESULT_MARKER):].strip()
    return None
