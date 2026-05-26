from __future__ import annotations

import json
import shutil
import socket
import os
import subprocess
from pathlib import Path
from typing import Any

from .platform_home import pacp_path
from .pi_dev_runtime import inspect_pi_container_image, pi_container_rebuild_state, pi_container_source_version


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 999, '', str(exc)


def _read_first(paths: list[str]) -> str | None:
    for item in paths:
        try:
            value = Path(item).read_text(encoding='utf-8', errors='ignore').strip()
            if value:
                return value
        except Exception:
            pass
    return None


def _read_mem_total() -> int | None:
    try:
        for line in Path('/proc/meminfo').read_text(encoding='utf-8', errors='ignore').splitlines():
            if line.startswith('MemTotal:'):
                return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _read_cpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        text = Path('/proc/cpuinfo').read_text(encoding='utf-8', errors='ignore')
        models = []
        processors = 0
        for line in text.splitlines():
            if line.startswith('processor'):
                processors += 1
            if line.lower().startswith('model name') or line.lower().startswith('hardware'):
                value = line.split(':', 1)[-1].strip()
                if value and value not in models:
                    models.append(value)
        if models:
            info['model'] = models[0]
        if processors:
            info['logical_cores'] = processors
    except Exception:
        pass
    if not info.get('logical_cores'):
        try:
            info['logical_cores'] = os.cpu_count() or None
        except Exception:
            pass
    return info


def _read_disk_total() -> int | None:
    try:
        return shutil.disk_usage('/').total
    except Exception:
        return None


def _read_os_info() -> dict[str, Any]:
    data: dict[str, Any] = {'platform': os.name}
    try:
        for line in Path('/etc/os-release').read_text(encoding='utf-8', errors='ignore').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                data[k.lower()] = v.strip().strip('"')
    except Exception:
        pass
    return data


def _parse_nvidia_smi(raw: str) -> list[dict[str, Any]]:
    devices = []
    for line in raw.splitlines():
        parts = [x.strip() for x in line.split(',')]
        if not parts or not parts[0]:
            continue
        item: dict[str, Any] = {'name': parts[0]}
        if len(parts) > 1:
            item['memory_total'] = parts[1]
        if len(parts) > 2:
            item['driver_version'] = parts[2]
        devices.append(item)
    return devices


def discover_host() -> dict[str, Any]:
    hardware = {
        'hostname': socket.gethostname(),
        'os': _read_os_info(),
        'cpu': _read_cpu_info(),
        'memory': {'total_bytes': _read_mem_total()},
        'disk': {'root_total_bytes': _read_disk_total(), 'total_bytes': _read_disk_total()},
    }
    pac_wrapper_path = pacp_path('bin', 'pac-endpoint')
    caps: dict[str, Any] = {
        'hostname': socket.gethostname(),
        'hardware': hardware,
        'cpu': hardware['cpu'],
        'memory': hardware['memory'],
        'disk': hardware['disk'],
        'tools': {},
        'container_runtimes': [],
        'gpu': {},
        'pi_container': {},
        'pac_wrapper': {
            'name': 'pac-endpoint',
            'path': str(pac_wrapper_path),
            'available': pac_wrapper_path.is_file() and os.access(pac_wrapper_path, os.X_OK),
            'reason': 'PAC wrapper is installed on the controller.' if pac_wrapper_path.is_file() else 'PAC wrapper binary is not installed yet under ~/.pacp/bin.',
        },
        'agent_requirements': {'node': False},
        'agent_runtime': {'available': False, 'requires': ['node', 'pac-wrapper'], 'reason': 'Node.js and the PAC wrapper are required before this endpoint can run pi.dev workloads.'},
        'command_channel': {'available': True, 'mode': 'controller-queued'},
    }
    for tool in ['git', 'python3', 'node', 'npm', 'npx', 'podman', 'docker', 'kubectl', 'oc', 'helm', 'kustomize', 'talosctl', 'nvidia-smi']:
        path = shutil.which(tool)
        caps['tools'][tool] = {'available': bool(path), 'path': path}
    for runtime in ['podman', 'docker']:
        if caps['tools'].get(runtime, {}).get('available'):
            caps['container_runtimes'].append(runtime)

    node_path = caps['tools'].get('node', {}).get('path')
    node_version = None
    if node_path:
        code, out, err = _run(['node', '--version'], timeout=3)
        node_version = out.strip() if code == 0 else None
    wrapper_ok = bool(caps.get('pac_wrapper', {}).get('available'))
    caps['agent_requirements'] = {'node': bool(node_path), 'node_path': node_path, 'node_version': node_version, 'pac_wrapper': wrapper_ok, 'pac_wrapper_path': str(pac_wrapper_path)}
    caps['agent_runtime'] = {
        'available': bool(node_path) and wrapper_ok,
        'requires': ['node', 'pac-wrapper'],
        'node_version': node_version,
        'pac_wrapper': caps.get('pac_wrapper'),
        'reason': 'Node.js and the PAC wrapper are available for pi.dev workloads.' if (node_path and wrapper_ok) else ('PAC wrapper is missing under ~/.pacp/bin.' if node_path else 'Node.js is required before this endpoint can run pi.dev through the PAC wrapper.'),
    }

    image = os.environ.get('PI_AGENT_PI_CONTAINER_IMAGE', 'localhost/pi-agent-harness:stage11')
    expected_pi_version = pi_container_source_version(Path(__file__).resolve().parents[2])
    caps['pi_container'] = {
        'image': image,
        'available': False,
        'image_available': False,
        'runtime': None,
        'source_version': expected_pi_version,
        'reason': 'No container runtime found. Install podman or docker on the endpoint.',
        'hint': 'The Pi agent harness image is built locally on each endpoint so it matches that machine and runtime.',
        'build_command': 'scripts/build-pi-container.sh localhost/pi-agent-harness:stage11',
        'source': 'containers/pi-agent-harness',
        'script': 'scripts/build-pi-container.sh',
        'source_hint': 'Open Sources to inspect or edit the build script and container source. Endpoints can receive these files from the PAC source library.',
    }
    if caps['container_runtimes']:
        caps['pi_container']['reason'] = f'Image is not present on this endpoint: {image}'
    for runtime in caps['container_runtimes']:
        image_info = inspect_pi_container_image(runtime, image)
        if image_info.get('available'):
            rebuild_state = pi_container_rebuild_state(image_info, expected_pi_version)
            caps['pi_container'] = {
                'image': image,
                'available': False,
                'image_available': True,
                'runtime': runtime,
                'reason': 'Pi agent harness image is installed on this endpoint, but the pi.dev runtime is not verified as running yet.',
                'hint': 'Start or bootstrap pi.dev before treating this endpoint as ready for harness-backed workloads.',
                'version': image_info.get('version'),
                'created': image_info.get('created'),
                'source_version': expected_pi_version,
                'rebuild_needed': rebuild_state.get('needs_rebuild'),
                'rebuild_reason': rebuild_state.get('reason'),
                'labels': image_info.get('labels') or {},
            }
            break
        caps['pi_container']['last_check'] = image_info.get('last_check') or {}
        caps['pi_container']['reason'] = image_info.get('reason') or caps['pi_container']['reason']

    if caps['tools']['nvidia-smi']['available']:
        code, out, err = _run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'], timeout=5)
        raw = out.strip() if code == 0 else err.strip()
        caps['gpu'] = {'available': code == 0, 'raw': raw, 'devices': _parse_nvidia_smi(raw) if code == 0 else []}
        caps['hardware']['gpu'] = caps['gpu']
    else:
        caps['gpu'] = {'available': False, 'devices': []}
        caps['hardware']['gpu'] = caps['gpu']
    return caps


def discover_containers() -> list[dict[str, Any]]:
    for runtime in ['podman', 'docker']:
        if not shutil.which(runtime):
            continue
        code, out, _ = _run([runtime, 'ps', '--format', 'json'], timeout=8)
        if code != 0 or not out.strip():
            continue
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            return [{'runtime': runtime, **item} for item in data]
        except Exception:
            # docker can output one json object per line with some versions/templates
            rows = []
            for line in out.splitlines():
                try:
                    rows.append({'runtime': runtime, **json.loads(line)})
                except Exception:
                    pass
            if rows:
                return rows
    return []


def safe_run_command(command: str, cwd: str | None = None) -> dict[str, Any]:
    workdir = Path(cwd or '.').resolve()
    p = subprocess.run(command, shell=True, cwd=workdir, capture_output=True, text=True, check=False)
    return {'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr, 'cwd': str(workdir)}
