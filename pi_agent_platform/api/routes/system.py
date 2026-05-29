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
from pi_agent_platform.core.dashboard_component_atlas import build_dashboard_topology
from pi_agent_platform.core.agent_tools.pipeline_metrics import pipeline_metrics_snapshot
from pi_agent_platform.core.model_metrics import model_metrics
from pi_agent_platform.core.observability import observability_status, tail_log
from pi_agent_platform.core.observability_store import query_metrics, query_traces, prune_observability_store
from pi_agent_platform.core.playbooks.metrics import playbook_metrics_snapshot


NOISY_EVENT_TYPES = {'runner_heartbeat', 'endpoint_heartbeat', 'provider_heartbeat'}
EMERGENCY_EVENT_HINTS = ("failed", "error", "warning", "warn", "danger", "critical", "alert", "approval", "security", "denied", "rejected", "unavailable")


def _version_tuple(value: str | None) -> tuple[int, ...]:
    parts: list[int] = []
    for token in str(value or "").strip().lstrip("v").split("."):
        number = ""
        for char in token:
            if char.isdigit():
                number += char
            else:
                break
        parts.append(int(number) if number else 0)
    return tuple(parts or [0])


def _event_reports_newer_update(data: dict[str, Any], current_version: str) -> bool:
    latest = str(data.get("latest_version") or "").strip()
    if not data.get("has_update") or not latest:
        return False
    return _version_tuple(latest) > _version_tuple(current_version)



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


def _build_notification_summary(*, tasks: list[Any], alerts: list[dict[str, Any]], component_health: dict[str, Any], setup: dict[str, Any], recent_events: list[Any], current_version: str) -> dict[str, Any]:
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
        if event_type == "update_checked" and _event_reports_newer_update(data, current_version):
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


def _event_severity(event: Any) -> str:
    data = getattr(event, "data", {}) or {}
    return str(data.get("severity") or data.get("level") or "").strip().lower()


def _is_emergency_event(event: Any) -> bool:
    event_type = str(getattr(event, "type", "") or "").strip().lower()
    severity = _event_severity(event)
    if severity in {"critical", "error", "warning", "warn", "danger", "alert"}:
        return True
    return any(hint in event_type for hint in EMERGENCY_EVENT_HINTS)


def _event_category(event: Any) -> str:
    event_type = str(getattr(event, "type", "") or "").strip().lower()
    if _is_emergency_event(event) or "failed" in event_type or "error" in event_type:
        return "failed"
    if any(hint in event_type for hint in ("approval", "attention", "reconnect", "slow", "unavailable")):
        return "attention"
    if any(hint in event_type for hint in ("queued", "started", "running", "thinking", "stream", "progress")):
        return "running"
    return "completed"


def _event_source(event: Any) -> dict[str, str]:
    data = getattr(event, "data", {}) or {}
    if data.get("runner_id"):
        return {"kind": "endpoint", "label": str(data.get("runner_id"))}
    if data.get("workspace_path"):
        return {"kind": "workspace", "label": str(data.get("workspace_path"))}
    if getattr(event, "session_id", None) and str(getattr(event, "session_id")) != "system":
        return {"kind": "session", "label": str(getattr(event, "session_id"))}
    component = str(data.get("component") or "").strip()
    if component:
        return {"kind": "component", "label": component}
    return {"kind": "system", "label": "controller"}


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
            'tool_pipeline': pipeline_metrics_snapshot(),
            'playbooks': playbook_metrics_snapshot(limit=200),
            'component_health': component_health,
            'alerts': alerts,
            'alert_counts': alert_counts,
        }


    @router.get('/v1/dashboard/topology')
    def dashboard_topology(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'dashboard', 'read')
        refresh_local_runner_metadata(emit_event=False)
        payload = config_payload(_auth)
        payload['sessions'] = [session.model_dump(mode='json') for session in list_sessions()]
        return build_dashboard_topology(payload, list_runners())

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
            current_version=pac_version,
        )

    @router.get('/v1/events/urgent')
    def urgent_events(
        limit: int = Query(default=80, ge=1, le=500),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'events', 'read')
        recent_events = list_recent_events(limit=max(limit * 6, 500), exclude_types=NOISY_EVENT_TYPES)
        events = [event.model_dump(mode='json') for event in recent_events if _is_emergency_event(event)][:limit]
        return {"events": events}

    @router.get('/v1/events/summary')
    def events_summary(
        limit: int = Query(default=260, ge=1, le=1000),
        source_kind: str | None = Query(default=None),
        source_label: str | None = Query(default=None),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'events', 'read')
        recent_events = list_recent_events(limit=max(limit * 6, 1000), exclude_types=NOISY_EVENT_TYPES)
        categories = {"failed": 0, "attention": 0, "running": 0, "completed": 0}
        sources = {"system": 0, "sessions": 0, "endpoints": 0, "workspaces": 0, "components": 0}
        source_labels: dict[str, list[dict[str, Any]]] = {}
        components: list[dict[str, Any]] = []
        grouped_counts: dict[tuple[str, str], int] = {}
        filtered: list[Any] = []
        emergency_total = 0
        for event in recent_events:
            category = _event_category(event)
            categories[category] = categories.get(category, 0) + 1
            if _is_emergency_event(event):
                emergency_total += 1
            source = _event_source(event)
            source_kind_key = str(source["kind"])
            source_label_value = str(source["label"])
            grouped_counts[(source_kind_key, source_label_value)] = grouped_counts.get((source_kind_key, source_label_value), 0) + 1
            if source_kind_key == "session":
                sources["sessions"] += 1
            elif source_kind_key == "endpoint":
                sources["endpoints"] += 1
            elif source_kind_key == "workspace":
                sources["workspaces"] += 1
            elif source_kind_key == "component":
                sources["components"] += 1
            else:
                sources["system"] += 1
            if source_kind and source_kind_key != str(source_kind):
                continue
            if source_label and source_label_value != str(source_label):
                continue
            filtered.append(event)
        for (kind, label), count in grouped_counts.items():
            if kind == "component":
                components.append({"label": label, "count": count})
                continue
            bucket = source_labels.setdefault(kind, [])
            bucket.append({"label": label, "count": count})
        for entries in source_labels.values():
            entries.sort(key=lambda item: (-int(item["count"]), str(item["label"])))
        components.sort(key=lambda item: (-int(item["count"]), str(item["label"])))
        filtered = filtered[:limit]
        return {
            "events": [event.model_dump(mode='json') for event in filtered],
            "summary": {
                "categories": categories,
                "sources": sources,
                "emergency": emergency_total,
            },
            "facets": {
                "source_labels": source_labels,
                "components": components[:12],
            },
        }

    @router.get('/v1/model-usage')
    def model_usage_summary(
        since_hours: int = Query(default=24, ge=1, le=24 * 90),
        limit: int = Query(default=10000, ge=1, le=10000),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'model-usage', 'read')
        return model_metrics.summarize_usage(since_hours=since_hours, limit=limit)



    @router.get('/v1/system/observability')
    def system_observability(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability', 'read')
        return observability_status()

    @router.get('/v1/system/logs/tail')
    def system_log_tail(
        name: str = Query(default='controller', pattern='^(controller|audit|wrapper|pi-agent|pacctl)$'),
        limit: int = Query(default=8000, ge=1, le=200000),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', f'logs:{name}', 'read')
        return tail_log(name=name, limit=limit)

    @router.get('/v1/observability/metrics')
    def embedded_observability_metrics(
        since_hours: int = Query(default=24, ge=1, le=24 * 90),
        limit: int = Query(default=200, ge=1, le=1000),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability:metrics', 'read')
        payload = query_metrics(since_hours=since_hours, limit=limit)
        payload['tool_pipeline'] = pipeline_metrics_snapshot()
        payload['playbooks'] = playbook_metrics_snapshot(limit=200)
        return payload

    @router.get('/v1/observability/playbooks')
    def playbook_observability(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability:playbooks', 'read')
        return {'playbooks': playbook_metrics_snapshot(limit=500)}

    @router.get('/v1/observability/tool-pipeline')
    def tool_pipeline_metrics(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability:tool-pipeline', 'read')
        return pipeline_metrics_snapshot()

    @router.get('/v1/observability/traces')
    def embedded_observability_traces(
        since_hours: int = Query(default=24, ge=1, le=24 * 90),
        limit: int = Query(default=80, ge=1, le=500),
        trace_id: str | None = Query(default=None),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability:traces', 'read')
        return query_traces(since_hours=since_hours, limit=limit, trace_id=trace_id)

    @router.post('/v1/observability/prune')
    def embedded_observability_prune(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'diagnostics', 'observability:prune', 'write')
        return prune_observability_store()

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
