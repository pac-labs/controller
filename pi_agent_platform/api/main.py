from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import shlex
import subprocess
import tempfile
import tarfile
import threading
import time
import sys
import uuid
import zipfile
import socket
import ipaddress
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import AppConfig, ProviderConfig, AgentProfile, WorkspaceProfile, SourceContextConfig, save_config, load_config, default_config_path, MAIN_PI_DEV_PROFILE, AGENT_CONTROL_WORKSPACE, MODEL_NOT_SELECTED, CODING_SESSION_PERMISSION_PROFILE
from pi_agent_platform.api.routes.auth import create_auth_router, public_user, public_group
from pi_agent_platform.api.routes.marketplace import create_marketplace_router
from pi_agent_platform.api.routes.mcp import create_mcp_router
from pi_agent_platform.api.routes.system import create_system_router
from pi_agent_platform.api.routes.endpoints import create_endpoints_router
from pi_agent_platform.api.routes.providers import create_providers_router
from pi_agent_platform.api.routes.proxy import create_proxy_router
from pi_agent_platform.api.routes.server_config import create_server_config_router
from pi_agent_platform.api.routes.package_upload import create_package_upload_router
from pi_agent_platform.api.routes.service_runtime import create_service_runtime_router
from pi_agent_platform.api.routes.sources import create_sources_router
from pi_agent_platform.api.routes.sessions import create_sessions_router
from pi_agent_platform.api.routes import sessions as session_routes
from pi_agent_platform.api.routes.updates import create_updates_router
from pi_agent_platform.api.routes.ui import register_ui_routes
from pi_agent_platform.api.routes.version import create_version_router
from pi_agent_platform.api.routes.workspaces import (
    AgentContextPayload,
    SharedStoragePayload,
    UserWorkspacePayload,
    create_workspaces_router,
)
from pi_agent_platform.core.platform_home import ensure_pacp_layout, pacp_path
from pi_agent_platform.core.models import AccessRequest, AccessRequestStatus, AgentContext, Event, Group, ResourceGrant, Session, SessionCreate, Task, TaskCreate, TaskStatus, SessionStatus, Runner, RunnerCreateRequest, RunnerRegisterRequest, RunnerHeartbeat, RunnerStatus, RunnerJobCreate, RunnerJob, RunnerJobStatus, RunnerJobUpdate, RunnerJobLog, RunnerExecutionMode, User, UserWorkspace, WorkspaceSpec
from pi_agent_platform.core.runtime import git_diff, git_status, run_shell_task
from pi_agent_platform.core.agent_loop import run_agent_loop, execute_tool
from pi_agent_platform.core.session_commands import list_session_slash_commands, parse_session_slash_command, slash_help_text
from pi_agent_platform.core.subagents import spawn_pi_dev_subagent
from pi_agent_platform.core.runner_discovery import discover_host, discover_containers
from pi_agent_platform.core.maintenance import run_endpoint_maintenance
from pi_agent_platform.core.providers import effective_context, model_card, provider_public, test_model, test_provider, list_provider_models, sync_models_from_provider, lmstudio_inspect_provider, lmstudio_load_model, lmstudio_unload_model, lmstudio_download_model, lmstudio_companion_script
from pi_agent_platform.core.store import store
from pi_agent_platform.core.artifacts import write_artifact, list_artifacts, task_artifact_dir, safe_artifact_path
from pi_agent_platform.core.secrets import secret_store
from pi_agent_platform.core.pac_ram import read_ram, write_ram, list_ram, all_ram, bundle_ram, search_ram
from pi_agent_platform.core.source_variables import source_variable_store
from pi_agent_platform.core.source_library import ensure_source_library, list_tree as source_list_tree, read_text as source_read_text, write_text as source_write_text, make_archive as source_make_archive, build_container as source_build_container, build_binary as source_build_binary, list_binary_artifacts as source_list_binary_artifacts, binary_artifact_path as source_binary_artifact_path, delete_binary_artifact as source_delete_binary_artifact, prune_binary_artifacts as source_prune_binary_artifacts, inspect_feature_pack as source_inspect_feature_pack, apply_feature_pack as source_apply_feature_pack, create_entry as source_create_entry, rename_entry as source_rename_entry, delete_entry as source_delete_entry, fetch_online_package_updates as source_fetch_online_package_updates
from pi_agent_platform.core.update_preservation import TRACKED_ROOTS, build_backup_archive, compare_trees, generate_local_diff, list_generated_diffs
from pi_agent_platform.updates import fetch_latest_release_metadata, download_release_package
from pi_agent_platform.core.shared_storage import SharedStorage, controller_storage_path, public_shared_storage, shared_storage_binding
from pi_agent_platform.core.letsencrypt_cert import (
    issue_letsencrypt_certificate,
    get_letsencrypt_status,
    check_domain_dns,
)
from pi_agent_platform.core.dns_providers import test_cloudflare_credentials
from pi_agent_platform.core.config import LetsEncryptConfig


def _model_available(model_name: str) -> tuple[bool, str | None]:
    model = config.models.get(model_name)
    if not model:
        return False, 'model is not configured'
    provider = config.providers.get(model.provider)
    if not provider:
        return False, f'provider is not configured: {model.provider}'
    if provider.enabled is False or provider.status in {'disabled', 'failed'}:
        return False, f'provider is not connected: {model.provider} ({provider.status})'
    cached = getattr(provider, 'cached_models', []) or []
    if cached:
        wanted = model.model or model_name
        ids = {str(item.get('id') or item.get('name') or item.get('model')) for item in cached if isinstance(item, dict)}
        if str(wanted) not in ids:
            return False, f'model is not in live provider model list: {wanted}'
    return True, None


def _acquire_single_instance_lock() -> object:
    """Prevent two PAC servers from using the same ~/.pacp state."""
    home = ensure_pacp_layout()
    lock_path = pacp_path('run', 'server.lock')
    lock_file = lock_path.open('w')
    try:
        import fcntl
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        existing = lock_path.read_text(encoding='utf-8', errors='ignore').strip()
        raise RuntimeError(f'PAC is already running for {home}. Lock: {lock_path}. {existing}') from exc
    except Exception:
        # Windows/limited platforms: keep going, but still write PID.
        pass
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f'pid={os.getpid()}\nhome={home}\n')
    lock_file.flush()
    return lock_file


_SINGLE_INSTANCE_LOCK = _acquire_single_instance_lock()

_CONTROLLER_WRAPPER_PROC: subprocess.Popen[str] | None = None
_CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE = False
_LAST_CONTROLLER_WRAPPER_EVENT_SIGNATURE: str | None = None
_LAST_CONTROLLER_WRAPPER_RUNNING_STATE: bool | None = None
_CONTROLLER_PI_CONTAINER_NAME = "pac-pi-dev-controller"

def _read_pac_version() -> str:
    # GitHub release builds are the version authority. The workflow writes the
    # tag version into VERSION before packaging, while service environments may
    # also inject PAC_VERSION/PAC_RELEASE_VERSION for containerized runs. Prefer
    # those explicit runtime values, then fall back to packaged markers.
    for env_name in ('PAC_VERSION', 'PAC_RELEASE_VERSION', 'GITHUB_REF_NAME'):
        value = os.environ.get(env_name, '').strip()
        if value:
            return value[1:] if value.startswith('v') and re.match(r'^v\d+\.\d+\.\d+$', value) else value
    for candidate in [Path(__file__).resolve().parents[2] / 'VERSION', Path(__file__).resolve().parents[2] / 'VERSION_CURRENT.md', Path(__file__).resolve().parents[1] / 'VERSION']:
        try:
            if candidate.exists():
                lines = [line.strip() for line in candidate.read_text(encoding='utf-8').splitlines() if line.strip()]
                if not lines:
                    continue
                value = lines[0]
                if not re.match(r'^\d+\.\d+\.\d+$', value) and len(lines) > 1:
                    for line in lines[1:]:
                        match = re.search(r'(\d+\.\d+\.\d+)', line)
                        if match:
                            value = match.group(1)
                            break
                if value:
                    return value[1:] if value.startswith('v') and re.match(r'^v\d+\.\d+\.\d+$', value) else value
        except Exception:
            pass
    return 'dev'


config = load_config()
PAC_VERSION = _read_pac_version()
SESSION_CAPABLE_PROVIDER_TYPES = {"openai", "openai-codex", "openai-compatible", "lmstudio", "vllm", "groq", "openrouter", "deepseek", "mistral", "ollama"}


def _web_dir() -> Path:
    return Path(__file__).resolve().parents[1] / 'web'


def _ui_build_info() -> dict[str, Any]:
    files = [
        _web_dir() / 'index.html',
        _web_dir() / 'app.js',
        _web_dir() / 'styles.css',
        _web_dir() / 'assets' / 'logo.png',
        _web_dir() / 'assets' / 'pac-banner-green.png',
        _web_dir() / 'assets' / 'pac-icon-green.png',
        _web_dir() / 'assets' / 'pac-icon-green-128.png',
        _web_dir() / 'assets' / 'pac-icon-green-32.png',
        _web_dir() / 'assets' / 'pac-logo-lockup-transparent.png',
        _web_dir() / 'assets' / 'pac-logo-compact-transparent.png',
        _web_dir() / 'assets' / 'pac-brand-mark-transparent-128.png',
        _web_dir() / 'assets' / 'pac-brand-mark-transparent-32.png',
    ]
    digest = hashlib.sha1()
    latest_mtime = 0.0
    for path in files:
        if not path.exists():
            continue
        stat = path.stat()
        latest_mtime = max(latest_mtime, stat.st_mtime)
        digest.update(path.name.encode('utf-8'))
        digest.update(str(int(stat.st_mtime)).encode('utf-8'))
        digest.update(str(stat.st_size).encode('utf-8'))
    stamp = f'{PAC_VERSION}-{digest.hexdigest()[:10]}'
    updated_at = datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat().replace('+00:00', 'Z') if latest_mtime else None
    return {'asset_stamp': stamp, 'updated_at': updated_at}


def _render_web_index() -> HTMLResponse:
    info = _ui_build_info()
    html = (_web_dir() / 'index.html').read_text(encoding='utf-8')
    replacements = {
        '/ui/styles.css': f"/ui/styles.css?v={info['asset_stamp']}",
        '/ui/app.js': f"/ui/app.js?v={info['asset_stamp']}",
        '/ui/assets/pac-brand-mark-transparent-32.png': f"/ui/assets/pac-brand-mark-transparent-32.png?v={info['asset_stamp']}",
        '/ui/assets/pac-icon-green-32.png': f"/ui/assets/pac-icon-green-32.png?v={info['asset_stamp']}",
        '/ui/assets/pac-icon-green-128.png': f"/ui/assets/pac-icon-green-128.png?v={info['asset_stamp']}",
        '/ui/assets/pac-icon-green.png': f"/ui/assets/pac-icon-green.png?v={info['asset_stamp']}",
        '/ui/assets/pac-banner-green.png': f"/ui/assets/pac-banner-green.png?v={info['asset_stamp']}",
        '/ui/assets/logo.png': f"/ui/assets/logo.png?v={info['asset_stamp']}",
        '/ui/assets/pac-logo-lockup-transparent.png': f"/ui/assets/pac-logo-lockup-transparent.png?v={info['asset_stamp']}",
        '/ui/assets/pac-logo-compact-transparent.png': f"/ui/assets/pac-logo-compact-transparent.png?v={info['asset_stamp']}",
        '/ui/assets/pac-brand-mark-transparent-128.png': f"/ui/assets/pac-brand-mark-transparent-128.png?v={info['asset_stamp']}",
        '/ui/assets/pac-loader.svg': f"/ui/assets/pac-loader.svg?v={info['asset_stamp']}",
    }
    for source, target in replacements.items():
        html = html.replace(source, target)
    return HTMLResponse(html, headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'})


def _version_key(value: str | None) -> tuple[int, ...]:
    text = str(value or '').strip().lstrip('v')
    parts: list[int] = []
    for token in text.split('.'):
        match = re.match(r'^(\d+)', token)
        parts.append(int(match.group(1)) if match else 0)
    return tuple(parts or [0])


def _load_pac_changelog() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / 'PAC_CHANGELOG.json'
    if not path.exists():
        return {'entries': [], 'current_version': PAC_VERSION}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'entries': [], 'current_version': PAC_VERSION}


def _current_release_package() -> Path:
    root = Path(__file__).resolve().parents[2]
    dist_dir = root / 'dist'
    package = dist_dir / 'pac-full.zip'
    version_marker = dist_dir / '.pac-full.version'
    if package.exists() and version_marker.exists():
        try:
            if version_marker.read_text(encoding='utf-8').strip() == PAC_VERSION:
                return package
        except Exception:
            pass
    script = root / 'scripts' / 'generate-pac-release.py'
    if not script.is_file():
        raise RuntimeError('PAC release generator is not available on this installation')
    proc = subprocess.run(
        [sys.executable, str(script), '--version', PAC_VERSION],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0 or not package.exists():
        raise RuntimeError((proc.stderr or proc.stdout or 'PAC release generation failed').strip()[:4000])
    version_marker.write_text(PAC_VERSION, encoding='utf-8')
    return package


def _changelog_delta(from_version: str | None, to_version: str | None) -> list[dict[str, Any]]:
    changelog = _load_pac_changelog()
    lower = _version_key(from_version)
    upper = _version_key(to_version or changelog.get('current_version') or PAC_VERSION)
    entries = []
    for entry in changelog.get('entries', []) or []:
        version = str(entry.get('version') or '').strip()
        key = _version_key(version)
        if key > lower and key <= upper:
            entries.append(entry)
    return sorted(entries, key=lambda item: _version_key(item.get('version')), reverse=True)


def _compose_release_notes_body(entries: list[dict[str, Any]], compare_changes: list[str], body: str | None) -> str:
    sections: list[str] = []
    for entry in entries:
        version = str(entry.get('version') or '').strip()
        title = str(entry.get('title') or '').strip() or (f'PAC v{version}' if version else 'PAC release')
        changes = [str(item).strip() for item in (entry.get('changes') or []) if str(item).strip()]
        if not changes:
            continue
        sections.append(title)
        sections.extend([f'- {item}' for item in changes])
        sections.append('')
    if compare_changes:
        sections.append('Git compare summary')
        sections.extend([f'- {item}' for item in compare_changes if str(item).strip()])
        sections.append('')
    raw = str(body or '').strip()
    if raw:
        sections.append('Release notes')
        sections.append(raw)
    return '\n'.join(line for line in sections).strip()


def _update_backups_root() -> Path:
    root = pacp_path('backups')
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_diffs_root() -> Path:
    root = _app_dir() / '.pac' / 'diffs'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _suggest_next_version(version: str | None) -> str:
    raw = str(version or '').strip().lstrip('v')
    parts = raw.split('.')
    if len(parts) != 3:
        return raw or '1.0.0'
    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return raw
    return f'{major}.{minor}.{patch + 1}'


def _read_version_from_tree(app_dir: Path) -> str | None:
    for candidate in (app_dir / 'VERSION', app_dir / 'VERSION_CURRENT.md'):
        try:
            if candidate.exists():
                lines = [line.strip() for line in candidate.read_text(encoding='utf-8').splitlines() if line.strip()]
                if lines:
                    return lines[0].lstrip('v')
        except Exception:
            continue
    return None


def _list_update_archives() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in sorted(_update_backups_root().iterdir(), key=lambda path: path.name, reverse=True):
        if not entry.is_dir():
            continue
        summary_path = entry / 'change-summary.json'
        summary = None
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding='utf-8'))
            except Exception:
                summary = None
        diff_file = next((path for path in entry.glob('*.diff') if path.is_file()), None)
        archive_file = entry / 'backup.tar.gz'
        items.append(
            {
                'stamp': entry.name,
                'archive_path': str(archive_file) if archive_file.exists() else None,
                'archive_size': archive_file.stat().st_size if archive_file.exists() else 0,
                'diff_path': str(diff_file) if diff_file else None,
                'diff_size': diff_file.stat().st_size if diff_file else 0,
                'summary_path': str(summary_path) if summary_path.exists() else None,
                'summary': summary,
                'created_at': summary.get('generated_at') if isinstance(summary, dict) else None,
            }
        )
    return items


_SOURCE_VARIABLE_REF = re.compile(r"\$\{var:([A-Za-z_][A-Za-z0-9_.-]*)\}|\{\{var:([A-Za-z_][A-Za-z0-9_.-]*)\}\}")


def _resolve_variable_tokens(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    resolved: dict[str, str] = {}
    used: dict[str, str] = {}

    for key, raw in (values or {}).items():
        text = str(raw or "")

        def _replace(match: re.Match[str]) -> str:
            variable_id = str(match.group(1) or match.group(2) or "").strip()
            item = source_variable_store.get(variable_id)
            if not item:
                return match.group(0)
            used[variable_id] = str(item.get("value") or "")
            return used[variable_id]

        resolved[key] = _SOURCE_VARIABLE_REF.sub(_replace, text)
    return resolved, used


def _setup_issue(issue_id: str, title: str, detail: str, action_tab: str, action_label: str, severity: str = 'required') -> dict[str, str]:
    return {
        'id': issue_id,
        'title': title,
        'detail': detail,
        'action_tab': action_tab,
        'action_label': action_label,
        'severity': severity,
    }


def _setup_status() -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    enabled_providers = {name: provider for name, provider in (config.providers or {}).items() if getattr(provider, 'enabled', False)}
    session_capable_models = []
    unsupported_models = []
    for name, model in (config.models or {}).items():
        provider = config.providers.get(model.provider)
        provider_type = provider.type if provider else None
        if provider and provider_type in SESSION_CAPABLE_PROVIDER_TYPES:
            session_capable_models.append(name)
        else:
            unsupported_models.append({'model': name, 'provider': model.provider, 'provider_type': provider_type or 'unknown'})

    if not config.models:
        issues.append(_setup_issue('no_models', 'Configure at least one model', 'PAC cannot start agent-backed sessions until a model is configured.', 'models-tab', 'Open Models'))
    if config.models and not enabled_providers:
        issues.append(_setup_issue('no_enabled_providers', 'Connect at least one provider', 'Models exist, but no provider is enabled. PAC cannot call a model provider yet.', 'providers-tab', 'Open Providers'))
    if config.models and not session_capable_models:
        issues.append(_setup_issue('no_session_capable_models', 'Add one session-capable model', 'Configured models only reference provider types that the agent loop cannot use yet.', 'models-tab', 'Review Models'))
    if config.controller_harness.enabled:
        model_name, profile_name, _permission = _harness_model_and_profile()
        if not model_name or model_name not in config.models:
            issues.append(_setup_issue('controller_model_missing', 'Select the controller pi.dev model', f'The controller pi.dev runtime is enabled, but profile {profile_name or MAIN_PI_DEV_PROFILE} does not resolve to a configured model.', 'settings:pi-dev', 'Open pi.dev Settings'))
        controller = next((runner for runner in store.list_runners() if _runner_bool(runner.metadata or {}, 'local_control_plane', 'controller_pi_dev')), None)
        controller_meta = (controller.metadata or {}) if controller else {}
        wrapper_version = str(controller_meta.get('runner_version') or controller_meta.get('endpoint_version') or '').strip()
        if wrapper_version and wrapper_version != PAC_VERSION:
            issues.append(_setup_issue('controller_wrapper_version_mismatch', 'Update the local PAC wrapper binary', f'The controller wrapper reports version {wrapper_version}, but the PAC server is running {PAC_VERSION}. Update the local wrapper before trusting controller pi.dev readiness.', 'settings:pi-dev', 'Open pi.dev Settings'))
    if config.auth.enabled and config.auth.mode == 'dev-token' and str(config.auth.dev_token or '').strip() in {'', 'change-me'}:
        issues.append(_setup_issue('dev_token_default', 'Replace the default bearer token', 'Authentication is enabled, but the bearer token is still the default placeholder.', 'settings-tab', 'Open Settings'))
    if unsupported_models:
        warnings.append(_setup_issue('unsupported_models_present', 'Some configured models are not session-capable yet', f'{len(unsupported_models)} model(s) point at provider types that are not supported by the current agent loop.', 'models-tab', 'Review Models', severity='warning'))
    return {
        'ok': not issues,
        'version': PAC_VERSION,
        'required_issues': issues,
        'warnings': warnings,
        'session_capable_provider_types': sorted(SESSION_CAPABLE_PROVIDER_TYPES),
        'session_capable_models': session_capable_models,
        'enabled_provider_count': len(enabled_providers),
        'configured_model_count': len(config.models or {}),
    }


def _platform_alerts(runners: list[Runner] | None = None) -> list[dict[str, Any]]:
    runners = runners or store.list_runners()
    alerts: list[dict[str, Any]] = []
    controller = next((runner for runner in runners if _runner_bool(runner.metadata or {}, 'local_control_plane', 'controller_pi_dev')), None)
    if config.controller_harness.enabled:
        if not controller:
            alerts.append({'id': 'controller_runner_missing', 'severity': 'critical', 'component': 'controller', 'title': 'Controller pi.dev endpoint is missing', 'detail': 'The local PAC endpoint for controller pi.dev is not registered.', 'metric': 'controller.runner_missing'})
        else:
            meta = controller.metadata or {}
            wrapper_process = meta.get('pac_wrapper_process') or {}
            pi_daemon = meta.get('pi_dev_daemon') or {}
            wrapper_version = str(meta.get('runner_version') or meta.get('endpoint_version') or '').strip()
            if wrapper_version and wrapper_version != PAC_VERSION:
                alerts.append({'id': 'controller_wrapper_version_mismatch', 'severity': 'critical', 'component': 'controller', 'title': 'Controller wrapper version mismatch', 'detail': f'PAC server is {PAC_VERSION}, but the local wrapper reports {wrapper_version}.', 'metric': 'controller.wrapper_version_mismatch', 'expected_version': PAC_VERSION, 'actual_version': wrapper_version})
            if not bool(wrapper_process.get('running')):
                alerts.append({'id': 'controller_wrapper_stopped', 'severity': 'warning', 'component': 'controller', 'title': 'Controller wrapper is not running', 'detail': 'The local PAC wrapper process is required before controller pi.dev sessions can execute.', 'metric': 'controller.wrapper_stopped'})
            if not bool(pi_daemon.get('running')):
                alerts.append({'id': 'controller_pi_dev_daemon_stopped', 'severity': 'warning', 'component': 'controller', 'title': 'pi.dev daemon is not running', 'detail': 'The local pi.dev daemon/container is required before controller harness-backed workloads can run.', 'metric': 'controller.pi_dev_daemon_stopped'})
    return alerts


def _config_payload() -> dict[str, Any]:
    return {
        'server': config.server.model_dump(),
        'runtime': config.runtime.model_dump(),
        'controller_harness': config.controller_harness.model_dump(exclude={'service_token'}),
        'source_updates': config.source_updates.model_dump(),
        'auth': config.auth.model_dump(exclude={'dev_token'}),
        'tls': config.tls.model_dump() if hasattr(config, 'tls') else {},
        'service': config.service.model_dump() if hasattr(config, 'service') else {'mode': 'user', 'name': 'pacp'},
        'providers': provider_public(config),
        'context_profiles': {name: cp.model_dump() for name, cp in config.context_profiles.items()},
        'permission_profiles': {name: p.model_dump() for name, p in config.permission_profiles.items()},
        'agent_profiles': {name: p.model_dump() for name, p in config.agent_profiles.items()},
        'workspaces': {name: w.model_dump() for name, w in config.workspaces.items()},
        'source_contexts': {name: ctx.model_dump() for name, ctx in config.source_contexts.items()},
        'models': {name: model.model_dump() for name, model in config.models.items()},
        'tools': {name: tool.model_dump() for name, tool in config.tools.items()},
        'tool_packages': {name: pkg.model_dump() for name, pkg in config.tool_packages.items()},
        'plugins': {name: plugin.model_dump() for name, plugin in config.plugins.items()},
        'session_slash_commands': list_session_slash_commands(),
        'pacp': {'home': str(ensure_pacp_layout()), 'config_path': str(default_config_path()), 'single_instance_lock': str(pacp_path('run', 'server.lock'))},
        'setup_status': _setup_status(),
    }


def _runner_bool(metadata: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if metadata.get(key):
            return True
    return False


def _metrics_component_health(runners: list[Runner]) -> dict[str, Any]:
    provider_status = {'total': len(config.providers or {}), 'enabled': 0, 'connected': 0, 'failed': 0, 'disabled': 0, 'unknown': 0}
    for provider in (config.providers or {}).values():
        if getattr(provider, 'enabled', False):
            provider_status['enabled'] += 1
        state = str(getattr(provider, 'status', 'unknown') or 'unknown')
        provider_status[state if state in provider_status else 'unknown'] = provider_status.get(state if state in provider_status else 'unknown', 0) + 1

    model_status = {'total': len(config.models or {}), 'session_capable': 0, 'available': 0, 'unavailable': 0, 'unsupported_provider': 0}
    for name, model in (config.models or {}).items():
        provider = config.providers.get(model.provider)
        provider_type = provider.type if provider else None
        if provider and provider_type in SESSION_CAPABLE_PROVIDER_TYPES:
            model_status['session_capable'] += 1
        else:
            model_status['unsupported_provider'] += 1
        available, _reason = _model_available(name)
        if available:
            model_status['available'] += 1
        else:
            model_status['unavailable'] += 1

    endpoint_status = {'total': len(runners), 'online': 0, 'offline': 0, 'agent_ready': 0, 'agent_blocked': 0, 'gpu_capable': 0, 'pi_dev_ready': 0}
    for runner in runners:
        status = getattr(runner.status, 'value', str(runner.status))
        if status == 'online':
            endpoint_status['online'] += 1
        else:
            endpoint_status['offline'] += 1
        meta = runner.metadata or {}
        agent_runtime = meta.get('agent_runtime') or {}
        if str(agent_runtime.get('status') or '') == 'ready':
            endpoint_status['agent_ready'] += 1
        elif meta.get('agent_requested') or meta.get('agent_enabled'):
            endpoint_status['agent_blocked'] += 1
        runtime = meta.get('provider_runtime') or meta.get('detected_runtime') or {}
        device = runtime.get('device') or {}
        accelerators = runtime.get('accelerators') or []
        if str(device.get('category') or '').lower() == 'gpu' or any('gpu' in str(item).lower() for item in accelerators):
            endpoint_status['gpu_capable'] += 1
        pi_daemon = meta.get('pi_dev_daemon') or {}
        if bool(pi_daemon.get('running')) or bool(meta.get('pi_container_available')):
            endpoint_status['pi_dev_ready'] += 1

    setup = _setup_status()
    secrets = secret_store.status()
    ram = list_ram()
    archives = _list_update_archives()
    diffs = list_generated_diffs(_local_diffs_root())
    controller = next((runner for runner in runners if _runner_bool(runner.metadata or {}, 'local_control_plane', 'controller_pi_dev')), None)
    controller_meta = (controller.metadata or {}) if controller else {}
    controller_runtime = controller_meta.get('agent_runtime') or {}
    controller_wrapper = controller_meta.get('pac_wrapper_process') or {}
    controller_pi = controller_meta.get('pi_dev_daemon') or {}
    return {
        'providers': provider_status,
        'models': model_status,
        'endpoints': endpoint_status,
        'setup': {
            'ready': bool(setup.get('ok')),
            'required_issues': len(setup.get('required_issues') or []),
            'warnings': len(setup.get('warnings') or []),
        },
        'secrets': secrets,
        'source': {
            'contexts': len(config.source_contexts or {}),
            'variables': len(source_variable_store.list()),
            'ram_profiles': len(ram.get('profiles') or []),
            'ram_users': len(ram.get('users') or []),
            'ram_workspaces': len(ram.get('workspaces') or []),
        },
        'updates': {
            'archives': len(archives),
            'local_diffs': len(diffs),
        },
        'controller': {
            'enabled': bool(config.controller_harness.enabled),
            'session_name': config.controller_harness.session_name,
            'runtime_status': controller_runtime.get('status') or ('disabled' if not config.controller_harness.enabled else 'unknown'),
            'wrapper_running': bool(controller_wrapper.get('running')),
            'pi_dev_running': bool(controller_pi.get('running')),
            'wrapper_version': str(controller_meta.get('runner_version') or controller_meta.get('endpoint_version') or ''),
            'endpoint_id': controller.id if controller else config.controller_harness.runner_id,
        },
    }

def _runtime_agent_state(kind: str, status: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {'kind': kind, 'status': status, 'version': PAC_VERSION}
    if detail:
        data['detail'] = detail
    data.update({k: v for k, v in extra.items() if v is not None})
    return data


def _platform_workspace_path() -> str:
    return str(Path(__file__).resolve().parents[2])


def _ensure_platform_plugin_sources() -> dict[str, Any]:
    root = Path(_platform_workspace_path())
    plugins_root = root / 'plugins'
    plugins_root.mkdir(parents=True, exist_ok=True)
    ids = sorted(set([*(config.tools or {}).keys(), *(config.plugins or {}).keys()]))
    created: list[str] = []
    for tool_id in ids:
        tool_dir = plugins_root / str(tool_id)
        tool_dir.mkdir(parents=True, exist_ok=True)
        readme = tool_dir / 'README.md'
        if not readme.exists():
            readme.write_text(
                f"# {tool_id}\n\n"
                f"Agent tool source for `{tool_id}` inside the PAC platform workspace.\n\n"
                "Use this folder for prompts, helper code, docs, or endpoint-side source related to this tool.\n"
            )
            created.append(f'plugins/{tool_id}/README.md')
    return {'root': str(plugins_root), 'created': created}


def _ensure_controller_harness_runner() -> Runner:
    settings = config.controller_harness
    # The PAC controller is already represented by the local endpoint. Do not
    # create a second controller/pi.dev endpoint; enrich the existing local
    # endpoint with the controller pi.dev role instead.
    if settings.runner_id != 'local-PAC':
        settings.runner_id = 'local-PAC'
        save_config(config)
    legacy = store.get_runner('controller-pi-dev')
    if legacy and legacy.id != settings.runner_id:
        store.delete_runner(legacy.id)
        store.add_event(Event(session_id='system', type='controller_pi_dev_endpoint_merged', message='Merged duplicate controller pi.dev endpoint into the local PAC endpoint', data={'from': legacy.id, 'to': settings.runner_id}))
    runner = _refresh_local_runner_metadata(emit_event=False) if settings.runner_id == 'local-PAC' else (store.get_runner(settings.runner_id) or _refresh_local_runner_metadata(emit_event=False))
    labels = ['controller', 'local', 'pac-controller', 'pi.dev']
    metadata = {
        'kind': 'pi_dev_controller',
        'runtime': settings.runtime,
        'deployment_mode': settings.deployment_mode,
        'wrapper': settings.wrapper,
        'managed': True,
        'controller_pi_dev': True,
        'pi_dev_required': True,
        'default_workspace': settings.workspace_profile,
        'agent_enabled': True,
        'agent_requested': True,
        'platform_workspace': _platform_workspace_path(),
        'agent_tools': list(config.tools.keys()) if settings.expose_platform_tools else [],
    }
    capabilities = {
        'controller_harness': True,
        'workspace_root': _platform_workspace_path(),
        'can_run_local_commands': True,
        'can_access_controller_config': True,
        'can_access_source_library': True,
    }
    runner.status = RunnerStatus.online
    runner.name = runner.name or 'local-PAC'
    runner.labels = sorted(set(list(runner.labels or []) + labels))
    runner.endpoint = 'local://PAC'
    runner.allow_host_execution = True
    runner.allow_container_execution = True
    runner.capabilities.update(capabilities)
    runner.metadata.update(metadata)
    runner.last_seen_at = datetime.now(timezone.utc)
    runner = _normalise_endpoint_metadata(runner, True)
    store.add_runner(runner)
    return runner


def _ensure_controller_harness_workspace() -> WorkspaceProfile:
    settings = config.controller_harness
    workspace = config.workspaces.get(settings.workspace_profile)
    if not workspace:
        workspace = WorkspaceProfile(
            description='Agent control workspace: the PAC controller application/source tree used by the main pi.dev runtime.',
            type='local',
            path=_platform_workspace_path(),
            default_agent_profile=settings.agent_profile,
            endpoint_id=settings.runner_id,
            endpoint_selector='controller',
            runtime='local',
            ephemeral=False,
            is_default=True,
        )
        config.workspaces[settings.workspace_profile] = workspace
        save_config(config)
    else:
        changed = False
        if not workspace.path:
            workspace.path = _platform_workspace_path(); changed = True
        if not workspace.endpoint_id:
            workspace.endpoint_id = settings.runner_id; changed = True
        if not workspace.endpoint_selector:
            workspace.endpoint_selector = 'controller'; changed = True
        if not workspace.default_agent_profile and settings.agent_profile:
            workspace.default_agent_profile = settings.agent_profile; changed = True
        if changed:
            save_config(config)
    return workspace


def _harness_model_and_profile() -> tuple[str | None, str | None, str | None]:
    settings = config.controller_harness
    profile_name = settings.agent_profile or MAIN_PI_DEV_PROFILE
    profile = config.agent_profiles.get(profile_name) if profile_name else None
    model_name = settings.model or (profile.model if profile else None)
    if model_name == MODEL_NOT_SELECTED:
        model_name = None
    permission = settings.permission_profile or (profile.permission_profile if profile else 'ask-first')
    return model_name, profile_name, permission


def _find_controller_harness_session() -> Session | None:
    for session in store.list_sessions():
        if session.metadata.get('controller_harness') is True:
            return session
    return None


def _ensure_controller_harness_session() -> dict[str, Any]:
    settings = config.controller_harness
    if not settings.enabled:
        return {'ok': True, 'enabled': False, 'message': 'Controller pi.dev runtime is disabled'}
    runner = _ensure_controller_harness_runner()
    workspace = _ensure_controller_harness_workspace()
    model_name, profile_name, permission = _harness_model_and_profile()
    profile = config.agent_profiles.get(profile_name) if profile_name else None
    desired_context_mode = (profile.context_mode if profile and getattr(profile, 'context_mode', None) else settings.context_mode) or 'medium'
    existing = _find_controller_harness_session()
    _ensure_auth_admin_scaffolding()
    system_context = _find_pac_system_context()
    pac_wrapper = (runner.capabilities or {}).get('pac_wrapper') or {}
    if not pac_wrapper.get('available'):
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': pac_wrapper.get('reason') or 'The main server requires the local PAC wrapper before the controller session can run.'}
    pi_container = (runner.capabilities or {}).get('pi_container') or {}
    if not (pi_container.get('image_available') or pi_container.get('available')):
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': pi_container.get('reason') or 'The main server requires the local pi.dev runtime image before the controller session can run.'}
    wrapper_process = (runner.metadata or {}).get('pac_wrapper_process') or {}
    if not wrapper_process.get('running'):
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': 'The main server requires the local PAC wrapper process to be running before the controller session can run.'}
    pi_daemon = (runner.metadata or {}).get('pi_dev_daemon') or {}
    if not pi_daemon.get('running'):
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': pi_daemon.get('reason') or 'The main server requires the local pi.dev daemon container to be running before the controller session can run.'}
    if not settings.auto_create_session:
        return {'ok': True, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': 'Controller pi.dev runtime is ready; auto session is disabled'}
    if not model_name:
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': 'Select a model for the main pi.dev profile in Settings'}
    if model_name not in config.models:
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': f'Configured pi.dev model is missing: {model_name}'}
    if permission not in config.permission_profiles:
        permission = 'ask-first'
    if existing:
        changed = False
        if existing.model != model_name:
            existing.model = model_name; changed = True
        if existing.agent_profile != profile_name:
            existing.agent_profile = profile_name; changed = True
        if existing.permission_profile != permission:
            existing.permission_profile = permission; changed = True
        if existing.context_mode != desired_context_mode:
            existing.context_mode = desired_context_mode; changed = True
        if existing.workspace_path != (workspace.path or _platform_workspace_path()):
            existing.workspace_path = workspace.path or _platform_workspace_path(); changed = True
        desired_tools = list(config.tools.keys()) if settings.expose_platform_tools else []
        if existing.tools != desired_tools:
            existing.tools = desired_tools; changed = True
        existing.workspace = existing.workspace.model_copy(update={'type': 'profile', 'profile': settings.workspace_profile, 'path': workspace.path})
        desired_metadata = {'controller_harness': True, 'preferred_endpoint': settings.runner_id, 'endpoint_locked': True, 'agent_enabled': True, 'execution_mode': 'pi.dev'}
        if system_context:
            desired_metadata.update({
                'agent_context_id': system_context.id,
                'agent_context_name': system_context.name,
                'agent_context_kind': system_context.kind,
                'system_context': True,
            })
        for key, value in desired_metadata.items():
            if existing.metadata.get(key) != value:
                existing.metadata[key] = value
                changed = True
        if changed:
            existing.touch()
            store.add_session(existing)
        if system_context and system_context.last_session_id != existing.id:
            system_context.last_session_id = existing.id
            store.add_agent_context(system_context)
        return {'ok': True, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump(), 'message': 'Controller pi.dev session is active'}
    session = Session(
        name=settings.session_name,
        agent_profile=profile_name,
        permission_profile=permission,
        context_mode=desired_context_mode,
        workspace={'type': 'profile', 'profile': settings.workspace_profile, 'path': workspace.path},
        workspace_path=workspace.path or _platform_workspace_path(),
        model=model_name,
        tools=list(config.tools.keys()) if settings.expose_platform_tools else [],
        metadata={
            'controller_harness': True,
            'preferred_endpoint': settings.runner_id,
            'endpoint_locked': True,
            'agent_enabled': True,
            'execution_mode': 'pi.dev',
            **({
                'agent_context_id': system_context.id,
                'agent_context_name': system_context.name,
                'agent_context_kind': system_context.kind,
                'system_context': True,
            } if system_context else {}),
        },
    )
    Path(session.workspace_path).mkdir(parents=True, exist_ok=True)
    store.add_session(session)
    if system_context and system_context.last_session_id != session.id:
        system_context.last_session_id = session.id
        store.add_agent_context(system_context)
    store.add_event(Event(session_id=session.id, type='controller_harness_started', message='Controller pi.dev session created', data={'workspace_path': session.workspace_path, 'runner_id': settings.runner_id, 'model': model_name, 'agent_profile': profile_name}))
    return {'ok': True, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': session.model_dump(), 'message': 'Controller pi.dev session created'}

app = FastAPI(title='PAC - Pi Agent Control', version=PAC_VERSION)
_MDNS_ZEROCONF = None
_MDNS_SERVICE_INFO = None
_MDNS_STATUS: dict[str, Any] = {'state': 'stopped', 'message': 'mDNS has not started yet'}
_SOURCE_BUILD_ACTIVE: dict[str, Any] | None = None
_BOOTSTRAP_ACTIVE = False


def _host_binary_target() -> str:
    system = platform.system().lower()
    goos = {'linux': 'linux', 'darwin': 'darwin', 'windows': 'windows'}.get(system, system or 'linux')
    machine = platform.machine().lower()
    if machine in {'x86_64', 'amd64'}:
        goarch = 'amd64'
    elif machine in {'aarch64', 'arm64'}:
        goarch = 'arm64'
    elif machine.startswith('armv7') or machine == 'arm':
        goarch = 'arm'
    else:
        goarch = machine or 'amd64'
    return f'{goos}/{goarch}'


def _controller_wrapper_path() -> Path:
    install_dir = Path(config.controller_harness.wrapper_install_dir).expanduser()
    name = config.controller_harness.wrapper_binary_name or 'pac-endpoint'
    if platform.system().lower() == 'windows' and not name.endswith('.exe'):
        name += '.exe'
    return install_dir / name


def _find_matching_binary_artifact(project: str, target: str) -> Path | None:
    goos, goarch = target.split('/', 1)
    root = pacp_path('source-builds', 'binaries', project)
    if not root.is_dir():
        return None
    suffix = f'-{goos}-{goarch}' + ('.exe' if goos == 'windows' else '')
    matches = [p for p in root.iterdir() if p.is_file() and p.name.startswith(project + '-') and p.name.endswith(suffix)]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _install_wrapper_artifact(project: str, artifact: Path) -> dict[str, Any]:
    target = _controller_wrapper_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.new')
    shutil.copy2(artifact, tmp)
    tmp.chmod(0o755)
    tmp.replace(target)
    return {'installed': True, 'project': project, 'source': str(artifact), 'path': str(target), 'size': target.stat().st_size}


def _ensure_controller_wrapper(allow_build: bool = True, force_rebuild: bool = False) -> dict[str, Any]:
    settings = config.controller_harness
    project = settings.wrapper_binary_project or 'pac-endpoint'
    target = _host_binary_target()
    wrapper_path = _controller_wrapper_path()
    if wrapper_path.is_file() and os.access(wrapper_path, os.X_OK) and not force_rebuild:
        return {'ok': True, 'status': 'ready', 'path': str(wrapper_path), 'target': target, 'message': 'PAC wrapper is installed.'}
    artifact = None if force_rebuild else _find_matching_binary_artifact(project, target)
    if artifact:
        installed = _install_wrapper_artifact(project, artifact)
        return {'ok': True, 'status': 'installed', 'target': target, 'message': 'PAC wrapper installed from existing artifact.', **installed}
    if not allow_build:
        return {'ok': False, 'status': 'missing', 'path': str(wrapper_path), 'target': target, 'message': 'PAC wrapper is missing and auto-build is disabled.'}
    old_build_server_url = os.environ.get('PAC_BUILD_SERVER_URL')
    compiled_url = str(config.server.public_url or '').strip().rstrip('/')
    if compiled_url:
        os.environ['PAC_BUILD_SERVER_URL'] = compiled_url
    try:
        result = source_build_binary(f'binaries/{project}', targets=[target], runtime='auto')
    finally:
        if old_build_server_url is None:
            os.environ.pop('PAC_BUILD_SERVER_URL', None)
        else:
            os.environ['PAC_BUILD_SERVER_URL'] = old_build_server_url
    artifact = _find_matching_binary_artifact(project, target)
    if result.get('ok') and artifact:
        installed = _install_wrapper_artifact(project, artifact)
        return {'ok': True, 'status': 'rebuilt_installed' if force_rebuild else 'built_installed', 'target': target, 'build': result, 'message': 'PAC wrapper rebuilt and installed.' if force_rebuild else 'PAC wrapper built and installed.', **installed}
    return {'ok': False, 'status': 'build_failed', 'target': target, 'build': result, 'message': 'PAC wrapper rebuild did not produce a host binary.' if force_rebuild else 'PAC wrapper build did not produce a host binary.'}


def _required_tool_state() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    missing: list[str] = []
    for name in config.controller_harness.required_tools or []:
        available = bool(shutil.which(name))
        tools[name] = {'available': available, 'path': shutil.which(name)}
        if not available:
            missing.append(name)
    return {'ok': not missing, 'tools': tools, 'missing': missing}



def _local_controller_url() -> str:
    port = int(config.server.port or config.service.preferred_port or 443)
    scheme = 'https' if config.tls.enabled else 'http'
    suffix = '' if port in {80, 443} else f':{port}'
    return f'{scheme}://127.0.0.1{suffix}'


def _controller_auth_token() -> str:
    if config.auth.enabled and config.auth.mode == 'dev-token' and config.auth.dev_token:
        return str(config.auth.dev_token)
    if config.auth.enabled:
        token = str(getattr(config.controller_harness, 'service_token', '') or '').strip()
        if token:
            return token
    return ''


def _ensure_controller_service_token() -> str:
    token = str(getattr(config.controller_harness, 'service_token', '') or '').strip()
    if token:
        return token
    token = uuid.uuid4().hex + uuid.uuid4().hex
    config.controller_harness.service_token = token
    save_config(config)
    return token


def _wrapper_process_state() -> dict[str, Any]:
    global _CONTROLLER_WRAPPER_PROC
    wrapper = _controller_wrapper_path()
    state: dict[str, Any] = {
        'available': wrapper.is_file() and os.access(wrapper, os.X_OK),
        'path': str(wrapper),
        'running': False,
        'pid': None,
        'supervised': True,
    }
    proc = _CONTROLLER_WRAPPER_PROC
    if proc is not None:
        rc = proc.poll()
        state.update({'running': rc is None, 'pid': proc.pid, 'return_code': rc})
    return state


def _start_controller_wrapper_once() -> dict[str, Any]:
    global _CONTROLLER_WRAPPER_PROC
    state = _wrapper_process_state()
    if state.get('running'):
        return {'ok': True, 'status': 'running', 'process': state, 'message': 'PAC wrapper process is already running.'}
    wrapper = _controller_wrapper_path()
    if not (wrapper.is_file() and os.access(wrapper, os.X_OK)):
        return {'ok': False, 'status': 'missing', 'process': state, 'message': 'PAC wrapper binary is not installed yet.'}
    workspace = _ensure_controller_harness_workspace()
    env = os.environ.copy()
    env.update({
        'PAC_URL': _local_controller_url(),
        'PAC_ENDPOINT_NAME': config.controller_harness.runner_id or 'local-PAC',
        'PAC_RUNNER_ENABLED': 'true',
        'PAC_WORKSPACE': workspace.path or _platform_workspace_path(),
        'PAC_CONTROLLER_WRAPPER': '1',
        'PAC_UPDATE_CHANNEL': 'controller',
    })
    token = _controller_auth_token()
    if config.auth.enabled and not token:
        token = _ensure_controller_service_token()
    if token:
        env['PAC_TOKEN'] = token
    ca_file = str(Path(config.tls.ca_cert_file).expanduser()) if config.tls.enabled else ''
    if ca_file and Path(ca_file).exists():
        env['PAC_CA_FILE'] = ca_file
    log_dir = pacp_path('logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'controller-pac-wrapper.log'
    try:
        fh = log_file.open('a', encoding='utf-8')
        proc = subprocess.Popen([str(wrapper)], cwd=workspace.path or _platform_workspace_path(), env=env, stdout=fh, stderr=subprocess.STDOUT, text=True)
        _CONTROLLER_WRAPPER_PROC = proc
        return {'ok': True, 'status': 'started', 'process': _wrapper_process_state(), 'log': str(log_file), 'url': env['PAC_URL'], 'workspace': env['PAC_WORKSPACE'], 'message': 'PAC wrapper process started.'}
    except Exception as exc:
        return {'ok': False, 'status': 'failed', 'process': state, 'log': str(log_file), 'error': str(exc), 'message': f'PAC wrapper process could not be started: {exc}'}


def _controller_wrapper_supervisor() -> None:
    global _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE, _LAST_CONTROLLER_WRAPPER_EVENT_SIGNATURE, _LAST_CONTROLLER_WRAPPER_RUNNING_STATE
    if _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE:
        return
    _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE = True
    try:
        # Let the ASGI server finish binding before the wrapper tries to register.
        time.sleep(3)
        while config.controller_harness.enabled:
            state = _wrapper_process_state()
            if not state.get('available'):
                time.sleep(10)
                continue
            running = bool(state.get('running'))
            if running:
                _LAST_CONTROLLER_WRAPPER_RUNNING_STATE = True
            if not running:
                result = _start_controller_wrapper_once()
                event_type = 'controller_wrapper_started' if result.get('ok') else 'controller_wrapper_start_failed'
                running_now = bool(result.get('ok'))
                status = str(result.get('status') or '')
                message = str(result.get('message') or '')
                signature = f"{event_type}:{status}:{message}"
                should_emit = (
                    _LAST_CONTROLLER_WRAPPER_RUNNING_STATE is not running_now
                    or signature != _LAST_CONTROLLER_WRAPPER_EVENT_SIGNATURE
                )
                _LAST_CONTROLLER_WRAPPER_RUNNING_STATE = running_now
                if should_emit:
                    _LAST_CONTROLLER_WRAPPER_EVENT_SIGNATURE = signature
                    store.add_event(Event(session_id='system', type=event_type, message=result.get('message', 'PAC wrapper start checked'), data=result))
            time.sleep(10)
    finally:
        _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE = False


def _start_controller_wrapper_supervisor() -> bool:
    if not config.controller_harness.enabled:
        return False
    threading.Thread(target=_controller_wrapper_supervisor, daemon=True).start()
    return True


def _restart_controller_wrapper() -> dict[str, Any]:
    global _CONTROLLER_WRAPPER_PROC
    proc = _CONTROLLER_WRAPPER_PROC
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
    _CONTROLLER_WRAPPER_PROC = None
    return _start_controller_wrapper_once()


def _container_runtime_for_pi_dev() -> str | None:
    for candidate in ('podman', 'docker'):
        if shutil.which(candidate):
            return candidate
    return None


def _pi_dev_daemon_state() -> dict[str, Any]:
    image = os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    runtime = _container_runtime_for_pi_dev()
    state: dict[str, Any] = {'image': image, 'name': _CONTROLLER_PI_CONTAINER_NAME, 'runtime': runtime, 'running': False, 'available': False}
    if not runtime:
        state['reason'] = 'No container runtime found.'
        return state
    exists = subprocess.run([runtime, 'image', 'exists', image], capture_output=True, text=True, timeout=5, check=False)
    state['image_available'] = exists.returncode == 0
    if exists.returncode != 0:
        state['reason'] = f'pi.dev image is not available: {image}'
        state['last_check'] = {'exit_code': exists.returncode, 'stdout': exists.stdout[-1000:], 'stderr': exists.stderr[-1000:]}
        return state
    inspect = subprocess.run([runtime, 'inspect', _CONTROLLER_PI_CONTAINER_NAME], capture_output=True, text=True, timeout=5, check=False)
    if inspect.returncode == 0 and inspect.stdout.strip():
        try:
            data = json.loads(inspect.stdout)[0]
            running = bool(((data.get('State') or {}).get('Running')))
            state.update({'running': running, 'available': running, 'container_id': data.get('Id'), 'status': (data.get('State') or {}).get('Status')})
            if not running:
                state['reason'] = 'pi.dev controller container exists but is not running.'
            return state
        except Exception as exc:
            state['reason'] = f'Could not parse container inspect output: {exc}'
    state['reason'] = 'pi.dev controller daemon is not running.'
    return state


def _start_pi_dev_daemon() -> dict[str, Any]:
    image = os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    runtime = _container_runtime_for_pi_dev()
    if not runtime:
        return {'ok': False, 'status': 'missing_runtime', 'message': 'No container runtime found. Install podman or docker.'}
    state = _pi_dev_daemon_state()
    if state.get('running'):
        return {'ok': True, 'status': 'running', 'state': state, 'message': 'pi.dev controller daemon is already running.'}
    if not state.get('image_available'):
        return {'ok': False, 'status': 'missing_image', 'state': state, 'message': state.get('reason') or 'pi.dev image is missing.'}
    workspace = _ensure_controller_harness_workspace()
    workdir = workspace.path or _platform_workspace_path()
    if runtime == 'podman':
        rm = subprocess.run([runtime, 'rm', '-f', _CONTROLLER_PI_CONTAINER_NAME], capture_output=True, text=True, timeout=30, check=False)
    else:
        rm = subprocess.run([runtime, 'rm', '-f', _CONTROLLER_PI_CONTAINER_NAME], capture_output=True, text=True, timeout=30, check=False)
    cmd = [runtime, 'run', '-d', '--name', _CONTROLLER_PI_CONTAINER_NAME, '-e', 'PI_AGENT_DAEMON=1', '-e', 'PI_AGENT_MODE=daemon', '-v', f'{workdir}:/workspace:Z', image]
    if runtime == 'docker':
        # Docker does not understand :Z on non-SELinux systems in every setup; retry without it below when needed.
        cmd = [runtime, 'run', '-d', '--name', _CONTROLLER_PI_CONTAINER_NAME, '-e', 'PI_AGENT_DAEMON=1', '-e', 'PI_AGENT_MODE=daemon', '-v', f'{workdir}:/workspace', image]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0 and runtime == 'podman' and ':Z' in ' '.join(cmd):
        cmd = [runtime, 'run', '-d', '--name', _CONTROLLER_PI_CONTAINER_NAME, '-e', 'PI_AGENT_DAEMON=1', '-e', 'PI_AGENT_MODE=daemon', '-v', f'{workdir}:/workspace', image]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    new_state = _pi_dev_daemon_state()
    ok = proc.returncode == 0 and bool(new_state.get('running'))
    return {'ok': ok, 'status': 'started' if ok else 'failed', 'command': shlex.join(cmd), 'exit_code': proc.returncode, 'stdout': proc.stdout[-4000:], 'stderr': proc.stderr[-4000:], 'state': new_state, 'message': 'pi.dev controller daemon started.' if ok else 'pi.dev controller daemon failed to start.'}

def _bootstrap_local_controller_pi_dev() -> dict[str, Any]:
    global _SOURCE_BUILD_ACTIVE
    settings = config.controller_harness
    steps: list[dict[str, Any]] = []
    ensure_source_library()
    tool_state = _required_tool_state()
    steps.append({'step': 'tools', **tool_state})
    wrapper_result = _ensure_controller_wrapper(allow_build=bool(settings.auto_build_wrapper))
    steps.append({'step': 'pac_wrapper', **wrapper_result})
    install_result = None
    refreshed = _refresh_local_runner_metadata(emit_event=False)
    pi_container = (refreshed.capabilities or {}).get('pi_container') or {}
    if settings.auto_install_pi_dev and not (pi_container.get('image_available') or pi_container.get('available')):
        install_result = _run_local_pi_harness_install(runtime='auto')
        steps.append({'step': 'pi_dev_image', **install_result})
    else:
        image_present = bool(pi_container.get('image_available') or pi_container.get('available'))
        steps.append({'step': 'pi_dev_image', 'ok': image_present, 'status': 'ready' if image_present else 'missing', 'pi_container': pi_container})
    daemon_result = _start_pi_dev_daemon() if settings.auto_install_pi_dev else {'ok': False, 'status': 'disabled', 'message': 'pi.dev daemon auto-start is disabled.'}
    steps.append({'step': 'pi_dev_daemon', **daemon_result})
    wrapper_process = _start_controller_wrapper_once()
    steps.append({'step': 'pac_wrapper_process', **wrapper_process})
    _start_controller_wrapper_supervisor()
    refreshed = _refresh_local_runner_metadata(emit_event=False)
    session_result = _ensure_controller_harness_session()
    ok = bool(wrapper_result.get('ok')) and bool(wrapper_process.get('ok')) and bool(daemon_result.get('ok')) and bool(session_result.get('ok'))
    return {'ok': ok, 'steps': steps, 'session': {k: v for k, v in session_result.items() if k not in {'runner', 'workspace', 'session'}}, 'wrapper': wrapper_result, 'wrapper_process': wrapper_process, 'tools': tool_state, 'pi_container': (refreshed.capabilities or {}).get('pi_container'), 'pi_daemon': _pi_dev_daemon_state(), 'install': install_result}


def _bootstrap_local_controller_worker() -> None:
    global _BOOTSTRAP_ACTIVE, _SOURCE_BUILD_ACTIVE
    if _BOOTSTRAP_ACTIVE:
        return
    _BOOTSTRAP_ACTIVE = True
    _SOURCE_BUILD_ACTIVE = {'kind': 'controller_pi_dev_bootstrap', 'path': 'local-PAC', 'status': 'running', 'message': 'Controller pi.dev bootstrap is running'}
    try:
        store.add_event(Event(session_id='system', type='controller_pi_dev_bootstrap_started', message='Controller pi.dev bootstrap started', data={'target': _host_binary_target(), 'wrapper': str(_controller_wrapper_path())}))
        result = _bootstrap_local_controller_pi_dev()
        store.add_event(Event(session_id='system', type='controller_pi_dev_bootstrap_completed' if result.get('ok') else 'controller_pi_dev_bootstrap_failed', message='Controller pi.dev bootstrap completed' if result.get('ok') else 'Controller pi.dev bootstrap needs attention', data=result))
    except Exception as exc:
        store.add_event(Event(session_id='system', type='controller_pi_dev_bootstrap_failed', message=f'Controller pi.dev bootstrap failed: {exc}', data={'error': str(exc)}))
    finally:
        _SOURCE_BUILD_ACTIVE = None
        _BOOTSTRAP_ACTIVE = False


def _start_controller_bootstrap(force: bool = False) -> bool:
    if not config.controller_harness.enabled:
        return False
    if not force and not config.controller_harness.auto_bootstrap:
        return False
    threading.Thread(target=_bootstrap_local_controller_worker, daemon=True).start()
    return True


def _start_controller_bootstrap_if_needed() -> None:
    _start_controller_bootstrap(force=False)


@app.on_event('startup')
def startup_controller_harness() -> None:
    try:
        result = _ensure_controller_harness_session()
        store.add_event(Event(session_id='system', type='controller_harness_ready' if result.get('ok') else 'controller_harness_needs_setup', message=result.get('message', 'Controller pi.dev runtime checked'), data={k:v for k,v in result.items() if k not in {'runner','session','workspace'}}))
    except Exception as exc:
        store.add_event(Event(session_id='system', type='controller_harness_failed', message=f'Controller pi.dev setup failed: {exc}', data={'error': str(exc)}))
    _start_controller_bootstrap_if_needed()
    _start_controller_wrapper_supervisor()



def _source_build_blocker() -> dict[str, Any] | None:
    if _SOURCE_BUILD_ACTIVE:
        return _SOURCE_BUILD_ACTIVE
    try:
        status_file = _mcp_status_file()
        if status_file.exists():
            data = json.loads(status_file.read_text(encoding='utf-8'))
            if data.get('status') in {'queued', 'running'}:
                return {'kind': 'mcp_binary_build', 'status': data.get('status'), 'message': data.get('message') or 'MCP binary build is active'}
    except Exception:
        pass
    return None


def _require_no_source_builds(action: str) -> None:
    blocker = _source_build_blocker()
    if blocker:
        store.add_event(Event(session_id='system', type='feature_pack_pending', message=f'{action} is pending while a build is active', data={'blocked_by': blocker}))
        raise HTTPException(status_code=409, detail={'message': f'{action} is pending while a container or binary build is active.', 'blocked_by': blocker})


def _local_ipv4_addresses(include_loopback: bool = False) -> list[str]:
    addresses: set[str] = {'127.0.0.1'} if include_loopback else set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            addr = info[4][0]
            if addr and (include_loopback or not addr.startswith('127.')):
                addresses.add(addr)
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        addr = sock.getsockname()[0]
        if addr and (include_loopback or not addr.startswith('127.')):
            addresses.add(addr)
        sock.close()
    except Exception:
        pass
    return sorted(addresses)


def _mdns_config() -> dict[str, Any]:
    mdns = getattr(config, 'mdns', None)
    return mdns.model_dump() if mdns else {
        'enabled': True,
        'hostname': 'admin.pac.local',
        'service_name': 'PAC Admin',
        'service_type': '_https._tcp.local.',
    }


def _start_mdns_advertiser() -> None:
    global _MDNS_ZEROCONF, _MDNS_SERVICE_INFO, _MDNS_STATUS
    cfg = _mdns_config()
    if not cfg.get('enabled', True):
        _MDNS_STATUS = {'state': 'disabled', 'message': 'mDNS is disabled in config'}
        return
    try:
        from zeroconf import IPVersion, InterfaceChoice, ServiceInfo, Zeroconf
    except Exception as exc:
        _MDNS_STATUS = {'state': 'unavailable', 'message': 'mDNS advertisement unavailable; install zeroconf dependency', 'error': str(exc)}
        store.add_event(Event(session_id='system', type='mdns_unavailable', message=_MDNS_STATUS['message'], data={'error': str(exc)}))
        return

    host = str(cfg.get('hostname') or 'admin.pac.local').rstrip('.') + '.'
    service_type = str(cfg.get('service_type') or '_https._tcp.local.')
    if not service_type.endswith('.'):
        service_type += '.'
    service_name = str(cfg.get('service_name') or 'PAC Admin')
    instance = f'{service_name}.{service_type}'
    address_strings = _local_ipv4_addresses(include_loopback=False)
    if not address_strings:
        address_strings = _local_ipv4_addresses(include_loopback=True)
    if not address_strings:
        _MDNS_STATUS = {'state': 'failed', 'message': 'mDNS advertisement failed: no IPv4 address found', 'hostname': host.rstrip('.')}
        store.add_event(Event(session_id='system', type='mdns_failed', message=_MDNS_STATUS['message'], data=_MDNS_STATUS))
        return

    addresses = [socket.inet_aton(a) for a in address_strings]
    properties = {
        b'path': b'/',
        b'api': b'/v1',
        b'mcp': b'/mcp',
        b'ca': b'/v1/tls/ca.pem',
        b'version': PAC_VERSION.encode('utf-8'),
        b'name': b'admin.pac.local',
        b'url': (f'https://{host.rstrip(".")}' + ('' if int(config.server.port) == 443 else f':{config.server.port}')).encode('utf-8'),
    }
    try:
        _MDNS_ZEROCONF = Zeroconf(interfaces=InterfaceChoice.All, ip_version=IPVersion.V4Only)
        _MDNS_SERVICE_INFO = ServiceInfo(
            service_type,
            instance,
            addresses=addresses,
            port=int(config.server.port),
            properties=properties,
            server=host,
        )
        _MDNS_ZEROCONF.register_service(_MDNS_SERVICE_INFO, allow_name_change=True)
        _MDNS_STATUS = {
            'state': 'started',
            'message': f'PAC advertised as {host.rstrip(".")}',
            'hostname': host.rstrip('.'),
            'port': config.server.port,
            'addresses': address_strings,
            'service_type': service_type,
            'service_name': instance,
        }
        store.add_event(Event(session_id='system', type='mdns_started', message=_MDNS_STATUS['message'], data=_MDNS_STATUS))
    except Exception as exc:
        hint = 'Check that UDP 5353/multicast is allowed and no other service owns the same mDNS name.'
        _MDNS_STATUS = {'state': 'failed', 'message': f'mDNS advertisement failed: {exc}', 'error': str(exc), 'hostname': host.rstrip('.'), 'port': config.server.port, 'addresses': address_strings, 'hint': hint}
        store.add_event(Event(session_id='system', type='mdns_failed', message=_MDNS_STATUS['message'], data=_MDNS_STATUS))

def _stop_mdns_advertiser() -> None:
    global _MDNS_ZEROCONF, _MDNS_SERVICE_INFO, _MDNS_STATUS
    try:
        if _MDNS_ZEROCONF and _MDNS_SERVICE_INFO:
            _MDNS_ZEROCONF.unregister_service(_MDNS_SERVICE_INFO)
        if _MDNS_ZEROCONF:
            _MDNS_ZEROCONF.close()
    except Exception:
        pass
    _MDNS_ZEROCONF = None
    _MDNS_SERVICE_INFO = None
    _MDNS_STATUS = {'state': 'stopped', 'message': 'mDNS stopped'}


@app.on_event('startup')
def _startup_services() -> None:
    _ensure_tls_material()
    info = ensure_source_library()
    if info.get('changed'):
        store.add_event(Event(session_id='system', type='source_library_initialized', message='Source library prepared', data=info))
    plugin_info = _ensure_platform_plugin_sources()
    if plugin_info.get('created'):
        store.add_event(Event(session_id='system', type='platform_plugin_sources_initialized', message='Platform plugin sources prepared', data=plugin_info))
    _start_mdns_advertiser()


@app.on_event('shutdown')
def _shutdown_services() -> None:
    _stop_mdns_advertiser()



class CurrentUser:
    def __init__(self, user: User | None = None, is_admin: bool = False):
        self.user = user
        self.is_admin = is_admin


def _bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = str(authorization or '').partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return None
    return token


def _admin_auth_valid(authorization: str | None) -> bool:
    if not config.auth.enabled:
        return True
    token = _bearer_token(authorization)
    if not token:
        return False
    service_token = str(getattr(config.controller_harness, 'service_token', '') or '').strip()
    if service_token and token == service_token:
        return True
    if config.auth.mode == 'dev-token':
        return token == config.auth.dev_token
    if config.auth.mode == 'user-password':
        user = store.get_user_by_token(token)
        return bool(user and user.role == 'admin')
    return False


def _get_user_from_auth(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not config.auth.enabled:
        return CurrentUser(None, True)
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail='Missing authorization header')
    service_token = str(getattr(config.controller_harness, 'service_token', '') or '').strip()
    if service_token and token == service_token:
        return CurrentUser(None, True)
    if config.auth.mode == 'dev-token':
        if token == config.auth.dev_token:
            return CurrentUser(None, True)
        raise HTTPException(status_code=401, detail='Invalid bearer token')
    if config.auth.mode == 'user-password':
        user = store.get_user_by_token(token)
        if user:
            return CurrentUser(user, user.role == 'admin')
        raise HTTPException(status_code=401, detail='Invalid or expired token')
    raise HTTPException(status_code=501, detail='OIDC auth mode is configured but not implemented in this starter')


def require_auth(_auth: CurrentUser = Depends(_get_user_from_auth)) -> CurrentUser:
    return _auth


def require_admin(_auth: CurrentUser = Depends(require_auth)) -> CurrentUser:
    if not _auth.is_admin:
        raise HTTPException(status_code=403, detail='Admin required')
    return _auth


app.include_router(create_marketplace_router(config, store, require_auth))
app.include_router(create_version_router(pac_version=PAC_VERSION, ui_build_info=_ui_build_info))
app.include_router(create_mcp_router(
    require_auth=require_auth,
    pac_version=PAC_VERSION,
    status_file=_mcp_status_file,
    artifacts=_mcp_artifacts,
    mcp_dir=_mcp_dir,
    write_status=_mcp_write_status,
    build_event=_mcp_build_event,
    run_builder=_run_mcp_builder,
))
register_ui_routes(app, render_index=_render_web_index, web_dir=_web_dir())


def _runner_from_auth_headers(authorization: str | None = None, runner_id: str | None = None, runner_key: str | None = None) -> Runner | None:
    if _admin_auth_valid(authorization):
        return None
    rid = str(runner_id or '').strip()
    if not rid:
        return None
    runner = store.get_runner(rid)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    expected = str(runner.api_key or '').strip()
    if not expected or str(runner_key or '').strip() != expected:
        raise HTTPException(status_code=401, detail='Missing or invalid endpoint key')
    return runner


def _require_admin_or_runner(
    authorization: str | None = None,
    runner_id: str | None = None,
    runner_key: str | None = None,
) -> Runner | None:
    runner = _runner_from_auth_headers(authorization, runner_id, runner_key)
    if _admin_auth_valid(authorization) or runner is not None:
        return runner
    _get_user_from_auth(authorization)
    return None



def _runner_target_from_task(task: Task) -> dict[str, Any] | None:
    runner_id = task.metadata.get('runner_id') or task.metadata.get('target_runner_id')
    if not runner_id:
        return None
    runner = store.get_runner(runner_id)
    if runner and runner.metadata.get('local_control_plane'):
        # The local endpoint uses the PAC process directly. It is shown in the
        # endpoint inventory, but jobs do not need to be placed on the polling
        # runner queue.
        return None
    execution_mode = task.metadata.get('execution_mode')
    if not execution_mode:
        execution_mode = 'host' if task.command else 'pi_container'
    return {
        'runner_id': runner_id,
        'execution_mode': execution_mode,
        'container_image': task.metadata.get('container_image'),
        'container_runtime': task.metadata.get('container_runtime', 'auto'),
    }


def _queue_task_on_runner(session: Session, task: Task, target: dict[str, Any]) -> Task:
    runner = store.get_runner(target['runner_id'])
    if not runner:
        task.status = TaskStatus.failed
        task.error = f"Runner not found: {target['runner_id']}"
        store.add_task(task)
        return task
    job = RunnerJob(
        runner_id=runner.id,
        prompt=task.prompt,
        command=task.command,
        execution_mode=target['execution_mode'],
        container_image=target.get('container_image'),
        container_runtime=target.get('container_runtime', 'auto'),
        workspace_path=session.workspace_path,
        session_id=session.id,
        task_id=task.id,
        metadata={'agent_profile': session.agent_profile, 'model': task.metadata.get('model') or session.model, **task.metadata},
    )
    store.add_runner_job(job)
    store.add_event(Event(session_id=session.id, task_id=task.id, type='runner_job_queued', message=f"Queued on runner {runner.name}", data={'runner_id': runner.id, 'runner_job_id': job.id, 'execution_mode': job.execution_mode, 'container_image': job.container_image}))
    task.metadata['runner_job_id'] = job.id
    task.status = TaskStatus.queued
    store.add_task(task)
    return task


def _session_agent_enabled(session: Session) -> bool:
    """Return true when a session must route user turns through the agent loop.

    pi.dev sessions are the default for PAC because pi.dev is the execution/runtime decision maker.
    Direct model mode is only allowed when the session explicitly opts out with
    metadata.agent_enabled=false or metadata.execution_mode/direct_model="direct_model".
    """
    meta = session.metadata or {}
    if meta.get('execution_mode') == 'direct_model' or meta.get('mode') == 'direct_model':
        return False
    if meta.get('direct_model') is True:
        return False
    if meta.get('agent_enabled') is False:
        return False
    return True


def _agent_prompt_for_task(prompt: str, command: str | None, metadata: dict[str, Any]) -> str:
    """Build the prompt the agent sees when the user used slash/command input."""
    if not command:
        return prompt
    tool_name = metadata.get('tool_name')
    args = metadata.get('args')
    if tool_name:
        arg_text = ' '.join(str(a) for a in args) if isinstance(args, list) else ''
        return (
            f"User requested endpoint tool execution via /{tool_name}.\n"
            f"Requested command: {command}\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {arg_text}\n\n"
            f"Original user text:\n{prompt}\n\n"
            "You are the session agent and decision maker. Decide whether to run the requested tool, inspect context first, or answer without running it. "
            "If you run it, use the shell tool with the exact safe command scoped to the workspace."
        )
    return (
        f"User requested command execution.\nRequested command: {command}\n\n"
        f"Original user text:\n{prompt}\n\n"
        "You are the session agent and decision maker. Decide whether this command should be run, requires context, or should be refused. "
        "If appropriate, call the shell tool with the command."
    )

def safe_workspace_path(session: Session, rel_path: str) -> Path:
    root = Path(session.workspace_path).resolve()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=400, detail='Path escapes workspace')
    return target




# ---- Zed binary builder/downloads --------------------------------------------------

def _mcp_dir() -> Path:
    path = pacp_path('mcp')
    path.mkdir(parents=True, exist_ok=True)
    (path / 'bin').mkdir(parents=True, exist_ok=True)
    return path


def _mcp_status_file() -> Path:
    return _mcp_dir() / 'build-status.json'


def _mcp_write_status(status: str, message: str, artifacts: list[dict[str, Any]] | None = None, logs: list[str] | None = None) -> None:
    payload = {
        'status': status,
        'message': message,
        'version': PAC_VERSION,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'artifacts': artifacts if artifacts is not None else _mcp_artifacts(),
        'logs': logs or [],
    }
    _mcp_status_file().write_text(json.dumps(payload, indent=2), encoding='utf-8')


def _mcp_artifacts() -> list[dict[str, Any]]:
    source_artifacts = source_list_binary_artifacts('zed-binary').get('projects', [])
    if source_artifacts and source_artifacts[0].get('artifacts'):
        return source_artifacts[0].get('artifacts', [])
    out = _mcp_dir() / 'bin'
    items: list[dict[str, Any]] = []
    if not out.exists():
        return items
    for item in sorted(out.iterdir(), key=lambda p: p.name):
        if item.is_file():
            items.append({'name': item.name, 'size': item.stat().st_size, 'download_url': f'/v1/mcp/download/{item.name}'})
    return items


def _find_container_runtime() -> str | None:
    for runtime in ('podman', 'docker'):
        if shutil.which(runtime):
            return runtime
    return None


def _tail(text: str, limit: int = 8000) -> str:
    if not text:
        return ''
    return text[-limit:]


def _mcp_build_event(build_id: str, event_type: str, message: str, **data: Any) -> None:
    payload = {'build_id': build_id, **data}
    store.add_event(Event(session_id='system', type=event_type, message=message, data=payload))


def _run_mcp_builder(runtime: str | None = None, build_id: str | None = None) -> None:
    build_id = build_id or uuid.uuid4().hex[:12]
    try:
        result = source_build_binary('binaries/zed-binary', runtime=runtime or 'auto')
        status = 'completed' if result.get('ok') else 'failed'
        _mcp_write_status(status, 'Zed binary build completed' if result.get('ok') else 'Zed binary build failed', artifacts=result.get('artifacts', []), logs=[result.get('stdout',''), result.get('stderr','')])
        _mcp_build_event(build_id, 'mcp_build_completed' if result.get('ok') else 'mcp_build_failed', 'Zed binary build completed' if result.get('ok') else 'Zed binary build failed', **result)
        return
    except Exception as source_exc:
        _mcp_build_event(build_id, 'mcp_build_warning', f'Sources zed-binary build path unavailable: {source_exc}', error=str(source_exc))
    runtime = runtime or _find_container_runtime()
    if not runtime:
        msg = 'No container runtime found. Install podman or docker on the PAC host.'
        _mcp_write_status('failed', msg, logs=[msg])
        _mcp_build_event(build_id, 'mcp_build_failed', msg, error=msg)
        return
    app_dir = Path(__file__).resolve().parents[2]
    dockerfile = app_dir / 'containers' / 'mcp-builder' / 'Dockerfile'
    # Self-heal the two accepted Go source locations. Older installed Dockerfiles
    # copied mcp/pac-mcp-go while newer package attempts also carried a
    # builder-local copy. Keep both populated so a partially-applied update or an
    # old Dockerfile cannot fail at COPY before the real Go build starts.
    mcp_src = app_dir / 'mcp' / 'pac-mcp-go'
    builder_src = app_dir / 'containers' / 'mcp-builder' / 'pac-mcp-go'
    try:
        if not mcp_src.exists() and builder_src.exists():
            mcp_src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(builder_src, mcp_src)
        if not builder_src.exists() and mcp_src.exists():
            builder_src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(mcp_src, builder_src)
    except Exception as exc:
        _mcp_build_event(build_id, 'mcp_build_warning', f'MCP source self-heal warning: {exc}', error=str(exc))
    out_dir = _mcp_dir() / 'bin'
    image = f'pac-mcp-builder:{PAC_VERSION}'
    logs: list[str] = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        msg = f'Could not create MCP output directory {out_dir}: {exc}'
        _mcp_write_status('failed', msg, logs=[msg])
        _mcp_build_event(build_id, 'mcp_build_failed', msg, error=str(exc), out_dir=str(out_dir))
        return

    _mcp_write_status('running', f'Building Zed binaries with {runtime}', logs=logs)
    _mcp_build_event(build_id, 'mcp_build_started', f'Zed binary build started with {runtime}', runtime=runtime, image=image, out_dir=str(out_dir))
    try:
        if not dockerfile.exists():
            raise FileNotFoundError(f'MCP builder Dockerfile not found: {dockerfile}')
        build_cmd = [runtime, 'build', '--pull=missing', '-t', image, '-f', str(dockerfile), str(app_dir)]
        proc = subprocess.run(build_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        build_log = _tail(proc.stdout)
        logs.append(build_log)
        if proc.returncode != 0:
            raise RuntimeError(f'container image build failed with exit code {proc.returncode}: {build_log[-2000:]}')
        volume = f'{out_dir}:/out:Z' if runtime == 'podman' else f'{out_dir}:/out'
        run_cmd = [runtime, 'run', '--rm', '-v', volume, image]
        proc = subprocess.run(run_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        run_log = _tail(proc.stdout)
        logs.append(run_log)
        if proc.returncode != 0:
            raise RuntimeError(f'builder container failed with exit code {proc.returncode}: {run_log[-2000:]}')
        artifacts = _mcp_artifacts()
        _mcp_write_status('completed', f'Zed binaries built: {len(artifacts)} files', artifacts=artifacts, logs=logs)
        _mcp_build_event(build_id, 'mcp_build_completed', f'Zed binaries built: {len(artifacts)} files', artifacts=artifacts, logs=logs[-2:])
    except Exception as exc:
        logs.append(str(exc))
        _mcp_write_status('failed', str(exc), logs=logs)
        _mcp_build_event(build_id, 'mcp_build_failed', f'Zed binary build failed: {exc}', error=str(exc), logs=logs[-3:])




def _storage_id_from_name(name: str) -> str:
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', str(name or '').strip().lower()).strip('-')
    return slug or f'storage-{uuid.uuid4().hex[:8]}'


def _best_default_agent_profile() -> str | None:
    for candidate in ('code_planner', MAIN_PI_DEV_PROFILE, 'main-pi-dev'):
        if candidate in (config.agent_profiles or {}):
            return candidate
    return next(iter(config.agent_profiles.keys()), None) if config.agent_profiles else None


def _workspace_template_catalog() -> dict[str, dict[str, Any]]:
    _storage_catalog()
    templates: dict[str, dict[str, Any]] = {}
    profile_name = _best_default_agent_profile()
    builtins = [
        {
            'id': 'builtin:general-coding',
            'name': 'General coding',
            'description': 'Container-backed coding workspace for a local or mounted project tree.',
            'workspace_type': 'local',
            'workspace_profile': None,
            'runtime': 'container',
            'shared_storage_id': 'shared-controller-workspaces',
            'endpoint_id': _default_coding_endpoint_id(),
            'container_image': 'localhost/python-dev:latest',
            'agent_profile': profile_name,
            'permission_profile': CODING_SESSION_PERMISSION_PROFILE,
        },
        {
            'id': 'builtin:documentation',
            'name': 'Documentation',
            'description': 'Documentation workspace with a docs/search-oriented container profile.',
            'workspace_type': 'local',
            'workspace_profile': None,
            'runtime': 'container',
            'shared_storage_id': 'shared-controller-workspaces',
            'endpoint_id': _default_coding_endpoint_id(),
            'container_image': 'localhost/docs-search:latest',
            'agent_profile': profile_name,
            'permission_profile': CODING_SESSION_PERMISSION_PROFILE,
        },
        {
            'id': 'builtin:repo-review',
            'name': 'Repo review',
            'description': 'Review and improve an existing checked-out repository in a container-backed coding session.',
            'workspace_type': 'local',
            'workspace_profile': None,
            'runtime': 'container',
            'shared_storage_id': 'shared-controller-workspaces',
            'endpoint_id': _default_coding_endpoint_id(),
            'container_image': 'localhost/python-dev:latest',
            'agent_profile': profile_name,
            'permission_profile': CODING_SESSION_PERMISSION_PROFILE,
        },
    ]
    for item in builtins:
        templates[item['id']] = item
    for name, workspace in (config.workspaces or {}).items():
        templates[f'workspace:{name}'] = {
            'id': f'workspace:{name}',
            'name': name,
            'description': workspace.description,
            'workspace_type': workspace.type,
            'workspace_profile': name,
            'runtime': workspace.runtime,
            'shared_storage_id': workspace.shared_storage_id,
            'storage_subpath': workspace.storage_subpath,
            'storage_mount_path': workspace.storage_mount_path,
            'endpoint_id': workspace.endpoint_id,
            'endpoint_selector': workspace.endpoint_selector,
            'container_image': workspace.container_image,
            'agent_profile': workspace.default_agent_profile,
            'source': 'config',
            'is_default': bool(workspace.is_default),
        }
    return templates


def _storage_catalog() -> list[SharedStorage]:
    items = store.list_shared_storages()
    if items:
        return items
    defaults = [
        SharedStorage(
            id='shared-controller-workspaces',
            name='Controller workspaces',
            description='Shared workspace root mounted on the controller and available to container-capable endpoints.',
            driver='custom',
            controller_path=str(Path(config.server.default_workspace_root).expanduser()),
            network_path=f'controller://{Path(config.server.default_workspace_root).expanduser()}',
            mount_path='/workspace',
            endpoint_selector='container',
            writable=True,
        ),
        SharedStorage(
            id='shared-controller-sources',
            name='Controller source tree',
            description='PAC source tree and plugin workspace shared for controller-maintenance and coding flows.',
            driver='custom',
            controller_path=str((_app_dir() / 'sources').expanduser()),
            network_path=f'controller://{(_app_dir() / "sources").expanduser()}',
            mount_path='/workspace',
            endpoint_selector='container',
            writable=True,
        ),
    ]
    for item in defaults:
        store.add_shared_storage(item)
    return store.list_shared_storages()


def _public_workspace_template(template: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': template.get('id'),
        'name': template.get('name'),
        'description': template.get('description'),
        'workspace_type': template.get('workspace_type'),
        'workspace_profile': template.get('workspace_profile'),
        'runtime': template.get('runtime'),
        'shared_storage_id': template.get('shared_storage_id'),
        'storage_subpath': template.get('storage_subpath'),
        'storage_mount_path': template.get('storage_mount_path'),
        'endpoint_id': template.get('endpoint_id'),
        'endpoint_selector': template.get('endpoint_selector'),
        'container_image': template.get('container_image'),
        'agent_profile': template.get('agent_profile'),
        'permission_profile': template.get('permission_profile'),
        'source': template.get('source') or 'builtin',
        'is_default': bool(template.get('is_default')),
    }


def _public_user_workspace(item: UserWorkspace) -> dict[str, Any]:
    template = _workspace_template_catalog().get(str(item.template_id or '').strip())
    storage = store.get_shared_storage(item.shared_storage_id) if item.shared_storage_id else None
    return {
        'id': item.id,
        'owner_id': item.owner_id,
        'owner_username': item.owner_username,
        'name': item.name,
        'description': item.description,
        'template_id': item.template_id,
        'template': _public_workspace_template(template) if template else None,
        'workspace_type': item.workspace_type,
        'workspace_profile': item.workspace_profile,
        'path': item.path,
        'url': item.url,
        'branch': item.branch,
        'shared_storage_id': item.shared_storage_id,
        'shared_storage': public_shared_storage(storage) if storage else None,
        'storage_subpath': item.storage_subpath,
        'storage_mount_path': item.storage_mount_path,
        'endpoint_id': item.endpoint_id,
        'endpoint_selector': item.endpoint_selector,
        'container_image': item.container_image,
        'agent_profile': item.agent_profile,
        'permission_profile': item.permission_profile,
        'model': item.model,
        'context_mode': item.context_mode,
        'open_files': list(item.open_files or []),
        'last_session_id': item.last_session_id,
        'pinned': item.pinned,
        'created_at': item.created_at.isoformat(),
        'updated_at': item.updated_at.isoformat(),
        'metadata': item.metadata or {},
    }


def _workspace_owner(auth: CurrentUser) -> tuple[str, str]:
    if auth.user:
        return auth.user.id, auth.user.username
    return 'controller', 'controller'


def _workspace_payload_to_item(existing: UserWorkspace | None, payload: UserWorkspacePayload, auth: CurrentUser) -> UserWorkspace:
    owner_id, owner_username = _workspace_owner(auth)
    template = _workspace_template_catalog().get(str(payload.template_id or '').strip()) if payload.template_id else None
    base = existing or UserWorkspace(owner_id=owner_id, owner_username=owner_username, name=payload.name.strip())
    base.owner_id = owner_id
    base.owner_username = owner_username
    base.name = payload.name.strip()
    base.description = payload.description if payload.description is not None else (template or {}).get('description')
    base.template_id = payload.template_id or None
    base.workspace_type = str(payload.workspace_type or (template or {}).get('workspace_type') or base.workspace_type or 'local')
    base.workspace_profile = payload.workspace_profile if payload.workspace_profile is not None else (template or {}).get('workspace_profile')
    base.path = payload.path if payload.path is not None else base.path
    base.url = payload.url if payload.url is not None else base.url
    base.branch = payload.branch if payload.branch is not None else base.branch
    base.shared_storage_id = payload.shared_storage_id if payload.shared_storage_id is not None else (template or {}).get('shared_storage_id')
    base.storage_subpath = payload.storage_subpath if payload.storage_subpath is not None else (template or {}).get('storage_subpath')
    base.storage_mount_path = payload.storage_mount_path if payload.storage_mount_path is not None else (template or {}).get('storage_mount_path')
    base.endpoint_id = payload.endpoint_id if payload.endpoint_id is not None else (template or {}).get('endpoint_id')
    base.endpoint_selector = payload.endpoint_selector if payload.endpoint_selector is not None else (template or {}).get('endpoint_selector')
    base.container_image = payload.container_image if payload.container_image is not None else (template or {}).get('container_image')
    base.agent_profile = payload.agent_profile if payload.agent_profile is not None else (template or {}).get('agent_profile')
    base.permission_profile = payload.permission_profile if payload.permission_profile is not None else (template or {}).get('permission_profile')
    base.model = payload.model if payload.model is not None else base.model
    base.context_mode = payload.context_mode if payload.context_mode is not None else base.context_mode
    base.open_files = list(payload.open_files or [])
    base.pinned = bool(payload.pinned)
    base.metadata = dict(base.metadata or {})
    if payload.metadata:
        base.metadata.update(payload.metadata)
    return base


def _user_workspace_to_session_spec(item: UserWorkspace) -> tuple[WorkspaceSpec, dict[str, Any]]:
    metadata = dict(item.metadata or {})
    metadata['coding_session'] = True
    metadata['ide_mode'] = True
    metadata['user_workspace_id'] = item.id
    metadata['workspace_trusted'] = True
    resolved_path = item.path
    if item.shared_storage_id:
        storage = store.get_shared_storage(item.shared_storage_id)
        if storage:
            metadata.update(shared_storage_binding(storage, item.storage_subpath, item.storage_mount_path))
            metadata['workspace_storage_required'] = True
            metadata['preferred_execution_mode'] = 'container'
            resolved_path = controller_storage_path(storage, item.storage_subpath) or resolved_path
    if item.endpoint_id:
        metadata['preferred_endpoint'] = item.endpoint_id
    if item.container_image:
        metadata['container_image'] = item.container_image
    if item.workspace_profile and item.workspace_profile in (config.workspaces or {}):
        return WorkspaceSpec(type='profile', profile=item.workspace_profile), metadata
    if item.workspace_type == 'git':
        return WorkspaceSpec(type='git', path=resolved_path, url=item.url, branch=item.branch), metadata
    return WorkspaceSpec(type='local', path=resolved_path), metadata


def _ensure_user_workspace_session(item: UserWorkspace, auth: CurrentUser) -> Session:
    if item.last_session_id:
        existing = store.get_session(item.last_session_id)
        if existing:
            return existing
    workspace_spec, metadata = _user_workspace_to_session_spec(item)
    session_creator = session_routes.create_session_for_internal_use
    if session_creator is None:
        raise RuntimeError('Session route creator is not registered')
    session = session_creator(
        SessionCreate(
            name=f'code-{re.sub(r"[^A-Za-z0-9._-]+", "-", item.name).lower()}',
            agent_profile=item.agent_profile,
            permission_profile=item.permission_profile or CODING_SESSION_PERMISSION_PROFILE,
            workspace=workspace_spec,
            model=item.model,
            context_mode=item.context_mode,
            metadata=metadata,
        ),
        _auth=auth,
    )
    item.last_session_id = session.id
    store.add_user_workspace(item)
    return session


def _public_agent_context(item: AgentContext) -> dict[str, Any]:
    workspace = store.get_user_workspace(item.workspace_id) if item.workspace_id else None
    template = _workspace_template_catalog().get(str(item.workspace_template_id or '').strip()) if item.workspace_template_id else None
    storage = store.get_shared_storage(item.shared_storage_id) if item.shared_storage_id else None
    metadata = item.metadata or {}
    return {
        'id': item.id,
        'owner_id': item.owner_id,
        'owner_username': item.owner_username,
        'name': item.name,
        'description': item.description,
        'kind': item.kind,
        'workspace_id': item.workspace_id,
        'workspace': _public_user_workspace(workspace) if workspace else None,
        'workspace_template_id': item.workspace_template_id,
        'workspace_template': _public_workspace_template(template) if template else None,
        'controller_workdir': item.controller_workdir,
        'shared_storage_id': item.shared_storage_id,
        'shared_storage': public_shared_storage(storage) if storage else None,
        'storage_subpath': item.storage_subpath,
        'storage_mount_path': item.storage_mount_path,
        'endpoint_id': item.endpoint_id,
        'endpoint_selector': item.endpoint_selector,
        'container_image': item.container_image,
        'requires_container': bool(item.requires_container),
        'agent_profile': item.agent_profile,
        'permission_profile': item.permission_profile,
        'context_mode': item.context_mode,
        'executor_model': item.executor_model,
        'planner_model': item.planner_model,
        'reviewer_model': item.reviewer_model,
        'retrieval_model': item.retrieval_model,
        'tools': list(item.tools or []),
        'use_groups': list(item.use_groups or []),
        'editor_groups': list(item.editor_groups or []),
        'last_session_id': item.last_session_id,
        'pinned': bool(item.pinned),
        'metadata': metadata,
        'workspace_label': metadata.get('workspace_label') or (DEFAULT_ADMIN_WORKSPACE_LABEL if metadata.get('system_context') else None),
        'runtime_label': metadata.get('runtime_label') or (item.endpoint_id or ('controller' if item.controller_workdir else None)),
        'builtin': bool(metadata.get('builtin_kind')),
        'builtin_kind': metadata.get('builtin_kind'),
        'system_context': bool(metadata.get('system_context')),
        'admin_only': bool(metadata.get('admin_only')),
        'protected': metadata.get('builtin_kind') == 'pac_admin_base',
        'created_at': item.created_at.isoformat(),
        'updated_at': item.updated_at.isoformat(),
    }


def _context_visibility_owner_ids(auth: CurrentUser) -> tuple[str, str]:
    return _workspace_owner(auth)


def _can_use_agent_context(item: AgentContext, auth: CurrentUser) -> bool:
    if auth.is_admin or not auth.user:
        return True
    if item.owner_id == auth.user.id:
        return True
    group_ids = set(auth.user.groups or [])
    allowed = set(item.use_groups or []) | set(item.editor_groups or [])
    return bool(group_ids & allowed)


def _can_edit_agent_context(item: AgentContext, auth: CurrentUser) -> bool:
    if auth.is_admin or not auth.user:
        return True
    if item.owner_id == auth.user.id:
        return True
    return bool(set(auth.user.groups or []) & set(item.editor_groups or []))


def _is_pac_system_context(item: AgentContext | None) -> bool:
    return bool(item and (item.metadata or {}).get('builtin_kind') == 'pac_admin_base')


def _agent_context_payload_to_item(existing: AgentContext | None, payload: AgentContextPayload, auth: CurrentUser) -> AgentContext:
    owner_id, owner_username = (existing.owner_id, existing.owner_username) if existing else _context_visibility_owner_ids(auth)
    base = existing or AgentContext(owner_id=owner_id, owner_username=owner_username, name=payload.name.strip())
    if _is_pac_system_context(existing):
        locked_profile = config.controller_harness.agent_profile or MAIN_PI_DEV_PROFILE
        locked_permission = _admin_permission_profile_name()
        locked_endpoint = config.controller_harness.runner_id or 'local-PAC'
        payload.workspace_id = None
        payload.workspace_template_id = None
        payload.shared_storage_id = None
        payload.storage_subpath = None
        payload.storage_mount_path = None
        payload.endpoint_selector = None
        payload.container_image = None
        payload.controller_workdir = str(_app_dir())
        payload.kind = 'controller'
        payload.requires_container = False
        payload.endpoint_id = locked_endpoint
        payload.agent_profile = locked_profile
        payload.permission_profile = locked_permission
        payload.use_groups = [DEFAULT_ADMIN_GROUP_ID]
        payload.editor_groups = [DEFAULT_ADMIN_GROUP_ID]
        payload.name = DEFAULT_ADMIN_CONTEXT_NAME
    base.owner_id = owner_id
    base.owner_username = owner_username
    base.name = payload.name.strip()
    base.description = payload.description.strip() if isinstance(payload.description, str) and payload.description.strip() else None
    base.kind = str(payload.kind or base.kind or 'coding')
    base.workspace_id = payload.workspace_id or None
    base.workspace_template_id = payload.workspace_template_id or None
    base.controller_workdir = payload.controller_workdir or None
    base.shared_storage_id = payload.shared_storage_id or None
    base.storage_subpath = payload.storage_subpath or None
    base.storage_mount_path = payload.storage_mount_path or None
    base.endpoint_id = payload.endpoint_id or None
    base.endpoint_selector = payload.endpoint_selector or None
    base.container_image = payload.container_image or None
    base.requires_container = bool(payload.requires_container)
    base.agent_profile = payload.agent_profile or None
    base.permission_profile = payload.permission_profile or None
    base.context_mode = payload.context_mode or None
    base.executor_model = payload.executor_model or None
    base.planner_model = payload.planner_model or None
    base.reviewer_model = payload.reviewer_model or None
    base.retrieval_model = payload.retrieval_model or None
    base.tools = [str(item).strip() for item in (payload.tools or []) if str(item).strip()]
    base.use_groups = [str(item).strip() for item in (payload.use_groups or []) if str(item).strip()]
    base.editor_groups = [str(item).strip() for item in (payload.editor_groups or []) if str(item).strip()]
    base.pinned = bool(payload.pinned)
    base.metadata = dict(base.metadata or {})
    if payload.metadata:
        base.metadata.update(payload.metadata)
    if _is_pac_system_context(base):
        base.metadata.update({
            'builtin_kind': 'pac_admin_base',
            'admin_only': True,
            'system_context': True,
            'workspace_label': DEFAULT_ADMIN_WORKSPACE_LABEL,
            'runtime_label': base.endpoint_id or 'local-PAC',
            'locked_endpoint': True,
            'locked_groups': True,
            'locked_workdir': True,
            'locked_workspace': True,
            'locked_agent_profile': True,
            'locked_permission_profile': True,
        })
    if base.shared_storage_id and not store.get_shared_storage(base.shared_storage_id):
        raise HTTPException(status_code=400, detail=f'Unknown shared storage: {base.shared_storage_id}')
    return base


def _agent_context_to_session_create(item: AgentContext) -> SessionCreate:
    metadata = dict(item.metadata or {})
    metadata['agent_context_id'] = item.id
    metadata['agent_context_name'] = item.name
    metadata['agent_context_kind'] = item.kind
    metadata['workspace_trusted'] = True
    metadata['agent_enabled'] = True
    metadata['endpoint_locked'] = bool(item.endpoint_id or item.endpoint_selector)
    if item.shared_storage_id:
        storage = store.get_shared_storage(item.shared_storage_id)
        if storage:
            metadata.update(shared_storage_binding(storage, item.storage_subpath, item.storage_mount_path))
            metadata['workspace_storage_required'] = True
            metadata['preferred_execution_mode'] = 'container'
    if item.endpoint_id:
        metadata['preferred_endpoint'] = item.endpoint_id
    if item.endpoint_selector:
        metadata['preferred_endpoint_selector'] = item.endpoint_selector
    if item.requires_container:
        metadata['preferred_execution_mode'] = 'container'
    if item.container_image:
        metadata['container_image'] = item.container_image
    if item.workspace_id:
        workspace = store.get_user_workspace(item.workspace_id)
        if workspace:
            spec, workspace_meta = _user_workspace_to_session_spec(workspace)
            metadata.update(workspace_meta)
            metadata['workspace_origin'] = 'user-workspace'
            return SessionCreate(
                name=f'ctx-{re.sub(r"[^A-Za-z0-9._-]+", "-", item.name).lower()}',
                agent_profile=item.agent_profile or workspace.agent_profile,
                permission_profile=item.permission_profile or workspace.permission_profile or CODING_SESSION_PERMISSION_PROFILE,
                workspace=spec,
                model=item.executor_model or workspace.model,
                context_mode=item.context_mode or workspace.context_mode,
                tools=list(item.tools or []),
                metadata=metadata,
            )
    if item.workspace_template_id:
        template = _workspace_template_catalog().get(item.workspace_template_id)
        if template and template.get('workspace_profile'):
            return SessionCreate(
                name=f'ctx-{re.sub(r"[^A-Za-z0-9._-]+", "-", item.name).lower()}',
                agent_profile=item.agent_profile or template.get('agent_profile'),
                permission_profile=item.permission_profile or template.get('permission_profile') or CODING_SESSION_PERMISSION_PROFILE,
                workspace=WorkspaceSpec(type='profile', profile=template.get('workspace_profile')),
                model=item.executor_model,
                context_mode=item.context_mode,
                tools=list(item.tools or []),
                metadata=metadata,
            )
    workspace_path = item.controller_workdir or None
    if item.shared_storage_id and (storage := store.get_shared_storage(item.shared_storage_id)):
        workspace_path = controller_storage_path(storage, item.storage_subpath) or workspace_path
    return SessionCreate(
        name=f'ctx-{re.sub(r"[^A-Za-z0-9._-]+", "-", item.name).lower()}',
        agent_profile=item.agent_profile,
        permission_profile=item.permission_profile or CODING_SESSION_PERMISSION_PROFILE,
        workspace=WorkspaceSpec(type='local', path=workspace_path),
        model=item.executor_model,
        context_mode=item.context_mode,
        tools=list(item.tools or []),
        metadata=metadata,
    )


def _ensure_agent_context_session(item: AgentContext, auth: CurrentUser) -> Session:
    if item.last_session_id:
        existing = store.get_session(item.last_session_id)
        if existing:
            return existing
    session_creator = session_routes.create_session_for_internal_use
    if session_creator is None:
        raise RuntimeError('Session route creator is not registered')
    session = session_creator(_agent_context_to_session_create(item), _auth=auth)
    item.last_session_id = session.id
    store.add_agent_context(item)
    return session


def _shared_storage_payload_to_item(existing: SharedStorage | None, payload: SharedStoragePayload) -> SharedStorage:
    base = existing or SharedStorage(id=(payload.id or _storage_id_from_name(payload.name.strip())), name=payload.name.strip())
    base.name = payload.name.strip()
    base.description = payload.description.strip() if isinstance(payload.description, str) and payload.description.strip() else None
    base.driver = str(payload.driver or base.driver or 'nfs')
    base.network_path = payload.network_path or None
    base.controller_path = payload.controller_path or None
    base.mount_path = str(payload.mount_path or base.mount_path or '/workspace').strip() or '/workspace'
    base.endpoint_selector = payload.endpoint_selector or None
    base.endpoint_ids = [str(item).strip() for item in (payload.endpoint_ids or []) if str(item).strip()]
    base.writable = bool(payload.writable)
    base.default_subpath = payload.default_subpath or None
    base.metadata = dict(base.metadata or {})
    if payload.metadata:
        base.metadata.update(payload.metadata)
    return base


def _resource_grants_from_user(user: User | None) -> list[ResourceGrant]:
    if not user or not isinstance(user.metadata, dict):
        return []
    raw = user.metadata.get('resource_grants')
    if not isinstance(raw, list):
        return []
    grants: list[ResourceGrant] = []
    for item in raw:
        try:
            grants.append(ResourceGrant.model_validate(item))
        except Exception:
            continue
    return grants


def _resource_match(rule: ResourceGrant, resource_type: str, resource_id: str, access: str) -> bool:
    if rule.resource_type != resource_type:
        return False
    if rule.access == 'read' and access == 'write':
        return False
    return fnmatch.fnmatch(resource_id, rule.pattern)


def _user_has_resource_access(auth: CurrentUser, resource_type: str, resource_id: str, access: str = 'read') -> bool:
    if auth.is_admin or not auth.user:
        return True
    for grant in _resource_grants_from_user(auth.user):
        if _resource_match(grant, resource_type, resource_id, access):
            return True
    group_ids = set(auth.user.groups or [])
    for group in store.list_groups():
        if group.id not in group_ids:
            continue
        for grant in group.grants:
            if _resource_match(grant, resource_type, resource_id, access):
                return True
    return False


def _ensure_access_request(auth: CurrentUser, resource_type: str, resource_id: str, access: str = 'read', reason: str | None = None, session_id: str = 'system') -> AccessRequest:
    if not auth.user:
        raise HTTPException(status_code=403, detail='Access denied')
    existing = store.find_pending_access_request(auth.user.id, resource_type, resource_id, access)
    if existing:
        return existing
    request = AccessRequest(
        user_id=auth.user.id,
        username=auth.user.username,
        resource_type=resource_type,
        resource_id=resource_id,
        access=access,
        reason=reason,
        metadata={'display_name': auth.user.display_name or auth.user.username},
    )
    store.add_access_request(request)
    store.add_event(Event(
        session_id=session_id,
        type='access_request_created',
        message=f'Access requested: {auth.user.username} -> {resource_type}:{resource_id}',
        data={'request_id': request.id, 'user_id': auth.user.id, 'resource_type': resource_type, 'resource_id': resource_id, 'access': access, 'reason': reason},
    ))
    return request


def _require_resource_access(auth: CurrentUser, resource_type: str, resource_id: str, access: str = 'read', reason: str | None = None, session_id: str = 'system') -> None:
    if _user_has_resource_access(auth, resource_type, resource_id, access):
        return
    req = _ensure_access_request(auth, resource_type, resource_id, access, reason=reason, session_id=session_id)
    raise HTTPException(status_code=403, detail=f'Access denied. Request queued: {req.id}')


def _session_resource_ref(session: Session) -> tuple[str, str]:
    profile = ''
    if isinstance(session.workspace, dict):
        profile = str(session.workspace.get('profile') or '').strip()
    else:
        profile = str(getattr(session.workspace, 'profile', '') or '').strip()
    if profile:
        return 'workspace', f'profile:{profile}'
    return 'workspace', f'path:{session.workspace_path}'


def _session_origin(metadata: dict[str, Any] | None) -> str:
    return str((metadata or {}).get('session_origin') or '').strip().lower()


def _is_coding_session_metadata(metadata: dict[str, Any] | None) -> bool:
    meta = metadata or {}
    origin = _session_origin(meta)
    return bool(
        meta.get('coding_session')
        or meta.get('ide_mode')
        or origin in {'vscode-extension', 'zed-extension', 'zed', 'ide'}
    )


def _default_coding_endpoint_id() -> str | None:
    for runner in store.list_runners():
        if runner.status == RunnerStatus.online and runner.allow_container_execution:
            return runner.id
    return None


def _resolve_endpoint_selector(selector: str | None, require_container: bool = False) -> str | None:
    tokens = [token.strip().lower() for token in str(selector or '').split(',') if token.strip()]
    for runner in store.list_runners():
        if runner.status != RunnerStatus.online:
            continue
        if require_container and not runner.allow_container_execution:
            continue
        if not tokens:
            return runner.id
        haystack = {str(runner.id).lower(), str(runner.name or '').lower(), *(str(label).lower() for label in (runner.labels or []))}
        if all(any(token in value for value in haystack) for token in tokens):
            return runner.id
    return None


def _preferred_endpoint_for_storage(meta: dict[str, Any]) -> str | None:
    preferred = str(meta.get('preferred_endpoint') or '').strip()
    if preferred:
        return preferred
    for endpoint_id in (meta.get('shared_storage_endpoint_ids') or []):
        runner = store.get_runner(str(endpoint_id))
        if runner and runner.status == RunnerStatus.online and runner.allow_container_execution:
            return runner.id
    return _resolve_endpoint_selector(meta.get('shared_storage_endpoint_selector'), require_container=True)


def _default_coding_container_image(workspace: WorkspaceSpec, metadata: dict[str, Any] | None) -> str:
    meta = metadata or {}
    explicit = str(meta.get('container_image') or '').strip()
    if explicit:
        return explicit
    if workspace.type == 'profile' and workspace.profile and workspace.profile in config.workspaces:
        candidate = str(config.workspaces[workspace.profile].container_image or '').strip()
        if candidate:
            return candidate
    return 'localhost/python-dev:latest'


DEFAULT_ADMIN_GROUP_ID = 'admin'
DEFAULT_ADMIN_CONTEXT_NAME = 'PAC/core'
DEFAULT_ADMIN_WORKSPACE_LABEL = 'PAC'


def _default_admin_group() -> Group:
    grants = [
        ResourceGrant(resource_type='workspace', pattern='*', access='write'),
        ResourceGrant(resource_type='source_context', pattern='*', access='write'),
        ResourceGrant(resource_type='secret', pattern='*', access='write'),
        ResourceGrant(resource_type='session', pattern='*', access='write'),
    ]
    return Group(
        id=DEFAULT_ADMIN_GROUP_ID,
        name='Admin',
        description='Default PAC administration and system-context usage group.',
        grants=grants,
    )


def _admin_permission_profile_name() -> str:
    if 'full-control' in config.permission_profiles:
        return 'full-control'
    return config.controller_harness.permission_profile or 'ask-first'


def _find_pac_system_context() -> AgentContext | None:
    builtins = [item for item in store.list_agent_contexts() if (item.metadata or {}).get('builtin_kind') == 'pac_admin_base']
    return builtins[0] if builtins else None


def _ensure_default_admin_group() -> Group:
    existing = store.get_group(DEFAULT_ADMIN_GROUP_ID)
    if existing:
        return existing
    group = _default_admin_group()
    store.add_group(group)
    return group


def _ensure_admin_user_group_membership(user: User) -> User:
    if user.role != 'admin':
        return user
    groups = list(user.groups or [])
    if DEFAULT_ADMIN_GROUP_ID in groups:
        return user
    user.groups = groups + [DEFAULT_ADMIN_GROUP_ID]
    store.add_user(user)
    return user


def _ensure_default_admin_context(user: User) -> AgentContext:
    item = _find_pac_system_context()
    permission_profile = _admin_permission_profile_name()
    model_name = str(config.controller_harness.model or '').strip()
    desired = {
        'owner_id': user.id,
        'owner_username': user.username,
        'name': DEFAULT_ADMIN_CONTEXT_NAME,
        'description': 'Built-in PAC system administration context for controller maintenance and direct PAC code/config work.',
        'kind': 'controller',
        'workspace_id': None,
        'workspace_template_id': None,
        'controller_workdir': str(_app_dir()),
        'shared_storage_id': None,
        'storage_subpath': None,
        'storage_mount_path': None,
        'endpoint_id': config.controller_harness.runner_id or 'local-PAC',
        'endpoint_selector': None,
        'container_image': None,
        'requires_container': False,
        'agent_profile': config.controller_harness.agent_profile or MAIN_PI_DEV_PROFILE,
        'permission_profile': permission_profile,
        'executor_model': None if model_name in {'', MODEL_NOT_SELECTED} else model_name,
        'use_groups': [DEFAULT_ADMIN_GROUP_ID],
        'editor_groups': [DEFAULT_ADMIN_GROUP_ID],
        'pinned': True,
    }
    if item is None:
        item = AgentContext(
            owner_id=desired['owner_id'],
            owner_username=desired['owner_username'],
            name=desired['name'],
            description=desired['description'],
            kind='controller',
            controller_workdir=desired['controller_workdir'],
            endpoint_id=desired['endpoint_id'],
            requires_container=False,
            agent_profile=desired['agent_profile'],
            permission_profile=desired['permission_profile'],
            executor_model=desired['executor_model'],
            use_groups=[DEFAULT_ADMIN_GROUP_ID],
            editor_groups=[DEFAULT_ADMIN_GROUP_ID],
            pinned=True,
            metadata={
                'builtin_kind': 'pac_admin_base',
                'admin_only': True,
                'system_context': True,
                'workspace_label': DEFAULT_ADMIN_WORKSPACE_LABEL,
                'runtime_label': desired['endpoint_id'],
                'locked_endpoint': True,
                'locked_groups': True,
                'locked_workdir': True,
                'locked_workspace': True,
                'locked_agent_profile': True,
                'locked_permission_profile': True,
            },
        )
        store.add_agent_context(item)
        return item
    changed = False
    for field, value in desired.items():
        if getattr(item, field) != value:
            setattr(item, field, value)
            changed = True
    metadata = dict(item.metadata or {})
    for key, value in {
        'builtin_kind': 'pac_admin_base',
        'admin_only': True,
        'system_context': True,
        'workspace_label': DEFAULT_ADMIN_WORKSPACE_LABEL,
        'runtime_label': desired['endpoint_id'],
        'locked_endpoint': True,
        'locked_groups': True,
        'locked_workdir': True,
        'locked_workspace': True,
        'locked_agent_profile': True,
        'locked_permission_profile': True,
    }.items():
        if metadata.get(key) != value:
            metadata[key] = value
            changed = True
    if changed:
        item.metadata = metadata
        store.add_agent_context(item)
    return item


def _ensure_auth_admin_scaffolding() -> None:
    if config.auth.mode != 'user-password':
        return
    admins = [user for user in store.list_users() if user.role == 'admin']
    if not admins:
        return
    _ensure_default_admin_group()
    for admin_user in admins:
        admin_user = _ensure_admin_user_group_membership(admin_user)
        _ensure_default_admin_context(admin_user)


app.include_router(create_auth_router(
    require_auth=require_auth,
    require_admin=require_admin,
    config=config,
    store=store,
    ensure_auth_admin_scaffolding=_ensure_auth_admin_scaffolding,
    resource_grants_from_user=_resource_grants_from_user,
    resource_match=_resource_match,
))

app.include_router(create_workspaces_router(
    require_auth=require_auth,
    require_admin=require_admin,
    config=config,
    store=store,
    save_config=save_config,
    workspace_template_catalog=_workspace_template_catalog,
    public_workspace_template=_public_workspace_template,
    public_user_workspace=_public_user_workspace,
    workspace_owner=_workspace_owner,
    workspace_payload_to_item=_workspace_payload_to_item,
    ensure_user_workspace_session=_ensure_user_workspace_session,
    context_visibility_owner_ids=_context_visibility_owner_ids,
    public_agent_context=_public_agent_context,
    can_use_agent_context=_can_use_agent_context,
    can_edit_agent_context=_can_edit_agent_context,
    is_pac_system_context=_is_pac_system_context,
    app_dir=_app_dir,
    agent_context_payload_to_item=_agent_context_payload_to_item,
    ensure_agent_context_session=_ensure_agent_context_session,
    storage_catalog=_storage_catalog,
    shared_storage_payload_to_item=_shared_storage_payload_to_item,
    public_shared_storage=public_shared_storage,
))

app.include_router(create_proxy_router(
    require_auth=require_auth,
    get_config=lambda: config,
    save_config=save_config,
    store=store,
    bearer_token=_bearer_token,
))

app.include_router(create_server_config_router(
    require_auth=require_auth,
    get_config=lambda: config,
    set_config=lambda new_config: globals().__setitem__('config', new_config),
    save_config=save_config,
    load_config=load_config,
    store=store,
    config_payload=_config_payload,
    stop_mdns_advertiser=_stop_mdns_advertiser,
    start_mdns_advertiser=_start_mdns_advertiser,
))

# ---- Versioned package self-update -------------------------------------------------

def _app_dir() -> Path:
    return Path(os.environ.get('PACP_APP_DIR', pacp_path('app'))).expanduser().resolve()


def _safe_zip_members(zf: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if not name or name.startswith('/') or name.startswith('../') or '/../' in name:
            raise HTTPException(status_code=400, detail=f'Unsafe zip member path: {info.filename}')
        names.append(name)
    return names


def _find_package_root(extract_dir: Path) -> Path:
    if (extract_dir / 'pyproject.toml').is_file() and (extract_dir / 'pi_agent_platform').is_dir():
        return extract_dir
    candidates = [p for p in extract_dir.iterdir() if p.is_dir()]
    for candidate in candidates:
        if (candidate / 'pyproject.toml').is_file() and (candidate / 'pi_agent_platform').is_dir():
            return candidate
    raise HTTPException(status_code=400, detail='Uploaded package does not look like a PAC version package: pyproject.toml and pi_agent_platform/ were not found')


def _copy_package_tree(src: Path, dst: Path) -> list[str]:
    entries = [
        'README.md', 'requirements.txt', 'pyproject.toml', '.gitignore',
        'pi_agent_platform', 'config', 'scripts', 'deploy', 'containers', 'docs', 'tests', 'vscode-extension', 'binaries',
        'VERSION', 'VERSION_CURRENT.md', 'FILES.txt', 'MANIFEST.json', 'docs-zed-mcp-example.json', 'install.sh', 'mcp',
    ]
    copied: list[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        source = src / entry
        if not source.exists():
            continue
        target = dst / entry
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, target)
        copied.append(entry)
    return copied


def _pip_install_editable(app_dir: Path) -> dict[str, Any]:
    venv_python = app_dir / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        return {'ok': False, 'skipped': True, 'reason': f'Venv Python not found: {venv_python}'}
    proc = subprocess.run(
        [str(venv_python), '-m', 'pip', 'install', '-e', str(app_dir)],
        cwd=str(app_dir), text=True, capture_output=True, timeout=180,
    )
    return {'ok': proc.returncode == 0, 'returncode': proc.returncode, 'stdout': proc.stdout[-4000:], 'stderr': proc.stderr[-4000:]}


def _write_runtime_run_script(app_dir: Path) -> dict[str, Any]:
    """Keep webUI updates from leaving an old 8443 run.sh behind."""
    pacp_home = str(ensure_pacp_layout())
    default_port = int(getattr(config.server, 'port', 443) or 443)
    fallback_port = int(getattr(config.service, 'fallback_port', 8443) or 8443)
    if fallback_port < 1024:
        fallback_port = 8443
    run_sh = app_dir / 'run.sh'
    content = f"""#!/usr/bin/env bash
set -euo pipefail
cd "{app_dir}"
. .venv/bin/activate
export PACP_HOME="${{PACP_HOME:-{pacp_home}}}"
PORT="${{PAC_PORT:-{default_port}}}"
if [ "$PORT" -lt 1024 ] 2>/dev/null; then
  if ! python - "$PORT" <<'PYBIND' >/dev/null 2>&1
import socket, sys
s = socket.socket()
try:
    s.bind(('0.0.0.0', int(sys.argv[1])))
finally:
    s.close()
PYBIND
  then
    echo "PAC cannot bind privileged port $PORT as this user; falling back to {fallback_port}. Run sudo ./install.sh or install the systemd service with CAP_NET_BIND_SERVICE for port 443." >&2
    PORT={fallback_port}
  fi
fi
export PAC_PORT="$PORT"
CERT="$PACP_HOME/config/tls/pac-server.crt"
KEY="$PACP_HOME/config/tls/private/pac-server.key"
if [ "${{PAC_HTTPS:-1}}" = "1" ] && [ ! -f "$CERT" ] && command -v openssl >/dev/null 2>&1; then
  "{app_dir}/scripts/ensure-pac-ca.sh" "$PACP_HOME" "$PORT" >/dev/null 2>&1 || true
fi
if [ "${{PAC_HTTPS:-1}}" = "1" ] && [ -f "$CERT" ] && [ -f "$KEY" ]; then
  exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --ssl-certfile "$CERT" --ssl-keyfile "$KEY" --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
"""
    run_sh.write_text(content, encoding='utf-8')
    try:
        run_sh.chmod(0o755)
    except Exception:
        pass
    return {'ok': True, 'run_script': str(run_sh), 'default_port': default_port, 'fallback_port': fallback_port}




def _delayed_restart_process() -> None:
    """Restart PAC after the HTTP response has been sent.

    Prefer systemd when available. If that fails, exit with a non-zero status so
    the installed Restart=on-failure unit, container restart policy, or supervisor
    can bring PAC back. Manual foreground runs will stop and need to be started
    again.
    """
    import time
    service = os.environ.get('PAC_SERVICE', 'pacp')
    time.sleep(0.8)
    try:
        if shutil.which('systemctl'):
            if os.getuid() == 0 and Path('/etc/systemd/system').exists():
                subprocess.Popen(['systemctl', 'restart', service], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)
            else:
                subprocess.Popen(['systemctl', '--user', 'restart', service], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)
    except Exception:
        pass
    os._exit(75)


def _schedule_local_restart(background_tasks: BackgroundTasks, reason: str) -> None:
    store.add_event(Event(session_id='system', type='restart_requested', message=reason))
    background_tasks.add_task(_delayed_restart_process)


app.include_router(create_package_upload_router(
    require_auth=require_auth,
    ensure_pacp_layout=ensure_pacp_layout,
    pacp_path=pacp_path,
    store=store,
    safe_zip_members=_safe_zip_members,
    find_package_root=_find_package_root,
    app_dir=_app_dir,
    build_backup_archive=build_backup_archive,
    compare_trees=compare_trees,
    copy_package_tree=_copy_package_tree,
    pip_install_editable=_pip_install_editable,
    write_runtime_run_script=_write_runtime_run_script,
    schedule_local_restart=_schedule_local_restart,
))





def _tls_paths() -> dict[str, Path]:
    base = pacp_path('config', 'tls')
    private = base / 'private'
    return {
        'ca_cert': base / 'pac-root-ca.crt',
        'ca_key': private / 'pac-root-ca.key',
        'server_cert': base / 'pac-server.crt',
        'server_key': private / 'pac-server.key',
        'details': base / 'ca-details.yaml',
    }


def _cert_not_after(path: Path) -> str | None:
    if not path.exists() or not shutil.which('openssl'):
        return None
    try:
        proc = subprocess.run(['openssl', 'x509', '-enddate', '-noout', '-in', str(path)], text=True, capture_output=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip().startswith('notAfter='):
            return proc.stdout.strip().split('=', 1)[1]
    except Exception:
        return None
    return None




def _cert_contains_text(path: Path, expected: str) -> bool:
    if not path.exists() or not shutil.which('openssl'):
        return False
    try:
        proc = subprocess.run(['openssl', 'x509', '-noout', '-text', '-in', str(path)], text=True, capture_output=True, timeout=5)
        return proc.returncode == 0 and expected in proc.stdout
    except Exception:
        return False

def _ensure_tls_material() -> dict[str, Any]:
    paths = _tls_paths()
    script = _app_dir() / 'scripts' / 'ensure-pac-ca.sh'
    generated = False
    if script.exists() and (not paths['ca_cert'].exists() or not paths['server_cert'].exists() or not _cert_contains_text(paths['server_cert'], 'DNS:admin.pac.local')):
        try:
            subprocess.run([str(script), str(ensure_pacp_layout()), str(config.server.port)], timeout=30, check=False, capture_output=True, text=True)
            generated = True
        except Exception:
            pass
    return {
        'enabled': getattr(config, 'tls', None).enabled if getattr(config, 'tls', None) else True,
        'generated_now': generated,
        'ca_cert_file': str(paths['ca_cert']),
        'server_cert_file': str(paths['server_cert']),
        'details_file': str(paths['details']),
        'ca_exists': paths['ca_cert'].exists(),
        'server_cert_exists': paths['server_cert'].exists(),
        'ca_valid_until': _cert_not_after(paths['ca_cert']),
        'server_valid_until': _cert_not_after(paths['server_cert']),
        'ca_download_url': '/v1/tls/ca.pem',
        'public_url': config.server.public_url,
    }




def _safe_runner_slug(name: str) -> str:
    cleaned = re.sub(r'[^a-z0-9-]+', '-', str(name or '').strip().lower())
    cleaned = re.sub(r'-+', '-', cleaned).strip('-')
    return cleaned[:80] or f'endpoint-{uuid.uuid4().hex[:8]}'

def _safe_cert_name(name: str) -> str:
    cleaned = ''.join(c if c.isalnum() or c in ('-', '_', '.') else '-' for c in name.strip())
    return cleaned[:80] or f'endpoint-{uuid.uuid4().hex[:8]}'


def _binary_artifact_meta(project: str, target: str, prefer_version: str | None = None) -> dict[str, Any] | None:
    inventory = source_list_binary_artifacts(project).get('projects', [])
    project_meta = next((item for item in inventory if item.get('project') == project), None)
    if not project_meta:
        return None
    artifacts = list(project_meta.get('artifacts') or [])
    if not artifacts:
        return None
    target_slug = str(target or '').strip().lower().replace('/', '-')
    candidates = [item for item in artifacts if target_slug in str(item.get('name') or '').lower()]
    if prefer_version:
        versioned = [item for item in candidates if str(item.get('version') or '') == str(prefer_version)]
        if versioned:
            candidates = versioned
    return candidates[0] if candidates else None


def _mint_endpoint_onboarding_token(current: CurrentUser, ttl_hours: int) -> tuple[str, str | None, str]:
    if config.auth.enabled and config.auth.mode == 'dev-token' and config.auth.dev_token:
        expires = (datetime.utcnow() + timedelta(hours=max(1, ttl_hours))).isoformat()
        return str(config.auth.dev_token), expires, 'controller-dev-token'
    if config.auth.enabled and config.auth.mode == 'user-password':
        token = uuid.uuid4().hex + uuid.uuid4().hex
        expires = (datetime.utcnow() + timedelta(hours=max(1, ttl_hours))).isoformat()
        user_id = current.user.id if current.user else 'admin'
        store.add_user_token(token, user_id, expires)
        store.add_event(Event(session_id='system', type='endpoint_onboarding_token_created', message=f'Endpoint onboarding token minted for: {current.user.username if current.user else "admin"}', data={'username': current.user.username if current.user else 'admin', 'ttl_hours': ttl_hours}))
        return token, expires, 'temporary-user-token'
    token = _controller_auth_token()
    if token:
        expires = (datetime.utcnow() + timedelta(hours=max(1, ttl_hours))).isoformat()
        return token, expires, 'controller-service-token'
    raise HTTPException(status_code=400, detail='No controller token is available for endpoint onboarding')


def _normalise_sans(name: str, sans: list[str] | None) -> list[str]:
    values: list[str] = []
    for item in ([name] + (sans or [])):
        item = str(item).strip()
        if not item:
            continue
        if item.startswith(('DNS:', 'IP:')):
            values.append(item)
            continue
        try:
            ipaddress.ip_address(item)
            values.append(f'IP:{item}')
        except ValueError:
            values.append(f'DNS:{item.rstrip(".")}')
    # Preserve order, remove duplicates.
    out: list[str] = []
    for item in values:
        if item not in out:
            out.append(item)
    return out


def _issue_endpoint_certificate(name: str, csr_pem: str | None = None, sans: list[str] | None = None, days: int | None = None) -> dict[str, Any]:
    status = _ensure_tls_material()
    if not status.get('ca_exists'):
        raise HTTPException(status_code=500, detail='PAC CA is not available')
    if not shutil.which('openssl'):
        raise HTTPException(status_code=500, detail='openssl is required to issue endpoint certificates')
    paths = _tls_paths()
    cert_name = _safe_cert_name(name)
    endpoint_dir = pacp_path('config', 'tls', 'endpoints', cert_name)
    endpoint_dir.mkdir(parents=True, exist_ok=True)
    key_path = endpoint_dir / f'{cert_name}.key'
    csr_path = endpoint_dir / f'{cert_name}.csr'
    cert_path = endpoint_dir / f'{cert_name}.crt'
    ext_path = endpoint_dir / f'{cert_name}.ext'
    serial_path = endpoint_dir / f'{cert_name}.serial'
    leaf_days = max(1, min(int(days or 825), 10950))
    san_values = _normalise_sans(name, sans)
    ext_path.write_text('\n'.join([
        f'subjectAltName={",".join(san_values)}',
        'keyUsage=digitalSignature,keyEncipherment',
        'extendedKeyUsage=clientAuth,serverAuth',
        'basicConstraints=CA:FALSE',
        '',
    ]), encoding='utf-8')
    generated_key = False
    if csr_pem:
        csr_path.write_text(csr_pem, encoding='utf-8')
    else:
        generated_key = True
        proc = subprocess.run([
            'openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(key_path), '-out', str(csr_path),
            '-subj', f'/CN={cert_name}/O=PAC Endpoint/C=NL',
        ], capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f'CSR/key generation failed: {_tail(proc.stderr or proc.stdout, 2000)}')
        try:
            key_path.chmod(0o600)
        except Exception:
            pass
    proc = subprocess.run([
        'openssl', 'x509', '-req', '-in', str(csr_path),
        '-CA', str(paths['ca_cert']), '-CAkey', str(paths['ca_key']), '-CAcreateserial',
        '-out', str(cert_path), '-days', str(leaf_days), '-sha256', '-extfile', str(ext_path),
    ], capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f'Certificate signing failed: {_tail(proc.stderr or proc.stdout, 2000)}')
    try:
        cert_path.chmod(0o644)
    except Exception:
        pass
    ca_pem = paths['ca_cert'].read_text(encoding='utf-8')
    result = {
        'name': cert_name,
        'cert_pem': cert_path.read_text(encoding='utf-8'),
        'ca_pem': ca_pem,
        'cert_file': str(cert_path),
        'ca_file': str(paths['ca_cert']),
        'days': leaf_days,
        'sans': san_values,
        'generated_key': generated_key,
    }
    if generated_key and key_path.exists():
        result['key_pem'] = key_path.read_text(encoding='utf-8')
        result['key_file'] = str(key_path)
    store.add_event(Event(session_id='system', type='endpoint_certificate_issued', message=f'Issued endpoint certificate for {cert_name}', data={'name': cert_name, 'sans': san_values, 'cert_file': str(cert_path), 'generated_key': generated_key}))
    return result




def _run_quiet(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {'cmd': cmd, 'returncode': proc.returncode, 'stdout': _tail(proc.stdout or '', 2000), 'stderr': _tail(proc.stderr or '', 2000), 'ok': proc.returncode == 0}
    except Exception as exc:
        return {'cmd': cmd, 'returncode': None, 'stdout': '', 'stderr': str(exc), 'ok': False}


def _systemctl_available() -> bool:
    return bool(shutil.which('systemctl'))


def _service_paths() -> dict[str, str]:
    service_name = getattr(getattr(config, 'service', None), 'name', 'pacp') or os.environ.get('PAC_SERVICE', 'pacp')
    user_unit = Path.home() / '.config' / 'systemd' / 'user' / f'{service_name}.service'
    system_unit = Path('/etc/systemd/system') / f'{service_name}.service'
    return {'service': service_name, 'user_unit': str(user_unit), 'system_unit': str(system_unit), 'app_dir': str(_app_dir()), 'pacp_home': str(ensure_pacp_layout())}


def _can_sudo_noninteractive() -> bool:
    if os.getuid() == 0:
        return True
    if not shutil.which('sudo'):
        return False
    try:
        proc = subprocess.run(['sudo', '-n', 'true'], capture_output=True, timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


def _service_status_payload() -> dict[str, Any]:
    paths = _service_paths()
    service_name = paths['service']
    status: dict[str, Any] = {
        **paths,
        'configured_mode': getattr(getattr(config, 'service', None), 'mode', 'user'),
        'effective_uid': os.getuid(),
        'systemctl': _systemctl_available(),
        'can_manage_host_now': os.getuid() == 0 or _can_sudo_noninteractive(),
        'user_unit_exists': Path(paths['user_unit']).exists(),
        'system_unit_exists': Path(paths['system_unit']).exists(),
        'port': config.server.port,
        'public_url': config.server.public_url,
    }
    if _systemctl_available():
        status['user_active'] = _run_quiet(['systemctl', '--user', 'is-active', service_name], timeout=5).get('stdout', '').strip() or 'unknown'
        status['system_active'] = _run_quiet(['systemctl', 'is-active', service_name], timeout=5).get('stdout', '').strip() or 'unknown'
    else:
        status['user_active'] = 'systemctl unavailable'
        status['system_active'] = 'systemctl unavailable'
    user_port = _user_service_port()
    status['manual_host_command'] = f'cd {paths["app_dir"]} && sudo PAC_SERVICE={service_name} PAC_PORT=443 PACP_HOME={paths["pacp_home"]} ./install.sh'
    status['manual_user_command'] = f'cd {paths["app_dir"]} && PAC_SERVICE={service_name} PAC_PORT={user_port} PACP_HOME={paths["pacp_home"]} ./install.sh'
    return status


def _default_public_url_for_port(port: int) -> str:
    return 'https://admin.pac.local' if int(port) == 443 else f'https://admin.pac.local:{int(port)}'


def _user_service_port() -> int:
    port = int(getattr(config.server, 'port', 8443) or 8443)
    fallback = int(getattr(config.service, 'fallback_port', 8443) or 8443)
    if port < 1024:
        port = fallback
    if port < 1024:
        port = 8443
    return port


def _preserve_or_default_public_url(current_url: str | None, port: int) -> str:
    value = str(current_url or '').rstrip('/')
    packaged_defaults = {
        'https://admin.pac.local',
        'https://admin.pac.local:443',
        'https://admin.pac.local:8443',
        'https://localhost:443',
        'https://localhost:8443',
        'https://127.0.0.1:443',
        'https://127.0.0.1:8443',
    }
    if not value or value in packaged_defaults:
        return _default_public_url_for_port(port)
    parsed = urllib.parse.urlparse(value if '://' in value else f'https://{value}')
    host = parsed.hostname or ''
    if not host:
        return _default_public_url_for_port(port)
    scheme = parsed.scheme or 'https'
    if int(port) == 443:
        return f'{scheme}://{host}'
    return f'{scheme}://{host}:{int(port)}'


def _write_user_service_unit(service_name: str, port: int) -> Path:
    unit = Path.home() / '.config' / 'systemd' / 'user' / f'{service_name}.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    app_dir = _app_dir()
    home = ensure_pacp_layout()
    content = f"""[Unit]
Description=PAC - Pi Agent Control
After=network-online.target

[Service]
WorkingDirectory={app_dir}
ExecStart={app_dir}/run.sh
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PACP_HOME={home}
Environment=PAC_PORT={port}
Environment=PAC_SERVICE={service_name}

[Install]
WantedBy=default.target
"""
    unit.write_text(content, encoding='utf-8')
    return unit


def _write_system_service_unit(service_name: str, port: int) -> tuple[Path, Path]:
    app_dir = _app_dir()
    home = ensure_pacp_layout()
    user = os.environ.get('SUDO_USER') or os.environ.get('USER') or 'root'
    if user == 'root' and os.getuid() != 0:
        try:
            user = Path.home().owner()
        except Exception:
            pass
    try:
        import pwd, grp
        pw = pwd.getpwnam(user)
        group = grp.getgrgid(pw.pw_gid).gr_name
    except Exception:
        group = user
    content = f"""[Unit]
Description=PAC - Pi Agent Control
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={app_dir}
ExecStart={app_dir}/run.sh
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PACP_HOME={home}
Environment=PAC_PORT={port}
Environment=PAC_SERVICE={service_name}
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
"""
    tmp = pacp_path('run', f'{service_name}.service.tmp')
    tmp.write_text(content, encoding='utf-8')
    return tmp, Path('/etc/systemd/system') / f'{service_name}.service'







app.include_router(create_service_runtime_router(
    require_auth=require_auth,
    get_config=lambda: config,
    save_config=save_config,
    store=store,
    service_status_payload=_service_status_payload,
    write_system_service_unit=_write_system_service_unit,
    write_user_service_unit=_write_user_service_unit,
    run_quiet=_run_quiet,
    can_sudo_noninteractive=_can_sudo_noninteractive,
    user_service_port=_user_service_port,
    preserve_or_default_public_url=_preserve_or_default_public_url,
    schedule_local_restart=_schedule_local_restart,
    ensure_tls_material=_ensure_tls_material,
    mdns_config=_mdns_config,
    mdns_status=lambda: _MDNS_STATUS,
    issue_endpoint_certificate=_issue_endpoint_certificate,
    get_letsencrypt_status=get_letsencrypt_status,
    check_domain_dns=check_domain_dns,
    test_cloudflare_credentials=test_cloudflare_credentials,
    issue_letsencrypt_certificate=issue_letsencrypt_certificate,
))

def _install_pi_harness_command(image: str | None = None) -> str:
    img = image or os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    quoted = shlex.quote(img)
    return f"./scripts/build-pi-container.sh {quoted}"


def _run_local_pi_harness_install(image: str | None = None, runtime: str = 'auto') -> dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'build-pi-container.sh'
    root = Path(__file__).resolve().parents[2]
    source = root / 'containers' / 'pi-agent-harness'
    img = image or os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    requested_runtime = runtime or 'auto'
    selected_runtime = requested_runtime if requested_runtime != 'auto' else None
    diagnostics: list[str] = []

    if not script.is_file():
        return {'exit_code': 127, 'stage': 'preflight', 'stdout': '', 'stderr': 'pi.dev container build script is missing from this PAC install', 'image': img, 'script': str(script), 'source': str(source), 'runtime': requested_runtime}
    if not os.access(script, os.X_OK):
        try:
            script.chmod(script.stat().st_mode | 0o111)
            diagnostics.append(f'Made build script executable: {script}')
        except Exception as exc:
            return {'exit_code': 126, 'stage': 'preflight', 'stdout': '', 'stderr': f'pi.dev container build script is not executable and could not be fixed: {exc}', 'image': img, 'script': str(script), 'source': str(source), 'runtime': requested_runtime}
    if not source.is_dir():
        return {'exit_code': 127, 'stage': 'preflight', 'stdout': '', 'stderr': 'pi.dev container source folder is missing from this PAC install', 'image': img, 'script': str(script), 'source': str(source), 'runtime': requested_runtime}

    if requested_runtime == 'auto':
        for candidate in ('podman', 'docker'):
            if shutil.which(candidate):
                selected_runtime = candidate
                break
    elif not shutil.which(requested_runtime):
        return {'exit_code': 127, 'stage': 'preflight', 'stdout': '', 'stderr': f'Configured container runtime is not available: {requested_runtime}', 'image': img, 'script': str(script), 'source': str(source), 'runtime': requested_runtime}
    if not selected_runtime:
        return {'exit_code': 127, 'stage': 'preflight', 'stdout': '', 'stderr': 'No container runtime found. Install podman or docker, then retry pi.dev install.', 'image': img, 'script': str(script), 'source': str(source), 'runtime': requested_runtime}

    env = os.environ.copy()
    env['CONTAINER_RUNTIME'] = selected_runtime
    try:
        proc = subprocess.run([str(script), img], cwd=str(root), capture_output=True, text=True, timeout=1800, check=False, env=env)
        stdout = ('\n'.join(diagnostics) + ('\n' if diagnostics else '') + (proc.stdout or ''))[-20000:]
        stderr = (proc.stderr or '')[-20000:]
        stage = 'completed' if proc.returncode == 0 else 'build'
        return {'exit_code': proc.returncode, 'stage': stage, 'stdout': stdout, 'stderr': stderr, 'image': img, 'script': str(script), 'source': str(source), 'runtime': selected_runtime, 'command': f'{script} {img}'}
    except subprocess.TimeoutExpired as exc:
        return {'exit_code': 124, 'stage': 'build', 'stdout': (exc.stdout or '')[-20000:] if isinstance(exc.stdout, str) else '', 'stderr': ((exc.stderr or '')[-20000:] if isinstance(exc.stderr, str) else '') + '\npi.dev container build timed out after 30 minutes.', 'image': img, 'script': str(script), 'source': str(source), 'runtime': selected_runtime}
    except Exception as exc:
        return {'exit_code': 1, 'stage': 'start', 'stdout': '\n'.join(diagnostics), 'stderr': f'pi.dev container build could not be started: {exc}', 'image': img, 'script': str(script), 'source': str(source), 'runtime': selected_runtime}


def _local_pi_harness_install_worker(endpoint_id: str, image: str, runtime: str) -> None:
    global _SOURCE_BUILD_ACTIVE
    endpoint = store.get_runner(endpoint_id)
    endpoint_name = endpoint.name if endpoint else endpoint_id
    try:
        result = _run_local_pi_harness_install(image=image, runtime=runtime)
        refreshed = _refresh_local_runner_metadata(emit_event=False)
        pi_state = (refreshed.capabilities or {}).get('pi_container')
        ok = result.get('exit_code') == 0 and bool((pi_state or {}).get('available'))
        event_type = 'endpoint_pi_harness_install_completed' if ok else 'endpoint_pi_harness_install_failed'
        message = f'pi.dev install {"completed" if ok else "failed"} on {endpoint_name}'
        store.add_event(Event(session_id='system', type=event_type, message=message, data={'endpoint_id': endpoint_id, 'result': result, 'pi_container': pi_state}))
    except Exception as exc:
        store.add_event(Event(session_id='system', type='endpoint_pi_harness_install_failed', message=f'pi.dev install failed on {endpoint_name}', data={'endpoint_id': endpoint_id, 'error': str(exc)}))
    finally:
        _SOURCE_BUILD_ACTIVE = None

def _node_install_command(method: str = 'auto') -> str:
    if method == 'apt':
        return 'sudo apt-get update && sudo apt-get install -y nodejs npm'
    if method == 'dnf':
        return 'sudo dnf install -y nodejs npm'
    if method == 'apk':
        return 'sudo apk add --no-cache nodejs npm'
    if method == 'zypper':
        return 'sudo zypper install -y nodejs npm'
    return "if command -v node >/dev/null 2>&1; then node --version; elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y nodejs npm; elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y nodejs npm; elif command -v apk >/dev/null 2>&1; then sudo apk add --no-cache nodejs npm; elif command -v zypper >/dev/null 2>&1; then sudo zypper install -y nodejs npm; else echo 'No supported package manager found for automatic Node.js install' >&2; exit 2; fi"


def _apply_version_package_from_path(package_path: Path, filename: str, restart_after_update: bool = True) -> dict[str, Any]:
    """Apply an already-uploaded PAC full/patch zip from disk."""
    if not zipfile.is_zipfile(package_path):
        raise HTTPException(status_code=400, detail='Uploaded file is not a valid PAC zip package')
    updates_dir = pacp_path('updates')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    extract_dir = updates_dir / f'extracted-{stamp}'
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path) as zf:
        members = _safe_zip_members(zf)
        zf.extractall(extract_dir)
    package_root = _find_package_root(extract_dir)
    app_dir = _app_dir()
    backup_dir = updates_dir / f'backup-app-{stamp}'
    preservation_dir = pacp_path('backups', stamp)
    archive_meta: dict[str, Any] | None = None
    diff_meta: dict[str, Any] | None = None
    if app_dir.exists():
        shutil.copytree(app_dir, backup_dir, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc'))
        archive_meta = build_backup_archive(app_dir, preservation_dir / 'backup.tar.gz')
        diff_summary = compare_trees(
            installed_root=app_dir,
            incoming_root=package_root,
            diff_path=preservation_dir / f'{Path(filename).stem}-user.diff',
            summary_path=preservation_dir / 'change-summary.json',
        )
        diff_meta = {
            'summary': diff_summary,
            'diff_path': str(preservation_dir / f'{Path(filename).stem}-user.diff'),
            'summary_path': str(preservation_dir / 'change-summary.json'),
        }
    copied = _copy_package_tree(package_root, app_dir)
    pip_result = _pip_install_editable(app_dir)
    run_script_result = _write_runtime_run_script(app_dir)
    wrapper_result = _ensure_controller_wrapper(allow_build=True, force_rebuild=True)
    wrapper_restart_result = _restart_controller_wrapper() if wrapper_result.get('ok') else {'ok': False, 'status': 'skipped', 'message': 'Wrapper restart skipped because wrapper update did not succeed.'}
    try:
        _refresh_local_runner_metadata()
    except Exception:
        pass
    marker = pacp_path('run', 'restart-required')
    marker.write_text(f'PAC update applied at {stamp}\nsource={package_path}\nbackup={backup_dir}\n', encoding='utf-8')
    status = 'installed_restarting' if restart_after_update else 'installed_restart_required'
    result = {
        'status': status,
        'package_type': 'pac_app_update',
        'filename': filename,
        'pacp_home': str(ensure_pacp_layout()),
        'app_dir': str(app_dir),
        'backup_dir': str(backup_dir),
        'copied': copied,
        'members': len(members),
        'pip': pip_result,
        'run_script': run_script_result,
        'wrapper_update': wrapper_result,
        'wrapper_restart': wrapper_restart_result,
        'preservation_archive': archive_meta,
        'preservation_diff': diff_meta,
        'restart_required': True,
        'restart_scheduled': restart_after_update,
        'restart_marker': str(marker),
    }
    store.add_event(Event(session_id='system', type='package_applied', message=f'PAC app update applied: {filename}. Restart required.', data=result))
    return result


# --- Endpoint / remote host PAC ---





def _agent_enablement_state(runner: Runner, requested: bool | None = None) -> dict[str, Any]:
    caps = runner.capabilities or {}
    req = caps.get('agent_requirements') or {}
    pi_container = caps.get('pi_container') or {}
    wrapper = caps.get('pac_wrapper') or {}
    node_ok = bool(req.get('node') or (caps.get('tools') or {}).get('node', {}).get('available'))
    wrapper_ok = bool(req.get('pac_wrapper') or wrapper.get('available'))
    pi_ok = bool(pi_container.get('image_available') or pi_container.get('available'))
    wrapper_process = runner.metadata.get('pac_wrapper_process') or {}
    pi_daemon = runner.metadata.get('pi_dev_daemon') or {}
    wants_agent = bool(requested if requested is not None else runner.metadata.get('agent_enabled'))
    main_server = bool(runner.metadata.get('local_control_plane') or runner.metadata.get('controller_pi_dev'))
    required = main_server or bool(runner.metadata.get('pi_dev_required'))
    wrapper_installed = wrapper_ok
    pi_installed = pi_ok
    wrapper_running = bool(wrapper_process.get('running'))
    pi_running = bool(pi_daemon.get('running'))
    if main_server:
        wrapper_ok = wrapper_installed and wrapper_running
        pi_ok = pi_installed and pi_running
    # PAC runs pi.dev through the container image plus the local PAC wrapper. Host
    # Node.js is useful for native pi.dev work, but it is not a blocker when the
    # container runtime path is available.
    enabled = wants_agent and wrapper_ok and pi_ok
    if enabled:
        status = 'ready'
        detail = 'pi.dev is running on this endpoint through the PAC wrapper.'
    elif main_server and wrapper_installed and pi_installed and (not wrapper_running or not pi_running):
        status = 'starting'
        missing = []
        if not wrapper_running:
            missing.append('PAC wrapper process')
        if not pi_running:
            missing.append('pi.dev daemon')
        detail = 'Installed, but not running yet: ' + ', '.join(missing)
    elif wants_agent and not wrapper_installed:
        status = 'blocked'
        detail = wrapper.get('reason') or 'Install the PAC wrapper binary before pi.dev workloads can run.'
    elif wants_agent and not pi_installed:
        status = 'blocked'
        detail = pi_container.get('reason') or 'Install the local pi.dev runtime image before workloads can run.'
    elif required and not wrapper_installed:
        status = 'blocked'
        detail = wrapper.get('reason') or 'The main PAC server requires the PAC wrapper.'
    elif required and not pi_installed:
        status = 'blocked'
        detail = pi_container.get('reason') or 'The main PAC server requires pi.dev to be installed.'
    else:
        status = 'disabled'
        detail = 'This endpoint is available for command execution. pi.dev workloads are not enabled.'
    return {
        'enabled': enabled,
        'requested': wants_agent,
        'required': required,
        'status': status,
        'requires': ['pac-wrapper', 'pi.dev'],
        'node_available': node_ok,
        'node_version': req.get('node_version'),
        'pac_wrapper_available': wrapper_ok,
        'pac_wrapper_installed': wrapper_installed,
        'pac_wrapper_running': wrapper_running,
        'pac_wrapper': wrapper,
        'pi_available': pi_ok,
        'pi_installed': pi_installed,
        'pi_running': pi_running,
        'pi_container': pi_container,
        'detail': detail,
    }


def _normalise_endpoint_metadata(runner: Runner, requested_agent: bool | None = None) -> Runner:
    runner.metadata['endpoint_role'] = 'remote-execution-environment'
    runner.metadata['is_model_host'] = False
    runner.metadata['command_channel'] = {'mode': 'controller-queued', 'can_send': True, 'can_receive': True}
    runner.metadata['agent_enablement'] = _agent_enablement_state(runner, requested_agent)
    runner.metadata['agent_enabled'] = bool(runner.metadata['agent_enablement'].get('enabled'))
    state = runner.metadata['agent_enablement']['status']
    if state == 'blocked':
        runner.metadata['agent_runtime'] = _runtime_agent_state('endpoint-agent', 'blocked', runner.metadata['agent_enablement']['detail'], requires=['pac-wrapper', 'pi.dev'])
    elif state == 'ready':
        runner.metadata['agent_runtime'] = _runtime_agent_state('endpoint-agent', 'ready', runner.metadata['agent_enablement']['detail'], requires=['pac-wrapper', 'pi.dev'])
    elif state == 'starting':
        runner.metadata['agent_runtime'] = _runtime_agent_state('endpoint-agent', 'starting', runner.metadata['agent_enablement']['detail'], requires=['pac-wrapper', 'pi.dev'])
    else:
        runner.metadata.setdefault('agent_runtime', _runtime_agent_state('remote-execution', 'available', 'Remote command execution is available.'))
    return runner

def _packages_for_tools(tool_names: list[str]) -> list[str]:
    selected = set(tool_names or [])
    packages: list[str] = []
    for package_name, package in config.tool_packages.items():
        package_tools = set(package.tools or [])
        if package_tools and package_tools.issubset(selected):
            packages.append(package_name)
    return packages


def _endpoint_default_workspace(runner_id: str, runner_name: str) -> str:
    """Return the default workspace profile for an endpoint, creating it when missing."""
    for name, workspace in config.workspaces.items():
        if workspace.endpoint_id == runner_id and workspace.is_default:
            return name
    safe = _safe_runner_slug(runner_name or runner_id)
    name = f'{safe}-default'
    base = name
    i = 2
    while name in config.workspaces and config.workspaces[name].endpoint_id not in (None, runner_id):
        name = f'{base}-{i}'
        i += 1
    config.workspaces[name] = WorkspaceProfile(
        description=f'Default workspace for {runner_name or runner_id}',
        type='local',
        path=None,
        endpoint_id=runner_id,
        is_default=True,
    )
    save_config(config)
    return name


def _refresh_local_runner_metadata(emit_event: bool = False) -> Runner:
    capabilities = discover_host()
    containers = discover_containers()
    runner = store.get_runner('local-PAC') or Runner(
        id='local-PAC',
        name='local-PAC',
        labels=['local', 'PAC'],
        endpoint='local://PAC',
        allow_host_execution=True,
        allow_container_execution=bool(capabilities.get('container_runtimes')),
        metadata={'local_control_plane': True},
    )
    runner.status = RunnerStatus.online
    runner.labels = sorted(set((runner.labels or []) + ['local', 'PAC']))
    runner.capabilities = capabilities
    runner.containers = containers
    runner.allow_container_execution = bool(capabilities.get('container_runtimes'))
    default_workspace = _endpoint_default_workspace('local-PAC', runner.name)
    pi_container = capabilities.get('pi_container') or {}
    image_present = bool(pi_container.get('image_available') or pi_container.get('available'))
    agent_status = 'attention'
    agent_detail = 'pi.dev image is installed, but the runtime is not running yet.' if image_present else (pi_container.get('reason') or 'pi.dev runtime image is not available on this endpoint.')
    previous_pi_state = runner.metadata.get('pi_container_available')
    runner.metadata.update({
        'local_control_plane': True,
        'agent_enabled': True,
        'controller_version': PAC_VERSION,
        'endpoint_version': runner.metadata.get('endpoint_version') or PAC_VERSION,
        'runner_version': runner.metadata.get('runner_version') or PAC_VERSION,
        'agent_runtime': _runtime_agent_state('pac-local', agent_status, agent_detail, pi_container=pi_container),
        'pi_container_available': image_present,
        'agent_tools': runner.metadata.get('agent_tools') or [name for name, tool in config.tools.items() if tool.enabled],
        'tool_packages': runner.metadata.get('tool_packages') or list(config.tool_packages.keys()),
        'default_workspace': default_workspace,
        'source_library': {'available': True, 'archive_url': '/v1/sources/archive', 'root': ensure_source_library().get('root')},
    })
    runner.metadata['pac_wrapper_process'] = _wrapper_process_state() if '_wrapper_process_state' in globals() else {'running': False}
    runner.metadata['pi_dev_daemon'] = _pi_dev_daemon_state() if '_pi_dev_daemon_state' in globals() else {'running': False}
    if runner.metadata.get('pac_wrapper_process', {}).get('running'):
        runtime_pi = dict(pi_container)
        runtime_pi['available'] = bool(runner.metadata.get('pi_dev_daemon', {}).get('running'))
        runner.metadata['agent_runtime'] = _runtime_agent_state('pac-wrapper', 'ready', 'Local PAC wrapper process is running and connected.', wrapper=runner.metadata.get('pac_wrapper_process'), pi_daemon=runner.metadata.get('pi_dev_daemon'), pi_container=runtime_pi)
    runner = _normalise_endpoint_metadata(runner, True)
    runner.last_seen_at = Event(session_id='system', type='noop', message='noop').created_at
    store.add_runner(runner)
    if previous_pi_state is None or bool(previous_pi_state) != image_present:
        event_type = 'endpoint_pi_container_ready' if image_present else 'endpoint_pi_container_unavailable'
        store.add_event(Event(session_id='system', type=event_type, message=agent_detail, data={'runner_id': runner.id, 'pi_container': pi_container}))
    if emit_event:
        store.add_event(Event(session_id='system', type='local_runner_added', message='Local PAC endpoint refreshed', data={'runner_id': runner.id, 'containers': len(containers), 'pi_container': pi_container}))
    return runner



app.include_router(create_updates_router(
    require_auth=require_auth,
    pac_version=PAC_VERSION,
    store=store,
    app_dir=_app_dir,
    list_update_archives=_list_update_archives,
    load_pac_changelog=_load_pac_changelog,
    update_backups_root=_update_backups_root,
    local_diffs_root=_local_diffs_root,
    current_release_package=_current_release_package,
    compose_release_notes_body=_compose_release_notes_body,
    changelog_delta=_changelog_delta,
    read_version_from_tree=_read_version_from_tree,
    suggest_next_version=_suggest_next_version,
    apply_version_package_from_path=_apply_version_package_from_path,
    pip_install_editable=_pip_install_editable,
    write_runtime_run_script=_write_runtime_run_script,
    schedule_local_restart=_schedule_local_restart,
))


app.include_router(create_system_router(
    require_auth=require_auth,
    pac_version=PAC_VERSION,
    pacp_home=ensure_pacp_layout,
    config_path=default_config_path,
    refresh_local_runner_metadata=_refresh_local_runner_metadata,
    list_sessions=store.list_sessions,
    list_tasks=store.list_tasks,
    list_runners=store.list_runners,
    list_recent_events=store.list_recent_events,
    metrics_component_health=_metrics_component_health,
    platform_alerts=_platform_alerts,
    ui_build_info=_ui_build_info,
    config_payload=_config_payload,
    public_url=lambda: config.server.public_url,
    source_contexts=lambda: config.source_contexts,
    workspaces=lambda: config.workspaces,
    session_slash_commands=list_session_slash_commands,
    setup_status=_setup_status,
    slash_help_text=slash_help_text,
    require_admin_or_runner=_require_admin_or_runner,
))


app.include_router(create_providers_router(
    require_auth=require_auth,
    config=config,
    save_config=save_config,
    store=store,
    model_available=_model_available,
    provider_public=provider_public,
    list_provider_models=list_provider_models,
    sync_models_from_provider=sync_models_from_provider,
    test_provider=test_provider,
    lmstudio_inspect_provider=lmstudio_inspect_provider,
    lmstudio_companion_script=lmstudio_companion_script,
    lmstudio_load_model=lmstudio_load_model,
    lmstudio_unload_model=lmstudio_unload_model,
    lmstudio_download_model=lmstudio_download_model,
    model_card=model_card,
    test_model=test_model,
    effective_context=effective_context,
    list_artifacts=list_artifacts,
    write_artifact=write_artifact,
    task_artifact_dir=task_artifact_dir,
    safe_artifact_path=safe_artifact_path,
))


app.include_router(create_sources_router(
    require_auth=require_auth,
    get_config=lambda: config,
    set_config=lambda new_config: globals().__setitem__('config', new_config),
    store=store,
    user_has_resource_access=_user_has_resource_access,
    require_resource_access=_require_resource_access,
    runner_from_auth_headers=_runner_from_auth_headers,
    admin_auth_valid=_admin_auth_valid,
    get_user_from_auth=_get_user_from_auth,
    require_admin_or_runner=_require_admin_or_runner,
    resolve_variable_tokens=_resolve_variable_tokens,
    require_no_source_builds=_require_no_source_builds,
    set_source_build_active=_set_source_build_active,
    apply_version_package_from_path=_apply_version_package_from_path,
    schedule_local_restart=_schedule_local_restart,
))

app.include_router(create_endpoints_router(
    require_auth=require_auth,
    pac_version=PAC_VERSION,
    config=config,
    store=store,
    save_config=save_config,
    discover_host=discover_host,
    discover_containers=discover_containers,
    ensure_source_library=ensure_source_library,
    source_build_binary=source_build_binary,
    run_endpoint_maintenance=run_endpoint_maintenance,
    issue_endpoint_certificate=_issue_endpoint_certificate,
    mint_endpoint_onboarding_token=_mint_endpoint_onboarding_token,
    safe_runner_slug=_safe_runner_slug,
    runtime_agent_state=_runtime_agent_state,
    endpoint_default_workspace=_endpoint_default_workspace,
    packages_for_tools=_packages_for_tools,
    normalise_endpoint_metadata=_normalise_endpoint_metadata,
    refresh_local_runner_metadata=_refresh_local_runner_metadata,
    source_build_blocker=_source_build_blocker,
    node_install_command=_node_install_command,
    install_pi_harness_command=_install_pi_harness_command,
    local_pi_harness_install_worker=_local_pi_harness_install_worker,
))


app.include_router(create_sessions_router(
    require_auth=require_auth,
    config=config,
    store=store,
    model_available=_model_available,
    session_resource_ref=_session_resource_ref,
    user_has_resource_access=_user_has_resource_access,
    require_resource_access=_require_resource_access,
    is_coding_session_metadata=_is_coding_session_metadata,
    preferred_endpoint_for_storage=_preferred_endpoint_for_storage,
    default_coding_endpoint_id=_default_coding_endpoint_id,
    default_coding_container_image=_default_coding_container_image,
    session_agent_enabled=_session_agent_enabled,
    runner_target_from_task=_runner_target_from_task,
    queue_task_on_runner=_queue_task_on_runner,
    agent_prompt_for_task=_agent_prompt_for_task,
    safe_workspace_path=safe_workspace_path,
    noisy_event_types=NOISY_EVENT_TYPES,
))
