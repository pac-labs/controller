from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pi_agent_platform.core.runner_discovery import discover_containers, discover_host
from pi_agent_platform.core.maintenance import run_endpoint_maintenance
from pi_agent_platform.core.platform_home import pacp_path

PAC_ENDPOINT_VERSION = '1.0.79'
DEFAULT_PI_IMAGE = os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')


def _safe_cert_name(name: str) -> str:
    cleaned = ''.join(c if c.isalnum() or c in ('-', '_', '.') else '-' for c in name.strip())
    return cleaned[:80] or 'endpoint'


def ensure_endpoint_certificate(base: str, token: str | None, name: str, tls_dir: str | None = None) -> dict[str, Any] | None:
    """Request a PAC-CA signed endpoint cert and store it locally.

    The endpoint creates its own private key and CSR; only the CSR is sent to
    the controller. The returned cert and CA are saved under the runner TLS dir.
    """
    if not shutil.which('openssl'):
        print('endpoint certificate skipped: openssl not found')
        return None
    cert_name = _safe_cert_name(name)
    root = Path(tls_dir or str(pacp_path('runner', 'tls'))) / cert_name
    root.mkdir(parents=True, exist_ok=True)
    key = root / f'{cert_name}.key'
    csr = root / f'{cert_name}.csr'
    cert = root / f'{cert_name}.crt'
    ca = root / 'pac-root-ca.crt'
    if not key.exists() or not csr.exists():
        proc = subprocess.run([
            'openssl', 'req', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(key), '-out', str(csr),
            '-subj', f'/CN={cert_name}/O=PAC Endpoint/C=NL',
        ], text=True, capture_output=True, timeout=20)
        if proc.returncode != 0:
            print(f'endpoint certificate CSR failed: {(proc.stderr or proc.stdout)[-1000:]}')
            return None
        try:
            key.chmod(0o600)
        except Exception:
            pass
    payload = {
        'name': cert_name,
        'csr_pem': csr.read_text(encoding='utf-8'),
        'sans': [cert_name, f'{cert_name}.local'],
    }
    result = post_json(f'{base}/v1/tls/issue-endpoint-cert', payload, token)
    cert.write_text(result['cert_pem'], encoding='utf-8')
    ca.write_text(result['ca_pem'], encoding='utf-8')
    print(f'endpoint certificate saved: {cert}')
    return {'cert_file': str(cert), 'key_file': str(key), 'ca_file': str(ca), 'name': cert_name}


def request_json(method: str, url: str, payload: dict | None = None, token: str | None = None, timeout: int = 30) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else None


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    return request_json('POST', url, payload, token)


def put_bytes(url: str, data: bytes, token: str | None = None, timeout: int = 60) -> Any:
    headers = {'Content-Type': 'application/octet-stream'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=data, headers=headers, method='PUT')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else None


def upload_workspace_artifacts(job: dict, base: str, token: str | None) -> None:
    workspace = Path(job.get('workspace_path') or str(pacp_path('runner', 'workspaces') / job['id']))
    candidates = [workspace / 'artifacts', workspace / 'pi-agent-artifacts']
    candidates = [p for p in candidates if p.exists()]
    explicit = job.get('metadata', {}).get('artifact_paths') or []
    for item in explicit:
        p = (workspace / str(item)).resolve()
        try:
            if workspace.resolve() in p.parents or workspace.resolve() == p:
                candidates.append(p)
        except Exception:
            pass
    if not candidates:
        return
    bundle = Path('/tmp') / f"pi-agent-artifacts-{job['id']}.tar.gz"
    with tarfile.open(bundle, 'w:gz') as tar:
        for candidate in candidates:
            if candidate.exists():
                tar.add(candidate, arcname=candidate.name)
    session_id = job.get('session_id') or 'runner'
    task_id = job.get('task_id') or 'session'
    target = f"{base}/v1/artifacts/{urllib.parse.quote(session_id)}/{urllib.parse.quote(task_id)}/runner-{job['id']}-artifacts.tar.gz"
    put_bytes(target, bundle.read_bytes(), token)
    log(base, token, job['id'], 'system', f'Uploaded artifact bundle: {bundle.name}')


def log(base: str, token: str | None, job_id: str, stream: str, message: str) -> None:
    try:
        post_json(f'{base}/v1/runner-jobs/{job_id}/log', {'stream': stream, 'message': message}, token)
    except Exception:
        pass


def update_job(base: str, token: str | None, job_id: str, status: str, **kwargs: Any) -> None:
    payload = {'status': status, **kwargs}
    post_json(f'{base}/v1/runner-jobs/{job_id}', payload, token)


def choose_runtime(preferred: str) -> str:
    if preferred in ('podman', 'docker') and shutil.which(preferred):
        return preferred
    for candidate in ('podman', 'docker'):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError('No container runtime found. Install podman or docker, or use execution_mode=host.')


def run_process(command: str, cwd: str | None, env: dict[str, str], base: str, token: str | None, job_id: str, timeout: int) -> tuple[int, str]:
    proc = subprocess.Popen(
        command,
        cwd=cwd or None,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, **env},
        bufsize=1,
    )
    output: list[str] = []
    start = time.time()
    assert proc.stdout is not None
    while True:
        if time.time() - start > timeout:
            proc.kill()
            raise TimeoutError(f'Job timed out after {timeout}s')
        line = proc.stdout.readline()
        if line:
            output.append(line)
            log(base, token, job_id, 'stdout', line.rstrip())
        elif proc.poll() is not None:
            rest = proc.stdout.read()
            if rest:
                output.append(rest)
                log(base, token, job_id, 'stdout', rest[-4000:])
            break
        else:
            time.sleep(0.05)
    return int(proc.returncode or 0), ''.join(output)

def run_host_job(job: dict, base: str, token: str | None, timeout: int) -> tuple[int, str]:
    command = job.get('command') or 'pwd && ls -la'
    workspace = job.get('workspace_path')
    if workspace:
        Path(workspace).mkdir(parents=True, exist_ok=True)
    return run_process(command, workspace, {'PI_AGENT_RUNNER_JOB_ID': job['id'], 'PI_AGENT_EXECUTION_MODE': 'host'}, base, token, job['id'], timeout)


def run_container_job(job: dict, base: str, token: str | None, timeout: int) -> tuple[int, str]:
    image = job.get('container_image')
    if not image:
        raise RuntimeError('Container job requires container_image')
    runtime = choose_runtime(job.get('container_runtime') or 'auto')
    command = job.get('command') or 'pwd && ls -la'
    workspace = job.get('workspace_path') or str(pacp_path('runner', 'workspaces') / job['id'])
    Path(workspace).mkdir(parents=True, exist_ok=True)
    # Docker/Podman command uses /workspace as the working dir.
    quoted_cmd = command.replace('"', '\\"')
    run_cmd = (
        f'{runtime} run --rm '
        f'-e PI_AGENT_RUNNER_JOB_ID={job["id"]} '
        f'-e PI_AGENT_EXECUTION_MODE=container '
        f'-v {workspace}:/workspace:Z '
        f'-w /workspace '
        f'{image} /bin/sh -lc "{quoted_cmd}"'
    )
    log(base, token, job['id'], 'system', f'Running container job with {runtime}: {image}')
    return run_process(run_cmd, None, {}, base, token, job['id'], timeout)



def shell_quote_single(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def run_pi_container_job(job: dict, base: str, token: str | None, timeout: int) -> tuple[int, str]:
    """Run pi.dev inside a disposable container.

    The container image is expected to provide /usr/local/bin/pi-agent-entrypoint.
    The runner passes the prompt via PI_AGENT_TASK so long prompts do not break
    shell quoting or process argv limits as quickly.
    """
    runtime = choose_runtime(job.get('container_runtime') or 'auto')
    image = job.get('container_image') or DEFAULT_PI_IMAGE
    prompt = job.get('prompt') or job.get('command') or 'Inspect the workspace.'
    workspace = job.get('workspace_path') or str(pacp_path('runner', 'workspaces') / job['id'])
    Path(workspace).mkdir(parents=True, exist_ok=True)
    artifacts = Path(workspace) / 'pi-agent-artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)

    env_parts = [
        f'-e PI_AGENT_RUNNER_JOB_ID={shell_quote_single(job["id"])}',
        f'-e PI_AGENT_EXECUTION_MODE=pi_container',
        f'-e PI_AGENT_TASK={shell_quote_single(prompt)}',
        f'-e PI_AGENT_MODEL={shell_quote_single(str(job.get("metadata", {}).get("model") or ""))}',
        f'-e PI_AGENT_PERMISSION_PROFILE={shell_quote_single(str(job.get("metadata", {}).get("permission_profile") or ""))}',
    ]
    # Best effort: forward common model/provider keys to the Pi container if the runner has them.
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'LMSTUDIO_BASE_URL', 'OLLAMA_BASE_URL', 'OPENAI_BASE_URL'):
        if os.environ.get(key):
            env_parts.append(f'-e {key}={shell_quote_single(os.environ[key])}')

    network_flag = ''
    permission = str(job.get('metadata', {}).get('permission_profile') or '')
    if permission not in ('full-control', 'full-control-coder') and os.environ.get('PI_AGENT_DISABLE_NETWORK_BY_DEFAULT') == '1':
        network_flag = '--network none '

    cmd = (
        f'{runtime} run --rm '
        f'--name pi-agent-job-{job["id"]} '
        f'{network_flag}'
        f'{" ".join(env_parts)} '
        f'-v {shell_quote_single(workspace)}:/workspace:Z '
        f'-w /workspace '
        f'{shell_quote_single(image)}'
    )
    log(base, token, job['id'], 'system', f'Running pi.dev container with {runtime}: {image}')
    return run_process(cmd, None, {}, base, token, job['id'], timeout)



def download_bytes(url: str, token: str | None = None, timeout: int = 300) -> bytes:
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def safe_zip_members(zf: zipfile.ZipFile) -> None:
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if not name or name.startswith('/') or name.startswith('../') or '/../' in name:
            raise RuntimeError(f'Unsafe zip member path: {info.filename}')


def find_package_root(extract_dir: Path) -> Path:
    if (extract_dir / 'pyproject.toml').is_file() and (extract_dir / 'pi_agent_platform').is_dir():
        return extract_dir
    for candidate in extract_dir.iterdir():
        if candidate.is_dir() and (candidate / 'pyproject.toml').is_file() and (candidate / 'pi_agent_platform').is_dir():
            return candidate
    raise RuntimeError('Downloaded package does not contain pyproject.toml and pi_agent_platform/')


def copy_package_tree(src: Path, dst: Path) -> list[str]:
    entries = [
        'README.md', 'requirements.txt', 'pyproject.toml', '.gitignore',
        'pi_agent_platform', 'config', 'scripts', 'deploy', 'containers', 'docs', 'tests', 'vscode-extension',
        'docs-zed-mcp-example.json', 'install.sh', 'VERSION', 'VERSION_CURRENT.md', 'mcp',
    ]
    entries += [p.name for p in src.glob('STAGE*_CHANGELOG.md')]
    copied: list[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    for entry in dict.fromkeys(entries):
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
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc', '.git'))
        else:
            shutil.copy2(source, target)
        copied.append(entry)
    return copied


def apply_endpoint_update(job: dict, base: str, token: str | None, timeout: int) -> tuple[int, str]:
    metadata = job.get('metadata') or {}
    package_url = metadata.get('package_url') or '/v1/admin/current-package'
    if package_url.startswith('/'):
        package_url = base.rstrip('/') + package_url
    log(base, token, job['id'], 'system', f'Downloading PAC endpoint update package: {package_url}')
    data = download_bytes(package_url, token=token, timeout=min(max(timeout, 60), 600))
    pacp_home = Path(os.environ.get('PACP_HOME', str(Path.home() / '.pacp'))).expanduser()
    app_dir = Path(os.environ.get('PACP_APP_DIR', str(pacp_home / 'app'))).expanduser()
    updates_dir = pacp_home / 'updates' / 'endpoint'
    updates_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    zip_path = updates_dir / f'endpoint-update-{stamp}.zip'
    zip_path.write_bytes(data)
    extract_dir = updates_dir / f'extracted-{stamp}'
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        safe_zip_members(zf)
        zf.extractall(extract_dir)
    package_root = find_package_root(extract_dir)
    backup_dir = updates_dir / f'backup-app-{stamp}'
    if app_dir.exists():
        shutil.copytree(app_dir, backup_dir, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc', '.git'))
    copied = copy_package_tree(package_root, app_dir)
    log(base, token, job['id'], 'system', f'Copied update into {app_dir}: {", ".join(copied)}')
    venv_python = app_dir / '.venv' / 'bin' / 'python'
    if venv_python.exists():
        code, output = run_process(f'{venv_python} -m pip install -e {app_dir}', str(app_dir), {}, base, token, job['id'], timeout)
        if code != 0:
            return code, output
    marker = pacp_home / 'run' / 'endpoint-restart-required'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f'Endpoint update applied at {stamp}\nsource={zip_path}\nbackup={backup_dir}\n', encoding='utf-8')
    if metadata.get('restart'):
        log(base, token, job['id'], 'system', 'Update applied. systemd should restart this endpoint after job completion if service policy is configured.')
    return 0, f'Endpoint update installed. app_dir={app_dir} backup={backup_dir} restart_required={bool(metadata.get("restart"))}'

def execute_job(job: dict, base: str, token: str | None, timeout: int) -> None:
    update_job(base, token, job['id'], 'running')
    try:
        operation = (job.get('metadata') or {}).get('operation')
        if operation == 'endpoint_update':
            code, output = apply_endpoint_update(job, base, token, timeout)
        elif operation == 'endpoint_maintenance':
            metadata = job.get('metadata') or {}
            result = run_endpoint_maintenance(
                max_age_hours=int(metadata.get('max_age_hours') or 24),
                dry_run=bool(metadata.get('dry_run') or False),
                remove_containers=bool(metadata.get('remove_containers', True)),
                remove_workspaces=bool(metadata.get('remove_workspaces', True)),
                remove_temp_artifacts=bool(metadata.get('remove_temp_artifacts', True)),
                prune_images=bool(metadata.get('prune_images') or False),
            )
            output = json.dumps(result, indent=2)
            log(base, token, job['id'], 'system', f'Endpoint maintenance completed: {result.get("summary")}')
            code = 0
        else:
            mode = job.get('execution_mode')
            if mode == 'container':
                code, output = run_container_job(job, base, token, timeout)
            elif mode == 'pi_container':
                code, output = run_pi_container_job(job, base, token, timeout)
            else:
                code, output = run_host_job(job, base, token, timeout)
        try:
            upload_workspace_artifacts(job, base, token)
        except Exception as art_exc:
            log(base, token, job['id'], 'system', f'Artifact upload skipped/failed: {art_exc}')
        update_job(base, token, job['id'], 'completed' if code == 0 else 'failed', output=output[-20000:], exit_code=code, error=None if code == 0 else f'Command exited with {code}')
    except Exception as exc:
        log(base, token, job['id'], 'system', f'Job failed: {exc}')
        update_job(base, token, job['id'], 'failed', error=str(exc), exit_code=1)


def main() -> None:
    parser = argparse.ArgumentParser(description='PAC endpoint service')
    parser.add_argument('--control-plane', '--PAC', dest='control_plane', required=True)
    parser.add_argument('--token', default=None)
    parser.add_argument('--name', required=True)
    parser.add_argument('--labels', default='linux,host-runner')
    parser.add_argument('--interval', type=int, default=5)
    parser.add_argument('--heartbeat-interval', type=int, default=20)
    parser.add_argument('--runner-id', default=None)
    parser.add_argument('--workdir', default=str(pacp_path('runner', 'workspaces')))
    parser.add_argument('--job-timeout', type=int, default=3600)
    parser.add_argument('--disable-host-execution', action='store_true')
    parser.add_argument('--disable-container-execution', action='store_true')
    parser.add_argument('--agent-enabled', action='store_true', help='Request agent workload enablement. Requires Node.js on the endpoint.')
    parser.add_argument('--pi-container-image', default=DEFAULT_PI_IMAGE)
    parser.add_argument('--tls-dir', default=None)
    parser.add_argument('--no-request-certificate', action='store_true', help='Do not request a PAC-CA signed endpoint certificate during registration')
    args = parser.parse_args()
    os.environ['PI_AGENT_PI_CONTAINER_IMAGE'] = args.pi_container_image

    base = args.control_plane.rstrip('/')
    labels = [x.strip() for x in args.labels.split(',') if x.strip()]
    runner_id = args.runner_id
    Path(args.workdir).mkdir(parents=True, exist_ok=True)

    if not runner_id:
        payload = {
            'name': args.name,
            'labels': labels,
            'allow_host_execution': not args.disable_host_execution,
            'allow_container_execution': not args.disable_container_execution,
            'agent_enabled': args.agent_enabled,
            'metadata': {'registered_by': 'pi-agent-runner', 'workdir': args.workdir, 'pi_container_image': args.pi_container_image, 'agent_requested': args.agent_enabled},
        }
        result = post_json(f'{base}/v1/runners/register', payload, args.token)
        runner_id = result['id']
        print(f'Registered runner: {runner_id}')
        if not args.no_request_certificate:
            try:
                cert_info = ensure_endpoint_certificate(base, args.token, args.name, args.tls_dir)
                if cert_info:
                    print(f"Registered endpoint certificate: {cert_info['cert_file']}")
            except Exception as cert_exc:
                print(f'endpoint certificate request failed: {cert_exc}')

    last_heartbeat = 0.0
    while True:
        try:
            now = time.time()
            if now - last_heartbeat >= args.heartbeat_interval:
                hb = {
                    'runner_id': runner_id,
                    'status': 'online',
                    'version': PAC_ENDPOINT_VERSION,
                    'labels': labels,
                    'capabilities': discover_host(),
                    'containers': discover_containers(),
                    'metadata': {'workdir': args.workdir, 'pi_container_image': args.pi_container_image, 'agent_requested': args.agent_enabled, 'endpoint_role': 'remote-execution-environment', 'command_channel': {'mode': 'controller-queued', 'can_send': True, 'can_receive': True}},
                }
                post_json(f'{base}/v1/runners/heartbeat', hb, args.token)
                last_heartbeat = now
                print(f'heartbeat sent for {runner_id}')

            job = request_json('GET', f'{base}/v1/runners/{runner_id}/jobs/next', token=args.token, timeout=20)
            if job:
                print(f"claimed job {job['id']} mode={job.get('execution_mode')}")
                execute_job(job, base, args.token, args.job_timeout)
            else:
                time.sleep(args.interval)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            print(f'runner loop error: {exc}')
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
