from __future__ import annotations

import hashlib
from typing import Any


def _safe_model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return {}


def _node(
    node_id: str,
    kind: str,
    label: str,
    status: str = "unknown",
    detail: str = "",
    data: dict[str, Any] | None = None,
    *,
    group: str | None = None,
    parent: str | None = None,
    depth: str = "instance",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "status": status or "unknown",
        "detail": detail or "",
        "group": group or kind,
        "parent": parent or "",
        "depth": depth,
        "data": data or {},
    }


def _edge(edge_id: str, source: str, target: str, label: str, kind: str = "connected") -> dict[str, Any]:
    return {"id": edge_id, "source": source, "target": target, "label": label, "kind": kind}


def _is_enabled(item: dict[str, Any]) -> str:
    if "enabled" not in item:
        return "configured"
    return "enabled" if item.get("enabled") else "disabled"


def _runner_status(runner: Any) -> str:
    return getattr(getattr(runner, "status", None), "value", None) or str(getattr(runner, "status", "unknown") or "unknown")


def _runner_metadata(runner: Any) -> dict[str, Any]:
    data = _safe_model_dump(runner)
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else getattr(runner, "metadata", {})
    return meta if isinstance(meta, dict) else {}


def _add_static_controller(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    def add(node: dict[str, Any]) -> None:
        nodes[node["id"]] = node

    add(_node("controller:pac", "controller", "PAC Controller", "online", "central orchestrator", group="controller", depth="core"))
    subsystems = [
        ("controller:web-ui", "Web UI", "interface", "serves dashboard and workflows"),
        ("controller:api", "API", "routing", "state, sessions and admin routes"),
        ("controller:event-stream", "Event stream", "events", "session and runtime activity"),
        ("controller:state-store", "State store", "state", "configuration and runtime objects"),
        ("controller:scheduler", "Agent loop", "planning", "routes tasks and tool calls"),
        ("controller:security", "Security", "access", "profiles, permissions and credentials"),
        ("controller:observability", "Observability", "signals", "health, logs, metrics and traces"),
    ]
    for node_id, label, status, detail in subsystems:
        add(_node(node_id, "subsystem", label, status, detail, group="controller", parent="controller:pac", depth="subcomponent"))
        edges.append(_edge(f"controller-subsystem-{node_id}", "controller:pac", node_id, "contains", "contains"))


def _add_agents(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    def add(node: dict[str, Any]) -> None:
        nodes[node["id"]] = node

    agents = [
        ("agent:pac", "PAC Agent", "active", "controller-side planning and routing"),
        ("agent:pi-dev", "pi.dev Agent", "runtime", "execution bridge and workspace runtime"),
    ]
    for node_id, label, status, detail in agents:
        add(_node(node_id, "agent", label, status, detail, group="agents", depth="core"))
        edges.append(_edge(f"controller-agent-{node_id}", "controller:pac", node_id, "coordinates", "controller-agent"))

    pac_parts = ["Planning", "Routing", "Context", "Intent", "Tool selection"]
    for part in pac_parts:
        node_id = f"agent:pac:{part.lower().replace(' ', '-')}"
        add(_node(node_id, "agent_part", part, "available", "PAC agent capability", group="agents", parent="agent:pac", depth="subcomponent"))
        edges.append(_edge(f"pac-agent-part-{node_id}", "agent:pac", node_id, "contains", "contains"))

    pi_parts = ["Runtime", "Execution bridge", "Artifacts", "Shell/tools", "Workspace interaction"]
    for part in pi_parts:
        node_id = f"agent:pi-dev:{part.lower().replace('/', '-').replace(' ', '-')}"
        add(_node(node_id, "agent_part", part, "available", "pi.dev runtime capability", group="agents", parent="agent:pi-dev", depth="subcomponent"))
        edges.append(_edge(f"pi-agent-part-{node_id}", "agent:pi-dev", node_id, "contains", "contains"))

    edges.append(_edge("pac-agent-to-pi-dev", "agent:pac", "agent:pi-dev", "hands execution to", "agent-handoff"))


def _add_observability(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    def add(node: dict[str, Any]) -> None:
        nodes[node["id"]] = node

    add(_node("observability:signals", "observability", "Signals", "available", "events, logs, metrics and traces", group="observability", depth="core"))
    edges.append(_edge("controller-observability-signals", "controller:observability", "observability:signals", "feeds", "observability"))
    for item in ["Events", "Logs", "Metrics", "Traces", "Health"]:
        node_id = f"observability:{item.lower()}"
        add(_node(node_id, "signal", item, "available", "runtime signal", group="observability", parent="observability:signals", depth="subcomponent"))
        edges.append(_edge(f"observability-signal-{item.lower()}", "observability:signals", node_id, "contains", "contains"))


def _add_providers_and_models(config: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    providers = config.get("providers") or {}
    for provider_id, provider in providers.items():
        provider = _safe_model_dump(provider)
        status = provider.get("status") or _is_enabled(provider)
        nodes[f"provider:{provider_id}"] = _node(
            f"provider:{provider_id}", "provider", str(provider_id), status,
            provider.get("type") or "model provider", provider, group="providers", depth="instance",
        )
        edges.append(_edge(f"controller-provider-{provider_id}", "controller:pac", f"provider:{provider_id}", "registers", "provider"))
        edges.append(_edge(f"agent-provider-{provider_id}", "agent:pac", f"provider:{provider_id}", "can call", "agent-provider"))

    models = config.get("models") or {}
    for model_id, model in models.items():
        model = _safe_model_dump(model)
        provider_id = model.get("provider") or "unassigned"
        status = "available" if provider_id in providers else "unresolved"
        label = model.get("display_name") or model.get("model") or str(model_id)
        parent = f"provider:{provider_id}" if provider_id in providers else ""
        nodes[f"model:{model_id}"] = _node(
            f"model:{model_id}", "model", label, status, str(model_id), model,
            group="providers", parent=parent, depth="instance",
        )
        if provider_id in providers:
            edges.append(_edge(f"provider-model-{model_id}", f"provider:{provider_id}", f"model:{model_id}", "exposes model", "provider-model"))
        capabilities = model.get("capabilities") if isinstance(model.get("capabilities"), dict) else {}
        for key, enabled in capabilities.items():
            if not enabled:
                continue
            cap_id = f"model:{model_id}:cap:{key}"
            nodes[cap_id] = _node(cap_id, "capability", str(key).replace("_", " "), "available", "model capability", group="providers", parent=f"model:{model_id}", depth="subcomponent")
            edges.append(_edge(f"model-capability-{model_id}-{key}", f"model:{model_id}", cap_id, "supports", "model-capability"))


def _add_endpoints(runners: list[Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    endpoints = {str(getattr(runner, "id", "") or ""): runner for runner in runners}
    for endpoint_id, runner in endpoints.items():
        if not endpoint_id:
            continue
        status = _runner_status(runner)
        labels = ", ".join(getattr(runner, "labels", []) or [])
        detail = labels or getattr(runner, "endpoint", None) or "endpoint"
        node_id = f"endpoint:{endpoint_id}"
        nodes[node_id] = _node(node_id, "endpoint", getattr(runner, "name", endpoint_id), status, detail, _safe_model_dump(runner), group="endpoints", depth="instance")
        edges.append(_edge(f"controller-endpoint-{endpoint_id}", "controller:pac", node_id, "controls", "endpoint"))
        edges.append(_edge(f"pi-agent-endpoint-{endpoint_id}", "agent:pi-dev", node_id, "executes on", "agent-endpoint"))
        meta = _runner_metadata(runner)
        runtime = meta.get("agent_runtime") if isinstance(meta.get("agent_runtime"), dict) else {}
        if runtime:
            runtime_status = str(runtime.get("status") or "unknown")
            runtime_id = f"endpoint:{endpoint_id}:agent-runtime"
            nodes[runtime_id] = _node(runtime_id, "runtime", "Endpoint agent runtime", runtime_status, "endpoint execution service", runtime, group="endpoints", parent=node_id, depth="subcomponent")
            edges.append(_edge(f"endpoint-runtime-{endpoint_id}", node_id, runtime_id, "hosts", "contains"))
        pi_daemon = meta.get("pi_dev_daemon") if isinstance(meta.get("pi_dev_daemon"), dict) else {}
        if pi_daemon:
            daemon_status = "running" if pi_daemon.get("running") else "stopped"
            daemon_id = f"endpoint:{endpoint_id}:pi-dev-daemon"
            nodes[daemon_id] = _node(daemon_id, "runtime", "pi.dev daemon", daemon_status, "local pi.dev runtime", pi_daemon, group="endpoints", parent=node_id, depth="subcomponent")
            edges.append(_edge(f"endpoint-pi-daemon-{endpoint_id}", node_id, daemon_id, "hosts", "contains"))
    return endpoints


def _add_workspaces_and_contexts(config: dict[str, Any], endpoints: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    workspaces = config.get("workspaces") or {}
    for workspace_id, workspace in workspaces.items():
        workspace = _safe_model_dump(workspace)
        endpoint_id = workspace.get("endpoint_id") or workspace.get("preferred_endpoint")
        node_id = f"workspace:{workspace_id}"
        nodes[node_id] = _node(node_id, "workspace", str(workspace_id), "configured", workspace.get("type") or "workspace", workspace, group="workspaces", depth="instance")
        edges.append(_edge(f"controller-workspace-{workspace_id}", "controller:pac", node_id, "has workspace", "workspace"))
        if endpoint_id and endpoint_id in endpoints:
            edges.append(_edge(f"endpoint-workspace-{endpoint_id}-{workspace_id}", f"endpoint:{endpoint_id}", node_id, "hosts", "endpoint-workspace"))

    contexts = config.get("source_contexts") or {}
    for context_id, context in contexts.items():
        context = _safe_model_dump(context)
        workspace_id = context.get("workspace_profile")
        endpoint_id = context.get("preferred_endpoint")
        node_id = f"context:{context_id}"
        nodes[node_id] = _node(node_id, "context", str(context_id), "configured", context.get("path_prefix") or "source context", context, group="workspaces", depth="subcomponent")
        if workspace_id and workspace_id in workspaces:
            edges.append(_edge(f"workspace-context-{workspace_id}-{context_id}", f"workspace:{workspace_id}", node_id, "provides context", "workspace-context"))
        else:
            edges.append(_edge(f"controller-context-{context_id}", "controller:pac", node_id, "has context", "context"))
        if endpoint_id and endpoint_id in endpoints:
            edges.append(_edge(f"context-endpoint-{context_id}-{endpoint_id}", node_id, f"endpoint:{endpoint_id}", "prefers", "context-endpoint"))


def _add_tools_and_plugins(config: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    packages = config.get("tool_packages") or {}
    tools = config.get("tools") or {}
    plugins = config.get("plugins") or {}
    for package_id, package in packages.items():
        package = _safe_model_dump(package)
        node_id = f"package:{package_id}"
        nodes[node_id] = _node(node_id, "tool_package", str(package_id), _is_enabled(package), package.get("description") or "tool package", package, group="tools", depth="instance")
        edges.append(_edge(f"controller-package-{package_id}", "controller:pac", node_id, "knows package", "tool-package"))
    for tool_id, tool in tools.items():
        tool = _safe_model_dump(tool)
        package_id = tool.get("package")
        node_id = f"tool:{tool_id}"
        nodes[node_id] = _node(node_id, "tool", str(tool_id), _is_enabled(tool), tool.get("description") or "endpoint binary", tool, group="tools", parent=f"package:{package_id}" if package_id in packages else "", depth="subcomponent")
        if package_id and package_id in packages:
            edges.append(_edge(f"package-tool-{package_id}-{tool_id}", f"package:{package_id}", node_id, "contains", "package-tool"))
        else:
            edges.append(_edge(f"controller-tool-{tool_id}", "controller:pac", node_id, "discovers", "tool"))
        edges.append(_edge(f"pi-agent-tool-{tool_id}", "agent:pi-dev", node_id, "can invoke", "agent-tool"))
    for plugin_id, plugin in plugins.items():
        plugin = _safe_model_dump(plugin)
        node_id = f"plugin:{plugin_id}"
        nodes[node_id] = _node(node_id, "plugin", str(plugin_id), _is_enabled(plugin), plugin.get("kind") or "agent plugin", plugin, group="plugins", depth="instance")
        edges.append(_edge(f"plugin-agent-{plugin_id}", node_id, "agent:pac", "extends", "plugin-agent"))
        for tool_id in plugin.get("requires_tools") or []:
            if f"tool:{tool_id}" in nodes:
                edges.append(_edge(f"plugin-tool-{plugin_id}-{tool_id}", node_id, f"tool:{tool_id}", "requires", "plugin-tool"))


def _add_profiles_and_sessions(config: dict[str, Any], endpoints: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    models = config.get("models") or {}
    workspaces = config.get("workspaces") or {}
    profiles = config.get("agent_profiles") or {}
    for profile_id, profile in profiles.items():
        profile = _safe_model_dump(profile)
        model_id = profile.get("model")
        workspace_id = profile.get("workspace_profile") or profile.get("default_workspace")
        node_id = f"profile:{profile_id}"
        nodes[node_id] = _node(node_id, "profile", profile.get("display_name") or str(profile_id), "available", profile.get("description") or "agent profile", profile, group="profiles", depth="instance")
        edges.append(_edge(f"controller-profile-{profile_id}", "controller:pac", node_id, "offers", "profile"))
        if model_id and model_id in models:
            edges.append(_edge(f"profile-model-{profile_id}-{model_id}", node_id, f"model:{model_id}", "selects model", "profile-model"))
        if workspace_id and workspace_id in workspaces:
            edges.append(_edge(f"profile-workspace-{profile_id}-{workspace_id}", node_id, f"workspace:{workspace_id}", "defaults to", "profile-workspace"))

    sessions = config.get("sessions") or []
    for session in sessions:
        session = _safe_model_dump(session)
        session_id = str(session.get("id") or "")
        if not session_id:
            continue
        status = session.get("status") or "unknown"
        label = session.get("name") or session_id
        node_id = f"session:{session_id}"
        nodes[node_id] = _node(node_id, "session", str(label), status, session.get("context_mode") or "session", session, group="sessions", depth="instance")
        edges.append(_edge(f"controller-session-{session_id}", "controller:pac", node_id, "tracks", "session"))
        edges.append(_edge(f"agent-session-{session_id}", "agent:pac", node_id, "runs", "agent-session"))
        workspace = session.get("workspace") or {}
        workspace_profile = workspace.get("profile") if isinstance(workspace, dict) else None
        workspace_path = session.get("workspace_path") or (workspace.get("path") if isinstance(workspace, dict) else None)
        model_id = session.get("model")
        profile_id = session.get("agent_profile")
        metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
        context_id = metadata.get("agent_context_id")
        endpoint_id = metadata.get("preferred_endpoint") or metadata.get("runner_id")
        if workspace_profile and workspace_profile in workspaces:
            edges.append(_edge(f"session-workspace-{session_id}-{workspace_profile}", node_id, f"workspace:{workspace_profile}", "uses workspace", "session-workspace"))
        elif workspace_path:
            synthetic_key = hashlib.sha1(str(workspace_path).encode("utf-8", "ignore")).hexdigest()[:12]
            synthetic_id = f"workspace:path:{synthetic_key}"
            if synthetic_id not in nodes:
                nodes[synthetic_id] = _node(synthetic_id, "workspace", str(workspace_path).split("/")[-1] or str(workspace_path), "runtime", str(workspace_path), {"path": workspace_path, "synthetic": True}, group="workspaces", depth="instance")
            edges.append(_edge(f"session-workspace-path-{session_id}", node_id, synthetic_id, "uses workspace", "session-workspace"))
        if model_id and model_id in models:
            edges.append(_edge(f"session-model-{session_id}-{model_id}", node_id, f"model:{model_id}", "uses model", "session-model"))
        if profile_id and profile_id in profiles:
            edges.append(_edge(f"session-profile-{session_id}-{profile_id}", node_id, f"profile:{profile_id}", "uses profile", "session-profile"))
        if context_id:
            context_node = f"context:{context_id}"
            if context_node not in nodes:
                nodes[context_node] = _node(context_node, "context", str(metadata.get("agent_context_name") or context_id), "configured", metadata.get("agent_context_kind") or "agent context", {"id": context_id, "from_session": session_id}, group="workspaces", depth="subcomponent")
            edges.append(_edge(f"session-context-{session_id}-{context_id}", node_id, context_node, "uses context", "session-context"))
        if endpoint_id and endpoint_id in endpoints:
            edges.append(_edge(f"session-endpoint-{session_id}-{endpoint_id}", node_id, f"endpoint:{endpoint_id}", "runs on", "session-endpoint"))
        artifact_id = f"artifact:{session_id}"
        nodes[artifact_id] = _node(artifact_id, "artifact", "Session artifacts", status, "outputs, diffs and zips", {"session_id": session_id}, group="artifacts", parent=node_id, depth="subcomponent")
        edges.append(_edge(f"session-artifacts-{session_id}", node_id, artifact_id, "produces", "session-artifact"))
        edges.append(_edge(f"session-events-{session_id}", node_id, "observability:events", "emits", "session-event"))


def build_dashboard_topology(config: dict[str, Any], runners: list[Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    _add_static_controller(nodes, edges)
    _add_agents(nodes, edges)
    _add_observability(nodes, edges)
    _add_providers_and_models(config, nodes, edges)
    endpoints = _add_endpoints(runners, nodes, edges)
    _add_workspaces_and_contexts(config, endpoints, nodes, edges)
    _add_tools_and_plugins(config, nodes, edges)
    _add_profiles_and_sessions(config, endpoints, nodes, edges)
    groups = {str(node.get("group") or node.get("kind") or "other") for node in nodes.values()}
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "summary": {
            "providers": len(config.get("providers") or {}),
            "models": len(config.get("models") or {}),
            "endpoints": len(runners),
            "workspaces": len(config.get("workspaces") or {}),
            "contexts": len(config.get("source_contexts") or {}),
            "profiles": len(config.get("agent_profiles") or {}),
            "sessions": len(config.get("sessions") or []),
            "tools": len(config.get("tools") or {}),
            "tool_packages": len(config.get("tool_packages") or {}),
            "plugins": len(config.get("plugins") or {}),
            "groups": len(groups),
        },
    }
