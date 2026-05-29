from __future__ import annotations

import json
import re
from typing import Any

def _extract_wrapped_tool_call(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    match = re.search(r"<\|tool_call\>\s*call:((?:tool_call:)?[A-Za-z0-9_:-]+)\s*(.*?)\s*<tool_call\|>", raw, re.DOTALL)
    if not match:
        return None
    tool = str(match.group(1) or "").strip()
    if tool.startswith("tool_call:"):
        tool = tool.split("tool_call:", 1)[1].strip()
    if not tool:
        return None
    raw_input = _extract_balanced_jsonish(str(match.group(2) or "").strip())
    try:
        parsed_input = _load_loose_json_object(raw_input)
    except Exception:
        parsed_input = None
    if not isinstance(parsed_input, dict):
        return None
    inp = parsed_input.get("input") if isinstance(parsed_input.get("input"), dict) else parsed_input
    return {"type": "tool_call", "tool": tool, "input": inp}


def _extract_balanced_jsonish(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    start = -1
    opener = ""
    for idx, ch in enumerate(raw):
        if ch in "{[":
            start = idx
            opener = ch
            break
    if start < 0:
        return raw
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    return raw[start:]


def _load_loose_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    normalized = raw
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = "{" + normalized[1:-1].strip() + "}"
    normalized = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)', r'\1"\2"\3', normalized)
    normalized = normalized.replace("'", '"')
    normalized = re.sub(r':\s*True\b', ': true', normalized)
    normalized = re.sub(r':\s*False\b', ': false', normalized)
    normalized = re.sub(r':\s*None\b', ': null', normalized)
    def _quote_bare_value(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_value = str(match.group(2) or "")
        stripped = raw_value.strip()
        if not stripped:
            return prefix + raw_value
        if stripped[0] in '"{[':
            return prefix + raw_value
        if stripped in {"true", "false", "null"}:
            return prefix + stripped
        if re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
            return prefix + stripped
        return prefix + json.dumps(stripped)

    normalized = re.sub(r'(:\s*)([^"\{\[\],][^,\}\]]*)', _quote_bare_value, normalized)
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start >= 0 and end > start:
        candidate = normalized[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    wrapped = _extract_wrapped_tool_call(text)
    if wrapped:
        return wrapped
    decoder = json.JSONDecoder()
    actions: list[dict[str, Any]] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        if text[idx] != "{":
            idx += 1
            continue
        try:
            parsed, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(parsed, dict):
            actions.append(parsed)
        idx = end
    if actions:
        tool_action = next((action for action in actions if str(action.get("type") or "") == "tool_call"), None)
        if tool_action:
            return tool_action
        final_action = next((action for action in actions if str(action.get("type") or "") == "final"), None)
        if final_action:
            return final_action
        return actions[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        loose = _load_loose_json_object(text)
        if loose:
            return loose
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            loose = _load_loose_json_object(text[start : end + 1])
            if loose:
                return loose
            return json.loads(text[start : end + 1])
        raise


def _looks_like_wrapped_tool_markup(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return (
        "<|tool_call>" in raw
        or "<tool_call|>" in raw
        or '"type":"tool_call"' in raw
        or '"type": "tool_call"' in raw
        or "call:tool_call:" in raw
        or re.search(r"\bcall:[a-z0-9_:-]+\s*[\[{]", raw) is not None
    )

