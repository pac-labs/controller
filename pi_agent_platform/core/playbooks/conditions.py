from __future__ import annotations

from typing import Any

from .schema import PlaybookCondition, PlaybookRun, PlaybookStep


def _value_at(data: Any, path: str | None) -> Any:
    if not path:
        return None
    current = data
    for part in path.split('.'):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


def _step_statuses(run: PlaybookRun) -> dict[str, str]:
    return {step.id: step.status for step in run.steps}


def condition_passes(condition: PlaybookCondition | None, run: PlaybookRun) -> bool:
    if not condition:
        return True
    if condition.all and not all(condition_passes(item, run) for item in condition.all):
        return False
    if condition.any and not any(condition_passes(item, run) for item in condition.any):
        return False
    if condition.not_condition and condition_passes(condition.not_condition, run):
        return False
    if condition.status:
        statuses = _step_statuses(run)
        for step_id, expected in condition.status.items():
            if statuses.get(step_id) != expected:
                return False
    if condition.present and not _value_at(run.parameters, condition.present):
        return False
    if condition.absent and _value_at(run.parameters, condition.absent):
        return False
    value = None
    if condition.param:
        value = _value_at(run.parameters, condition.param)
    elif condition.output:
        value = _value_at(run.outputs, condition.output)
    if condition.equals is not None and value != condition.equals:
        return False
    if condition.not_equals is not None and value == condition.not_equals:
        return False
    if condition.contains is not None:
        if isinstance(value, (list, tuple, set)) and condition.contains not in value:
            return False
        if isinstance(value, str) and str(condition.contains) not in value:
            return False
        if not isinstance(value, (list, tuple, set, str)):
            return False
    return True


def step_condition_passes(step: PlaybookStep, run: PlaybookRun) -> bool:
    return condition_passes(step.when, run)
