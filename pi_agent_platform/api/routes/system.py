from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query


AuthDependency = Callable[..., Any]
ConfigPayloadProvider = Callable[[Any | None], dict[str, Any]]
NoArgDictProvider = Callable[[], dict[str, Any]]
NoArgListProvider = Callable[[], list[Any]]
RunnerAuthProvider = Callable[[str | None, str | None, str | None], Any]
from pi_agent_platform.core.model_metrics import model_metrics


NOISY_EVENT_TYPES = {'runner_heartbeat', 'endpoint_heartbeat', 'provider_heartbeat'}


def _node(node_id: str, kind: str, label: str, status: str = "unknown", detail: str = "", data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "status": status or "unknown",
        "detail": detail or "",
        "data": data or {},
    }


def _edge(edge_id: str, source: str, target: str, label: str, kind: str = "connected") -> dict[str, Any]:
    return {"id": edge_id, "source": source, "target": target, "label": label, "kind": kind}


def _safe_model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return {}


def _build_dashboard_topology(config: dict[str, Any], runners: list[Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add(node: dict[str, Any]) -> None:
        nodes[node["id"]] = node

    add(_node("controller:pac", "controller", "PAC Controller", "online", "control plane"))

    providers = config.get("providers") or {}
    for provider_id, provider in providers.items():
        provider = _safe_model_dump(provider)
        status = provider.get("status") or ("enabled" if provider.get("enabled") else "disabled")
        add(_node(f"provider:{provider_id}", "provider", str(provider_id), status, provider.get("type") or "provider", provider))
        edges.append(_edge(f"controller-provider-{provider_id}", "controller:pac", f"provider:{provider_id}", "uses provider", "provider"))

    models = config.get("models") or {}
    for model_id, model in models.items():
        model = _safe_model_dump(model)
        provider_id = model.get("provider") or "unassigned"
        status = "available" if provider_id in providers else "unresolved"
        label = model.get("display_name") or model.get("model") or str(model_id)
        add(_node(f"model:{model_id}", "model", label, status, str(model_id), model))
        if provider_id in providers:
            edges.append(_edge(f"model-provider-{model_id}", f"model:{model_id}", f"provider:{provider_id}", "served by", "model-provider"))

    endpoints = {getattr(runner, "id", ""): runner for runner in runners}
    for runner in runners:
        endpoint_id = str(getattr(runner, "id", "") or "unknown")
        status = getattr(getattr(runner, "status", None), "value", None) or str(getattr(runner, "status", "unknown") or "unknown")
        labels = ", ".join(getattr(runner, "labels", []) or [])
        detail = labels or getattr(runner, "endpoint", None) or "endpoint"
        add(_node(f"endpoint:{endpoint_id}", "endpoint", getattr(runner, "name", endpoint_id), status, detail, _safe_model_dump(runner)))
        edges.append(_edge(f"controller-endpoint-{endpoint_id}", "controller:pac", f"endpoint:{endpoint_id}", "controls", "endpoint"))

    workspaces = config.get("workspaces") or {}
    for workspace_id, workspace in workspaces.items():
        workspace = _safe_model_dump(workspace)
        endpoint_id = workspace.get("endpoint_id") or workspace.get("preferred_endpoint")
        add(_node(f"workspace:{workspace_id}", "workspace", str(workspace_id), "configured", workspace.get("type") or "workspace", workspace))
        edges.append(_edge(f"controller-workspace-{workspace_id}", "controller:pac", f"workspace:{workspace_id}", "has workspace", "workspace"))
        if endpoint_id and endpoint_id in endpoints:
            edges.append(_edge(f"workspace-endpoint-{workspace_id}-{endpoint_id}", f"workspace:{workspace_id}", f"endpoint:{endpoint_id}", "runs on", "workspace-endpoint"))

    contexts = config.get("source_contexts") or {}
    for context_id, context in contexts.items():
        context = _safe_model_dump(context)
        workspace_id = context.get("workspace_profile")
        endpoint_id = context.get("preferred_endpoint")
        add(_node(f"context:{context_id}", "context", str(context_id), "configured", context.get("path_prefix") or "source context", context))
        if workspace_id and workspace_id in workspaces:
            edges.append(_edge(f"context-workspace-{context_id}-{workspace_id}", f"context:{context_id}", f"workspace:{workspace_id}", "uses workspace", "context-workspace"))
        else:
            edges.append(_edge(f"controller-context-{context_id}", "controller:pac", f"context:{context_id}", "has context", "context"))
        if endpoint_id and endpoint_id in endpoints:
            edges.append(_edge(f"context-endpoint-{context_id}-{endpoint_id}", f"context:{context_id}", f"endpoint:{endpoint_id}", "prefers", "context-endpoint"))

    profiles = config.get("agent_profiles") or {}
    for profile_id, profile in profiles.items():
        profile = _safe_model_dump(profile)
        model_id = profile.get("model")
        workspace_id = profile.get("workspace_profile") or profile.get("default_workspace")
        add(_node(f"profile:{profile_id}", "profile", profile.get("display_name") or str(profile_id), "available", profile.get("description") or "agent profile", profile))
        if model_id and model_id in models:
            edges.append(_edge(f"profile-model-{profile_id}-{model_id}", f"profile:{profile_id}", f"model:{model_id}", "uses model", "profile-model"))
        else:
            edges.append(_edge(f"controller-profile-{profile_id}", "controller:pac", f"profile:{profile_id}", "offers profile", "profile"))
        if workspace_id and workspace_id in workspaces:
            edges.append(_edge(f"profile-workspace-{profile_id}-{workspace_id}", f"profile:{profile_id}", f"workspace:{workspace_id}", "defaults to", "profile-workspace"))

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "summary": {
            "providers": len(providers),
            "models": len(models),
            "endpoints": len(runners),
            "workspaces": len(workspaces),
            "contexts": len(contexts),
            "profiles": len(profiles),
        },
    }


def _notification_item(kind: str, severity: str, title: str, detail: str = "", action: str | None = None, target: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "action": action,
        "target": target,
        "data": data or {},
    }


def _build_notification_summary(*, tasks: list[Any], alerts: list[dict[str, Any]], component_health: dict[str, Any], setup: dict[str, Any], recent_events: list[Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    pending = [task for task in tasks if (getattr(getattr(task, "status", None), "value", None) or str(getattr(task, "status", ""))) == "approval_required"]
    if pending:
        items.append(_notification_item("approval", "warning", f"{len(pending)} approval request(s) are waiting", "Review pending agent/tool approvals.", "Open approvals", "settings:approvals", {"count": len(pending)}))
    for alert in alerts[:8]:
        items.append(_notification_item("alert", str(alert.get("severity") or "warning"), str(alert.get("title") or "Platform alert"), str(alert.get("detail") or ""), "Review", str(alert.get("target") or "settings-tab"), alert))
    required = setup.get("required_issues") or []
    warnings = setup.get("warnings") or []
    for issue in [*required, *warnings][:8]:
        items.append(_notification_item("setup", str(issue.get("severity") or ("critical" if issue in required else "warning")), str(issue.get("title") or "Setup issue"), str(issue.get("detail") or ""), str(issue.get("action_label") or "Review setup"), str(issue.get("target") or "settings-tab"), issue))
    providers = component_health.get("providers") or {}
    models = component_health.get("models") or {}
    if providers.get("failed"):
        items.append(_notification_item("optimization", "warning", f"{providers.get('failed')} provider connection issue(s)", "A provider is failing health checks or model discovery.", "Open providers", "providers-tab", providers))
    if models.get("unavailable") or models.get("unsupported_provider"):
        count = int(models.get("unavailable") or 0) + int(models.get("unsupported_provider") or 0)
        items.append(_notification_item("optimization", "warning", f"{count} model configuration issue(s)", "Review unavailable models or unsupported provider assignments.", "Open models", "models-tab", models))
    for event in recent_events:
        data = getattr(event, "data", {}) or {}
        event_type = str(getattr(event, "type", "") or "")
        if event_type == "update_checked" and data.get("has_update"):
            latest = data.get("latest_version") or "latest"
            items.append(_notification_item("update", "info", f"PAC update available: v{latest}", "A newer PAC release was detected.", "Open updates", "settings:updates", data))
            break
        if event_type in {"source_online_updates_checked", "source_package_update_checked"} and int(data.get("update_count") or 0) > 0:
            items.append(_notification_item("update", "info", f"{data.get('update_count')} source package update(s) available", "Source/package modules have newer versions.", "Open packages", "tools-tab", data))
            break
    severity_rank = {"critical": 0, "danger": 0, "warning": 1, "warn": 1, "info": 2, "ok": 3}
    items.sort(key=lambda item: (severity_rank.get(str(item.get("severity") or "info"), 2), str(item.get("kind") or "")))
    counts = {"total": len(items), "updates": 0, "approvals": len(pending), "alerts": len(alerts), "optimizations": 0, "critical": 0, "warning": 0}
    for item in items:
        if item["kind"] == "update":
            counts["updates"] += 1
        if item["kind"] == "optimization":
            counts["optimizations"] += 1
        if item["severity"] in {"critical", "danger"}:
            counts["critical"] += 1
        if item["severity"] in {"warning", "warn"}:
            counts["warning"] += 1
    return {"counts": counts, "items": items[:24]}


def create_system_router(
    *,
    require_auth: AuthDependency,
    pac_version: str,
    pacp_home: Callable[[], Path],
    config_path: Callable[[], Path],
    refresh_local_runner_metadata: Callable[..., Any],
    list_sessions: NoArgListProvider,
    list_tasks: NoArgListProvider,
    list_runners: NoArgListProvider,
    list_recent_events: Callable[..., list[Any]],
    metrics_component_health: Callable[[list[Any]], dict[str, Any]],
    platform_alerts: Callable[[list[Any]], list[dict[str, Any]]],
    ui_build_info: NoArgDictProvider,
    config_payload: ConfigPayloadProvider,
    public_url: Callable[[], str],
    source_contexts: Callable[[], dict[str, Any]],
    workspaces: Callable[[], dict[str, Any]],
    session_slash_commands: Callable[[], list[Any]],
    setup_status: NoArgDictProvider,
    slash_help_text: Callable[[], str],
    require_admin_or_runner: RunnerAuthProvider,
    require_resource_access: Callable[[Any, str, str, str], None],
) -> APIRouter:
    """System/status routes that read controller state but do not mutate it.

    This keeps low-coupling status/config endpoints out of the controller
    bootstrap file while avoiding a wider behavior change during the staged
    API split.
    """
    router = APIRouter()

    @router.get('/healthz')
    def healthz() -> dict[str, str]:
        return {'status': 'ok', 'version': pac_version, 'pacp_home': str(pacp_home()), 'config_path': str(config_path())}

    @router.get('/v1/metrics/summary')
    def metrics_summary(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'summary', 'read')
        refresh_local_runner_metadata(emit_event=False)
        sessions = list_sessions()
        tasks = list_tasks()
        runners = list_runners()
        recent_events = list_recent_events(limit=500, exclude_types=NOISY_EVENT_TYPES)
        now = datetime.now(timezone.utc)
        day_keys = [(now - timedelta(days=idx)).date().isoformat() for idx in range(6, -1, -1)]
        events_by_day = {key: 0 for key in day_keys}
        event_types: dict[str, int] = {}
        for event in recent_events:
            event_types[event.type] = event_types.get(event.type, 0) + 1
            key = event.created_at.astimezone(timezone.utc).date().isoformat()
            if key in events_by_day:
                events_by_day[key] += 1
        task_status: dict[str, int] = {}
        for task in tasks:
            status = task.status.value if hasattr(task.status, 'value') else str(task.status)
            task_status[status] = task_status.get(status, 0) + 1
        session_status: dict[str, int] = {}
        for session in sessions:
            status = session.status.value if hasattr(session.status, 'value') else str(session.status)
            session_status[status] = session_status.get(status, 0) + 1
        online = sum(1 for runner in runners if str(runner.status) == 'online' or getattr(runner.status, 'value', None) == 'online')
        failed_tasks = task_status.get('failed', 0)
        completed_tasks = task_status.get('completed', 0)
        running_tasks = task_status.get('running', 0) + task_status.get('queued', 0) + task_status.get('approval_required', 0)
        component_health = metrics_component_health(runners)
        alerts = platform_alerts(runners)
        alert_counts = {
            'total': len(alerts),
            'critical': sum(1 for item in alerts if str(item.get('severity') or '') == 'critical'),
            'warning': sum(1 for item in alerts if str(item.get('severity') or '') == 'warning'),
            'info': sum(1 for item in alerts if str(item.get('severity') or '') == 'info'),
        }
        ui = ui_build_info()
        return {
            'version': pac_version,
            'ui_build': ui['asset_stamp'],
            'ui_updated_at': ui['updated_at'],
            'sessions_total': len(sessions),
            'sessions_active': session_status.get('running', 0) + session_status.get('created', 0),
            'tasks_total': len(tasks),
            'tasks_running': running_tasks,
            'tasks_completed': completed_tasks,
            'tasks_failed': failed_tasks,
            'approvals_pending': task_status.get('approval_required', 0),
            'endpoints_total': len(runners),
            'endpoints_online': online,
            'task_status': task_status,
            'session_status': session_status,
            'events_by_day': [{'date': key, 'count': events_by_day[key]} for key in day_keys],
            'top_event_types': sorted(event_types.items(), key=lambda item: item[1], reverse=True)[:8],
            'model_usage': model_metrics.summarize_usage(since_hours=24, limit=10000),
            'component_health': component_health,
            'alerts': alerts,
            'alert_counts': alert_counts,
        }


    @router.get('/v1/dashboard/topology')
    def dashboard_topology(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'dashboard', 'read')
        refresh_local_runner_metadata(emit_event=False)
        return _build_dashboard_topology(config_payload(_auth), list_runners())

    @router.get('/v1/notifications/summary')
    def notifications_summary(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'notifications', 'read')
        refresh_local_runner_metadata(emit_event=False)
        runners = list_runners()
        recent_events = list_recent_events(limit=200, exclude_types=NOISY_EVENT_TYPES)
        component_health = metrics_component_health(runners)
        alerts = platform_alerts(runners)
        return _build_notification_summary(
            tasks=list_tasks(),
            alerts=alerts,
            component_health=component_health,
            setup=setup_status(),
            recent_events=recent_events,
        )

    @router.get('/v1/model-usage')
    def model_usage_summary(
        since_hours: int = Query(default=24, ge=1, le=24 * 90),
        limit: int = Query(default=10000, ge=1, le=10000),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'model-usage', 'read')
        return model_metrics.summarize_usage(since_hours=since_hours, limit=limit)


    @router.get('/v1/config')
    def get_config(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'system', 'config', 'read')
        return config_payload(_auth)

    @router.get('/v1/ide/config')
    def get_ide_config(
        authorization: str | None = Header(default=None),
        x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
        x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
    ) -> dict[str, Any]:
        runner = require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
        payload = {
            'version': pac_version,
            'server': {'public_url': public_url()},
            'source_contexts': {name: ctx.model_dump() for name, ctx in source_contexts().items()},
            'workspaces': {name: item.model_dump() for name, item in workspaces().items()},
            'session_slash_commands': session_slash_commands(),
            'setup_status': setup_status(),
        }
        if runner:
            payload['requested_by'] = {'kind': 'endpoint', 'runner_id': runner.id, 'runner_name': runner.name}
        else:
            payload['requested_by'] = {'kind': 'admin'}
        return payload

    @router.get('/v1/session-slash-commands')
    def get_session_slash_commands(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return {'commands': session_slash_commands(), 'help_text': slash_help_text()}

    @router.get('/v1/setup/status')
    def get_setup_status(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'system', 'setup', 'read')
        return setup_status()

    return router
