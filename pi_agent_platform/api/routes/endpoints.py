from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pi_agent_platform.core.config import WorkspaceProfile
from pi_agent_platform.core.directory_identities import ensure_endpoint_principal, retire_endpoint_principal
from .endpoint_heartbeat_events import emit_heartbeat_events, stable_capability_signature

from pi_agent_platform.core.models import (
    Event,
    Runner,
    RunnerCreateRequest,
    RunnerExecutionMode,
    RunnerHeartbeat,
    RunnerJob,
    RunnerJobCreate,
    RunnerJobLog,
    RunnerJobStatus,
    RunnerJobUpdate,
    RunnerRegisterRequest,
    RunnerStatus,
    TaskStatus,
    now_utc,
)


class EndpointMaintenanceRequest(BaseModel):
    max_age_hours: int = 24
    dry_run: bool = False
    remove_containers: bool = True
    remove_workspaces: bool = True
    remove_temp_artifacts: bool = True
    prune_images: bool = False


class EndpointOnboardingRequest(BaseModel):
    endpoint_name: str
    target: str = 'linux/amd64'
    ttl_hours: int = 24
    workspace_path: str | None = None
    runner_enabled: bool = True


class EndpointInstallNodeRequest(BaseModel):
    method: str = 'auto'


class EndpointInstallHarnessRequest(BaseModel):
    image: str | None = None
    runtime: str = 'auto'


class EndpointUpdateRequest(BaseModel):
    package_url: str | None = None
    restart: bool = True


def create_endpoints_router(
    *,
    require_auth: Any,
    pac_version: str,
    config: Any,
    store: Any,
    save_config: Any,
    discover_host: Any,
    discover_containers: Any,
    ensure_source_library: Any,
    source_build_binary: Any,
    run_endpoint_maintenance: Any,
    issue_endpoint_certificate: Any,
    mint_endpoint_onboarding_token: Any,
    safe_runner_slug: Any,
    runtime_agent_state: Any,
    endpoint_default_workspace: Any,
    packages_for_tools: Any,
    normalise_endpoint_metadata: Any,
    refresh_local_runner_metadata: Any,
    source_build_blocker: Any,
    node_install_command: Any,
    install_pi_harness_command: Any,
    local_pi_harness_install_worker: Any,
    require_resource_access: Any,
) -> APIRouter:
    """Endpoint and runner routes extracted from the controller bootstrap file."""
    router = APIRouter()
    log = logging.getLogger("pac.endpoints")

    _issue_endpoint_certificate = issue_endpoint_certificate
    _mint_endpoint_onboarding_token = mint_endpoint_onboarding_token
    _safe_runner_slug = safe_runner_slug
    _runtime_agent_state = runtime_agent_state
    _endpoint_default_workspace = endpoint_default_workspace
    _packages_for_tools = packages_for_tools
    _normalise_endpoint_metadata = normalise_endpoint_metadata
    _refresh_local_runner_metadata = refresh_local_runner_metadata
    _source_build_blocker = source_build_blocker
    _node_install_command = node_install_command
    _install_pi_harness_command = install_pi_harness_command
    _local_pi_harness_install_worker = local_pi_harness_install_worker

    def _endpoint_os_family(runner: Runner) -> str:
        metadata = runner.metadata or {}
        values = [metadata.get('os_family'), metadata.get('os'), metadata.get('host_os'), metadata.get('platform'), metadata.get('onboarding_target'), *(runner.labels or [])]
        for value in values:
            text = str(value or '').lower()
            if 'windows' in text or text in {'win32', 'win64'}:
                return 'windows'
            if 'darwin' in text or 'macos' in text or text == 'mac':
                return 'darwin'
            if 'linux' in text:
                return 'linux'
        return 'unknown'

    def _default_host_shell_for_runner(runner: Runner) -> str:
        return 'powershell' if _endpoint_os_family(runner) == 'windows' else 'sh'

    @router.get('/v1/runners', response_model=list[Runner])
    @router.get('/v1/endpoints', response_model=list[Runner])
    def list_runners(_auth: Any = Depends(require_auth)) -> list[Runner]:
        require_resource_access(_auth, 'endpoint', '*', 'read')
        _refresh_local_runner_metadata(emit_event=False)
        return store.list_runners()


    @router.post('/v1/runners', response_model=Runner)
    @router.post('/v1/endpoints', response_model=Runner)
    def create_runner(payload: RunnerCreateRequest, _auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', '*', 'manage')
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
        ensure_endpoint_principal(store, runner)
        store.add_event(Event(session_id='system', type='runner_created', message=f'Endpoint {runner.name} added', data={'runner_id': runner.id}))
        return runner




    @router.put('/v1/runners/{runner_id}', response_model=Runner)
    @router.put('/v1/endpoints/{runner_id}', response_model=Runner)
    def update_runner(runner_id: str, payload: RunnerCreateRequest, _auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', runner_id, 'manage')
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
        ensure_endpoint_principal(store, runner)
        store.add_event(Event(session_id='system', type='endpoint_updated', message=f'Endpoint updated: {runner.name}', data={'runner_id': runner.id, 'agent_tools': runner.metadata.get('agent_tools', [])}))
        return runner

    @router.post('/v1/runners/register', response_model=Runner)
    @router.post('/v1/endpoints/register', response_model=Runner)
    def register_runner(payload: RunnerRegisterRequest, _auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', '*', 'execute')
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
        ensure_endpoint_principal(store, runner)
        store.add_event(Event(session_id='system', type='runner_registered', message=f'Endpoint {runner.name} registered', data={'runner_id': runner.id, 'labels': runner.labels, 'certificate_issued': bool(cert_result)}))
        return runner


    @router.get('/v1/runners/local/discover')
    @router.get('/v1/endpoints/local/discover')
    def local_discover(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'endpoint', 'local-PAC', 'read')
        return {'capabilities': discover_host(), 'containers': discover_containers()}


    @router.post('/v1/endpoints/onboarding-kit')
    def endpoint_onboarding_kit(payload: EndpointOnboardingRequest, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'endpoint', '*', 'manage')
        public_url = str(config.server.public_url or '').strip().rstrip('/')
        if not public_url:
            raise HTTPException(status_code=400, detail='Controller public_url is not configured')
        target = str(payload.target or 'linux/amd64').strip()
        ttl_hours = max(1, min(int(payload.ttl_hours or 24), 24 * 30))
        token, expires_at, token_kind = _mint_endpoint_onboarding_token(_auth, ttl_hours)
        endpoint_name = str(payload.endpoint_name or '').strip() or _safe_runner_slug(uuid.uuid4().hex[:8])
        workspace_path = str(payload.workspace_path or '').strip()
        runner_enabled = bool(payload.runner_enabled)
        endpoint_slug = re.sub(r'[^a-z0-9]+', '-', endpoint_name.lower()).strip('-') or 'endpoint'
        binary_name = f'pac-endpoint-{endpoint_slug}'
        build_result = source_build_binary(
            'binaries/pac-endpoint',
            targets=[target],
            runtime='auto',
            binary_name=binary_name,
            compiled_server_url=public_url,
            compiled_endpoint_name=endpoint_name,
            compiled_runner_enabled=runner_enabled,
            compiled_workspace_root=workspace_path or None,
        )
        artifact = next(iter(build_result.get('artifacts') or []), None)
        binary_filename = str((artifact or {}).get('name') or '').strip()
        download_url = f'{public_url}/v1/sources/binary-artifacts/pac-endpoint/{binary_filename}' if binary_filename else ''
        linux_path = '$HOME/.local/bin/pac-endpoint'
        linux_install = [
            'mkdir -p "$HOME/.local/bin"',
            f'curl -L -H "Authorization: Bearer {token}" "{download_url}" -o "{linux_path}"' if download_url else '# Build the pac-endpoint binary for this target first.',
            f'chmod +x "{linux_path}"',
            f'export PAC_TOKEN={shlex.quote(token)}',
        ]
        if workspace_path:
            linux_install.append(f'export PAC_WORKSPACE={shlex.quote(workspace_path)}')
        linux_install.append(f'"{linux_path}"')
        powershell_install = [
            '$ErrorActionPreference = "Stop"',
            '$dest = "$env:USERPROFILE\\pac-endpoint.exe"',
            f'Invoke-WebRequest -Headers @{{ Authorization = "Bearer {token}" }} -Uri "{download_url}" -OutFile $dest' if download_url else '# Build the pac-endpoint binary for this target first.',
            '$env:PAC_TOKEN = "' + token + '"',
            '$env:PAC_RUNNER_ENABLED = "true"',
        ]
        if workspace_path:
            powershell_install.append('$env:PAC_WORKSPACE = "' + workspace_path.replace('\\', '\\\\') + '"')
        powershell_install.extend([
            'Write-Host "Starting PAC Windows endpoint. Leave this window open, or wrap this command in a Windows Service/Scheduled Task."',
            '& $dest',
        ])
        return {
            'ok': True,
            'endpoint_name': endpoint_name,
            'target': target,
            'public_url': public_url,
            'token': token,
            'token_kind': token_kind,
            'expires_at': expires_at,
            'artifact': artifact,
            'build_result': build_result,
            'workspace_path': workspace_path or None,
            'runner_enabled': runner_enabled,
            'download_url': download_url or None,
            'artifact_missing': not bool(artifact),
            'build_hint': {
                'path': 'binaries/pac-endpoint',
                'targets': [target],
                'server_url': public_url,
                'binary_name': binary_name,
                'endpoint_name': endpoint_name,
                'runner_enabled': runner_enabled,
                'workspace_path': workspace_path or None,
            },
            'commands': {
                'linux': '\n'.join(linux_install),
                'powershell': '\n'.join(powershell_install),
            },
            'notes': [
                'The endpoint binary is preconfigured with the controller URL and endpoint name from this wizard.',
                'At install time you usually only need PAC_TOKEN. PAC_WORKSPACE remains optional as a host-specific override.',
                'Keep the process running on the endpoint to maintain heartbeats and receive jobs.',
                'On Windows, host jobs run through PowerShell by default and remain scoped to the selected endpoint workspace.',
                'Trusted workspaces can expose plugin and tool source live to containerized coding sessions.',
            ],
        }


    @router.post('/v1/runners/local', response_model=Runner)
    @router.post('/v1/endpoints/local', response_model=Runner)
    def add_local_runner(_auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', 'local-PAC', 'manage')
        """Add or refresh the PAC host as a first-class endpoint entry."""
        try:
            return _refresh_local_runner_metadata(emit_event=True)
        except Exception as exc:
            store.add_event(Event(session_id='system', type='local_endpoint_add_failed', message=f'Local endpoint could not be added: {exc}', data={'error': str(exc)}))
            raise HTTPException(status_code=500, detail=f'Local endpoint could not be added: {exc}')


    @router.get('/v1/runners/{runner_id}', response_model=Runner)
    @router.get('/v1/endpoints/{runner_id}', response_model=Runner)
    def get_runner(runner_id: str, _auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', runner_id, 'read')
        runner = store.get_runner(runner_id)
        if not runner:
            raise HTTPException(status_code=404, detail='Endpoint not found')
        return runner


    @router.post('/v1/runners/heartbeat', response_model=Runner)
    @router.post('/v1/endpoints/heartbeat', response_model=Runner)
    def runner_heartbeat(payload: RunnerHeartbeat, _auth: Any = Depends(require_auth)) -> Runner:
        require_resource_access(_auth, 'endpoint', payload.runner_id, 'execute')
        runner = store.get_runner(payload.runner_id)
        if not runner:
            raise HTTPException(status_code=404, detail='Endpoint not found')
        previous_status = runner.status
        previous_labels = list(runner.labels or [])
        previous_version = str(runner.metadata.get('runner_version') or runner.metadata.get('endpoint_version') or '')
        previous_capability_signature = stable_capability_signature(runner.capabilities)
        runner.status = payload.status
        runner.labels = payload.labels or runner.labels
        runner.capabilities = payload.capabilities
        runner.containers = payload.containers
        runner.metadata.update(payload.metadata)
        runner.metadata['runner_version'] = payload.version or runner.metadata.get('runner_version')
        runner.metadata['endpoint_version'] = payload.version or runner.metadata.get('endpoint_version')
        pi_container = runner.capabilities.get('pi_container') if isinstance(runner.capabilities, dict) else None
        advertised_runtime = ((payload.metadata or {}).get('agent_runtime') or {})
        pi_available = str(advertised_runtime.get('status') or '').lower() == 'ready'
        pi_image_present = bool((pi_container or {}).get('image_available') or (pi_container or {}).get('available'))
        runner.metadata['agent_runtime'] = _runtime_agent_state(
            'remote-runner',
            'ready' if pi_available else 'attention',
            'Endpoint runner heartbeat received.' if pi_available else (str(advertised_runtime.get('detail') or '').strip() or ((pi_container or {}).get('reason') or ('pi.dev image is installed, but the runtime is not ready on this endpoint.' if pi_image_present else 'pi.dev runtime image is not available on this endpoint.'))),
            pi_container_image=runner.metadata.get('pi_container_image'),
            pi_container=pi_container,
        )
        runner = _normalise_endpoint_metadata(runner, runner.metadata.get('agent_requested') or runner.metadata.get('agent_enabled', False))
        runner.last_seen_at = Event(session_id='system', type='noop', message='noop').created_at
        store.add_runner(runner)
        ensure_endpoint_principal(store, runner)
        current_version = str(runner.metadata.get('runner_version') or runner.metadata.get('endpoint_version') or '')
        current_capability_signature = stable_capability_signature(runner.capabilities)
        emit_heartbeat_events(
            store,
            runner=runner,
            previous_status=previous_status,
            previous_labels=previous_labels,
            previous_version=previous_version,
            previous_capability_signature=previous_capability_signature,
            current_version=current_version,
            current_capability_signature=current_capability_signature,
        )
        return runner


    @router.delete('/v1/runners/{runner_id}')
    @router.delete('/v1/endpoints/{runner_id}')
    def delete_runner(runner_id: str, _auth: Any = Depends(require_auth)) -> dict[str, str]:
        require_resource_access(_auth, 'endpoint', runner_id, 'manage')
        if runner_id == 'local-PAC':
            _refresh_local_runner_metadata(emit_event=False)
            raise HTTPException(status_code=400, detail='The local PAC endpoint is required by the controller pi.dev runtime and cannot be deleted.')
        if not store.delete_runner(runner_id):
            raise HTTPException(status_code=404, detail='Endpoint not found')
        retire_endpoint_principal(store, runner_id)
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




    @router.post('/v1/endpoints/{runner_id}/commands', response_model=RunnerJob)
    def queue_endpoint_command(runner_id: str, payload: RunnerJobCreate, _auth: Any = Depends(require_auth)) -> RunnerJob:
        require_resource_access(_auth, 'endpoint', runner_id, 'execute')
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
        log.info('endpoint command queued endpoint_id=%s job_id=%s mode=%s shell=%s', runner.id, job.id, job.execution_mode, job.metadata.get('shell'))
        return job




    @router.post('/v1/endpoints/{runner_id}/install-node', response_model=RunnerJob | dict[str, Any])
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



    @router.post('/v1/endpoints/{runner_id}/install-pi-harness', response_model=RunnerJob | dict[str, Any])
    @router.post('/v1/runners/{runner_id}/install-pi-harness', response_model=RunnerJob | dict[str, Any])
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


    @router.post('/v1/endpoints/{runner_id}/maintenance', response_model=RunnerJob | dict[str, Any])
    @router.post('/v1/runners/{runner_id}/maintenance', response_model=RunnerJob | dict[str, Any])
    def queue_endpoint_maintenance(runner_id: str, payload: EndpointMaintenanceRequest | None = None, _auth: Any = Depends(require_auth)) -> RunnerJob | dict[str, Any]:
        require_resource_access(_auth, 'endpoint', runner_id, 'manage')
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


    @router.post('/v1/endpoints/maintenance-all')
    def queue_all_endpoint_maintenance(payload: EndpointMaintenanceRequest | None = None, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'endpoint', '*', 'manage')
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



    @router.post('/v1/endpoints/{runner_id}/update', response_model=RunnerJob)
    @router.post('/v1/runners/{runner_id}/update', response_model=RunnerJob)
    def queue_endpoint_update(runner_id: str, payload: EndpointUpdateRequest | None = None, _auth: Any = Depends(require_auth)) -> RunnerJob:
        require_resource_access(_auth, 'endpoint', runner_id, 'manage')
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
            metadata={'operation': 'endpoint_update', 'package_url': package_url, 'restart': req.restart, 'target_version': pac_version},
        )
        endpoint.metadata['update_status'] = 'queued'
        endpoint.metadata['target_version'] = pac_version
        endpoint.touch()
        store.add_runner(endpoint)
        store.add_runner_job(job)
        store.add_event(Event(session_id='system', type='endpoint_update_queued', message=f'Endpoint update queued for {endpoint.name}', data={'endpoint_id': endpoint.id, 'job_id': job.id, 'target_version': pac_version, 'package_url': package_url}))
        return job

    @router.post('/v1/endpoints/update-all')
    def queue_all_endpoint_updates(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        require_resource_access(_auth, 'endpoint', '*', 'manage')
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
                metadata={'operation': 'endpoint_update', 'package_url': '/v1/admin/current-package', 'restart': True, 'target_version': pac_version},
            )
            endpoint.metadata['update_status'] = 'queued'
            endpoint.metadata['target_version'] = pac_version
            store.add_runner(endpoint)
            store.add_runner_job(job)
            queued.append({'id': endpoint.id, 'name': endpoint.name, 'job_id': job.id})
        store.add_event(Event(session_id='system', type='endpoint_update_all_queued', message=f'Queued endpoint updates: {len(queued)}', data={'queued': queued, 'skipped': skipped, 'target_version': pac_version}))
        return {'queued': queued, 'skipped': skipped, 'target_version': pac_version}

    @router.get('/v1/runner-jobs', response_model=list[RunnerJob])
    def list_runner_jobs(runner_id: str | None = None, status: str | None = None, _auth: Any = Depends(require_auth)) -> list[RunnerJob]:
        require_resource_access(_auth, 'endpoint', runner_id or '*', 'read')
        return store.list_runner_jobs(runner_id=runner_id, status=status)


    @router.post('/v1/runners/{runner_id}/jobs', response_model=RunnerJob)
    def create_runner_job(runner_id: str, payload: RunnerJobCreate, _auth: Any = Depends(require_auth)) -> RunnerJob:
        require_resource_access(_auth, 'endpoint', runner_id, 'execute')
        runner = store.get_runner(runner_id)
        if not runner:
            raise HTTPException(status_code=404, detail='Endpoint not found')
        if payload.execution_mode == 'host' and not runner.allow_host_execution:
            raise HTTPException(status_code=400, detail='Endpoint does not allow host execution')
        if payload.execution_mode in ('container', 'pi_container') and not runner.allow_container_execution:
            raise HTTPException(status_code=400, detail='Endpoint does not allow container execution')
        if payload.execution_mode == 'container' and not payload.container_image:
            raise HTTPException(status_code=400, detail='Container execution requires container_image')
        job_metadata = dict(payload.metadata or {})
        if payload.execution_mode == 'host' and job_metadata.get('shell') is None:
            job_metadata['shell'] = _default_host_shell_for_runner(runner)
        job_metadata.setdefault('endpoint_os_family', _endpoint_os_family(runner))
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
            metadata=job_metadata,
        )
        store.add_runner_job(job)
        store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type='runner_job_queued', message=payload.prompt, data={'runner_id': runner.id, 'runner_job_id': job.id, 'execution_mode': job.execution_mode, 'command': job.command, 'container_image': job.container_image}))
        return job


    @router.get('/v1/runners/{runner_id}/jobs/next', response_model=RunnerJob | None)
    @router.get('/v1/endpoints/{runner_id}/jobs/next', response_model=RunnerJob | None)
    def runner_next_job(runner_id: str, _auth: Any = Depends(require_auth)) -> RunnerJob | None:
        require_resource_access(_auth, 'endpoint', runner_id, 'execute')
        runner = store.get_runner(runner_id)
        if not runner:
            raise HTTPException(status_code=404, detail='Endpoint not found')
        job = store.claim_next_runner_job(runner_id)
        if job:
            store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type='runner_job_claimed', message=f'Endpoint {runner.name} claimed {job.id}', data={'runner_id': runner.id, 'runner_job_id': job.id}))
        return job


    @router.post('/v1/runner-jobs/{job_id}/log')
    def runner_job_log(job_id: str, payload: RunnerJobLog, _auth: None = Depends(require_auth)) -> dict[str, str]:
        job = store.get_runner_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail='Runner job not found')
        store.add_event(Event(session_id=job.session_id or 'system', task_id=job.task_id, type=f'runner_{payload.stream}', message=payload.message[-4000:], data={'runner_job_id': job.id, 'runner_id': job.runner_id}))
        return {'status': 'ok'}



    @router.get('/v1/runner-jobs/{job_id}')
    def get_runner_job_detail(job_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        job = store.get_runner_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail='Runner job not found')
        require_resource_access(_auth, 'endpoint', job.runner_id, 'read')
        events = []
        for event in store.list_recent_events(limit=250):
            data = event.data or {}
            if data.get('runner_job_id') == job.id:
                events.append(event.model_dump(mode='json'))
        events.reverse()
        endpoint = store.get_runner(job.runner_id)
        return {
            'job': job.model_dump(mode='json'),
            'endpoint': endpoint.model_dump(mode='json') if endpoint else None,
            'events': events,
        }

    @router.post('/v1/runner-jobs/{job_id}', response_model=RunnerJob)
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
        log.info('endpoint job status job_id=%s endpoint_id=%s status=%s exit_code=%s operation=%s', job.id, job.runner_id, status_value, job.exit_code, job.metadata.get('operation'))
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

    return router
