from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import shlex
import subprocess
import tempfile
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

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pi_agent_platform.core.config import AppConfig, ProviderConfig, AgentProfile, WorkspaceProfile, SourceContextConfig, save_config, load_config, default_config_path, MAIN_PI_DEV_PROFILE, AGENT_CONTROL_WORKSPACE, MODEL_NOT_SELECTED
from pi_agent_platform.core.platform_home import ensure_pacp_layout, pacp_path
from pi_agent_platform.core.models import Event, Session, SessionCreate, Task, TaskCreate, TaskStatus, SessionStatus, Runner, RunnerCreateRequest, RunnerRegisterRequest, RunnerHeartbeat, RunnerStatus, RunnerJobCreate, RunnerJob, RunnerJobStatus, RunnerJobUpdate, RunnerJobLog, RunnerExecutionMode, User
from pi_agent_platform.core.runtime import git_diff, git_status, run_shell_task
from pi_agent_platform.core.agent_loop import run_agent_loop
from pi_agent_platform.core.session_commands import list_session_slash_commands, parse_session_slash_command, slash_help_text
from pi_agent_platform.core.subagents import spawn_pi_dev_subagent
from pi_agent_platform.core.runner_discovery import discover_host, discover_containers
from pi_agent_platform.core.maintenance import run_endpoint_maintenance
from pi_agent_platform.core.providers import effective_context, model_card, provider_public, test_model, test_provider, list_provider_models, sync_models_from_provider, lmstudio_inspect_provider, lmstudio_load_model, lmstudio_unload_model, lmstudio_download_model, lmstudio_companion_script
from pi_agent_platform.core.store import store
from pi_agent_platform.core.artifacts import write_artifact, list_artifacts, task_artifact_dir, safe_artifact_path
from pi_agent_platform.core.secrets import secret_store
from pi_agent_platform.core.pac_ram import read_ram, write_ram, list_ram, all_ram
from pi_agent_platform.core.source_variables import source_variable_store
from pi_agent_platform.core.source_library import ensure_source_library, list_tree as source_list_tree, read_text as source_read_text, write_text as source_write_text, make_archive as source_make_archive, build_container as source_build_container, build_binary as source_build_binary, list_binary_artifacts as source_list_binary_artifacts, binary_artifact_path as source_binary_artifact_path, delete_binary_artifact as source_delete_binary_artifact, prune_binary_artifacts as source_prune_binary_artifacts, inspect_feature_pack as source_inspect_feature_pack, apply_feature_pack as source_apply_feature_pack, create_entry as source_create_entry, rename_entry as source_rename_entry, delete_entry as source_delete_entry, fetch_online_package_updates as source_fetch_online_package_updates
from pi_agent_platform.core.update_preservation import build_backup_archive, compare_trees, generate_local_diff, list_generated_diffs
from pi_agent_platform.updates import fetch_latest_release_metadata, download_release_package


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
        _web_dir() / 'assets' / 'pac-logo.svg',
        _web_dir() / 'assets' / 'pac-icon.svg',
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
        '/ui/assets/favicon.svg': f"/ui/assets/favicon.svg?v={info['asset_stamp']}",
        '/ui/assets/pac-logo.svg': f"/ui/assets/pac-logo.svg?v={info['asset_stamp']}",
        '/ui/assets/pac-icon.svg': f"/ui/assets/pac-icon.svg?v={info['asset_stamp']}",
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
            issues.append(_setup_issue('controller_model_missing', 'Select the controller pi.dev model', f'The controller pi.dev runtime is enabled, but profile {profile_name or MAIN_PI_DEV_PROFILE} does not resolve to a configured model.', 'settings-tab', 'Open Settings'))
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


def _config_payload() -> dict[str, Any]:
    return {
        'server': config.server.model_dump(),
        'runtime': config.runtime.model_dump(),
        'controller_harness': config.controller_harness.model_dump(),
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
    runner = store.get_runner(settings.runner_id) or _refresh_local_runner_metadata(emit_event=False)
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
    existing = _find_controller_harness_session()
    pac_wrapper = (runner.capabilities or {}).get('pac_wrapper') or {}
    if not pac_wrapper.get('available'):
        return {'ok': False, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump() if existing else None, 'message': pac_wrapper.get('reason') or 'The main server requires the local PAC wrapper before the controller session can run.'}
    pi_container = (runner.capabilities or {}).get('pi_container') or {}
    if not pi_container.get('available'):
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
        if existing.workspace_path != (workspace.path or _platform_workspace_path()):
            existing.workspace_path = workspace.path or _platform_workspace_path(); changed = True
        existing.workspace = existing.workspace.model_copy(update={'type': 'profile', 'profile': settings.workspace_profile, 'path': workspace.path})
        existing.metadata.update({'controller_harness': True, 'preferred_endpoint': settings.runner_id, 'endpoint_locked': True, 'agent_enabled': True, 'execution_mode': 'pi.dev'})
        if changed:
            store.add_session(existing)
        return {'ok': True, 'enabled': True, 'runner': runner.model_dump(), 'workspace': workspace.model_dump(), 'session': existing.model_dump(), 'message': 'Controller pi.dev session is active'}
    session = Session(
        name=settings.session_name,
        agent_profile=profile_name,
        permission_profile=permission,
        context_mode=settings.context_mode,
        workspace={'type': 'profile', 'profile': settings.workspace_profile, 'path': workspace.path},
        workspace_path=workspace.path or _platform_workspace_path(),
        model=model_name,
        tools=list(config.tools.keys()) if settings.expose_platform_tools else [],
        metadata={'controller_harness': True, 'preferred_endpoint': settings.runner_id, 'endpoint_locked': True, 'agent_enabled': True, 'execution_mode': 'pi.dev'},
    )
    Path(session.workspace_path).mkdir(parents=True, exist_ok=True)
    store.add_session(session)
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


def _ensure_controller_wrapper(allow_build: bool = True) -> dict[str, Any]:
    settings = config.controller_harness
    project = settings.wrapper_binary_project or 'pac-endpoint'
    target = _host_binary_target()
    wrapper_path = _controller_wrapper_path()
    if wrapper_path.is_file() and os.access(wrapper_path, os.X_OK):
        return {'ok': True, 'status': 'ready', 'path': str(wrapper_path), 'target': target, 'message': 'PAC wrapper is installed.'}
    artifact = _find_matching_binary_artifact(project, target)
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
        return {'ok': True, 'status': 'built_installed', 'target': target, 'build': result, 'message': 'PAC wrapper built and installed.', **installed}
    return {'ok': False, 'status': 'build_failed', 'target': target, 'build': result, 'message': 'PAC wrapper build did not produce a host binary.'}


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
    return ''


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
    global _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE
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
            if not state.get('running'):
                result = _start_controller_wrapper_once()
                store.add_event(Event(session_id='system', type='controller_wrapper_started' if result.get('ok') else 'controller_wrapper_start_failed', message=result.get('message', 'PAC wrapper start checked'), data=result))
            time.sleep(10)
    finally:
        _CONTROLLER_WRAPPER_SUPERVISOR_ACTIVE = False


def _start_controller_wrapper_supervisor() -> bool:
    if not config.controller_harness.enabled:
        return False
    threading.Thread(target=_controller_wrapper_supervisor, daemon=True).start()
    return True


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
    if settings.auto_install_pi_dev and not pi_container.get('available'):
        install_result = _run_local_pi_harness_install(runtime='auto')
        steps.append({'step': 'pi_dev_image', **install_result})
    else:
        steps.append({'step': 'pi_dev_image', 'ok': bool(pi_container.get('available')), 'status': 'ready' if pi_container.get('available') else 'missing', 'pi_container': pi_container})
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


class TimelineEventCreate(BaseModel):
    type: str = 'agent_note'
    message: str = ''
    task_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


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
    _start_mdns_advertiser()


@app.on_event('shutdown')
def _shutdown_services() -> None:
    _stop_mdns_advertiser()


class FileWriteRequest(BaseModel):
    path: str
    content: str


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class EndpointMaintenanceRequest(BaseModel):
    max_age_hours: int = 24
    dry_run: bool = False
    remove_containers: bool = True
    remove_workspaces: bool = True
    remove_temp_artifacts: bool = True
    prune_images: bool = False


class EndpointCertificateRequest(BaseModel):
    name: str
    csr_pem: str | None = None
    sans: list[str] = []
    days: int | None = None


class ServiceModeRequest(BaseModel):
    mode: str


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
        metadata={'agent_profile': session.agent_profile, 'model': session.model, **task.metadata},
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


@app.post('/v1/mcp/build')
def build_mcp_bridge(background_tasks: BackgroundTasks, runtime: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    build_id = uuid.uuid4().hex[:12]
    _mcp_write_status('queued', 'Zed binary build queued from Sources / binaries / zed-binary')
    _mcp_build_event(build_id, 'mcp_build_queued', 'Zed binary build queued from Sources')
    background_tasks.add_task(_run_mcp_builder, runtime, build_id)
    return {'ok': True, 'status': 'queued', 'build_id': build_id, 'status_url': '/v1/mcp/build/status'}


@app.get('/v1/mcp/build/status')
def mcp_build_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    status_file = _mcp_status_file()
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding='utf-8'))
        except Exception:
            data = {'status': 'unknown', 'message': 'Status file could not be parsed'}
    else:
        data = {'status': 'not_built', 'message': 'No Zed binary build has run yet.'}
    data['artifacts'] = _mcp_artifacts()
    data['version'] = PAC_VERSION
    return data


@app.get('/v1/mcp/download/{filename}')
def mcp_download(filename: str, _auth: None = Depends(require_auth)):
    if '/' in filename or '\\' in filename or filename.startswith('.'):
        raise HTTPException(status_code=400, detail='Invalid filename')
    path = (_mcp_dir() / 'bin' / filename).resolve()
    if _mcp_dir().resolve() not in path.parents:
        raise HTTPException(status_code=400, detail='Invalid path')
    if not path.is_file():
        raise HTTPException(status_code=404, detail='MCP binary not found')
    return FileResponse(path, filename=filename, media_type='application/octet-stream')


@app.get('/v1/version')
def get_version() -> dict[str, Any]:
    ui = _ui_build_info()
    return {
        'version': PAC_VERSION,
        'name': 'PAC',
        'full_name': 'Pi Agent Control',
        'ui_build': ui['asset_stamp'],
        'ui_updated_at': ui['updated_at'],
    }


def _public_user(user: User) -> dict[str, Any]:
    return {
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'role': user.role,
        'created_at': user.created_at.isoformat(),
        'updated_at': user.updated_at.isoformat(),
        'metadata': user.metadata or {},
    }


@app.get('/v1/auth/status')
def auth_status() -> dict[str, Any]:
    user_count = len(store.list_users())
    return {
        'enabled': config.auth.enabled,
        'mode': config.auth.mode,
        'needs_setup': config.auth.mode == 'user-password' and user_count == 0,
        'user_count': user_count,
        'token_ttl_hours': config.auth.token_ttl_hours,
    }


@app.post('/v1/auth/setup')
def auth_setup(payload: dict[str, Any]) -> dict[str, Any]:
    if config.auth.mode != 'user-password':
        raise HTTPException(status_code=400, detail='User-password auth not enabled')
    if store.list_users():
        raise HTTPException(status_code=403, detail='System already has users. Use /v1/auth/login.')
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    display_name = str(payload.get('display_name') or username).strip() or username
    if not username or not password:
        raise HTTPException(status_code=400, detail='username and password required')
    if len(password) < 8:
        raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
    user = User(id=username, username=username, display_name=display_name, role='admin')
    user.set_password(password)
    store.add_user(user)
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires_at = (datetime.utcnow() + timedelta(hours=max(1, int(config.auth.token_ttl_hours or 720)))).isoformat()
    store.add_user_token(token, user.id, expires_at)
    store.add_event(Event(session_id='system', type='initial_setup', message=f'Initial admin user created: {username}', data={'username': username}))
    return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': _public_user(user)}


@app.post('/v1/auth/login')
def auth_login(payload: dict[str, Any]) -> dict[str, Any]:
    if config.auth.mode != 'user-password':
        raise HTTPException(status_code=400, detail='User-password auth not enabled')
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    if not username or not password:
        raise HTTPException(status_code=400, detail='username and password required')
    user = store.get_user_by_username(username)
    if not user or not user.verify_password(password):
        raise HTTPException(status_code=401, detail='Invalid credentials')
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires_at = (datetime.utcnow() + timedelta(hours=max(1, int(config.auth.token_ttl_hours or 720)))).isoformat()
    store.add_user_token(token, user.id, expires_at)
    store.add_event(Event(session_id='system', type='user_login', message=f'User login: {username}', data={'username': username}))
    return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': _public_user(user)}


@app.get('/v1/auth/me')
def auth_me(_auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
    if not _auth.user:
        return {'id': 'controller', 'username': 'controller', 'display_name': 'Controller', 'role': 'admin'}
    return _public_user(_auth.user)


@app.get('/v1/users/me')
def users_me(_auth: CurrentUser = Depends(require_auth)) -> dict[str, Any]:
    return auth_me(_auth)


@app.get('/v1/users')
def list_users(_auth: CurrentUser = Depends(require_auth)) -> list[dict[str, Any]]:
    return [_public_user(user) for user in store.list_users()]


@app.post('/v1/users')
def create_user(payload: dict[str, Any], _auth: CurrentUser = Depends(require_admin)) -> dict[str, Any]:
    username = str(payload.get('username') or payload.get('id') or '').strip()
    password = str(payload.get('password') or '')
    if not username:
        raise HTTPException(status_code=400, detail='username required')
    if not password:
        raise HTTPException(status_code=400, detail='password required')
    if len(password) < 8:
        raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
    if store.get_user_by_username(username):
        raise HTTPException(status_code=409, detail='User already exists')
    user = User(
        id=username,
        username=username,
        display_name=str(payload.get('display_name') or username).strip() or username,
        role=str(payload.get('role') or 'user'),
        metadata=payload.get('metadata') or {},
    )
    user.set_password(password)
    store.add_user(user)
    store.add_event(Event(session_id='system', type='user_created', message=f'User created: {username}', data={'username': username}))
    return {'ok': True, 'user': _public_user(user)}


@app.delete('/v1/users/{user_id}')
def delete_user(user_id: str, _auth: CurrentUser = Depends(require_admin)) -> dict[str, Any]:
    if not store.delete_user(user_id):
        raise HTTPException(status_code=404, detail='User not found')
    store.add_event(Event(session_id='system', type='user_deleted', message=f'User deleted: {user_id}', data={'user_id': user_id}))
    return {'ok': True}


@app.get('/v1/auth/tokens')
def auth_tokens(_auth: CurrentUser = Depends(require_admin)) -> list[dict[str, Any]]:
    return store.list_user_tokens()


@app.post('/v1/auth/tokens')
def create_auth_token(payload: dict[str, Any], _auth: CurrentUser = Depends(require_admin)) -> dict[str, Any]:
    username = str(payload.get('username') or '').strip()
    ttl_hours = int(payload.get('ttl_hours') or config.auth.token_ttl_hours or 720)
    if not username:
        raise HTTPException(status_code=400, detail='username required')
    user = store.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires_at = (datetime.utcnow() + timedelta(hours=max(1, ttl_hours))).isoformat()
    store.add_user_token(token, user.id, expires_at)
    store.add_event(Event(session_id='system', type='token_created', message=f'Token minted for: {username}', data={'username': username, 'created_by': _auth.user.username if _auth.user else 'controller'}))
    return {'ok': True, 'token': token, 'expires_at': expires_at, 'user': _public_user(user)}


@app.delete('/v1/auth/tokens/{token}')
def revoke_auth_token(token: str, _auth: CurrentUser = Depends(require_admin)) -> dict[str, Any]:
    store.delete_user_token(token)
    return {'ok': True}


@app.get('/healthz')
def healthz() -> dict[str, str]:
    return {'status': 'ok', 'version': PAC_VERSION, 'pacp_home': str(ensure_pacp_layout()), 'config_path': str(default_config_path())}




@app.get('/v1/metrics/summary')
def metrics_summary(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    _refresh_local_runner_metadata(emit_event=False)
    sessions = store.list_sessions()
    tasks = store.list_tasks()
    runners = store.list_runners()
    recent_events = store.list_recent_events(limit=500)
    now = datetime.now(timezone.utc)
    day_keys = [(now - timedelta(days=idx)).date().isoformat() for idx in range(6, -1, -1)]
    events_by_day = {key: 0 for key in day_keys}
    event_types: dict[str, int] = {}
    noisy_metric_events = {'runner_heartbeat', 'endpoint_heartbeat', 'provider_heartbeat'}
    for event in recent_events:
        if event.type not in noisy_metric_events:
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
    component_health = _metrics_component_health(runners)
    ui = _ui_build_info()
    return {
        'version': PAC_VERSION,
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
    }


@app.get('/v1/config')
def get_config(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return _config_payload()


@app.get('/v1/ide/config')
def get_ide_config(
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    runner = _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    payload = {
        'version': PAC_VERSION,
        'server': {'public_url': config.server.public_url},
        'source_contexts': {name: ctx.model_dump() for name, ctx in config.source_contexts.items()},
        'workspaces': {name: item.model_dump() for name, item in config.workspaces.items()},
        'session_slash_commands': list_session_slash_commands(),
        'setup_status': _setup_status(),
    }
    if runner:
        payload['requested_by'] = {'kind': 'endpoint', 'runner_id': runner.id, 'runner_name': runner.name}
    else:
        payload['requested_by'] = {'kind': 'admin'}
    return payload


@app.get('/v1/session-slash-commands')
def get_session_slash_commands(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return {'commands': list_session_slash_commands(), 'help_text': slash_help_text()}


@app.get('/v1/setup/status')
def get_setup_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return _setup_status()


@app.get('/v1/updates/status')
def get_updates_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    archives = _list_update_archives()
    changelog = _load_pac_changelog()
    return {
        'current_version': PAC_VERSION,
        'archive_count': len(archives),
        'latest_archive': archives[0] if archives else None,
        'archives': archives[:12],
        'changelog_current_version': changelog.get('current_version') or PAC_VERSION,
    }


@app.get('/v1/updates/check')
def check_for_updates(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    meta = fetch_latest_release_metadata(PAC_VERSION)
    store.add_event(Event(session_id='system', type='update_checked', message=meta.get('has_update') and f"Update available: v{meta.get('latest_version')}" or 'PAC release channel checked', data=meta))
    return meta


@app.get('/v1/updates/archives')
def list_update_archives(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return {'archives': _list_update_archives()}


@app.get('/v1/updates/archives/{stamp}')
def get_update_archive(stamp: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    target = _update_backups_root() / stamp
    if not target.is_dir():
        raise HTTPException(status_code=404, detail='Update archive not found')
    archive = next((item for item in _list_update_archives() if item['stamp'] == stamp), None)
    if not archive:
        raise HTTPException(status_code=404, detail='Update archive not found')
    return archive


@app.get('/v1/updates/archives/{stamp}/download')
def download_update_archive(stamp: str, kind: str = 'archive', _auth: None = Depends(require_auth)) -> FileResponse:
    target = _update_backups_root() / stamp
    if not target.is_dir():
        raise HTTPException(status_code=404, detail='Update archive not found')
    if kind == 'archive':
        path = target / 'backup.tar.gz'
    elif kind == 'summary':
        path = target / 'change-summary.json'
    elif kind == 'diff':
        path = next((item for item in target.glob('*.diff') if item.is_file()), None)
    else:
        raise HTTPException(status_code=400, detail='Unsupported archive download kind')
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail='Requested archive file not found')
    return FileResponse(Path(path), filename=Path(path).name)


@app.get('/v1/updates/release-notes')
def get_update_release_notes(from_version: str | None = None, to_version: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    entries = _changelog_delta(from_version, to_version)
    return {
        'from_version': from_version or PAC_VERSION,
        'to_version': to_version or (_load_pac_changelog().get('current_version') or PAC_VERSION),
        'entries': entries,
    }


@app.get('/v1/updates/local-diffs')
def get_generated_local_diffs(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    version = _read_version_from_tree(_app_dir()) or PAC_VERSION
    return {
        'current_version': version,
        'suggested_version': _suggest_next_version(version),
        'diffs': list_generated_diffs(_local_diffs_root()),
    }


@app.post('/v1/updates/generate-local-diff')
def create_generated_local_diff(version: str = Query(..., description='Version for the diff, e.g. 1.0.107'), _auth: None = Depends(require_auth)) -> dict[str, Any]:
    clean_version = str(version or '').strip().lstrip('v')
    if not clean_version:
        raise HTTPException(status_code=400, detail='Version is required')
    result = generate_local_diff(_app_dir(), clean_version, _local_diffs_root())
    store.add_event(Event(
        session_id='system',
        type='local_diff_generated',
        message=f'Local diff {("generated" if result.get("status") == "written" else "checked")}: v{clean_version}.diff',
        data=result,
    ))
    return result


@app.get('/v1/updates/diff/{version}')
def download_generated_local_diff(version: str, _auth: None = Depends(require_auth)) -> FileResponse:
    clean_version = str(version or '').strip().lstrip('v')
    diff_path = (_local_diffs_root() / f'v{clean_version}.diff').resolve()
    if not diff_path.exists():
        raise HTTPException(status_code=404, detail=f'Diff not found: v{clean_version}.diff')
    return FileResponse(path=str(diff_path), filename=f'v{clean_version}.diff', media_type='text/plain')


@app.post('/v1/updates/apply')
def apply_release_update(
    background_tasks: BackgroundTasks,
    restart_after_update: bool = Query(default=True),
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    meta = fetch_latest_release_metadata(PAC_VERSION)
    if not meta.get('ok'):
        raise HTTPException(status_code=503, detail=meta.get('error') or 'The PAC release feed is unavailable')
    if not meta.get('has_update'):
        return {'ok': False, 'current_version': PAC_VERSION, 'latest_version': meta.get('latest_version'), 'message': 'PAC is already up to date'}
    download_url = str(meta.get('download_url') or '').strip()
    if not download_url:
        raise HTTPException(status_code=404, detail='Latest PAC release does not provide pac-full.zip')
    downloads_dir = pacp_path('updates', 'downloads')
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target = downloads_dir / f"pac-full-{meta.get('latest_version') or 'latest'}.zip"
    download = download_release_package(download_url, target)
    if not download.get('ok'):
        raise HTTPException(status_code=502, detail=f"Release download failed: {download.get('error')}")
    result = _apply_version_package_from_path(target, target.name, restart_after_update=restart_after_update)
    result.update({'ok': True, 'current_version': PAC_VERSION, 'latest_version': meta.get('latest_version'), 'release_url': meta.get('release_url'), 'download_url': download_url, 'download': download})
    if restart_after_update:
        _schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying release {meta.get("latest_version")}')
    return result


@app.get('/v1/admin/current-package')
def download_current_package(_auth: None = Depends(require_auth)) -> FileResponse:
    try:
        package = _current_release_package()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(package, filename='pac-full.zip')




@app.get('/')
def web_index():
    return _render_web_index()


@app.get('/favicon.ico')
def favicon_ico():
    icon = Path(__file__).resolve().parents[1] / 'web' / 'assets' / 'favicon.svg'
    return FileResponse(icon, media_type='image/svg+xml')


@app.get('/app')
def web_app():
    return _render_web_index()


@app.get('/app/{path:path}')
def web_app_path(path: str):
    return _render_web_index()


@app.get('/ui')
def web_ui_root():
    return _render_web_index()


@app.get('/ui/')
def web_ui_root_slash():
    return _render_web_index()


@app.get('/ui/index.html')
def web_ui_index():
    return _render_web_index()


app.mount('/ui', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'web', html=True), name='ui')




@app.put('/v1/config')
def update_config(payload: ConfigUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global config
    new_config = AppConfig.model_validate(payload.config)
    save_config(new_config)
    config = load_config()
    store.add_event(Event(session_id='system', type='config_updated', message='Configuration updated from Web UI'))
    return _config_payload()



@app.post('/v1/server/connection')
def update_server_connection(payload: ServerConnectionRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    """Update the URL that endpoint/agent binaries should use.

    This is intentionally separate from the raw JSON config editor because mDNS
    is not reliable in every network. Users can set an IP/FQDN-based HTTPS URL
    and future purpose-built binaries will compile that URL in by default.
    """
    global config
    public_url = str(payload.public_url or '').strip().rstrip('/')
    if not (public_url.startswith('https://') or public_url.startswith('http://')):
        raise HTTPException(status_code=400, detail='Controller URL must start with http:// or https://')
    config.server.public_url = public_url
    if payload.mdns_enabled is not None:
        config.mdns.enabled = bool(payload.mdns_enabled)
    save_config(config)
    config = load_config()
    store.add_event(Event(session_id='system', type='server_connection_updated', message=f'Endpoint controller URL set to {config.server.public_url}', data={'public_url': config.server.public_url, 'mdns_enabled': config.mdns.enabled}))
    return {'ok': True, 'public_url': config.server.public_url, 'mdns_enabled': config.mdns.enabled, 'message': 'Endpoint connection settings saved. Rebuild endpoint/agent binaries to compile this URL in.'}


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
    run_sh = app_dir / 'run.sh'
    content = f"""#!/usr/bin/env bash
set -euo pipefail
cd "{app_dir}"
. .venv/bin/activate
export PACP_HOME="${{PACP_HOME:-{pacp_home}}}"
PORT="${{PAC_PORT:-443}}"
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
    echo "PAC cannot bind privileged port $PORT as this user; falling back to 8443. Run sudo ./install.sh or install the systemd service with CAP_NET_BIND_SERVICE for port 443." >&2
    PORT=8443
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
    return {'ok': True, 'run_script': str(run_sh), 'default_port': 443, 'fallback_port': 8443}


@app.post('/v1/admin/stage-package')
@app.post('/v1/update/upload')
@app.post('/v1/admin/upload-stage-package')
async def upload_stage_package(background_tasks: BackgroundTasks, file: UploadFile = File(...), apply_update: bool = Query(default=True), restart_after_update: bool = Query(default=True), _auth: None = Depends(require_auth)) -> dict[str, Any]:
    """Upload a PAC patch/full .pac or .zip package and apply it to ~/.pacp/app.

    This is intentionally conservative: it validates the package layout, creates
    a backup, copies only known project-owned entries, reinstalls editable deps
    into the existing venv, and leaves the running process alive. Restart PAC
    afterwards to load the new Python modules.
    """
    filename = file.filename or 'pac-patch.pac'
    lower_filename = filename.lower()
    if not (lower_filename.endswith('.zip') or lower_filename.endswith('.pac')):
        raise HTTPException(status_code=400, detail='Only .zip or .pac version packages are accepted')
    home = ensure_pacp_layout()
    updates_dir = pacp_path('updates')
    uploads_dir = updates_dir / 'uploads'
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    upload_path = uploads_dir / f'{stamp}-{Path(filename).name}'
    with upload_path.open('wb') as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    extract_dir = updates_dir / f'extracted-{stamp}'
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(upload_path) as zf:
            members = _safe_zip_members(zf)
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail='Uploaded file is not a valid PAC zip package') from exc

    package_root = _find_package_root(extract_dir)
    if not apply_update:
        store.add_event(Event(session_id='system', type='package_uploaded', message=f'Version package uploaded: {filename}', data={'upload_path': str(upload_path), 'package_root': str(package_root)}))
        return {'status': 'uploaded', 'filename': filename, 'upload_path': str(upload_path), 'package_root': str(package_root), 'members': len(members)}

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
    marker = pacp_path('run', 'restart-required')
    marker.write_text(f'PAC update applied at {stamp}\nsource={upload_path}\nbackup={backup_dir}\n', encoding='utf-8')
    store.add_event(Event(session_id='system', type='package_applied', message=f'Version package applied: {filename}. Restart required.', data={'upload_path': str(upload_path), 'backup_dir': str(backup_dir), 'copied': copied, 'pip': pip_result, 'run_script': run_script_result, 'restart_after_update': restart_after_update, 'preservation_archive': archive_meta, 'preservation_diff': diff_meta}))
    status = 'installed_restarting' if restart_after_update else 'installed_restart_required'
    if restart_after_update:
        _schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying version package: {filename}')
    return {
        'status': status,
        'filename': filename,
        'pacp_home': str(home),
        'app_dir': str(app_dir),
        'backup_dir': str(backup_dir),
        'copied': copied,
        'pip': pip_result,
        'run_script': run_script_result,
        'preservation_archive': archive_meta,
        'preservation_diff': diff_meta,
        'restart_required': True,
        'restart_scheduled': restart_after_update,
        'restart_marker': str(marker),
    }


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


@app.post('/v1/admin/restart')
def restart_server(background_tasks: BackgroundTasks, _auth: None = Depends(require_auth)) -> dict[str, str]:
    """Restart PAC using systemd when possible, otherwise exit for supervisor restart."""
    _schedule_local_restart(background_tasks, 'PAC restart requested from Web UI')
    return {'status': 'restarting', 'note': 'PAC will restart through systemd when possible. If PAC was started manually, start it again with run.sh.'}



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
    status['manual_host_command'] = f'cd {paths["app_dir"]} && sudo PAC_SERVICE={service_name} PAC_PORT=443 PACP_HOME={paths["pacp_home"]} ./install.sh'
    status['manual_user_command'] = f'cd {paths["app_dir"]} && PAC_SERVICE={service_name} PAC_PORT=8443 PACP_HOME={paths["pacp_home"]} ./install.sh'
    return status


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


@app.get('/v1/admin/service/status')
def service_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return _service_status_payload()


@app.post('/v1/admin/service/mode')
def set_service_mode(payload: ServiceModeRequest, background_tasks: BackgroundTasks, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global config
    requested = (payload.mode or '').strip().lower()
    if requested not in ('user', 'host'):
        raise HTTPException(status_code=400, detail='mode must be user or host')
    service_name = getattr(config.service, 'name', 'pacp') if hasattr(config, 'service') else os.environ.get('PAC_SERVICE', 'pacp')
    results: list[dict[str, Any]] = []
    if requested == 'host':
        tmp, unit = _write_system_service_unit(service_name, 443)
        if os.getuid() == 0:
            results.append(_run_quiet(['mv', str(tmp), str(unit)]))
            results.append(_run_quiet(['systemctl', 'daemon-reload']))
            results.append(_run_quiet(['systemctl', 'enable', '--now', service_name]))
            results.append(_run_quiet(['systemctl', '--user', 'disable', '--now', service_name], timeout=8))
        elif _can_sudo_noninteractive():
            results.append(_run_quiet(['sudo', '-n', 'mv', str(tmp), str(unit)]))
            results.append(_run_quiet(['sudo', '-n', 'systemctl', 'daemon-reload']))
            results.append(_run_quiet(['sudo', '-n', 'systemctl', 'enable', '--now', service_name]))
            results.append(_run_quiet(['systemctl', '--user', 'disable', '--now', service_name], timeout=8))
        else:
            return {'ok': False, 'needs_sudo': True, 'message': 'Host service requires sudo/root. Run the manual command shown, or start PAC with sudo once to switch modes.', 'status': _service_status_payload(), 'prepared_unit': str(tmp)}
        config.service.mode = 'host'
        config.server.port = 443
        config.server.public_url = 'https://admin.pac.local'
    else:
        _write_user_service_unit(service_name, 8443)
        results.append(_run_quiet(['systemctl', '--user', 'daemon-reload'], timeout=8))
        results.append(_run_quiet(['systemctl', '--user', 'enable', '--now', service_name], timeout=8))
        if os.getuid() == 0:
            results.append(_run_quiet(['systemctl', 'disable', '--now', service_name], timeout=8))
        elif _can_sudo_noninteractive():
            results.append(_run_quiet(['sudo', '-n', 'systemctl', 'disable', '--now', service_name], timeout=8))
        config.service.mode = 'user'
        config.server.port = 8443
        config.server.public_url = 'https://admin.pac.local:8443'
    save_config(config)
    store.add_event(Event(session_id='system', type='service_mode_changed', message=f'PAC service mode set to {requested}', data={'mode': requested, 'results': results}))
    _schedule_local_restart(background_tasks, f'PAC restart scheduled after switching service mode to {requested}')
    return {'ok': all(r.get('ok') for r in results if r.get('returncode') is not None), 'mode': requested, 'results': results, 'restart_scheduled': True, 'status': _service_status_payload()}

@app.get('/v1/tls/status')
def tls_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    status = _ensure_tls_material()
    status['mdns'] = _mdns_config()
    status['mdns_status'] = _MDNS_STATUS
    status['mdns_hostname'] = str(_mdns_config().get('hostname', 'admin.pac.local'))
    suffix = '' if int(config.server.port) == 443 else f':{config.server.port}'
    status['mdns_url'] = f'https://{status["mdns_hostname"].rstrip(".")}{suffix}'
    status['port_443'] = {
        'configured': int(config.server.port) == 443,
        'requires': 'root, systemd AmbientCapabilities=CAP_NET_BIND_SERVICE, or a reverse proxy/socket activator',
    }
    return status


@app.get('/v1/tls/ca.pem')
def download_tls_ca(_auth: None = Depends(require_auth)):
    status = _ensure_tls_material()
    path = Path(status['ca_cert_file'])
    if not path.exists():
        raise HTTPException(status_code=404, detail='PAC CA has not been generated yet')
    return FileResponse(path, media_type='application/x-pem-file', filename='pac-root-ca.crt')


@app.post('/v1/tls/issue-endpoint-cert')
def issue_endpoint_certificate(payload: EndpointCertificateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    """Issue a PAC-CA signed certificate for an endpoint.

    Preferred flow: endpoint submits a CSR so its private key never leaves the
    endpoint. Fallback flow: omit csr_pem and PAC returns a generated key with
    the signed cert for simple/manual setups.
    """
    return _issue_endpoint_certificate(payload.name, payload.csr_pem, payload.sans, payload.days)

@app.get('/v1/models')
def list_models(_auth: None = Depends(require_auth)) -> dict:
    result = {}
    for name, model in config.models.items():
        data = model.model_dump()
        available, reason = _model_available(name)
        data['available'] = available
        data['availability_reason'] = reason
        result[name] = data
    return result


@app.get('/v1/providers')
def list_providers(_auth: None = Depends(require_auth)) -> dict:
    return provider_public(config)


@app.get('/v1/providers/{provider_name}/models')
def provider_models(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
    return list_provider_models(config, provider_name)


@app.post('/v1/providers/{provider_name}/toggle')
def provider_toggle(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    global config
    if provider_name not in config.providers:
        raise HTTPException(status_code=404, detail='Provider not found')
    enabled = bool(payload.get('enabled'))
    provider = config.providers[provider_name]
    provider.enabled = enabled
    provider.last_checked_at = datetime.now(timezone.utc).isoformat()
    if not enabled:
        provider.status = 'disabled'
        provider.last_error = None
        save_config(config)
        store.add_event(Event(session_id='system', type='provider_disabled', message=f'Provider disabled: {provider_name}'))
        return {'ok': True, 'enabled': False, 'status': provider.status, 'models': provider.cached_models}
    result = list_provider_models(config, provider_name, force=True)
    provider.cached_models = result.get('models', []) or []
    synced_models = sync_models_from_provider(config, provider_name, provider.cached_models) if result.get('ok') else []
    provider.status = 'connected' if result.get('ok') else 'failed'
    provider.last_error = None if result.get('ok') else (result.get('error') or result.get('response', {}).get('error') if isinstance(result.get('response'), dict) else 'connection failed')
    save_config(config)
    store.add_event(Event(session_id='system', type='provider_connected' if result.get('ok') else 'provider_failed', message=f'Provider {provider_name}: {provider.status}', data={'provider': provider_name, 'status': provider.status, 'models': len(provider.cached_models), 'synced_models': synced_models}))
    return {'ok': result.get('ok', False), 'enabled': True, 'status': provider.status, 'last_error': provider.last_error, 'endpoint': result.get('endpoint'), 'models': provider.cached_models, 'synced_models': synced_models, 'response': result.get('response')}


@app.put('/v1/providers/{provider_name}')
def provider_update(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    global config
    existing = config.providers.get(provider_name)
    data = dict(payload)
    if existing:
        merged = existing.model_dump(mode='json', exclude_none=True)
        merged.update(data)
        data = merged
    config.providers[provider_name] = ProviderConfig.model_validate(data)
    save_config(config)
    store.add_event(Event(session_id='system', type='provider_updated', message=f'Provider updated: {provider_name}'))
    return provider_public(config)[provider_name]


@app.delete('/v1/providers/{provider_name}')
def provider_delete(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
    global config
    if provider_name not in config.providers:
        raise HTTPException(status_code=404, detail='Provider not found')
    del config.providers[provider_name]
    removed_models = [name for name, model in list(config.models.items()) if model.provider == provider_name]
    for name in removed_models:
        del config.models[name]
    save_config(config)
    store.add_event(Event(session_id='system', type='provider_deleted', message=f'Provider deleted: {provider_name}', data={'removed_models': removed_models}))
    return {'ok': True, 'deleted': provider_name, 'removed_models': removed_models}


@app.post('/v1/providers/{provider_name}/test')
def provider_health(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
    return test_provider(config, provider_name)



@app.get('/v1/providers/{provider_name}/lmstudio/inspect')
def provider_lmstudio_inspect(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    result = lmstudio_inspect_provider(provider)
    store.add_event(Event(session_id='system', type='lmstudio_inspected', message=f'LM Studio inspected: {provider_name}', data={'provider': provider_name, 'ok': result.get('ok'), 'models': len(result.get('models') or [])}))
    return result


@app.get('/v1/providers/{provider_name}/lmstudio/companion-script')
def provider_lmstudio_companion_script(provider_name: str, _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    public = (config.server.public_url or '').rstrip('/')
    report_url = f'{public}/v1/providers/{provider_name}/lmstudio/companion-report' if public else ''
    return {'ok': True, 'provider': provider_name, 'script': lmstudio_companion_script(provider_name, provider, report_url), 'report_url': report_url}


@app.post('/v1/providers/{provider_name}/lmstudio/companion-report')
def provider_lmstudio_companion_report(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    extra = provider.default_headers.setdefault('x-pac-companion-report', 'available')
    provider.notes = ((provider.notes or '') + '\nLM Studio companion report received.').strip()
    provider.last_checked_at = datetime.now(timezone.utc).isoformat()
    provider.cached_models = payload.get('lmstudio', {}).get('models', {}).get('body', {}).get('data', provider.cached_models) if isinstance(payload, dict) else provider.cached_models
    save_config(config)
    store.add_event(Event(session_id='system', type='lmstudio_companion_reported', message=f'LM Studio companion reported hardware: {provider_name}', data={'provider': provider_name, 'host': payload.get('host'), 'hardware': payload.get('hardware')}))
    return {'ok': True, 'provider': provider_name, 'message': 'report received'}


@app.post('/v1/providers/{provider_name}/lmstudio/load')
def provider_lmstudio_load(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    model = str(payload.get('model') or '').strip()
    if not model:
        raise HTTPException(status_code=400, detail='model is required')
    result = lmstudio_load_model(provider, model, payload)
    store.add_event(Event(session_id='system', type='lmstudio_model_load', message=f'LM Studio load {model}: {"ok" if result.get("ok") else "failed"}', data={'provider': provider_name, 'model': model, 'result': result}))
    return result


@app.post('/v1/providers/{provider_name}/lmstudio/unload')
def provider_lmstudio_unload(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    instance_id = str(payload.get('instance_id') or payload.get('model') or '').strip()
    if not instance_id:
        raise HTTPException(status_code=400, detail='instance_id is required')
    result = lmstudio_unload_model(provider, instance_id)
    store.add_event(Event(session_id='system', type='lmstudio_model_unload', message=f'LM Studio unload {instance_id}: {"ok" if result.get("ok") else "failed"}', data={'provider': provider_name, 'instance_id': instance_id, 'result': result}))
    return result


@app.post('/v1/providers/{provider_name}/lmstudio/download')
def provider_lmstudio_download(provider_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    provider = config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    model = str(payload.get('model') or '').strip()
    if not model:
        raise HTTPException(status_code=400, detail='model is required')
    result = lmstudio_download_model(provider, model)
    store.add_event(Event(session_id='system', type='lmstudio_model_download', message=f'LM Studio download {model}: {"queued" if result.get("ok") else "failed"}', data={'provider': provider_name, 'model': model, 'result': result}))
    return result


@app.get('/v1/models/{model_name}/card')
def get_model_card(model_name: str, context_profile: str | None = None, _auth: None = Depends(require_auth)) -> dict:
    if model_name not in config.models:
        raise HTTPException(status_code=404, detail='Model not found')
    card = model_card(config, model_name)
    if context_profile:
        card['effective_context'] = effective_context(config, model_name, context_profile)
    return card


@app.post('/v1/models/{model_name}/test')
def model_health(model_name: str, _auth: None = Depends(require_auth)) -> dict:
    return test_model(config, model_name)


@app.get('/v1/models/{model_name}/lmstudio/inspect')
def model_lmstudio_inspect(model_name: str, _auth: None = Depends(require_auth)) -> dict:
    if model_name not in config.models:
        raise HTTPException(status_code=404, detail='Model not found')
    model = config.models[model_name]
    provider = config.providers.get(model.provider)
    if not provider or provider.type != 'lmstudio':
        raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
    result = lmstudio_inspect_provider(provider)
    result['model_name'] = model_name
    result['provider_model_id'] = model.model
    result['saved_runtime'] = (model.extra or {}).get('lmstudio_runtime', {})
    store.add_event(Event(session_id='system', type='lmstudio_model_view_inspected', message=f'LM Studio model inspected: {model_name}', data={'model': model_name, 'provider': model.provider, 'ok': result.get('ok')}))
    return result


@app.post('/v1/models/{model_name}/lmstudio/load')
def model_lmstudio_load(model_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    if model_name not in config.models:
        raise HTTPException(status_code=404, detail='Model not found')
    model = config.models[model_name]
    provider = config.providers.get(model.provider)
    if not provider or provider.type != 'lmstudio':
        raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
    runtime = dict((model.extra or {}).get('lmstudio_runtime', {}))
    runtime.update({k: v for k, v in payload.items() if v is not None and k != 'model'})
    target_model = str(payload.get('model') or model.model or model_name).strip()
    if not target_model:
        raise HTTPException(status_code=400, detail='provider model id is required')
    result = lmstudio_load_model(provider, target_model, runtime)
    store.add_event(Event(session_id='system', type='lmstudio_model_view_load', message=f'LM Studio load from model view {model_name}: {"ok" if result.get("ok") else "failed"}', data={'model': model_name, 'provider': model.provider, 'provider_model': target_model, 'runtime': runtime, 'result': result}))
    return result


@app.post('/v1/models/{model_name}/lmstudio/unload')
def model_lmstudio_unload(model_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict:
    if model_name not in config.models:
        raise HTTPException(status_code=404, detail='Model not found')
    model = config.models[model_name]
    provider = config.providers.get(model.provider)
    if not provider or provider.type != 'lmstudio':
        raise HTTPException(status_code=400, detail='Model is not backed by an LM Studio provider')
    instance_id = str(payload.get('instance_id') or payload.get('model') or model.model or model_name).strip()
    if not instance_id:
        raise HTTPException(status_code=400, detail='instance_id is required')
    result = lmstudio_unload_model(provider, instance_id)
    store.add_event(Event(session_id='system', type='lmstudio_model_view_unload', message=f'LM Studio unload from model view {model_name}: {"ok" if result.get("ok") else "failed"}', data={'model': model_name, 'provider': model.provider, 'instance_id': instance_id, 'result': result}))
    return result


@app.get('/v1/context-profiles')
def list_context_profiles(_auth: None = Depends(require_auth)) -> dict:
    return {name: cp.model_dump() for name, cp in config.context_profiles.items()}


@app.get('/v1/models/{model_name}/effective-context')
def get_effective_context(model_name: str, context_profile: str = 'medium', _auth: None = Depends(require_auth)) -> dict:
    if model_name not in config.models:
        raise HTTPException(status_code=404, detail='Model not found')
    return effective_context(config, model_name, context_profile)


HF_API = 'https://huggingface.co/api'
MARKETPLACE_QUANTS = ['q2_k', 'q3_k_m', 'q4_0', 'q4_k_m', 'q5_k_m', 'q6_k', 'q8_0', 'f16', 'f32']


class MarketplaceDownloadRequest(BaseModel):
    model: str
    provider: str
    quantization: str | None = None


def _hf_headers() -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    token = os.environ.get('HF_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _hf_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=_hf_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as handle:
            return json.loads(handle.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Hugging Face API error {exc.code}: {exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f'Hugging Face API unreachable: {exc.reason or exc}') from exc


def _marketplace_param_billions(model_id: str) -> float | None:
    match = re.search(r'(\d+(?:\.\d+)?)\s*[bB](?:[^a-zA-Z]|$)', model_id or '')
    return float(match.group(1)) if match else None


def _marketplace_vram_gb(params_b: float | None, quant: str) -> float | None:
    if not params_b:
        return None
    bits = {
        'q8_0': 8,
        'q6_k': 6,
        'q5_k_m': 5,
        'q4_k_m': 4.5,
        'q4_0': 4,
        'q3_k_m': 3.5,
        'q2_k': 2.5,
        'f16': 16,
        'f32': 32,
    }.get(str(quant or '').lower(), 4.5)
    return round(params_b * bits / 8, 2)


def _marketplace_capabilities(model_id: str, tags: list[str]) -> dict[str, bool]:
    text = str(model_id or '').lower()
    tag_set = {str(tag).lower() for tag in (tags or [])}
    return {
        'coding': any(token in text for token in ['coder', 'codellama', 'starcoder', 'deepseek-coder', 'qwen2.5-coder', 'code']),
        'reasoning': any(token in text for token in ['reason', 'r1', 'think']) or 'reasoning' in tag_set,
        'tool_use': any(token in text for token in ['tool', 'function', 'agent']) or 'tool-use' in tag_set,
        'vision': any(token in text for token in ['vision', 'llava', 'vl']) or 'vision' in tag_set,
        'embedding': 'embedding' in text or 'feature-extraction' in tag_set,
        'fast': any(token in text for token in ['0.5b', '1b', '2b', '3b', 'tiny', 'nano']),
        'chat': any(token in tag_set for token in ['conversational', 'text-generation', 'causal-lm']),
    }


def _marketplace_available_quants(siblings: list[dict[str, Any]]) -> list[str]:
    quants: set[str] = set()
    for sibling in siblings or []:
        filename = str(sibling.get('rfilename') or '')
        if not filename.endswith('.gguf'):
            continue
        match = re.search(r'(q\d(?:[_-][a-z0-9]+)+|f16|f32)', filename, re.IGNORECASE)
        if match:
            quants.add(match.group(1).lower().replace('-', '_'))
    return sorted(quants, key=lambda value: MARKETPLACE_QUANTS.index(value) if value in MARKETPLACE_QUANTS else 999)


def _marketplace_provider_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for name, provider in sorted((config.providers or {}).items()):
        runtime = provider.runtime
        provider_models = [model_name for model_name, model in (config.models or {}).items() if model.provider == name]
        attached_endpoints = sorted({model.runs_on for model in config.models.values() if model.provider == name and model.runs_on})
        profiles.append(
            {
                'name': name,
                'type': provider.type,
                'enabled': provider.enabled,
                'status': provider.status,
                'base_url': provider.base_url,
                'cached_model_count': len(provider.cached_models or []),
                'execution_type': runtime.execution_type,
                'provider_class': runtime.provider_class,
                'device': runtime.device.model_dump(),
                'host': runtime.host.model_dump(),
                'accelerators': list(runtime.accelerators or []),
                'configured_models': provider_models,
                'attached_endpoints': attached_endpoints,
            }
        )
    return profiles


def _provider_marketplace_fit(params_b: float | None, quants: list[str], profile: dict[str, Any]) -> dict[str, Any]:
    device = profile.get('device') or {}
    memory_gb = device.get('memory_gb')
    candidates = quants or ['q4_k_m']
    if not params_b:
        return {'can_run': None, 'reason': 'Model parameter size could not be inferred', 'quant_recommended': None, 'estimated_vram_gb': None}
    chosen_quant = None
    chosen_vram = None
    if memory_gb:
        for quant in candidates:
            needed = _marketplace_vram_gb(params_b, quant)
            if needed is not None and needed <= float(memory_gb):
                chosen_quant = quant
                chosen_vram = needed
                break
    if not memory_gb:
        fallback = candidates[0] if candidates else 'q4_k_m'
        return {'can_run': None, 'reason': 'Provider memory is not configured yet', 'quant_recommended': fallback.upper(), 'estimated_vram_gb': _marketplace_vram_gb(params_b, fallback)}
    if not chosen_quant:
        smallest = _marketplace_vram_gb(params_b, candidates[0])
        return {'can_run': False, 'reason': f'Needs about {smallest} GB at {candidates[0].upper()}, provider advertises {memory_gb} GB', 'quant_recommended': None, 'estimated_vram_gb': smallest}
    headroom = round(float(memory_gb) - float(chosen_vram or 0), 2)
    return {'can_run': True, 'reason': f'{chosen_quant.upper()} fits with {headroom} GB headroom', 'quant_recommended': chosen_quant.upper(), 'estimated_vram_gb': chosen_vram}


def _marketplace_model_detail(model_id: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(model_id, safe='')
    model = _hf_get_json(f'{HF_API}/models/{encoded}')
    siblings = model.get('siblings', []) or []
    tags = [str(tag) for tag in (model.get('tags') or [])]
    quants = _marketplace_available_quants(siblings)
    params_b = _marketplace_param_billions(model.get('id') or model_id)
    providers = []
    for profile in _marketplace_provider_profiles():
        providers.append({'provider': profile, **_provider_marketplace_fit(params_b, quants, profile)})
    return {
        'model_id': model.get('id') or model_id,
        'author': model.get('author'),
        'downloads': model.get('downloads', 0),
        'likes': model.get('likes', 0),
        'tags': tags,
        'last_modified': model.get('lastModified'),
        'pipeline_tag': model.get('pipeline_tag'),
        'params_b': params_b,
        'capabilities': _marketplace_capabilities(model.get('id') or model_id, tags),
        'available_quants': quants,
        'provider_scores': providers,
        'gated': bool(model.get('gated')),
        'private': bool(model.get('private')),
    }


@app.get('/v1/models/marketplace/providers')
def marketplace_providers(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return {'providers': _marketplace_provider_profiles()}


@app.get('/v1/models/marketplace/search')
def marketplace_search_models(q: str = '', limit: int = 20, sort: str = 'downloads', capability: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    params = [('search', q), ('direction', '-1'), ('limit', max(1, min(limit, 50))), ('sort', sort)]
    query = '&'.join(f'{key}={urllib.parse.quote(str(value))}' for key, value in params if str(value))
    raw = _hf_get_json(f'{HF_API}/models?{query}')
    results: list[dict[str, Any]] = []
    for item in list(raw or [])[:limit]:
        model_id = str(item.get('id') or '')
        tags = [str(tag) for tag in (item.get('tags') or [])]
        siblings = item.get('siblings') or []
        if not any(str(sibling.get('rfilename') or '').endswith('.gguf') for sibling in siblings):
            try:
                detail = _hf_get_json(f'{HF_API}/models/{urllib.parse.quote(model_id, safe="")}')
                siblings = detail.get('siblings') or []
            except HTTPException:
                siblings = []
        quants = _marketplace_available_quants(siblings)
        if not quants:
            continue
        capabilities = _marketplace_capabilities(model_id, tags)
        if capability and capability not in {'all', 'any'} and not capabilities.get(capability, False):
            continue
        params_b = _marketplace_param_billions(model_id)
        results.append(
            {
                'model_id': model_id,
                'author': item.get('author'),
                'downloads': item.get('downloads', 0),
                'likes': item.get('likes', 0),
                'tags': tags,
                'last_modified': item.get('lastModified'),
                'capabilities': capabilities,
                'params_b': params_b,
                'available_quants': quants,
                'vram_q4_k_m_gb': _marketplace_vram_gb(params_b, 'q4_k_m'),
                'gated': bool(item.get('gated')),
                'private': bool(item.get('private')),
            }
        )
    return {'query': q, 'results': results, 'total': len(results)}


@app.get('/v1/models/marketplace/model/{model_id:path}')
def marketplace_model_detail(model_id: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    return _marketplace_model_detail(model_id)


@app.post('/v1/models/marketplace/download')
def marketplace_download_model(payload: MarketplaceDownloadRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    provider = config.providers.get(payload.provider)
    if not provider:
        raise HTTPException(status_code=404, detail='Provider not found')
    if provider.type != 'lmstudio' or not provider.base_url:
        raise HTTPException(status_code=400, detail='Marketplace download is currently supported only for configured LM Studio providers')
    base = provider.base_url.rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    request_body = json.dumps({'model': f'https://huggingface.co/{payload.model}', 'quantization': payload.quantization or 'Q4_K_M'}).encode('utf-8')
    request = urllib.request.Request(
        f'{base}/api/v1/models/download',
        data=request_body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as handle:
            result = json.loads(handle.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise HTTPException(status_code=502, detail=f'LM Studio download failed ({exc.code}): {body}') from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f'LM Studio provider unreachable: {exc.reason or exc}') from exc
    store.add_event(Event(session_id='system', type='marketplace_download_started', message=f'Marketplace download requested: {payload.model} via {payload.provider}', data={'model': payload.model, 'provider': payload.provider, 'quantization': payload.quantization or 'Q4_K_M', 'result': result}))
    return result


@app.get('/v1/tool-packages')
def list_tool_packages(_auth: None = Depends(require_auth)) -> dict:
    return {name: package.model_dump() for name, package in config.tool_packages.items()}

@app.get('/v1/plugins')
def list_plugins(_auth: None = Depends(require_auth)) -> dict:
    return {name: plugin.model_dump() for name, plugin in config.plugins.items()}

@app.get('/v1/tools')
def list_tools(_auth: None = Depends(require_auth)) -> dict:
    return {name: tool.model_dump() for name, tool in config.tools.items()}


@app.get('/v1/artifacts')
def api_list_artifacts(session_id: str | None = None, task_id: str | None = None, _auth: None = Depends(require_auth)) -> list[dict[str, Any]]:
    return list_artifacts(config.server.data_dir, session_id, task_id)


@app.put('/v1/artifacts/{session_id}/{task_id}/{name:path}')
async def api_put_artifact(session_id: str, task_id: str, name: str, request: Request, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    data = await request.body()
    task_id_norm = None if task_id == 'session' else task_id
    meta = write_artifact(config.server.data_dir, session_id, task_id_norm, name, data)
    store.add_event(Event(session_id=session_id, task_id=task_id_norm, type='artifact_uploaded', message=f'Uploaded artifact {name}', data=meta))
    return meta


@app.get('/v1/artifacts/{session_id}/{task_id}/{name:path}')
def api_get_artifact(session_id: str, task_id: str, name: str, _auth: None = Depends(require_auth)):
    task_id_norm = None if task_id == 'session' else task_id
    base = task_artifact_dir(config.server.data_dir, session_id, task_id_norm)
    try:
        target = safe_artifact_path(base, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not target.exists() or target.name.endswith('.meta.json'):
        raise HTTPException(status_code=404, detail='Artifact not found')
    return FileResponse(target, filename=Path(name).name)





@app.get('/v1/controller-harness')
def controller_harness_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return _ensure_controller_harness_session()


@app.post('/v1/controller-harness/bootstrap')
def bootstrap_controller_harness(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    if _BOOTSTRAP_ACTIVE:
        return {'status': 'running', 'message': 'Controller pi.dev bootstrap is already running. Progress is shown in Events.'}
    started = _start_controller_bootstrap(force=True)
    return {'status': 'running' if started else 'disabled', 'message': 'Controller pi.dev bootstrap started. Progress is shown in Events.' if started else 'Controller pi.dev is disabled in Settings.'}


@app.post('/v1/controller-harness/settings')
def save_controller_harness_settings(payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global config
    current = config.controller_harness.model_dump()
    allowed = set(current.keys())
    merged = {**current, **{k: v for k, v in payload.items() if k in allowed}}
    if merged.get('agent_profile') in ('', 'none'):
        merged['agent_profile'] = None
    if merged.get('model') in ('', 'profile'):
        merged['model'] = None
    if merged.get('workspace_profile') not in config.workspaces:
        # It is valid to name a new workspace here; the harness will create it.
        pass
    if merged.get('agent_profile') and merged['agent_profile'] not in config.agent_profiles:
        raise HTTPException(status_code=400, detail=f"Unknown agent profile: {merged['agent_profile']}")
    if merged.get('model') and merged['model'] not in config.models:
        raise HTTPException(status_code=400, detail=f"Unknown model: {merged['model']}")
    if merged.get('permission_profile') and merged['permission_profile'] not in config.permission_profiles:
        raise HTTPException(status_code=400, detail=f"Unknown permission profile: {merged['permission_profile']}")
    config.controller_harness = type(config.controller_harness).model_validate(merged)
    save_config(config)
    config = load_config()
    result = _ensure_controller_harness_session()
    store.add_event(Event(session_id='system', type='controller_harness_settings_saved', message='Controller pi.dev settings saved', data={'ok': result.get('ok'), 'message': result.get('message')}))
    return result


@app.get('/v1/profiles')
def list_profiles(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return {
        'agent_profiles': {name: p.model_dump() for name, p in config.agent_profiles.items()},
        'permission_profiles': {name: p.model_dump() for name, p in config.permission_profiles.items()},
        'workspaces': {name: w.model_dump() for name, w in config.workspaces.items()},
    }

@app.get('/v1/agent-profiles')
def list_agent_profiles(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    profiles = {}
    for name, profile in config.agent_profiles.items():
        data = profile.model_dump()
        available, reason = _model_available(profile.model)
        data['valid'] = available
        data['missing_model'] = None if data['valid'] else profile.model
        data['availability_reason'] = reason
        profiles[name] = data
    return profiles


@app.put('/v1/agent-profiles/{profile_name}')
def upsert_agent_profile(profile_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
    if not payload.get('model') or payload['model'] not in config.models:
        raise HTTPException(status_code=400, detail='Profile requires an existing configured model')
    available, reason = _model_available(payload['model'])
    if not available:
        raise HTTPException(status_code=400, detail=f'Profile model is not available: {reason}')
    permission_profile = payload.get('permission_profile') or 'ask-first'
    if permission_profile not in config.permission_profiles:
        raise HTTPException(status_code=400, detail='Unknown permission profile')
    context_profile = payload.get('context_profile')
    if context_profile and context_profile not in config.context_profiles:
        raise HTTPException(status_code=400, detail='Unknown context profile')
    tools = payload.get('tools') or []
    unknown_tools = [tool for tool in tools if tool not in config.tools]
    if unknown_tools:
        raise HTTPException(status_code=400, detail=f'Unknown tools: {unknown_tools}')
    config.agent_profiles[profile_name] = AgentProfile.model_validate(payload)
    save_config(config)
    store.add_event(Event(session_id='system', type='agent_profile_saved', message=f'Profile saved: {profile_name}', data={'profile': profile_name, 'model': payload.get('model')}))
    data = config.agent_profiles[profile_name].model_dump()
    data['valid'] = True
    return data


@app.delete('/v1/agent-profiles/{profile_name}')
def delete_agent_profile(profile_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    if profile_name not in config.agent_profiles:
        raise HTTPException(status_code=404, detail='Profile not found')
    del config.agent_profiles[profile_name]
    save_config(config)
    store.add_event(Event(session_id='system', type='agent_profile_deleted', message=f'Profile deleted: {profile_name}'))
    return {'ok': True, 'deleted': profile_name}


@app.put('/v1/workspaces/{workspace_name}')
def save_workspace_profile(workspace_name: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> dict[str, Any]:
    name = workspace_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail='Workspace name is required')
    wtype = payload.get('type') or 'local'
    if wtype not in {'local', 'git', 'container'}:
        raise HTTPException(status_code=400, detail='Workspace type must be local, git or container')
    default_agent_profile = payload.get('default_agent_profile') or None
    if default_agent_profile and default_agent_profile not in config.agent_profiles:
        raise HTTPException(status_code=400, detail=f'Unknown default agent profile: {default_agent_profile}')
    endpoint_id = payload.get('endpoint_id') or None
    if endpoint_id and endpoint_id not in store.runners:
        raise HTTPException(status_code=400, detail=f'Unknown endpoint: {endpoint_id}')
    runtime = payload.get('runtime') or 'any'
    if runtime not in {'any', 'local', 'container'}:
        raise HTTPException(status_code=400, detail='Workspace runtime must be any, local or container')
    if wtype == 'git' and not payload.get('url'):
        raise HTTPException(status_code=400, detail='Git URL is required for git workspaces')
    ttl_hours = payload.get('ttl_hours')
    if ttl_hours in ('', None):
        ttl_hours = None
    elif isinstance(ttl_hours, str):
        try:
            ttl_hours = int(ttl_hours)
        except ValueError:
            raise HTTPException(status_code=400, detail='TTL must be a number of hours')
    if ttl_hours is not None and ttl_hours < 1:
        raise HTTPException(status_code=400, detail='TTL must be at least 1 hour')
    config.workspaces[name] = WorkspaceProfile(
        description=payload.get('description') or None,
        type=wtype,
        path=payload.get('path') or None,
        url=payload.get('url') or None,
        branch=payload.get('branch') or None,
        default_agent_profile=default_agent_profile,
        endpoint_id=endpoint_id,
        endpoint_selector=payload.get('endpoint_selector') or None,
        runtime=runtime,
        container_image=payload.get('container_image') or None,
        data_bundle_url=payload.get('data_bundle_url') or None,
        data_bundle_path=payload.get('data_bundle_path') or None,
        data_mount_path=payload.get('data_mount_path') or None,
        ephemeral=bool(payload.get('ephemeral')),
        ttl_hours=ttl_hours,
        delete_on_expire=bool(payload.get('delete_on_expire', True)),
        is_default=bool(payload.get('is_default')),
    )
    save_config(config)
    store.add_event(Event(session_id='system', type='workspace_saved', message=f'Workspace saved: {name}', data={'workspace': name, 'type': wtype}))
    return {'ok': True, 'name': name, **config.workspaces[name].model_dump()}


@app.delete('/v1/workspaces/{workspace_name}')
def delete_workspace_profile(workspace_name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    if workspace_name not in config.workspaces:
        raise HTTPException(status_code=404, detail='Workspace not found')
    del config.workspaces[workspace_name]
    if not config.workspaces:
        config.workspaces['scratch'] = WorkspaceProfile(description='Default local workspace', type='local', path=None)
    save_config(config)
    store.add_event(Event(session_id='system', type='workspace_deleted', message=f'Workspace deleted: {workspace_name}'))
    return {'ok': True, 'deleted': workspace_name}


@app.get('/v1/sessions', response_model=list[Session])
def list_sessions(_auth: None = Depends(require_auth)) -> list[Session]:
    return store.list_sessions()


@app.post('/v1/sessions', response_model=Session)
def create_session(payload: SessionCreate, _auth: None = Depends(require_auth)) -> Session:
    # Resolve workspace first so a workspace default_agent_profile can satisfy
    # session creation. Previously this happened after model resolution, so a
    # modal request with only a workspace profile could fail with
    # "Session requires model or agent_profile" and appear to do nothing.
    workspace = payload.workspace
    if workspace.type == 'profile' and not workspace.profile:
        if config.workspaces:
            workspace.profile = next(iter(config.workspaces.keys()))
        else:
            workspace.type = 'local'
    if workspace.type == 'profile':
        if not workspace.profile or workspace.profile not in config.workspaces:
            raise HTTPException(status_code=400, detail='Unknown workspace profile')
        w = config.workspaces[workspace.profile]
        workspace.type = w.type
        workspace.path = w.path
        workspace.url = w.url
        workspace.branch = w.branch
        if not payload.agent_profile and w.default_agent_profile and w.default_agent_profile in config.agent_profiles:
            payload.agent_profile = w.default_agent_profile

    agent_profile = config.agent_profiles.get(payload.agent_profile) if payload.agent_profile else None

    selected_model = payload.model or (agent_profile.model if agent_profile else None)
    if not selected_model:
        raise HTTPException(status_code=400, detail='Session requires model or agent_profile')
    if selected_model not in config.models:
        raise HTTPException(status_code=400, detail=f'Unknown model: {selected_model}')
    model_available, model_reason = _model_available(selected_model)
    if not model_available:
        raise HTTPException(status_code=400, detail=f'Model is not available for sessions: {selected_model} ({model_reason})')

    selected_model_config = config.models[selected_model]
    if selected_model_config.runs_on and 'preferred_endpoint' not in payload.metadata:
        payload.metadata['preferred_endpoint'] = selected_model_config.runs_on
    if payload.metadata.get('preferred_endpoint'):
        endpoint_id = str(payload.metadata.get('preferred_endpoint'))
        if not store.get_runner(endpoint_id):
            raise HTTPException(status_code=400, detail=f'Unknown endpoint: {endpoint_id}')
        payload.metadata['endpoint_locked'] = True

    selected_tools = payload.tools or (agent_profile.tools if agent_profile else [])
    unknown_tools = [t for t in selected_tools if t not in config.tools]
    if unknown_tools:
        raise HTTPException(status_code=400, detail=f'Unknown tools: {unknown_tools}')
    preferred_endpoint = payload.metadata.get('preferred_endpoint') or selected_model_config.runs_on
    if selected_tools and preferred_endpoint:
        endpoint = store.get_runner(preferred_endpoint)
        endpoint_tools = (endpoint.metadata.get('agent_tools', []) if endpoint else [])
        if endpoint_tools:
            missing_on_endpoint = [t for t in selected_tools if t not in endpoint_tools]
            if missing_on_endpoint:
                raise HTTPException(status_code=400, detail=f'Endpoint does not provide selected tools: {missing_on_endpoint}')

    selected_permission = payload.permission_profile or (agent_profile.permission_profile if agent_profile else 'ask-first')
    if selected_permission not in config.permission_profiles:
        raise HTTPException(status_code=400, detail=f'Unknown permission profile: {selected_permission}')

    root = Path(config.server.default_workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    safe_name = (payload.name or payload.agent_profile or 'session').replace('/', '-').replace(' ', '-')
    workspace_path = workspace.path or str(root / f'workspace-{safe_name}')

    payload.metadata.setdefault('agent_enabled', True)
    payload.metadata.setdefault('execution_mode', 'pi.dev')

    session = Session(
        name=payload.name,
        agent_profile=payload.agent_profile,
        permission_profile=selected_permission,
        context_mode=payload.context_mode or (agent_profile.context_mode if agent_profile else 'medium'),
        workspace=workspace,
        workspace_path=workspace_path,
        model=selected_model,
        tools=selected_tools,
        metadata=payload.metadata,
    )
    Path(session.workspace_path).mkdir(parents=True, exist_ok=True)

    if workspace.type == 'git':
        if not workspace.url:
            raise HTTPException(status_code=400, detail='Git workspace requires url')
        if not Path(session.workspace_path, '.git').exists():
            cmd = ['git', 'clone']
            if workspace.branch:
                cmd += ['--branch', workspace.branch]
            cmd += [workspace.url, session.workspace_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=result.stderr)

    store.add_session(session)
    store.add_event(Event(session_id=session.id, type='session_created', message='Session created', data={'workspace_path': session.workspace_path, 'agent_profile': session.agent_profile, 'permission_profile': session.permission_profile, 'context_mode': session.context_mode, 'endpoint': session.metadata.get('preferred_endpoint'), 'endpoint_locked': session.metadata.get('endpoint_locked'), 'agent_enabled': session.metadata.get('agent_enabled', True), 'execution_mode': session.metadata.get('execution_mode', 'pi.dev'), 'effective_context': effective_context(config, session.model, agent_profile.context_profile if agent_profile else session.context_mode)}))
    return session


@app.get('/v1/sessions/{session_id}', response_model=Session)
def get_session(session_id: str, _auth: None = Depends(require_auth)) -> Session:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return session


@app.put('/v1/sessions/{session_id}', response_model=Session)
def update_session(session_id: str, payload: dict[str, Any], _auth: None = Depends(require_auth)) -> Session:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    changed = False
    permission_profile = payload.get('permission_profile')
    if permission_profile is not None:
        if permission_profile not in config.permission_profiles:
            raise HTTPException(status_code=400, detail=f'Unknown permission profile: {permission_profile}')
        if session.permission_profile != permission_profile:
            session.permission_profile = permission_profile
            changed = True
            store.add_event(Event(session_id=session.id, type='session_permission_profile_changed', message='Session permission profile updated', data={'permission_profile': permission_profile}))
    if not changed:
        return session
    store.add_session(session)
    return session


@app.get('/v1/sessions/{session_id}/tasks', response_model=list[Task])
def list_tasks(session_id: str, _auth: None = Depends(require_auth)) -> list[Task]:
    if not store.get_session(session_id):
        raise HTTPException(status_code=404, detail='Session not found')
    return store.list_tasks(session_id)


@app.post('/v1/sessions/{session_id}/tasks', response_model=Task)
async def create_task(session_id: str, payload: TaskCreate, background_tasks: BackgroundTasks, wait: bool = Query(default=False), _auth: None = Depends(require_auth)) -> Task:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    metadata = dict(payload.metadata or {})
    parsed_slash = parse_session_slash_command(payload.prompt)
    if parsed_slash:
        if parsed_slash.get('error'):
            raise HTTPException(status_code=400, detail=parsed_slash['error'])
        metadata.update(parsed_slash.get('metadata') or {})
        if parsed_slash['kind'] == 'help':
            task = Task(session_id=session_id, prompt=payload.prompt, metadata={**metadata, 'slash_command': 'help'})
            task.status = TaskStatus.completed
            task.output = slash_help_text()
            store.add_task(task)
            store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data={'role': 'user', 'model': metadata.get('model') or session.model, 'session_model': session.model, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'command': None, 'execution_mode': metadata.get('execution_mode'), 'stored': True}))
            store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'slash_command': 'help'}))
            return task
        payload = TaskCreate(
            prompt=parsed_slash.get('prompt') or payload.prompt,
            command=parsed_slash.get('command') or payload.command,
            require_approval=payload.require_approval,
            metadata=metadata,
        )
        if parsed_slash['kind'] == 'tool':
            metadata['execution_mode'] = 'host'
        elif parsed_slash['kind'] == 'subagent':
            metadata['execution_mode'] = metadata.get('execution_mode') or 'pi_container'

    locked_endpoint = session.metadata.get('preferred_endpoint') if session.metadata.get('endpoint_locked') else None
    if locked_endpoint:
        requested_endpoint = metadata.get('runner_id') or metadata.get('target_runner_id')
        if requested_endpoint and requested_endpoint != locked_endpoint:
            raise HTTPException(status_code=400, detail=f'Session is locked to endpoint: {locked_endpoint}')
        metadata['runner_id'] = locked_endpoint
        metadata['endpoint_locked'] = True
    task = Task(session_id=session_id, prompt=payload.prompt, command=payload.command, metadata=metadata)
    store.add_task(task)
    target = _runner_target_from_task(task)
    endpoint_id = metadata.get('runner_id') or metadata.get('target_runner_id')
    endpoint_name = None
    if endpoint_id:
        endpoint_obj = store.get_runner(str(endpoint_id))
        endpoint_name = endpoint_obj.name if endpoint_obj else str(endpoint_id)
    message_meta = {
        'role': 'user',
        'model': metadata.get('model') or session.model,
        'session_model': session.model,
        'endpoint_id': endpoint_id,
        'endpoint_name': endpoint_name,
        'command': payload.command,
        'execution_mode': metadata.get('execution_mode'),
        'stored': True,
    }
    store.add_event(Event(session_id=session_id, task_id=task.id, type='user_message', message=payload.prompt, data=message_meta))
    if metadata.get('context_action') == 'compact':
        task.status = TaskStatus.completed
        task.output = 'Context compaction requested for this session.'
        store.add_task(task)
        store.add_event(Event(session_id=session_id, task_id=task.id, type='context_compacted', message='Context compaction requested', data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'slash_command': metadata.get('slash_command')}))
        return task
    if metadata.get('subagent'):
        spawned = await spawn_pi_dev_subagent(session, task, str(metadata.get('subagent_instruction') or payload.prompt or ''), config, run_agent_loop)
        child_session = spawned['session']
        child_task = spawned['task']
        task.status = TaskStatus.completed
        task.output = f"{spawned['message']} Open session {child_session.id} to follow it."
        task.metadata['subagent_session_id'] = child_session.id
        task.metadata['subagent_task_id'] = child_task.id
        store.add_task(task)
        store.add_event(Event(session_id=session_id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': metadata.get('model') or session.model, 'agent_profile': session.agent_profile, 'endpoint_id': metadata.get('runner_id') or session.metadata.get('preferred_endpoint'), 'subagent_session_id': child_session.id, 'subagent_task_id': child_task.id, 'slash_command': metadata.get('slash_command'), 'timeline': {'title': 'Subagent launched', 'summary': task.output, 'fields': {'Session': child_session.id, 'Task': child_task.id, 'Mode': 'pi.dev', 'Endpoint': metadata.get('runner_id') or session.metadata.get('preferred_endpoint') or '-'}}}))
        return task
    agent_enabled = _session_agent_enabled(session) and metadata.get('direct_model') is not True
    store.add_event(Event(session_id=session_id, task_id=task.id, type='task_queued', message='Task queued', data={**message_meta, 'internal': True, 'agent_enabled': agent_enabled}))

    if agent_enabled:
        task.metadata['agent_loop'] = True
        task.metadata['agent_enabled'] = True
        task.metadata['requested_command'] = task.command
        task.metadata['routing'] = 'agent'
        if target and not task.metadata.get('execution_mode'):
            task.metadata['execution_mode'] = target['execution_mode']
        if target:
            task.metadata['runner_id'] = target['runner_id']
            task.metadata['endpoint_locked'] = True
        # Commands and slash-tool invocations are not executed directly in an agent-enabled session.
        # The agent receives the command as intent/context and chooses the next action.
        task.prompt = _agent_prompt_for_task(task.prompt, task.command, task.metadata)
        task.command = None
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_routing', message='Routed to session agent', data={'agent_profile': session.agent_profile, 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'requested_command': task.metadata.get('requested_command')}))
        if wait:
            await run_agent_loop(session, task, config)
        else:
            background_tasks.add_task(run_agent_loop, session, task, config)
        return store.get_task(task.id) or task

    if target:
        if task.command:
            decision, reason = __import__('pi_agent_platform.core.runtime', fromlist=['command_policy']).command_policy(task.command, session, config)
            if decision == 'deny':
                task.status = TaskStatus.failed
                task.error = reason
                store.add_task(task)
                store.add_event(Event(session_id=session.id, task_id=task.id, type='task_failed', message=reason or 'Command denied'))
                return task
            if task.status != TaskStatus.approval_required and (decision == 'ask' or payload.require_approval is True):
                task.status = TaskStatus.approval_required
                store.add_task(task)
                store.add_event(Event(session_id=session.id, task_id=task.id, type='approval_required', message=f'Runner command requires approval: {task.command}', data={'command': task.command, 'runner_id': target['runner_id'], 'reason': reason}))
                return task
        return _queue_task_on_runner(session, task, target)
    if task.command:
        if str(task.command).startswith('tool:') and metadata.get('tool_name'):
            # Local-control-plane endpoints do not use the polling endpoint queue.
            # Convert the named tool invocation into a safe local shell command.
            tool = str(metadata.get('tool_name') or '').strip()
            if tool == 'bad':
                tool = 'bat'
            args = metadata.get('args') if isinstance(metadata.get('args'), list) else []
            task.command = shlex.join([tool, *[str(a) for a in args]])
            store.add_task(task)
        if wait:
            await run_shell_task(session, task, config)
        else:
            background_tasks.add_task(run_shell_task, session, task, config)
    else:
        task.metadata['agent_loop'] = True
        if wait:
            await run_agent_loop(session, task, config)
        else:
            background_tasks.add_task(run_agent_loop, session, task, config)
    return store.get_task(task.id) or task




@app.get('/v1/tasks/pending-approvals', response_model=list[Task])
def pending_approvals(_auth: None = Depends(require_auth)) -> list[Task]:
    return [task for task in store.list_tasks() if task.status == TaskStatus.approval_required]


@app.get('/v1/tasks/{task_id}', response_model=Task)
def get_task(task_id: str, _auth: None = Depends(require_auth)) -> Task:
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@app.post('/v1/tasks/{task_id}/approve', response_model=Task)
async def approve_task(task_id: str, background_tasks: BackgroundTasks, wait: bool = Query(default=False), _auth: None = Depends(require_auth)) -> Task:
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    if task.status != TaskStatus.approval_required:
        return task
    session = store.get_session(task.session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    task.status = TaskStatus.queued
    task.error = None
    store.add_task(task)
    store.add_event(Event(session_id=session.id, task_id=task.id, type='task_approved', message='Approved'))
    target = _runner_target_from_task(task)
    if target:
        return _queue_task_on_runner(session, task, target)
    if task.metadata.get('agent_loop') and not task.command:
        if wait:
            await run_agent_loop(session, task, config)
        else:
            background_tasks.add_task(run_agent_loop, session, task, config)
    else:
        if wait:
            await run_shell_task(session, task, config)
        else:
            background_tasks.add_task(run_shell_task, session, task, config)
    return store.get_task(task.id) or task


@app.post('/v1/tasks/{task_id}/reject', response_model=Task)
def reject_task(task_id: str, reason: str = 'Rejected by user', _auth: None = Depends(require_auth)) -> Task:
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    task.status = TaskStatus.failed
    task.error = reason
    store.add_task(task)
    store.add_event(Event(session_id=task.session_id, task_id=task.id, type='task_rejected', message=reason))
    return task


@app.post('/v1/tasks/{task_id}/stop', response_model=Task)
def stop_task(task_id: str, _auth: None = Depends(require_auth)) -> Task:
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    session = store.get_session(task.session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    if task.status in {TaskStatus.completed, TaskStatus.failed}:
        return task
    task.metadata = dict(task.metadata or {})
    task.metadata['stop_requested'] = True
    task.metadata['stop_requested_at'] = datetime.now(timezone.utc).isoformat()
    if task.status in {TaskStatus.queued, TaskStatus.approval_required}:
        task.status = TaskStatus.completed
        task.output = 'Agent stopped by user.'
        task.error = None
        store.add_task(task)
        store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_stop', message='Agent stopped by user', data={'stop_reason': 'user_stop'}))
        store.add_event(Event(session_id=session.id, task_id=task.id, type='result', message=task.output, data={'role': 'assistant', 'model': session.model, 'endpoint_id': task.metadata.get('runner_id'), 'agent_profile': session.agent_profile, 'permission_profile': session.permission_profile, 'stop_reason': 'user_stop'}))
        session.status = SessionStatus.created
        store.add_session(session)
        return task
    store.add_task(task)
    store.add_event(Event(session_id=session.id, task_id=task.id, type='agent_stop', message='Stop requested; the agent will stop after the current step.', data={'stop_reason': 'user_stop'}))
    return task




@app.get('/v1/events/recent')
def recent_events(limit: int = Query(default=80, ge=1, le=500), _auth: None = Depends(require_auth)) -> list[Event]:
    return store.list_recent_events(limit=limit)


@app.post('/v1/sessions/{session_id}/events', response_model=Event)
def add_session_event(session_id: str, payload: TimelineEventCreate, _auth: None = Depends(require_auth)) -> Event:
    if not store.get_session(session_id):
        raise HTTPException(status_code=404, detail='Session not found')
    event_type = re.sub(r'[^a-zA-Z0-9_:-]+', '_', payload.type or 'agent_note')[:80]
    event = Event(session_id=session_id, task_id=payload.task_id, type=event_type, message=payload.message or event_type, data=payload.data or {})
    store.add_event(event)
    return event


@app.get('/v1/sessions/{session_id}/events')
async def stream_events(session_id: str, _auth: None = Depends(require_auth)):
    if not store.get_session(session_id):
        raise HTTPException(status_code=404, detail='Session not found')

    async def event_stream():
        last_id = None
        while True:
            events = store.get_events(session_id, after_id=last_id)
            for event in events:
                last_id = event.id
                yield f"event: {event.type}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type='text/event-stream')


@app.get('/v1/sessions/{session_id}/events/snapshot')
def event_snapshot(session_id: str, after_id: str | None = None, limit: int = 500, _auth: None = Depends(require_auth)) -> list[Event]:
    if not store.get_session(session_id):
        raise HTTPException(status_code=404, detail='Session not found')
    return store.get_events(session_id, after_id=after_id, limit=limit)


@app.get('/v1/sessions/{session_id}/files')
def list_files(session_id: str, path: str = '.', _auth: None = Depends(require_auth)) -> dict[str, Any]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    target = safe_workspace_path(session, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail='Path not found')
    if target.is_file():
        return {'path': path, 'type': 'file', 'size': target.stat().st_size}
    items = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]:
        items.append({'name': item.name, 'type': 'dir' if item.is_dir() else 'file', 'size': item.stat().st_size if item.is_file() else None})
    return {'path': path, 'type': 'dir', 'items': items}


@app.get('/v1/sessions/{session_id}/files/content')
def read_file(session_id: str, path: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    target = safe_workspace_path(session, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail='File not found')
    return {'path': path, 'content': target.read_text(errors='replace')}


@app.put('/v1/sessions/{session_id}/files/content')
def write_file(session_id: str, payload: FileWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, str]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    target = safe_workspace_path(session, payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content)
    store.add_event(Event(session_id=session.id, type='file_written', message=payload.path))
    return {'status': 'written', 'path': payload.path}


@app.get('/v1/sessions/{session_id}/diff')
def get_diff(session_id: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'diff': git_diff(session)}


@app.get('/v1/sessions/{session_id}/git/status')
def get_git_status(session_id: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': git_status(session)}


@app.delete('/v1/sessions/{session_id}')
def delete_session(session_id: str, remove_workspace: bool = False, _auth: None = Depends(require_auth)) -> dict[str, str]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    session.status = 'closed'
    store.add_session(session)
    if remove_workspace:
        shutil.rmtree(session.workspace_path, ignore_errors=True)
    store.add_event(Event(session_id=session.id, type='session_closed', message='Session closed'))
    return {'status': 'closed'}




class SourceWriteRequest(BaseModel):
    path: str
    content: str


class SourceCreateRequest(BaseModel):
    path: str
    type: str = 'file'


class SourceRenameRequest(BaseModel):
    path: str
    new_name: str


class SourceDeleteRequest(BaseModel):
    path: str


class SourceBuildRequest(BaseModel):
    path: str
    runtime: str = 'auto'
    tag: str | None = None
    targets: list[str] | None = None
    server_url: str | None = None


class SourceContextUpdateRequest(BaseModel):
    description: str | None = None
    path_prefix: str
    customer_id: str | None = None
    user_scope: str | None = None
    workspace_profile: str | None = None
    preferred_endpoint: str | None = None
    container_image: str | None = None
    profile: str | None = None
    config_vars: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class SecretUpdateRequest(BaseModel):
    value: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SourceVariableUpdateRequest(BaseModel):
    value: str
    description: str = ''
    tags: list[str] = Field(default_factory=list)


class PacRamWriteRequest(BaseModel):
    content: str


class ServerConnectionRequest(BaseModel):
    public_url: str
    mdns_enabled: bool | None = None


class SourceFeaturePackApplyRequest(BaseModel):
    upload_id: str


class EndpointInstallNodeRequest(BaseModel):
    method: str = 'auto'


class EndpointInstallHarnessRequest(BaseModel):
    image: str | None = None
    runtime: str = 'auto'


def _normalise_source_context_name(name: str) -> str:
    value = str(name or '').strip()
    if not value:
        raise HTTPException(status_code=400, detail='Source context name is required')
    if '/' in value or '\\' in value:
        raise HTTPException(status_code=400, detail='Source context name must not contain path separators')
    return value


def _normalise_source_context_path(path: str | None) -> str:
    value = str(path or '').strip().replace('\\', '/').strip('/')
    if not value:
        raise HTTPException(status_code=400, detail='path_prefix is required')
    return value


def _save_source_context(name: str, payload: SourceContextUpdateRequest) -> dict[str, Any]:
    global config
    context = SourceContextConfig.model_validate(
        {
            **payload.model_dump(),
            'path_prefix': _normalise_source_context_path(payload.path_prefix),
        }
    )
    config.source_contexts[name] = context
    save_config(config)
    config = load_config()
    result = config.source_contexts[name].model_dump()
    store.add_event(Event(session_id='system', type='source_context_saved', message=f'Source context saved: {name}', data={'name': name, **result}))
    return result


def _match_source_context(path: str | None = None, name: str | None = None) -> tuple[str, SourceContextConfig]:
    if name:
        context = config.source_contexts.get(name)
        if not context:
            raise HTTPException(status_code=404, detail='Source context not found')
        return name, context
    clean = str(path or '').strip().replace('\\', '/').strip('/')
    if not clean:
        raise HTTPException(status_code=400, detail='path or name is required')
    matches: list[tuple[int, str, SourceContextConfig]] = []
    for ctx_name, ctx in (config.source_contexts or {}).items():
        prefix = str(ctx.path_prefix or '').strip('/').replace('\\', '/')
        if not prefix:
            continue
        if clean == prefix or clean.startswith(prefix + '/'):
            matches.append((len(prefix), ctx_name, ctx))
    if not matches:
        raise HTTPException(status_code=404, detail='No source context matches this path')
    _len, matched_name, matched_context = sorted(matches, key=lambda item: item[0], reverse=True)[0]
    return matched_name, matched_context


def _resolve_source_context(path: str | None = None, name: str | None = None, include_secret_values: bool = False) -> dict[str, Any]:
    context_name, context = _match_source_context(path=path, name=name)
    config_vars, resolved_variables = _resolve_variable_tokens(dict(context.config_vars or {}))
    secret_refs = dict(context.secret_refs or {})
    resolved_secrets: dict[str, str | None] = {}
    for env_name, secret_id in secret_refs.items():
        try:
            resolved_secrets[env_name] = secret_store.get(secret_id) if include_secret_values else None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        'name': context_name,
        'context': context.model_dump(),
        'path': str(path or '').strip().replace('\\', '/'),
        'environment': {
            **config_vars,
            **({env_name: value for env_name, value in resolved_secrets.items() if value is not None} if include_secret_values else {}),
        },
        'config_vars': config_vars,
        'resolved_variables': resolved_variables,
        'secret_refs': secret_refs,
        'resolved_secrets': resolved_secrets,
    }



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


@app.get('/v1/sources')
def get_sources(path: str = '', _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        info = ensure_source_library()
        tree = source_list_tree(path)
        return {'root': info['root'], 'top_level': info['top_level'], **tree}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Source path not found')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get('/v1/sources/content')
def get_source_content(path: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        return source_read_text(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Source file not found')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put('/v1/sources/content')
def put_source_content(payload: SourceWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = source_write_text(payload.path, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.add_event(Event(session_id='system', type='source_file_saved', message=f'Source saved: {result["path"]}', data=result))
    return {'status': 'saved', **result}


@app.get('/v1/source-contexts')
@app.get('/v1/ide/contexts')
def list_source_contexts(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    items = [{'name': name, **ctx.model_dump()} for name, ctx in sorted((config.source_contexts or {}).items())]
    return {'contexts': items}


@app.get('/v1/source-contexts/resolve')
@app.get('/v1/ide/context/resolve')
def resolve_source_context(
    path: str | None = None,
    name: str | None = None,
    include_secrets: bool = Query(default=False),
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    runner = _runner_from_auth_headers(authorization, x_pac_runner_id, x_pac_runner_key)
    include_secret_values = include_secrets and (_admin_auth_valid(authorization) or runner is not None)
    result = _resolve_source_context(path=path, name=name, include_secret_values=include_secret_values)
    if runner:
        result['requested_by'] = {'kind': 'endpoint', 'runner_id': runner.id, 'runner_name': runner.name}
    elif _admin_auth_valid(authorization):
        result['requested_by'] = {'kind': 'admin'}
    return result


@app.get('/v1/source-contexts/{name}')
@app.get('/v1/ide/contexts/{name}')
def get_source_context(name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    key = _normalise_source_context_name(name)
    context = config.source_contexts.get(key)
    if not context:
        raise HTTPException(status_code=404, detail='Source context not found')
    return {'name': key, **context.model_dump()}


@app.put('/v1/source-contexts/{name}')
@app.put('/v1/ide/contexts/{name}')
def put_source_context(name: str, payload: SourceContextUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    key = _normalise_source_context_name(name)
    result = _save_source_context(key, payload)
    return {'status': 'saved', 'name': key, **result}


@app.delete('/v1/source-contexts/{name}')
@app.delete('/v1/ide/contexts/{name}')
def delete_source_context(name: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global config
    key = _normalise_source_context_name(name)
    if key not in config.source_contexts:
        raise HTTPException(status_code=404, detail='Source context not found')
    del config.source_contexts[key]
    save_config(config)
    config = load_config()
    store.add_event(Event(session_id='system', type='source_context_deleted', message=f'Source context deleted: {key}', data={'name': key}))
    return {'status': 'deleted', 'name': key}


@app.get('/v1/source-variables')
@app.get('/v1/ide/variables')
def list_source_variables(
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    return {'variables': source_variable_store.list()}


@app.get('/v1/source-variables/{variable_id}')
@app.get('/v1/ide/variables/{variable_id}')
def get_source_variable(
    variable_id: str,
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    try:
        item = source_variable_store.get(variable_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail='Variable not found')
    return item


@app.put('/v1/source-variables/{variable_id}')
@app.put('/v1/ide/variables/{variable_id}')
def put_source_variable(variable_id: str, payload: SourceVariableUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        item = source_variable_store.set(variable_id, payload.value, payload.description, payload.tags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.add_event(Event(session_id='system', type='source_variable_saved', message=f'Source variable saved: {item["id"]}', data=item))
    return {'status': 'saved', **item}


@app.delete('/v1/source-variables/{variable_id}')
@app.delete('/v1/ide/variables/{variable_id}')
def delete_source_variable(variable_id: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        deleted = source_variable_store.delete(variable_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='Variable not found')
    store.add_event(Event(session_id='system', type='source_variable_deleted', message=f'Source variable deleted: {variable_id}', data={'id': variable_id}))
    return {'status': 'deleted', 'id': variable_id}


@app.get('/v1/pac-ram/list')
@app.get('/v1/ide/pac-ram/list')
def get_pac_ram_list(
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    return list_ram()


@app.get('/v1/pac-ram/all')
@app.get('/v1/ide/pac-ram/all')
def get_all_pac_ram(
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    return all_ram()


@app.get('/v1/pac-ram/profile/{profile}')
def get_profile_ram(
    profile: str,
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    try:
        return read_ram('profile', profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put('/v1/pac-ram/profile/{profile}')
def put_profile_ram(profile: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = write_ram('profile', profile, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM profile saved: {result["key"]}', data={'kind': 'profile', **result}))
    return result


@app.get('/v1/pac-ram/user/{user_id}')
def get_user_ram(
    user_id: str,
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    try:
        return read_ram('user', user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put('/v1/pac-ram/user/{user_id}')
def put_user_ram(user_id: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = write_ram('user', user_id, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM user saved: {result["key"]}', data={'kind': 'user', **result}))
    return result


@app.get('/v1/pac-ram/workspace/{workspace}')
def get_workspace_ram(
    workspace: str,
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    _require_admin_or_runner(authorization, x_pac_runner_id, x_pac_runner_key)
    try:
        return read_ram('workspace', workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put('/v1/pac-ram/workspace/{workspace}')
def put_workspace_ram(workspace: str, payload: PacRamWriteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = write_ram('workspace', workspace, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.add_event(Event(session_id='system', type='pac_ram_saved', message=f'PAC RAM workspace saved: {result["key"]}', data={'kind': 'workspace', **result}))
    return result


@app.get('/v1/secrets')
@app.get('/v1/ide/secrets')
def list_secrets(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        return {'secrets': secret_store.list()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get('/v1/secrets/audit')
@app.get('/v1/ide/secrets/audit')
def list_secret_audit(limit: int = 20, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        return {'items': secret_store.audit_tail(max(1, min(limit, 200)))}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put('/v1/secrets/{secret_id}')
@app.put('/v1/ide/secrets/{secret_id}')
def put_secret(secret_id: str, payload: SecretUpdateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        item = secret_store.set(secret_id, payload.value, actor='web-ui', meta=payload.meta)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    store.add_event(Event(session_id='system', type='secret_saved', message=f'Secret saved: {secret_id}', data={'secret_id': secret_id, 'meta': payload.meta}))
    return {'status': 'saved', **item}


@app.delete('/v1/secrets/{secret_id}')
@app.delete('/v1/ide/secrets/{secret_id}')
def delete_secret(secret_id: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        deleted = secret_store.delete(secret_id, actor='web-ui')
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='Secret not found')
    store.add_event(Event(session_id='system', type='secret_deleted', message=f'Secret deleted: {secret_id}', data={'secret_id': secret_id}))
    return {'status': 'deleted', 'secret_id': secret_id}


@app.get('/v1/secrets/{secret_id}')
@app.get('/v1/ide/secrets/{secret_id}')
def get_secret(
    secret_id: str,
    authorization: str | None = Header(default=None),
    x_pac_runner_id: str | None = Header(default=None, alias='X-PAC-Runner-ID'),
    x_pac_runner_key: str | None = Header(default=None, alias='X-PAC-Runner-Key'),
) -> dict[str, Any]:
    runner = _runner_from_auth_headers(authorization, x_pac_runner_id, x_pac_runner_key)
    try:
        value = secret_store.get(secret_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail='Secret not found')
    return {
        'secret_id': secret_id,
        'value': value,
        'requested_by': {'kind': 'endpoint', 'runner_id': runner.id} if runner else {'kind': 'admin'},
    }





@app.post('/v1/sources/entry')
def create_source_entry(payload: SourceCreateRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = source_create_entry(payload.path, payload.type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.add_event(Event(session_id='system', type='source_entry_created', message=f'Source {result["type"]} created: {result["path"]}', data=result))
    return result


@app.post('/v1/sources/entry/rename')
def rename_source_entry(payload: SourceRenameRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = source_rename_entry(payload.path, payload.new_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Source path not found')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.add_event(Event(session_id='system', type='source_entry_renamed', message=f'Source renamed: {result["path"]} -> {result["new_path"]}', data=result))
    return result


@app.delete('/v1/sources/entry')
def delete_source_entry(payload: SourceDeleteRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = source_delete_entry(payload.path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Source path not found')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.add_event(Event(session_id='system', type='source_entry_deleted', message=f'Source deleted: {result["path"]}', data=result))
    return result


@app.post('/v1/sources/build-container')
def build_source_container(payload: SourceBuildRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global _SOURCE_BUILD_ACTIVE
    _SOURCE_BUILD_ACTIVE = {'kind': 'container', 'path': payload.path, 'status': 'running', 'message': 'Container build is running'}
    try:
        result = source_build_container(payload.path, runtime=payload.runtime, tag=payload.tag)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Container source folder not found')
    except Exception as exc:
        store.add_event(Event(session_id='system', type='source_container_build_failed', message=f'Container build failed: {payload.path}', data={'path': payload.path, 'error': str(exc)}))
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        _SOURCE_BUILD_ACTIVE = None
    store.add_event(Event(session_id='system', type='source_container_built' if result.get('ok') else 'source_container_build_failed', message=f'Container build {"completed" if result.get("ok") else "failed"}: {result.get("image")}', data=result))
    return result


@app.post('/v1/sources/build-binary')
def build_source_binary(payload: SourceBuildRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    global _SOURCE_BUILD_ACTIVE
    _SOURCE_BUILD_ACTIVE = {'kind': 'binary', 'path': payload.path, 'status': 'running', 'message': 'Binary build is running'}
    try:
        old_build_server_url = os.environ.get('PAC_BUILD_SERVER_URL')
        compiled_url = (payload.server_url or str(config.server.public_url) or '').strip().rstrip('/')
        if compiled_url:
            os.environ['PAC_BUILD_SERVER_URL'] = compiled_url
        try:
            result = source_build_binary(payload.path, targets=payload.targets, runtime=payload.runtime)
            result['compiled_server_url'] = compiled_url
        finally:
            if old_build_server_url is None:
                os.environ.pop('PAC_BUILD_SERVER_URL', None)
            else:
                os.environ['PAC_BUILD_SERVER_URL'] = old_build_server_url
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Binary source folder not found')
    except Exception as exc:
        store.add_event(Event(session_id='system', type='source_binary_build_failed', message=f'Binary build failed: {payload.path}', data={'path': payload.path, 'error': str(exc)}))
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        _SOURCE_BUILD_ACTIVE = None
    store.add_event(Event(session_id='system', type='source_binary_built' if result.get('ok') else 'source_binary_build_failed', message=f'Binary build {"completed" if result.get("ok") else "failed"}: {payload.path}', data=result))
    return result


@app.post('/v1/sources/feature-pack/inspect')
def inspect_source_feature_pack(file: UploadFile = File(...), _auth: None = Depends(require_auth)) -> dict[str, Any]:
    _require_no_source_builds('Feature update inspection')
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail='Feature update must be a .zip file')
    upload_dir = pacp_path('cache', 'feature-packs')
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    path = upload_dir / f'{upload_id}.zip'
    with path.open('wb') as dst:
        shutil.copyfileobj(file.file, dst)
    try:
        result = source_inspect_feature_pack(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        store.add_event(Event(session_id='system', type='feature_pack_inspect_failed', message=f'Feature update inspection failed: {exc}', data={'filename': file.filename, 'error': str(exc)}))
        raise HTTPException(status_code=400, detail=str(exc))
    result['upload_id'] = upload_id
    result['pending_apply_url'] = '/v1/sources/feature-pack/apply'
    if result.get('package_type') == 'pac_app_update':
        message = f'PAC app update inspected: {result.get("current_version", "unknown")} -> {result.get("target_version", "unknown")}'
    else:
        message = f'Feature update inspected: {len(result.get("components", []))} source folders'
    store.add_event(Event(session_id='system', type='feature_pack_inspected', message=message, data=result))
    return result




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
        'preservation_archive': archive_meta,
        'preservation_diff': diff_meta,
        'restart_required': True,
        'restart_scheduled': restart_after_update,
        'restart_marker': str(marker),
    }
    store.add_event(Event(session_id='system', type='package_applied', message=f'PAC app update applied: {filename}. Restart required.', data=result))
    return result


@app.post('/v1/sources/feature-pack/apply')
def apply_source_feature_pack(background_tasks: BackgroundTasks, payload: SourceFeaturePackApplyRequest, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    _require_no_source_builds('Feature update apply')
    upload_id = ''.join(ch for ch in payload.upload_id if ch.isalnum())[:32]
    path = pacp_path('cache', 'feature-packs', f'{upload_id}.zip')
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Feature update upload was not found; inspect the zip again')
    try:
        preview = source_inspect_feature_pack(path)
        if preview.get('package_type') == 'pac_app_update':
            result = _apply_version_package_from_path(path, preview.get('filename') or path.name, restart_after_update=True)
            result.update({'preview': preview})
            _schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying app update: {path.name}')
            return result
        result = source_apply_feature_pack(path)
    except Exception as exc:
        store.add_event(Event(session_id='system', type='feature_pack_apply_failed', message=f'Feature update failed: {exc}', data={'upload_id': upload_id, 'error': str(exc)}))
        raise HTTPException(status_code=400, detail=str(exc))
    store.add_event(Event(session_id='system', type='feature_pack_applied', message=f'Feature update applied: {len(result.get("components", []))} source folders', data=result))
    path.unlink(missing_ok=True)
    return result




@app.get('/v1/sources/online-updates')
def check_source_online_updates(manifest_url: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    url = manifest_url or getattr(config.source_updates, 'packages_manifest_url', None)
    result = source_fetch_online_package_updates(url)
    event_type = 'source_online_updates_checked' if result.get('ok') else 'source_online_updates_failed'
    message = f"Source package updates checked: {result.get('update_count', 0)} available" if result.get('ok') else f"Source package update check failed: {result.get('error', 'unknown error')}"
    store.add_event(Event(session_id='system', type=event_type, message=message, data=result))
    return result


@app.get('/v1/sources/binary-artifacts')
def list_source_binary_artifacts(project: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    return source_list_binary_artifacts(project)


@app.get('/v1/sources/binary-artifacts/{project}/{filename}')
def download_source_binary_artifact(project: str, filename: str, _auth: None = Depends(require_auth)) -> FileResponse:
    try:
        path = source_binary_artifact_path(project, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Binary artifact not found')
    return FileResponse(path, filename=path.name)




@app.delete('/v1/sources/binary-artifacts/{project}/{filename}')
def delete_source_binary_artifact(project: str, filename: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        result = source_delete_binary_artifact(project, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Binary artifact not found')
    store.add_event(Event(session_id='system', type='source_binary_artifact_deleted', message=f'Binary artifact deleted: {project}/{filename}', data=result))
    return result


@app.post('/v1/sources/binary-artifacts/prune')
def prune_source_binary_artifacts(payload: dict[str, Any] | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    payload = payload or {}
    project = payload.get('project') or None
    keep_versions = int(payload.get('keep_versions') or 1)
    dry_run = bool(payload.get('dry_run') or False)
    result = source_prune_binary_artifacts(project=project, keep_versions=keep_versions, dry_run=dry_run)
    store.add_event(Event(session_id='system', type='source_binary_artifacts_pruned', message=f'Binary artifacts prune {"previewed" if dry_run else "completed"}: kept newest {keep_versions} version(s)', data={**result, 'project': project}))
    return result

@app.get('/v1/sources/archive')
def download_source_archive(_auth: None = Depends(require_auth)) -> FileResponse:
    archive = source_make_archive()
    return FileResponse(archive, filename='pac-sources.tar.gz')


# --- Endpoint / remote host PAC ---





def _agent_enablement_state(runner: Runner, requested: bool | None = None) -> dict[str, Any]:
    caps = runner.capabilities or {}
    req = caps.get('agent_requirements') or {}
    pi_container = caps.get('pi_container') or {}
    wrapper = caps.get('pac_wrapper') or {}
    node_ok = bool(req.get('node') or (caps.get('tools') or {}).get('node', {}).get('available'))
    wrapper_ok = bool(req.get('pac_wrapper') or wrapper.get('available'))
    pi_ok = bool(pi_container.get('available'))
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
    agent_status = 'ready' if pi_container.get('available') else 'attention'
    agent_detail = 'pi.dev runtime is available.' if pi_container.get('available') else (pi_container.get('reason') or 'pi.dev runtime image is not available on this endpoint.')
    previous_pi_state = runner.metadata.get('pi_container_available')
    runner.metadata.update({
        'local_control_plane': True,
        'agent_enabled': True,
        'endpoint_version': PAC_VERSION,
        'runner_version': PAC_VERSION,
        'agent_runtime': _runtime_agent_state('pac-local', agent_status, agent_detail, pi_container=pi_container),
        'pi_container_available': bool(pi_container.get('available')),
        'agent_tools': runner.metadata.get('agent_tools') or [name for name, tool in config.tools.items() if tool.enabled],
        'tool_packages': runner.metadata.get('tool_packages') or list(config.tool_packages.keys()),
        'default_workspace': default_workspace,
        'source_library': {'available': True, 'archive_url': '/v1/sources/archive', 'root': ensure_source_library().get('root')},
    })
    runner.metadata['pac_wrapper_process'] = _wrapper_process_state() if '_wrapper_process_state' in globals() else {'running': False}
    runner.metadata['pi_dev_daemon'] = _pi_dev_daemon_state() if '_pi_dev_daemon_state' in globals() else {'running': False}
    if runner.metadata.get('pac_wrapper_process', {}).get('running'):
        runner.metadata['agent_runtime'] = _runtime_agent_state('pac-wrapper', 'ready', 'Local PAC wrapper process is running and connected.', wrapper=runner.metadata.get('pac_wrapper_process'), pi_daemon=runner.metadata.get('pi_dev_daemon'))
    runner = _normalise_endpoint_metadata(runner, True)
    runner.last_seen_at = Event(session_id='system', type='noop', message='noop').created_at
    store.add_runner(runner)
    if previous_pi_state is None or bool(previous_pi_state) != bool(pi_container.get('available')):
        event_type = 'endpoint_pi_container_ready' if pi_container.get('available') else 'endpoint_pi_container_unavailable'
        store.add_event(Event(session_id='system', type=event_type, message=agent_detail, data={'runner_id': runner.id, 'pi_container': pi_container}))
    if emit_event:
        store.add_event(Event(session_id='system', type='local_runner_added', message='Local PAC endpoint refreshed', data={'runner_id': runner.id, 'containers': len(containers), 'pi_container': pi_container}))
    return runner

@app.get('/v1/runners', response_model=list[Runner])
@app.get('/v1/endpoints', response_model=list[Runner])
def list_runners(_auth: None = Depends(require_auth)) -> list[Runner]:
    _refresh_local_runner_metadata(emit_event=False)
    return store.list_runners()


@app.post('/v1/runners', response_model=Runner)
@app.post('/v1/endpoints', response_model=Runner)
def create_runner(payload: RunnerCreateRequest, _auth: None = Depends(require_auth)) -> Runner:
    runner = Runner(
        name=payload.name,
        labels=payload.labels,
        endpoint=payload.endpoint,
        allow_host_execution=payload.allow_host_execution,
        allow_container_execution=payload.allow_container_execution,
        metadata={**payload.metadata, 'agent_requested': payload.agent_enabled, 'certificate_request_url': '/v1/tls/issue-endpoint-cert', 'ca_download_url': '/v1/tls/ca.pem', 'agent_runtime': (payload.metadata or {}).get('agent_runtime') or _runtime_agent_state('remote-execution', 'waiting', 'Waiting for endpoint heartbeat.')},
        status=RunnerStatus.pending,
    )
    runner.metadata['default_workspace'] = runner.metadata.get('default_workspace') or _endpoint_default_workspace(runner.id, runner.name)
    runner.metadata.setdefault('tool_packages', _packages_for_tools(runner.metadata.get('agent_tools', [])))
    runner = _normalise_endpoint_metadata(runner, payload.agent_enabled)
    store.add_runner(runner)
    store.add_event(Event(session_id='system', type='runner_created', message=f'Endpoint {runner.name} added', data={'runner_id': runner.id}))
    return runner




@app.put('/v1/runners/{runner_id}', response_model=Runner)
@app.put('/v1/endpoints/{runner_id}', response_model=Runner)
def update_runner(runner_id: str, payload: RunnerCreateRequest, _auth: None = Depends(require_auth)) -> Runner:
    runner = store.get_runner(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    runner.name = payload.name
    runner.labels = payload.labels
    runner.endpoint = payload.endpoint
    runner.allow_host_execution = payload.allow_host_execution
    runner.allow_container_execution = payload.allow_container_execution
    runner.metadata.update(payload.metadata or {})
    runner.metadata['agent_requested'] = payload.agent_enabled
    runner.metadata['default_workspace'] = runner.metadata.get('default_workspace') or _endpoint_default_workspace(runner.id, runner.name)
    runner.metadata.setdefault('tool_packages', _packages_for_tools(runner.metadata.get('agent_tools', [])))
    runner.metadata.setdefault('agent_runtime', _runtime_agent_state('remote-execution', 'waiting', 'Waiting for endpoint heartbeat.'))
    runner = _normalise_endpoint_metadata(runner, payload.agent_enabled)
    runner = store.add_runner(runner)
    store.add_event(Event(session_id='system', type='endpoint_updated', message=f'Endpoint updated: {runner.name}', data={'runner_id': runner.id, 'agent_tools': runner.metadata.get('agent_tools', [])}))
    return runner

@app.post('/v1/runners/register', response_model=Runner)
@app.post('/v1/endpoints/register', response_model=Runner)
def register_runner(payload: RunnerRegisterRequest, _auth: None = Depends(require_auth)) -> Runner:
    requested_name = str(payload.name or '').strip()
    is_local_wrapper = requested_name == 'local-PAC' or str(payload.endpoint or '') == 'pac-endpoint://local-PAC' or bool((payload.metadata or {}).get('controller_wrapper'))
    existing_local = store.get_runner('local-PAC') if is_local_wrapper else None
    runner = existing_local or Runner(
        name=payload.name,
        labels=payload.labels,
        endpoint=payload.endpoint,
        api_key=payload.api_key,
        allow_host_execution=payload.allow_host_execution,
        allow_container_execution=payload.allow_container_execution,
        metadata={**payload.metadata, 'agent_requested': payload.agent_enabled, 'certificate_request_url': '/v1/tls/issue-endpoint-cert', 'ca_download_url': '/v1/tls/ca.pem', 'agent_runtime': (payload.metadata or {}).get('agent_runtime') or _runtime_agent_state('remote-execution', 'registered', 'Waiting for first heartbeat.')},
        status=RunnerStatus.pending,
    )
    if existing_local:
        runner.name = 'local-PAC'
        runner.labels = sorted(set((runner.labels or []) + list(payload.labels or []) + ['controller', 'local', 'PAC', 'pi.dev']))
        runner.endpoint = 'pac-endpoint://local-PAC'
        runner.api_key = payload.api_key
        runner.allow_host_execution = payload.allow_host_execution
        runner.allow_container_execution = payload.allow_container_execution
        runner.metadata.update(payload.metadata or {})
        runner.metadata.update({'local_control_plane': True, 'controller_wrapper': True, 'agent_requested': True, 'certificate_request_url': '/v1/tls/issue-endpoint-cert', 'ca_download_url': '/v1/tls/ca.pem', 'agent_runtime': _runtime_agent_state('pac-wrapper', 'registered', 'Local PAC wrapper registered and waiting for heartbeat.')})
        runner.status = RunnerStatus.pending
    cert_result = None
    try:
        if getattr(payload, 'csr_pem', None):
            cert_result = _issue_endpoint_certificate(runner.name, payload.csr_pem, getattr(payload, 'certificate_sans', []), None)
            runner.metadata['certificate_issued'] = True
            runner.metadata['certificate_name'] = cert_result.get('name')
            runner.metadata['certificate_file'] = cert_result.get('cert_file')
    except Exception as exc:
        runner.metadata['certificate_issued'] = False
        runner.metadata['certificate_error'] = str(exc)
    runner.metadata['default_workspace'] = runner.metadata.get('default_workspace') or _endpoint_default_workspace(runner.id, runner.name)
    runner.metadata.setdefault('tool_packages', _packages_for_tools(runner.metadata.get('agent_tools', [])))
    runner = _normalise_endpoint_metadata(runner, payload.agent_enabled)
    store.add_runner(runner)
    store.add_event(Event(session_id='system', type='runner_registered', message=f'Endpoint {runner.name} registered', data={'runner_id': runner.id, 'labels': runner.labels, 'certificate_issued': bool(cert_result)}))
    return runner


@app.get('/v1/runners/local/discover')
@app.get('/v1/endpoints/local/discover')
def local_discover(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    return {'capabilities': discover_host(), 'containers': discover_containers()}


@app.post('/v1/runners/local', response_model=Runner)
@app.post('/v1/endpoints/local', response_model=Runner)
def add_local_runner(_auth: None = Depends(require_auth)) -> Runner:
    """Add or refresh the PAC host as a first-class endpoint entry."""
    try:
        return _refresh_local_runner_metadata(emit_event=True)
    except Exception as exc:
        store.add_event(Event(session_id='system', type='local_endpoint_add_failed', message=f'Local endpoint could not be added: {exc}', data={'error': str(exc)}))
        raise HTTPException(status_code=500, detail=f'Local endpoint could not be added: {exc}')


@app.get('/v1/runners/{runner_id}', response_model=Runner)
@app.get('/v1/endpoints/{runner_id}', response_model=Runner)
def get_runner(runner_id: str, _auth: None = Depends(require_auth)) -> Runner:
    runner = store.get_runner(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    return runner


@app.post('/v1/runners/heartbeat', response_model=Runner)
@app.post('/v1/endpoints/heartbeat', response_model=Runner)
def runner_heartbeat(payload: RunnerHeartbeat, _auth: None = Depends(require_auth)) -> Runner:
    runner = store.get_runner(payload.runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    runner.status = payload.status
    runner.labels = payload.labels or runner.labels
    runner.capabilities = payload.capabilities
    runner.containers = payload.containers
    runner.metadata.update(payload.metadata)
    runner.metadata['runner_version'] = payload.version or runner.metadata.get('runner_version')
    runner.metadata['endpoint_version'] = payload.version or runner.metadata.get('endpoint_version')
    pi_container = runner.capabilities.get('pi_container') if isinstance(runner.capabilities, dict) else None
    pi_available = bool((pi_container or {}).get('available'))
    runner.metadata['agent_runtime'] = _runtime_agent_state(
        'remote-runner',
        'ready' if pi_available else 'attention',
        'Endpoint runner heartbeat received.' if pi_available else ((pi_container or {}).get('reason') or 'pi.dev runtime image is not available on this endpoint.'),
        pi_container_image=runner.metadata.get('pi_container_image'),
        pi_container=pi_container,
    )
    runner = _normalise_endpoint_metadata(runner, runner.metadata.get('agent_requested') or runner.metadata.get('agent_enabled', False))
    runner.last_seen_at = Event(session_id='system', type='noop', message='noop').created_at
    store.add_runner(runner)
    store.add_event(Event(session_id='system', type='runner_heartbeat', message=f'Heartbeat from endpoint {runner.name}', data={'runner_id': runner.id, 'containers': len(runner.containers), 'capabilities': runner.capabilities}))
    return runner


@app.delete('/v1/runners/{runner_id}')
@app.delete('/v1/endpoints/{runner_id}')
def delete_runner(runner_id: str, _auth: None = Depends(require_auth)) -> dict[str, str]:
    if runner_id == 'local-PAC':
        _refresh_local_runner_metadata(emit_event=False)
        raise HTTPException(status_code=400, detail='The local PAC endpoint is required by the controller pi.dev runtime and cannot be deleted.')
    if not store.delete_runner(runner_id):
        raise HTTPException(status_code=404, detail='Endpoint not found')
    store.add_event(Event(session_id='system', type='runner_deleted', message=f'Endpoint {runner_id} deleted'))
    return {'status': 'deleted'}




def _maintenance_job_for_endpoint(endpoint: Runner, req: EndpointMaintenanceRequest) -> RunnerJob:
    job = RunnerJob(
        runner_id=endpoint.id,
        prompt='Run PAC endpoint maintenance cleanup',
        command=None,
        execution_mode=RunnerExecutionMode.host,
        metadata={'operation': 'endpoint_maintenance', **req.model_dump()},
    )
    endpoint.metadata['maintenance_status'] = 'queued'
    endpoint.metadata['maintenance_requested_at'] = datetime.now(timezone.utc).isoformat()
    store.add_runner(endpoint)
    store.add_runner_job(job)
    store.add_event(Event(session_id='system', type='endpoint_maintenance_queued', message=f'Maintenance queued for endpoint {endpoint.name}', data={'endpoint_id': endpoint.id, 'job_id': job.id, **req.model_dump()}))
    return job




@app.post('/v1/endpoints/{runner_id}/commands', response_model=RunnerJob)
def queue_endpoint_command(runner_id: str, payload: RunnerJobCreate, _auth: None = Depends(require_auth)) -> RunnerJob:
    runner = store.get_runner(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    if runner.status != RunnerStatus.online and not runner.metadata.get('local_control_plane'):
        raise HTTPException(status_code=400, detail='Endpoint must be online before commands can be queued')
    if payload.execution_mode == RunnerExecutionMode.pi_container:
        enablement = runner.metadata.get('agent_enablement') or {}
        if enablement.get('status') != 'ready':
            raise HTTPException(status_code=400, detail=enablement.get('detail') or 'Agent workloads are not ready on this endpoint')
    tool_name = (payload.metadata or {}).get('tool_name')
    if tool_name:
        tools = (runner.capabilities or {}).get('tools') or {}
        tool_state = tools.get(tool_name) or {}
        if tools and not tool_state.get('available'):
            raise HTTPException(status_code=400, detail=f'Endpoint tool is not available: {tool_name}')
        if not payload.command:
            payload.command = f'tool:{tool_name}'
    job = RunnerJob(
        runner_id=runner.id,
        prompt=payload.prompt,
        command=payload.command,
        execution_mode=payload.execution_mode,
        container_image=payload.container_image,
        container_runtime=payload.container_runtime,
        workspace_path=payload.workspace_path,
        session_id=payload.session_id,
        task_id=payload.task_id,
        metadata={**(payload.metadata or {}), 'command_channel': 'endpoint', 'source_endpoint_id': (payload.metadata or {}).get('source_endpoint_id') or 'controller', 'target_endpoint_id': runner.id},
    )
    store.add_runner_job(job)
    store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type='endpoint_command_queued', message=f'Command queued for endpoint {runner.name}', data={'runner_id': runner.id, 'runner_job_id': job.id, 'execution_mode': job.execution_mode, 'command': job.command}))
    return job




@app.post('/v1/endpoints/{runner_id}/install-node', response_model=RunnerJob | dict[str, Any])
def install_node_on_endpoint(runner_id: str, payload: EndpointInstallNodeRequest | None = None, _auth: None = Depends(require_auth)) -> RunnerJob | dict[str, Any]:
    endpoint = store.get_runner(runner_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    req = payload or EndpointInstallNodeRequest()
    command = _node_install_command(req.method)
    if endpoint.metadata.get('local_control_plane'):
        proc = subprocess.run(command, cwd=str(Path.home()), shell=True, capture_output=True, text=True, timeout=900, check=False)
        _refresh_local_runner_metadata(emit_event=False)
        result = {'exit_code': proc.returncode, 'stdout': proc.stdout[-12000:], 'stderr': proc.stderr[-12000:]}
        ok = proc.returncode == 0
        store.add_event(Event(session_id='system', type='endpoint_node_install_completed' if ok else 'endpoint_node_install_failed', message=f'Node.js install {"completed" if ok else "failed"} on {endpoint.name}', data={'endpoint_id': endpoint.id, 'command': command, 'result': result}))
        return {'status': 'completed' if ok else 'failed', 'endpoint_id': endpoint.id, 'command': command, 'result': result}
    if endpoint.status != RunnerStatus.online:
        raise HTTPException(status_code=400, detail='Endpoint must be online to install Node.js')
    job = RunnerJob(runner_id=endpoint.id, prompt='Install Node.js on endpoint', command=command, execution_mode=RunnerExecutionMode.host, metadata={'operation': 'install_node', 'method': req.method})
    store.add_runner_job(job)
    store.add_event(Event(session_id='system', type='endpoint_node_install_queued', message=f'Node.js install queued for {endpoint.name}', data={'endpoint_id': endpoint.id, 'job_id': job.id, 'command': command}))
    return job



@app.post('/v1/endpoints/{runner_id}/install-pi-harness', response_model=RunnerJob | dict[str, Any])
@app.post('/v1/runners/{runner_id}/install-pi-harness', response_model=RunnerJob | dict[str, Any])
def install_pi_harness_on_endpoint(runner_id: str, payload: EndpointInstallHarnessRequest | None = None, _auth: None = Depends(require_auth)) -> RunnerJob | dict[str, Any]:
    global _SOURCE_BUILD_ACTIVE
    endpoint = store.get_runner(runner_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    blocker = _source_build_blocker()
    if blocker:
        store.add_event(Event(session_id='system', type='endpoint_pi_harness_install_pending', message='pi.dev install is pending while a build is active', data={'endpoint_id': endpoint.id, 'blocked_by': blocker}))
        raise HTTPException(status_code=409, detail={'message': 'pi.dev install is pending while a container or binary build is active.', 'blocked_by': blocker})
    req = payload or EndpointInstallHarnessRequest()
    image = req.image or (endpoint.capabilities or {}).get('pi_container', {}).get('image') or os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    if endpoint.metadata.get('local_control_plane'):
        _SOURCE_BUILD_ACTIVE = {'kind': 'pi_dev' , 'path': 'containers/pi-agent-harness', 'status': 'running', 'message': 'pi.dev install is running'}
        store.add_event(Event(session_id='system', type='endpoint_pi_harness_install_started', message=f'pi.dev install started on {endpoint.name}', data={'endpoint_id': endpoint.id, 'image': image, 'source': 'containers/pi-agent-harness'}))
        worker = threading.Thread(target=_local_pi_harness_install_worker, args=(endpoint.id, image, req.runtime), daemon=True)
        worker.start()
        return {'status': 'running', 'endpoint_id': endpoint.id, 'image': image, 'message': 'pi.dev install started. Progress and final result will appear in Events.'}
    if endpoint.status != RunnerStatus.online:
        raise HTTPException(status_code=400, detail='Endpoint must be online to install pi.dev')
    command = _install_pi_harness_command(image)
    job = RunnerJob(runner_id=endpoint.id, prompt='Install pi.dev on endpoint', command=command, execution_mode=RunnerExecutionMode.host, metadata={'operation': 'install_pi_harness', 'image': image, 'source': 'containers/pi-agent-harness'})
    store.add_runner_job(job)
    store.add_event(Event(session_id='system', type='endpoint_pi_harness_install_queued', message=f'pi.dev install queued for {endpoint.name}', data={'endpoint_id': endpoint.id, 'job_id': job.id, 'command': command, 'image': image}))
    return job


@app.post('/v1/endpoints/{runner_id}/maintenance', response_model=RunnerJob | dict[str, Any])
@app.post('/v1/runners/{runner_id}/maintenance', response_model=RunnerJob | dict[str, Any])
def queue_endpoint_maintenance(runner_id: str, payload: EndpointMaintenanceRequest | None = None, _auth: None = Depends(require_auth)) -> RunnerJob | dict[str, Any]:
    endpoint = store.get_runner(runner_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    req = payload or EndpointMaintenanceRequest()
    if endpoint.metadata.get('local_control_plane'):
        result = run_endpoint_maintenance(**req.model_dump())
        endpoint.metadata['maintenance_status'] = 'completed'
        endpoint.metadata['maintenance_result'] = result.get('summary', {})
        endpoint.last_seen_at = datetime.now(timezone.utc)
        store.add_runner(endpoint)
        store.add_event(Event(session_id='system', type='endpoint_maintenance_completed', message=f'Local endpoint maintenance completed: {result.get("summary")}', data={'endpoint_id': endpoint.id, 'result': result}))
        return {'status': 'completed', 'endpoint_id': endpoint.id, 'result': result}
    if endpoint.status != RunnerStatus.online:
        raise HTTPException(status_code=400, detail='Endpoint must be online to queue maintenance')
    return _maintenance_job_for_endpoint(endpoint, req)


@app.post('/v1/endpoints/maintenance-all')
def queue_all_endpoint_maintenance(payload: EndpointMaintenanceRequest | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
    req = payload or EndpointMaintenanceRequest()
    queued: list[dict[str, str]] = []
    completed_local: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for endpoint in store.list_runners():
        if endpoint.metadata.get('local_control_plane'):
            result = run_endpoint_maintenance(**req.model_dump())
            endpoint.metadata['maintenance_status'] = 'completed'
            endpoint.metadata['maintenance_result'] = result.get('summary', {})
            store.add_runner(endpoint)
            completed_local.append({'id': endpoint.id, 'name': endpoint.name, 'summary': result.get('summary', {})})
            continue
        if endpoint.status != RunnerStatus.online:
            skipped.append({'id': endpoint.id, 'name': endpoint.name, 'reason': f'status={endpoint.status}'})
            continue
        job = _maintenance_job_for_endpoint(endpoint, req)
        queued.append({'id': endpoint.id, 'name': endpoint.name, 'job_id': job.id})
    store.add_event(Event(session_id='system', type='endpoint_maintenance_all_queued', message=f'Maintenance queued for {len(queued)} endpoint(s); local completed: {len(completed_local)}', data={'queued': queued, 'completed_local': completed_local, 'skipped': skipped, **req.model_dump()}))
    return {'queued': queued, 'completed_local': completed_local, 'skipped': skipped}



@app.post('/v1/endpoints/{runner_id}/update', response_model=RunnerJob)
@app.post('/v1/runners/{runner_id}/update', response_model=RunnerJob)
def queue_endpoint_update(runner_id: str, payload: EndpointUpdateRequest | None = None, _auth: None = Depends(require_auth)) -> RunnerJob:
    endpoint = store.get_runner(runner_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    if endpoint.metadata.get('local_control_plane'):
        raise HTTPException(status_code=400, detail='Local PAC endpoint is updated through Settings -> Self update, not endpoint update')
    if endpoint.status != RunnerStatus.online:
        raise HTTPException(status_code=400, detail='Endpoint must be online to queue update')
    req = payload or EndpointUpdateRequest()
    package_url = req.package_url or '/v1/admin/current-package'
    job = RunnerJob(
        runner_id=endpoint.id,
        prompt='Update PAC endpoint software',
        command=None,
        execution_mode=RunnerExecutionMode.host,
        metadata={'operation': 'endpoint_update', 'package_url': package_url, 'restart': req.restart, 'target_version': PAC_VERSION},
    )
    endpoint.metadata['update_status'] = 'queued'
    endpoint.metadata['target_version'] = PAC_VERSION
    endpoint.touch()
    store.add_runner(endpoint)
    store.add_runner_job(job)
    store.add_event(Event(session_id='system', type='endpoint_update_queued', message=f'Endpoint update queued for {endpoint.name}', data={'endpoint_id': endpoint.id, 'job_id': job.id, 'target_version': PAC_VERSION, 'package_url': package_url}))
    return job

@app.post('/v1/endpoints/update-all')
def queue_all_endpoint_updates(_auth: None = Depends(require_auth)) -> dict[str, Any]:
    queued: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for endpoint in store.list_runners():
        if endpoint.metadata.get('local_control_plane'):
            skipped.append({'id': endpoint.id, 'name': endpoint.name, 'reason': 'local endpoint uses self-update'})
            continue
        if endpoint.status != RunnerStatus.online:
            skipped.append({'id': endpoint.id, 'name': endpoint.name, 'reason': f'status={endpoint.status}'})
            continue
        job = RunnerJob(
            runner_id=endpoint.id,
            prompt='Update PAC endpoint software',
            execution_mode=RunnerExecutionMode.host,
            metadata={'operation': 'endpoint_update', 'package_url': '/v1/admin/current-package', 'restart': True, 'target_version': PAC_VERSION},
        )
        endpoint.metadata['update_status'] = 'queued'
        endpoint.metadata['target_version'] = PAC_VERSION
        store.add_runner(endpoint)
        store.add_runner_job(job)
        queued.append({'id': endpoint.id, 'name': endpoint.name, 'job_id': job.id})
    store.add_event(Event(session_id='system', type='endpoint_update_all_queued', message=f'Queued endpoint updates: {len(queued)}', data={'queued': queued, 'skipped': skipped, 'target_version': PAC_VERSION}))
    return {'queued': queued, 'skipped': skipped, 'target_version': PAC_VERSION}

@app.get('/v1/runner-jobs', response_model=list[RunnerJob])
def list_runner_jobs(runner_id: str | None = None, status: str | None = None, _auth: None = Depends(require_auth)) -> list[RunnerJob]:
    return store.list_runner_jobs(runner_id=runner_id, status=status)


@app.post('/v1/runners/{runner_id}/jobs', response_model=RunnerJob)
def create_runner_job(runner_id: str, payload: RunnerJobCreate, _auth: None = Depends(require_auth)) -> RunnerJob:
    runner = store.get_runner(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    if payload.execution_mode == 'host' and not runner.allow_host_execution:
        raise HTTPException(status_code=400, detail='Endpoint does not allow host execution')
    if payload.execution_mode in ('container', 'pi_container') and not runner.allow_container_execution:
        raise HTTPException(status_code=400, detail='Endpoint does not allow container execution')
    if payload.execution_mode == 'container' and not payload.container_image:
        raise HTTPException(status_code=400, detail='Container execution requires container_image')
    job = RunnerJob(
        runner_id=runner.id,
        prompt=payload.prompt,
        command=payload.command,
        execution_mode=payload.execution_mode,
        container_image=payload.container_image,
        container_runtime=payload.container_runtime,
        workspace_path=payload.workspace_path,
        session_id=payload.session_id,
        task_id=payload.task_id,
        metadata=payload.metadata,
    )
    store.add_runner_job(job)
    store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type='runner_job_queued', message=payload.prompt, data={'runner_id': runner.id, 'runner_job_id': job.id, 'execution_mode': job.execution_mode, 'command': job.command, 'container_image': job.container_image}))
    return job


@app.get('/v1/runners/{runner_id}/jobs/next', response_model=RunnerJob | None)
@app.get('/v1/endpoints/{runner_id}/jobs/next', response_model=RunnerJob | None)
def runner_next_job(runner_id: str, _auth: None = Depends(require_auth)) -> RunnerJob | None:
    runner = store.get_runner(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail='Endpoint not found')
    job = store.claim_next_runner_job(runner_id)
    if job:
        store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type='runner_job_claimed', message=f'Endpoint {runner.name} claimed {job.id}', data={'runner_id': runner.id, 'runner_job_id': job.id}))
    return job


@app.post('/v1/runner-jobs/{job_id}/log')
def runner_job_log(job_id: str, payload: RunnerJobLog, _auth: None = Depends(require_auth)) -> dict[str, str]:
    job = store.get_runner_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Runner job not found')
    store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type=f'runner_{payload.stream}', message=payload.message[-4000:], data={'runner_job_id': job.id, 'runner_id': job.runner_id}))
    return {'status': 'ok'}


@app.post('/v1/runner-jobs/{job_id}', response_model=RunnerJob)
def update_runner_job(job_id: str, payload: RunnerJobUpdate, _auth: None = Depends(require_auth)) -> RunnerJob:
    job = store.get_runner_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Runner job not found')
    job.status = payload.status
    job.output = payload.output if payload.output is not None else job.output
    job.error = payload.error if payload.error is not None else job.error
    job.exit_code = payload.exit_code if payload.exit_code is not None else job.exit_code
    job.metadata.update(payload.metadata)
    from pi_agent_platform.core.models import now_utc
    if payload.status == RunnerJobStatus.running:
        job.started_at = job.started_at or now_utc()
    if payload.status in (RunnerJobStatus.completed, RunnerJobStatus.failed, RunnerJobStatus.cancelled):
        job.completed_at = now_utc()
    store.add_runner_job(job)
    if job.metadata.get('operation') == 'endpoint_update':
        endpoint = store.get_runner(job.runner_id)
        if endpoint:
            endpoint.metadata['update_status'] = payload.status.value if hasattr(payload.status, 'value') else str(payload.status)
            endpoint.metadata['last_update_job'] = job.id
            endpoint.metadata['target_version'] = job.metadata.get('target_version') or endpoint.metadata.get('target_version')
            endpoint.touch()
            store.add_runner(endpoint)
    event_data = {'endpoint_id': job.runner_id, 'runner_job_id': job.id, 'exit_code': job.exit_code, 'operation': job.metadata.get('operation')}
    if job.error:
        event_data['error'] = job.error
    if job.output and payload.status in (RunnerJobStatus.failed, RunnerJobStatus.cancelled):
        event_data['output_tail'] = job.output[-4000:]
    status_value = payload.status.value if hasattr(payload.status, 'value') else str(payload.status)
    store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type=f'endpoint_job_{status_value}', message=f'Endpoint job {job.id} {status_value}', data=event_data))
    if job.task_id:
        task = store.get_task(job.task_id)
        if task:
            if payload.status == RunnerJobStatus.running:
                task.status = TaskStatus.running
            elif payload.status == RunnerJobStatus.completed:
                task.status = TaskStatus.completed
                task.output = job.output
                task.exit_code = job.exit_code
            elif payload.status in (RunnerJobStatus.failed, RunnerJobStatus.cancelled):
                task.status = TaskStatus.failed
                task.error = job.error
                task.output = job.output
                task.exit_code = job.exit_code
            store.add_task(task)
    return job
