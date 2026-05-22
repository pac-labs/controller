from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header


AuthDependency = Callable[..., Any]
ConfigPayloadProvider = Callable[[Any | None], dict[str, Any]]
NoArgDictProvider = Callable[[], dict[str, Any]]
NoArgListProvider = Callable[[], list[Any]]
RunnerAuthProvider = Callable[[str | None, str | None, str | None], Any]

NOISY_EVENT_TYPES = {'runner_heartbeat', 'endpoint_heartbeat', 'provider_heartbeat'}


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
            'component_health': component_health,
            'alerts': alerts,
            'alert_counts': alert_counts,
        }

    @router.get('/v1/config')
    def get_config(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
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
        return setup_status()

    return router
