from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..config import AppConfig, ToolConfig
from .pipeline_schema import TOOL_SPECS

_SCHEMA_KEYS = {"argument_schema", "input_schema", "schema", "properties", "fields"}
_METADATA_KEYS = {
    "description",
    "permission_class",
    "read_only",
    "mutating",
    "path_scoped",
    "path_fields",
    "cache_policy",
    "schema_version",
    "pre_hooks",
    "post_hooks",
}
_ALLOWED_CACHE_POLICIES = {"auto", "read_only", "disabled"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signature(payload: dict[str, Any]) -> str:
    interesting = {key: payload.get(key) for key in sorted((*_METADATA_KEYS, "argument_schema", "available")) if key in payload}
    raw = json.dumps(interesting, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _tool_schema_from_payload(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("argument_schema", "input_schema", "schema"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    if isinstance(raw.get("properties"), dict) or isinstance(raw.get("fields"), dict):
        return {key: raw[key] for key in raw.keys() & _SCHEMA_KEYS}
    return {}


def _normalise_tool_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"description": raw}
    if not isinstance(raw, dict):
        return {}
    payload = dict(raw)
    schema = _tool_schema_from_payload(payload)
    if schema:
        payload["argument_schema"] = schema
    return payload


def endpoint_tool_definitions(capabilities: dict[str, Any] | None, metadata: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Extract advertised endpoint tool definitions from current heartbeat shapes."""
    result: dict[str, dict[str, Any]] = {}
    for source in (_as_dict(capabilities), _as_dict(metadata)):
        for container_key in ("tool_schemas", "tools", "agent_tools"):
            container = source.get(container_key)
            if isinstance(container, list):
                for item in container:
                    if isinstance(item, str):
                        result.setdefault(item, {"description": "Endpoint-advertised tool"})
                    elif isinstance(item, dict):
                        name = str(item.get("name") or item.get("id") or "").strip()
                        if name:
                            result[name] = {**result.get(name, {}), **_normalise_tool_payload(item)}
            elif isinstance(container, dict):
                for name, raw in container.items():
                    tool_name = str(name or "").strip()
                    if not tool_name:
                        continue
                    payload = _normalise_tool_payload(raw)
                    if isinstance(raw, dict) and not payload.get("name"):
                        payload["name"] = tool_name
                    result[tool_name] = {**result.get(tool_name, {}), **payload}
    return result


def _apply_payload_to_tool_config(existing: ToolConfig | None, payload: dict[str, Any], *, package: str) -> tuple[ToolConfig, bool]:
    tool_cfg = existing or ToolConfig(enabled=True, package=package)
    changed = existing is None
    seen_at = _now()

    if existing is None and payload.get("available") is False:
        tool_cfg.enabled = False

    if not (tool_cfg.package or "").strip():
        tool_cfg.package = package
        changed = True

    schema = payload.get("argument_schema")
    if isinstance(schema, dict) and schema and tool_cfg.argument_schema != schema:
        tool_cfg.argument_schema = schema
        changed = True

    for field_name in _METADATA_KEYS:
        if field_name not in payload:
            continue
        value = payload.get(field_name)
        if field_name == "cache_policy" and str(value) not in _ALLOWED_CACHE_POLICIES:
            continue
        if field_name in {"path_fields", "pre_hooks", "post_hooks"} and not isinstance(value, list):
            continue
        if field_name in {"read_only", "mutating", "path_scoped"} and value is not None:
            value = bool(value)
        if getattr(tool_cfg, field_name) != value:
            setattr(tool_cfg, field_name, value)
            changed = True

    if not (tool_cfg.description or "").strip():
        description = str(payload.get("description") or payload.get("title") or "Endpoint-advertised tool").strip()
        if description:
            tool_cfg.description = description
            changed = True

    signature = _signature(payload)
    for name, value in {
        "schema_source": package,
        "schema_signature": signature,
        "schema_last_seen_at": seen_at,
        "schema_stale": False,
    }.items():
        if getattr(tool_cfg, name) != value:
            setattr(tool_cfg, name, value)
            changed = True
    return tool_cfg, changed


def _retire_stale_endpoint_tools(config: AppConfig, *, package: str, live_tools: set[str]) -> tuple[list[str], bool]:
    retired: list[str] = []
    changed = False
    for tool_name, tool_cfg in list(config.tools.items()):
        if str(tool_cfg.package or "") != package:
            continue
        if tool_name in live_tools:
            continue
        if tool_cfg.schema_stale and not tool_cfg.enabled:
            continue
        tool_cfg.schema_stale = True
        tool_cfg.enabled = False
        tool_cfg.schema_last_seen_at = _now()
        retired.append(tool_name)
        changed = True
    return retired, changed


def sync_endpoint_tool_schemas(config: AppConfig, runner: Any) -> dict[str, Any]:
    """Merge and retire endpoint-advertised tool schemas from heartbeat data."""
    definitions = endpoint_tool_definitions(getattr(runner, "capabilities", None), getattr(runner, "metadata", None))
    synced: list[str] = []
    skipped: list[str] = []
    changed = False
    package = f"endpoint:{getattr(runner, 'id', 'unknown')}"

    for tool_name, payload in sorted(definitions.items()):
        if tool_name in TOOL_SPECS:
            skipped.append(tool_name)
            continue
        if not any(key in payload for key in (*_METADATA_KEYS, "argument_schema", "available")):
            skipped.append(tool_name)
            continue
        current = config.tools.get(tool_name)
        updated, tool_changed = _apply_payload_to_tool_config(current, payload, package=package)
        if tool_changed:
            config.tools[tool_name] = updated
            changed = True
        synced.append(tool_name)

    retired, retired_changed = _retire_stale_endpoint_tools(config, package=package, live_tools=set(synced))
    changed = changed or retired_changed
    return {"changed": changed, "synced": synced, "skipped": skipped, "retired": retired, "schema_source": package}
