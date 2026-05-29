from __future__ import annotations

from typing import Any

from .pipeline_schema import FieldSpec, JsonKind, ToolSpec

_JSON_KIND_MAP: dict[str, JsonKind] = {
    "str": "string",
    "string": "string",
    "text": "string",
    "int": "integer",
    "integer": "integer",
    "number": "number",
    "float": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "object": "object",
    "dict": "object",
    "array": "array",
    "list": "array",
}


def _kind(raw: Any, default: JsonKind = "string") -> JsonKind:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    return _JSON_KIND_MAP.get(str(raw or "").strip().lower(), default)


def _field_from_schema(name: str, schema: dict[str, Any], required: set[str]) -> FieldSpec:
    enum_values = tuple(schema.get("enum") or schema.get("allowed_values") or ())
    item_kind = None
    items = schema.get("items")
    if isinstance(items, dict):
        item_kind = _kind(items.get("type"))
    elif isinstance(items, str):
        item_kind = _kind(items)
    return FieldSpec(
        _kind(schema.get("type") or schema.get("kind")),
        required=name in required or bool(schema.get("required")),
        min_value=schema.get("minimum", schema.get("min_value")),
        max_value=schema.get("maximum", schema.get("max_value")),
        min_length=schema.get("minLength", schema.get("min_length")),
        max_length=schema.get("maxLength", schema.get("max_length")),
        allowed_values=enum_values,
        item_kind=item_kind,
        allow_empty=bool(schema.get("allow_empty", not (name in required))),
    )


def _field_from_shorthand(name: str, raw: Any, required: set[str]) -> FieldSpec:
    if isinstance(raw, str):
        return FieldSpec(_kind(raw), required=name in required, allow_empty=not (name in required))
    if isinstance(raw, dict):
        return _field_from_schema(name, raw, required)
    return FieldSpec("string", required=name in required, allow_empty=not (name in required))


def _schema_dict(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("argument_schema"), dict):
        return raw["argument_schema"]
    if isinstance(raw.get("input_schema"), dict):
        return raw["input_schema"]
    if isinstance(raw.get("schema"), dict):
        return raw["schema"]
    return raw


def _spec_from_schema(tool: str, raw_schema: Any) -> ToolSpec | None:
    schema = _schema_dict(raw_schema)
    if not schema:
        return None
    required = set(str(item) for item in (schema.get("required") or ()))
    raw_properties = schema.get("properties") or schema.get("fields") or {}
    if not isinstance(raw_properties, dict):
        return None
    fields = {name: _field_from_shorthand(name, value, required) for name, value in raw_properties.items()}
    allow_extra = bool(schema.get("additionalProperties", schema.get("allow_extra", True)))
    any_of = tuple(tuple(str(item) for item in group) for group in (schema.get("any_of") or schema.get("anyOf") or ()))
    one_of = tuple(tuple(str(item) for item in group) for group in (schema.get("one_of") or schema.get("oneOf") or ()))
    return ToolSpec(tool, fields, allow_extra=allow_extra, any_of=any_of, one_of=one_of)


def dynamic_tool_spec(tool: str, config: Any | None) -> ToolSpec | None:
    if config is None:
        return None
    tool_cfg = getattr(config, "tools", {}).get(tool) if getattr(config, "tools", None) else None
    if tool_cfg is not None:
        spec = _spec_from_schema(tool, getattr(tool_cfg, "argument_schema", None))
        if spec is not None:
            return spec
    for plugin in getattr(config, "plugins", {}).values():
        if not getattr(plugin, "enabled", True):
            continue
        tools = getattr(plugin, "tools", {}) or {}
        raw = tools.get(tool) if isinstance(tools, dict) else None
        spec = _spec_from_schema(tool, raw)
        if spec is not None:
            return spec
    return None
