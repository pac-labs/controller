from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..agent_events import AgentEvents
from ..config import AppConfig, ModelConfig, ProviderConfig, WorkspaceProfile, save_config
from ..controller_component_context import get_controller_store
from ..directory_identities import ensure_endpoint_principal, ensure_provider_principal
from ..models import Event, Runner, RunnerStatus, Session, Task, WorkspaceSpec
from ..workspace_bootstrap import ensure_workspace_materialized
from ..coding_session_readiness import CodingSessionReadinessError, prepare_coding_session

_COMPONENT_TOOLS = {
    "pac_list_components",
    "pac_create_provider",
    "pac_create_model",
    "pac_create_endpoint",
    "pac_create_workspace_profile",
    "pac_create_session",
}


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, sort_keys=True)[:20000]


def _safe_name(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip() or fallback
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-._")
    return name or fallback


def _safe_slug(value: Any, *, fallback: str) -> str:
    raw = str(value or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug or fallback


def _controller_session_only(session: Session) -> str | None:
    meta = session.metadata or {}
    if meta.get("controller_harness") or meta.get("system_context"):
        return None
    if str(meta.get("agent_context_name") or "").strip() == "PAC/core":
        return None
    return "DENIED: PAC component creation tools are only available to the built-in PAC controller system session."


def _enabled(config: AppConfig, tool: str) -> bool:
    return bool(getattr(config.tools.get(tool), "enabled", True)) if tool in config.tools else False


def _component_summary(config: AppConfig, store: Any) -> dict[str, Any]:
    runners = store.list_runners() if hasattr(store, "list_runners") else []
    sessions = store.list_sessions() if hasattr(store, "list_sessions") else []
    return {
        "providers": sorted(config.providers.keys()),
        "models": sorted(config.models.keys()),
        "workspace_profiles": sorted(config.workspaces.keys()),
        "endpoints": [
            {"id": runner.id, "name": runner.name, "status": str(runner.status), "endpoint": runner.endpoint, "labels": runner.labels}
            for runner in runners
        ],
        "sessions": [
            {"id": item.id, "name": item.name, "model": item.model, "workspace": item.workspace.model_dump(mode="json"), "status": str(item.status)}
            for item in sessions[-20:]
        ],
    }


def _create_provider(inp: dict[str, Any], config: AppConfig, store: Any) -> dict[str, Any]:
    name = _safe_name(inp.get("name") or inp.get("provider"), fallback="provider")
    if name in config.providers and not bool(inp.get("overwrite", False)):
        raise ValueError(f"Provider already exists: {name}. Pass overwrite=true to replace it.")
    data = {
        "type": inp.get("type") or inp.get("provider_type") or "openai-compatible",
        "base_url": inp.get("base_url") or inp.get("endpoint"),
        "api_key_env": inp.get("api_key_env"),
        "api_key": inp.get("api_key"),
        "timeout_seconds": int(inp.get("timeout_seconds") or 30),
        "default_headers": dict(inp.get("default_headers") or {}),
        "notes": inp.get("notes"),
        "enabled": bool(inp.get("enabled", False)),
        "status": "unknown" if bool(inp.get("enabled", False)) else "disabled",
    }
    provider = ProviderConfig.model_validate({k: v for k, v in data.items() if v is not None})
    config.providers[name] = provider
    save_config(config)
    ensure_provider_principal(store, name, provider)
    store.add_event(Event(session_id="system", type="pac_component_created", message=f"Provider created by PAC tool: {name}", data={"component": "provider", "name": name}))
    return {"ok": True, "component": "provider", "name": name, "provider": provider.model_dump(mode="json", exclude={"api_key"})}


def _create_model(inp: dict[str, Any], config: AppConfig, store: Any) -> dict[str, Any]:
    provider = str(inp.get("provider") or "").strip()
    if not provider:
        raise ValueError("provider is required")
    if provider not in config.providers:
        raise ValueError(f"Unknown provider: {provider}")
    model_ref = str(inp.get("model") or inp.get("model_id") or inp.get("name") or "").strip()
    name = _safe_name(inp.get("name") or model_ref, fallback="model")
    if name in config.models and not bool(inp.get("overwrite", False)):
        raise ValueError(f"Model already exists: {name}. Pass overwrite=true to replace it.")
    data = {
        "display_name": inp.get("display_name") or name,
        "provider": provider,
        "model": model_ref or name,
        "context_window": int(inp.get("context_window") or 32768),
        "max_output_tokens": int(inp.get("max_output_tokens") or 4096),
        "capabilities": dict(inp.get("capabilities") or {}),
        "extra": dict(inp.get("extra") or {}),
    }
    config.models[name] = ModelConfig.model_validate(data)
    save_config(config)
    store.add_event(Event(session_id="system", type="pac_component_created", message=f"Model created by PAC tool: {name}", data={"component": "model", "name": name, "provider": provider}))
    return {"ok": True, "component": "model", "name": name, "model": config.models[name].model_dump(mode="json")}


def _endpoint_default_workspace(runner_id: str, name: str, config: AppConfig) -> dict[str, Any]:
    root = Path(config.server.default_workspace_root or Path(config.server.data_dir) / "workspaces")
    return {
        "type": "local",
        "path": str(root / _safe_slug(name or runner_id, fallback=runner_id)),
        "label": "Default endpoint workspace",
    }


def _create_endpoint(inp: dict[str, Any], config: AppConfig, store: Any) -> dict[str, Any]:
    name = _safe_name(inp.get("name"), fallback="endpoint")
    runner_id = _safe_name(inp.get("id") or f"run-{_safe_slug(name, fallback='endpoint')}", fallback="run-endpoint")
    if store.get_runner(runner_id) and not bool(inp.get("overwrite", False)):
        raise ValueError(f"Endpoint already exists: {runner_id}. Pass overwrite=true to replace it.")
    labels = [str(item).strip() for item in (inp.get("labels") or []) if str(item).strip()]
    metadata = dict(inp.get("metadata") or {})
    metadata.setdefault("agent_requested", bool(inp.get("agent_enabled", True)))
    metadata.setdefault("default_workspace", inp.get("default_workspace") or _endpoint_default_workspace(runner_id, name, config))
    metadata.setdefault("agent_tools", [str(item).strip() for item in (inp.get("tools") or []) if str(item).strip()])
    metadata.setdefault("agent_runtime", {"kind": "remote-execution", "status": "waiting", "message": "Waiting for endpoint heartbeat."})
    runner = Runner(
        id=runner_id,
        name=name,
        labels=labels,
        endpoint=inp.get("endpoint"),
        allow_host_execution=bool(inp.get("allow_host_execution", True)),
        allow_container_execution=bool(inp.get("allow_container_execution", True)),
        metadata=metadata,
        status=RunnerStatus.pending,
    )
    store.add_runner(runner)
    ensure_endpoint_principal(store, runner)
    store.add_event(Event(session_id="system", type="pac_component_created", message=f"Endpoint created by PAC tool: {name}", data={"component": "endpoint", "runner_id": runner.id}))
    return {"ok": True, "component": "endpoint", "endpoint": runner.model_dump(mode="json")}


def _create_workspace_profile(inp: dict[str, Any], config: AppConfig, store: Any) -> dict[str, Any]:
    name = _safe_name(inp.get("name") or inp.get("profile"), fallback="workspace")
    if name in config.workspaces and not bool(inp.get("overwrite", False)):
        existing = config.workspaces[name]
        if bool(inp.get("idempotent", False)):
            store.add_event(Event(session_id="system", type="pac_component_exists", message=f"Workspace profile already exists: {name}", data={"component": "workspace_profile", "name": name}))
            return {"ok": True, "component": "workspace_profile", "name": name, "existing": True, "workspace": existing.model_dump(mode="json")}
        raise ValueError(f"Workspace profile already exists: {name}. Pass overwrite=true to replace it.")
    data = {
        "description": inp.get("description"),
        "type": inp.get("type") or "local",
        "path": inp.get("path"),
        "url": inp.get("url"),
        "branch": inp.get("branch"),
        "shared_storage_id": inp.get("shared_storage_id"),
        "storage_subpath": inp.get("storage_subpath"),
        "storage_mount_path": inp.get("storage_mount_path"),
        "default_agent_profile": inp.get("default_agent_profile") or inp.get("agent_profile"),
        "endpoint_id": inp.get("endpoint_id"),
        "endpoint_selector": inp.get("endpoint_selector"),
        "runtime": inp.get("runtime") or "any",
        "container_image": inp.get("container_image"),
        "ephemeral": bool(inp.get("ephemeral", False)),
        "ttl_hours": inp.get("ttl_hours"),
        "delete_on_expire": bool(inp.get("delete_on_expire", True)),
        "is_default": bool(inp.get("is_default", False)),
    }
    profile = WorkspaceProfile.model_validate({k: v for k, v in data.items() if v is not None})
    config.workspaces[name] = profile
    save_config(config)
    store.add_event(Event(session_id="system", type="pac_component_created", message=f"Workspace profile created by PAC tool: {name}", data={"component": "workspace_profile", "name": name}))
    return {"ok": True, "component": "workspace_profile", "name": name, "workspace": profile.model_dump(mode="json")}




def _online_container_endpoint(store: Any, preferred: Any = None) -> Runner | None:
    preferred_id = str(preferred or "").strip()
    runners = list(store.list_runners()) if hasattr(store, "list_runners") else []
    if preferred_id:
        runner = store.get_runner(preferred_id) if hasattr(store, "get_runner") else None
        if runner and runner.status == RunnerStatus.online and runner.allow_container_execution:
            return runner
    for runner in runners:
        if runner.status == RunnerStatus.online and runner.allow_container_execution:
            return runner
    return None


def _container_image_for_session(inp: dict[str, Any], profile: WorkspaceProfile | None, metadata: dict[str, Any]) -> str:
    for candidate in (
        inp.get("container_image"),
        metadata.get("container_image"),
        getattr(profile, "container_image", None) if profile else None,
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    return "localhost/python-dev:latest"


def _metadata_for_created_session(inp: dict[str, Any], profile: WorkspaceProfile | None, store: Any) -> dict[str, Any]:
    metadata = {"created_by": "pac_create_session", **dict(inp.get("metadata") or {})}
    workspace_runtime = str(getattr(profile, "runtime", "") or "").strip().lower()
    wants_container = bool(
        metadata.get("coding_session")
        or inp.get("container_image")
        or metadata.get("container_image")
        or workspace_runtime == "container"
        or getattr(profile, "container_image", None)
    )
    if not wants_container:
        return metadata

    metadata["coding_session"] = True
    metadata["agent_enabled"] = True
    metadata["execution_mode"] = "container"
    metadata["preferred_execution_mode"] = "container"
    metadata["container_image"] = _container_image_for_session(inp, profile, metadata)

    preferred = inp.get("preferred_endpoint") or metadata.get("preferred_endpoint") or getattr(profile, "endpoint_id", None)
    runner = _online_container_endpoint(store, preferred)
    if not runner:
        raise ValueError("Container-backed PAC-created sessions require an online endpoint with container execution enabled")
    metadata["preferred_endpoint"] = runner.id
    metadata["runner_id"] = runner.id
    metadata["endpoint_locked"] = True
    metadata["endpoint_name"] = runner.name
    return metadata


def _workspace_for_session(inp: dict[str, Any], config: AppConfig, session_id_hint: str) -> tuple[WorkspaceSpec, str, WorkspaceProfile | None]:
    workspace_profile = str(inp.get("workspace_profile") or "").strip()
    if workspace_profile:
        if workspace_profile not in config.workspaces:
            raise ValueError(f"Unknown workspace profile: {workspace_profile}")
        profile = config.workspaces[workspace_profile]
        path = profile.path or str(Path(config.server.default_workspace_root or Path(config.server.data_dir) / "workspaces") / session_id_hint)
        return WorkspaceSpec(type="profile", profile=workspace_profile, path=path, url=profile.url, branch=profile.branch), path, profile
    workspace_type = str(inp.get("workspace_type") or inp.get("type") or "local")
    path = str(inp.get("path") or "").strip()
    if not path:
        path = str(Path(config.server.default_workspace_root or Path(config.server.data_dir) / "workspaces") / session_id_hint)
    spec = WorkspaceSpec(type=workspace_type if workspace_type in {"local", "git"} else "local", path=path, url=inp.get("url"), branch=inp.get("branch"))
    return spec, path, None


def _create_session(inp: dict[str, Any], config: AppConfig, store: Any) -> dict[str, Any]:
    model = str(inp.get("model") or config.controller_harness.model or next(iter(config.models.keys()), "")).strip()
    if not model or model not in config.models:
        raise ValueError("A known model is required. Create/configure a model first or pass model=<configured model name>.")
    name = str(inp.get("name") or "PAC-created session").strip()
    session_id_hint = _safe_slug(name, fallback="session")
    workspace, workspace_path, workspace_profile = _workspace_for_session(inp, config, session_id_hint)
    session_metadata = _metadata_for_created_session(inp, workspace_profile, store)
    permission = str(inp.get("permission_profile") or "ask-first").strip()
    if permission not in config.permission_profiles:
        permission = "ask-first"
    tools = [str(item).strip() for item in (inp.get("tools") or []) if str(item).strip()]
    if not tools:
        tools = list(config.tools.keys()) if bool(inp.get("expose_platform_tools", False)) else []
    session = Session(
        name=name,
        agent_profile=inp.get("agent_profile"),
        permission_profile=permission,
        context_mode=str(inp.get("context_mode") or "medium"),
        workspace=workspace,
        workspace_path=workspace_path,
        model=model,
        tools=tools,
        metadata=session_metadata,
    )
    store.add_session(session)
    if session.metadata.get("coding_session"):
        readiness = prepare_coding_session(session, config, store=store)
        workspace_materialization = session.metadata.get("workspace_materialization") or readiness.get("materialization") or {}
    else:
        workspace_materialization = ensure_workspace_materialized(session)
        session.metadata["workspace_materialization"] = workspace_materialization
        store.add_session(session)
    store.add_event(Event(session_id=session.id, type="session_created", message=f"Session created by PAC tool: {name}", data={"component": "session", "workspace_materialization": workspace_materialization, "coding_readiness": session.metadata.get("coding_readiness"), "endpoint": session.metadata.get("preferred_endpoint"), "endpoint_locked": session.metadata.get("endpoint_locked"), "agent_enabled": session.metadata.get("agent_enabled", True), "execution_mode": session.metadata.get("execution_mode"), "container_image": session.metadata.get("container_image")}))
    return {"ok": True, "component": "session", "session": session.model_dump(mode="json"), "workspace_materialization": workspace_materialization, "coding_readiness": session.metadata.get("coding_readiness")}


async def try_execute_pac_component_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    allowed: set[str],
) -> tuple[str, bool] | None:
    if tool not in _COMPONENT_TOOLS:
        return None
    if tool not in allowed:
        return f"DENIED: {tool} is not enabled for this session", False
    if not _enabled(config, tool):
        return f"DENIED: {tool} is disabled in PAC configuration", False
    if denied := _controller_session_only(session):
        return denied, False
    events = AgentEvents(session, task)
    try:
        store = get_controller_store()
        if store is None:
            return "DENIED: PAC component tools require controller store access", False
        if tool == "pac_list_components":
            result = _component_summary(config, store)
        elif tool == "pac_create_provider":
            result = _create_provider(inp, config, store)
        elif tool == "pac_create_model":
            result = _create_model(inp, config, store)
        elif tool == "pac_create_endpoint":
            result = _create_endpoint(inp, config, store)
        elif tool == "pac_create_workspace_profile":
            result = _create_workspace_profile(inp, config, store)
        elif tool == "pac_create_session":
            result = _create_session(inp, config, store)
        else:
            return None
    except Exception as exc:
        events.tool_result(tool=tool, message=f"{tool} failed", data={"error": str(exc)})
        return _json({"ok": False, "error": str(exc), "tool": tool}), False
    events.tool_result(tool=tool, message=f"{tool} completed", data={"component": result.get("component"), "name": result.get("name")})
    return _json(result), False
