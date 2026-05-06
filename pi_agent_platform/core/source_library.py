from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_home import pacp_path

SOURCE_ROOT = pacp_path('sources')
_ALLOWED_TOP_LEVEL = {'scripts', 'containers', 'plugins', 'docs', 'binaries'}


def packaged_root() -> Path:
    return Path(__file__).resolve().parents[2]


def source_root() -> Path:
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    return SOURCE_ROOT


def _safe_rel(path: str | Path = '') -> Path:
    rel = Path(str(path).strip().lstrip('/'))
    if str(rel) in ('', '.'):
        return Path('')
    if any(part in ('..', '') for part in rel.parts):
        raise ValueError('Invalid source path')
    if rel.parts[0] not in _ALLOWED_TOP_LEVEL:
        raise ValueError('Source path must be under scripts, containers, plugins, docs, or binaries')
    return rel


def safe_source_path(path: str | Path = '') -> Path:
    root = source_root().resolve()
    rel = _safe_rel(path)
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError('Source path escapes source library')
    return target


def _copy_default_file(src: Path, dst: Path) -> bool:
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_default_tree(src: Path, dst: Path) -> bool:
    changed = False
    if not src.exists():
        return False
    for item in src.rglob('*'):
        if item.is_file():
            rel = item.relative_to(src)
            changed = _copy_default_file(item, dst / rel) or changed
    return changed


def ensure_source_library() -> dict[str, Any]:
    root = source_root()
    pkg = packaged_root()
    changed = False
    for dirname in sorted(_ALLOWED_TOP_LEVEL):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    changed = _copy_default_tree(pkg / 'scripts', root / 'scripts') or changed
    changed = _copy_default_tree(pkg / 'containers' / 'pi-agent-harness', root / 'containers' / 'pi-agent-harness') or changed
    changed = _copy_default_tree(pkg / 'binaries', root / 'binaries') or changed
    # Keep the controller-provided build source folders present even on upgraded
    # systems where the source library was created before binary sources existed.
    for binary_dir in ('pac-endpoint', 'pac-endpoint-runner', 'pac-agent', 'zed-binary'):
        changed = _copy_default_tree(pkg / 'binaries' / binary_dir, root / 'binaries' / binary_dir) or changed
    changed = _copy_default_tree(pkg / 'docs', root / 'docs') or changed
    changed = _copy_default_file(pkg / 'SOURCE_VERSIONS.md', root / 'docs' / 'SOURCE_VERSIONS.md') or changed
    readme = root / 'README.md'
    if not readme.exists():
        readme.write_text(
            '# PAC source library\n\n'
            'Files in this library are stored by the PAC controller and can be used by endpoints.\n\n'
            '- `scripts/` contains scripts PAC or endpoints can execute.\n'
            '- `containers/` contains container build sources.\n'
            '- `plugins/` contains agent skills, scripts and documentation.\n'
            '- `docs/` contains supporting documentation.\n- `binaries/` contains source folders that build endpoint/client binaries.\n',
            encoding='utf-8',
        )
        changed = True
    return {'root': str(root), 'changed': changed, 'top_level': sorted(_ALLOWED_TOP_LEVEL)}



_FEATURE_TOP_LEVEL = {'plugins', 'containers', 'binaries', 'scripts', 'docs'}


def _is_ignored_pack_path(path: Path) -> bool:
    return any(part.startswith('.') or part in {'__MACOSX', '__pycache__', 'node_modules', '.git'} for part in path.parts)


def _read_component_metadata(folder: Path, rel: Path) -> dict[str, Any] | None:
    for name in ('pac-component.json', 'PAC_COMPONENT.json', 'component.json'):
        candidate = folder / name
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        meta = {k: v for k, v in data.items() if k in {'id', 'title', 'description', 'kind', 'maintainers', 'repository', 'homepage', 'license', 'tags', 'entrypoint', 'runtime', 'version'}}
        meta.setdefault('id', str(rel).replace('\\', '/'))
        meta.setdefault('title', folder.name.replace('-', ' ').title())
        return meta
    return None


def _read_version_file(folder: Path) -> str | None:
    for name in ('VERSION', 'version.txt', 'VERSION.txt'):
        candidate = folder / name
        if candidate.is_file():
            value = candidate.read_text(encoding='utf-8', errors='replace').strip()
            if value:
                return value.splitlines()[0].strip()
    return None


def _pack_members(zip_path: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(zip_path) as zf:
        return [info for info in zf.infolist() if not info.is_dir()]


def _normal_pack_rel(raw: str) -> Path | None:
    raw = raw.replace('\\', '/').lstrip('/')
    parts = [p for p in raw.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        return None
    while parts and parts[0] not in _FEATURE_TOP_LEVEL:
        # Allow zips with one wrapping directory, for example pac-feature-pack/plugins/foo/...
        if len(parts) == 1:
            return None
        parts = parts[1:]
    if not parts or parts[0] not in _FEATURE_TOP_LEVEL:
        return None
    rel = Path(*parts)
    if _is_ignored_pack_path(rel):
        return None
    return rel


def _component_key(rel: Path) -> tuple[str, str] | None:
    if not rel.parts or rel.parts[0] not in _FEATURE_TOP_LEVEL:
        return None
    if len(rel.parts) >= 2 and rel.parts[0] in {'plugins', 'containers', 'binaries'}:
        return (rel.parts[0], rel.parts[1])
    return (rel.parts[0], rel.parts[0])




def _read_zip_text(zf: zipfile.ZipFile, name: str) -> str | None:
    try:
        return zf.read(name).decode('utf-8', errors='replace').strip()
    except Exception:
        return None




def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _read_zip_json(zf: zipfile.ZipFile, name: str) -> Any | None:
    text = _read_zip_text(zf, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_change_lines(text: str) -> list[str]:
    changes: list[str] = []
    for raw in text.splitlines()[1:]:
        line = raw.strip()
        if line.startswith('- '):
            changes.append(line[2:].strip())
        elif line and changes and not re.match(r'^v?\d+\.\d+\.\d+', line, re.I):
            changes[-1] += ' ' + line
    return [change for change in changes if change]


def _read_package_changelog(zf: zipfile.ZipFile, package_root: str, files: list[str], current: str | None, target: str | None) -> dict[str, Any]:
    prefix = package_root
    candidates = [prefix + 'PAC_CHANGELOG.json', prefix + 'UPDATE_CHANGELOG.json', prefix + 'CHANGELOG.json']
    entries: list[dict[str, Any]] = []
    source = None
    for candidate in candidates:
        data = _read_zip_json(zf, candidate)
        if isinstance(data, dict):
            source = candidate[len(prefix):] if candidate.startswith(prefix) else candidate
            raw_entries = data.get('entries') or data.get('versions') or []
            if isinstance(raw_entries, dict):
                raw_entries = [{'version': version, **(record if isinstance(record, dict) else {'changes': record})} for version, record in raw_entries.items()]
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                version = str(entry.get('version') or '').strip()
                if not version:
                    continue
                changes = entry.get('changes') or entry.get('items') or []
                if isinstance(changes, str):
                    changes = _extract_change_lines(changes) or [changes.strip()]
                if not isinstance(changes, list):
                    changes = [str(changes)]
                entries.append({'version': version, 'title': entry.get('title') or f'PAC v{version}', 'changes': [str(c).strip() for c in changes if str(c).strip()]})
            break
    if not entries:
        changed_files = [name for name in files if name.startswith(prefix + 'changed_') and name.endswith('.txt')]
        for name in sorted(changed_files):
            match = re.search(r'(\d+\.\d+\.\d+)', name)
            if not match:
                continue
            version = match.group(1)
            text = _read_zip_text(zf, name) or ''
            entries.append({'version': version, 'title': f'PAC v{version}', 'changes': _extract_change_lines(text) or [text.strip()]})
        if entries:
            source = 'changed_*.txt'
    current_tuple = _version_tuple(current)
    target_tuple = _version_tuple(target)
    delta = []
    for entry in entries:
        version_tuple = _version_tuple(entry.get('version'))
        if not version_tuple:
            continue
        if current_tuple and version_tuple <= current_tuple:
            continue
        if target_tuple and version_tuple > target_tuple:
            continue
        delta.append(entry)
    delta.sort(key=lambda e: _version_tuple(e.get('version')) or (0, 0, 0))
    return {'source': source, 'entries': entries, 'delta': delta, 'delta_count': len(delta)}

def _is_pac_app_package(zip_path: str | Path) -> dict[str, Any] | None:
    path = Path(zip_path)
    try:
        with zipfile.ZipFile(path) as zf:
            files = [info.filename.replace('\\', '/').lstrip('/') for info in zf.infolist() if not info.is_dir()]
            roots = ['']
            top_dirs = sorted({f.split('/', 1)[0] for f in files if '/' in f})
            roots.extend([d + '/' for d in top_dirs])
            package_root = None
            for root in roots:
                if (root + 'pyproject.toml') in files and any(f.startswith(root + 'pi_agent_platform/') for f in files):
                    package_root = root
                    break
            if package_root is None:
                return None
            version = None
            for name in (package_root + 'VERSION', package_root + 'VERSION_CURRENT.md'):
                txt = _read_zip_text(zf, name)
                if txt:
                    m = re.search(r'(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)', txt)
                    version = m.group(1) if m else txt.splitlines()[0].strip()
                    break
            current = _packaged_version()
            target_version = version or 'unknown'
            changelog = _read_package_changelog(zf, package_root, files, current, target_version)
            files_count = sum(1 for f in files if f.startswith(package_root))
            return {
                'ok': True,
                'package_type': 'pac_app_update',
                'filename': path.name,
                'root_version': target_version,
                'target_version': target_version,
                'current_version': current,
                'package_root': package_root.rstrip('/') or '.',
                'files': files_count,
                'changelog': changelog,
                'changes': changelog.get('delta', []),
                'components': [{
                    'kind': 'pac-app',
                    'name': 'PAC application',
                    'path': '.',
                    'files': files_count,
                    'bytes': path.stat().st_size if path.exists() else 0,
                    'from_version': current,
                    'to_version': version or 'unknown',
                    'status': 'update',
                }],
                'component_count': 1,
                'summary': 'PAC application patch/full package',
            }
    except zipfile.BadZipFile:
        return None

def inspect_feature_pack(zip_path: str | Path) -> dict[str, Any]:
    ensure_source_library()
    path = Path(zip_path)
    if not zipfile.is_zipfile(path):
        raise ValueError('Feature update must be a .zip file')
    app_package = _is_pac_app_package(path)
    if app_package:
        return app_package
    temp = Path(tempfile.mkdtemp(prefix='pac-feature-pack-inspect-'))
    try:
        components: dict[tuple[str, str], dict[str, Any]] = {}
        root_version: str | None = None
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = _normal_pack_rel(info.filename)
                raw_parts = Path(info.filename.replace('\\', '/')).parts
                if Path(info.filename).name == 'VERSION' and len(raw_parts) <= 2:
                    try:
                        root_version = zf.read(info.filename).decode('utf-8', errors='replace').strip().splitlines()[0]
                    except Exception:
                        pass
                if rel is None:
                    continue
                key = _component_key(rel)
                if not key:
                    continue
                top, name = key
                record = components.setdefault(key, {'kind': top, 'name': name, 'path': f'{top}/{name}' if top in {'plugins','containers','binaries'} else top, 'files': 0, 'bytes': 0, 'from_version': None, 'to_version': None, 'status': 'new'})
                record['files'] += 1
                record['bytes'] += int(info.file_size or 0)
                if rel.name in {'VERSION', 'version.txt', 'VERSION.txt'}:
                    try:
                        value = zf.read(info.filename).decode('utf-8', errors='replace').strip().splitlines()[0]
                        if value:
                            record['to_version'] = value
                    except Exception:
                        pass
        for record in components.values():
            target = source_root() / record['path']
            record['from_version'] = _read_version_file(target) if target.exists() else None
            record['to_version'] = record.get('to_version') or root_version or _packaged_version()
            record['status'] = 'update' if target.exists() else 'new'
        return {'ok': True, 'filename': path.name, 'components': sorted(components.values(), key=lambda r: (r['kind'], r['name'])), 'component_count': len(components), 'root_version': root_version or _packaged_version()}
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def apply_feature_pack(zip_path: str | Path) -> dict[str, Any]:
    ensure_source_library()
    path = Path(zip_path)
    preview = inspect_feature_pack(path)
    if preview.get('package_type') == 'pac_app_update':
        raise ValueError('PAC app patches must be applied through the PAC version updater, not the source-folder updater.')
    if not preview.get('components'):
        raise ValueError('Feature pack contains no supported source folders. Expected plugins/, containers/, binaries/, scripts/, or docs/.')
    written: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _normal_pack_rel(info.filename)
            if rel is None:
                continue
            target = safe_source_path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, 'r') as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            written.append({'path': str(rel), 'size': target.stat().st_size})
    # Every updated component should expose a VERSION at its root for future previews.
    for component in preview['components']:
        root = safe_source_path(component['path'])
        if root.is_dir():
            version = component.get('to_version') or preview.get('root_version') or _packaged_version()
            vf = root / 'VERSION'
            vf.write_text(str(version).strip() + '\n', encoding='utf-8')
            if not any(w['path'] == str(Path(component['path']) / 'VERSION') for w in written):
                written.append({'path': str(Path(component['path']) / 'VERSION'), 'size': vf.stat().st_size})
    return {'ok': True, 'status': 'applied', 'written_files': len(written), 'written': written[:500], **preview}


def _buildable_kind_for_rel(rel: Path, target: Path) -> str | None:
    if not target.is_dir() or len(rel.parts) != 2:
        return None
    if rel.parts[0] == 'containers' and any((target / name).is_file() for name in ('Containerfile', 'Dockerfile', 'containerfile', 'dockerfile')):
        return 'container'
    if rel.parts[0] == 'binaries' and any((target / name).is_file() for name in ('Containerfile', 'Dockerfile', 'containerfile', 'dockerfile')):
        return 'binary'
    return None


def list_tree(path: str = '') -> dict[str, Any]:
    ensure_source_library()
    target = safe_source_path(path)
    current_rel = _safe_rel(path)
    if not target.exists():
        raise FileNotFoundError(path)
    if target.is_file():
        return {'path': str(current_rel), 'type': 'file', 'size': target.stat().st_size}
    items = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith('.'):
            continue
        rel = item.relative_to(source_root())
        record = {'name': item.name, 'path': str(rel), 'type': 'dir' if item.is_dir() else 'file', 'size': item.stat().st_size if item.is_file() else None}
        if item.is_dir():
            version = _read_version_file(item)
            if version:
                record['source_version'] = version
            metadata = _read_component_metadata(item, rel)
            if metadata:
                record['component'] = metadata
                record['component_title'] = metadata.get('title')
                record['component_description'] = metadata.get('description')
                record['component_kind'] = metadata.get('kind')
                record['component_maintainers'] = metadata.get('maintainers')
        buildable = _buildable_kind_for_rel(rel, item)
        if buildable:
            record['buildable_kind'] = buildable
        items.append(record)
    buildable_current = _buildable_kind_for_rel(current_rel, target)
    result = {'path': str(current_rel), 'type': 'dir', 'items': items}
    if buildable_current:
        result['buildable_kind'] = buildable_current
    return result


def read_text(path: str) -> dict[str, Any]:
    ensure_source_library()
    target = safe_source_path(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    if target.stat().st_size > 1024 * 1024:
        raise ValueError('Source file is too large to edit in the UI')
    return {'path': str(_safe_rel(path)), 'content': target.read_text(encoding='utf-8', errors='replace')}


def write_text(path: str, content: str) -> dict[str, Any]:
    ensure_source_library()
    target = safe_source_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    return {'path': str(_safe_rel(path)), 'size': target.stat().st_size}





def create_entry(path: str, entry_type: str = 'file') -> dict[str, Any]:
    ensure_source_library()
    target = safe_source_path(path)
    rel = _safe_rel(path)
    if target.exists():
        raise ValueError('Source path already exists')
    if entry_type == 'dir':
        target.mkdir(parents=True, exist_ok=False)
        return {'ok': True, 'path': str(rel), 'type': 'dir'}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('', encoding='utf-8')
    return {'ok': True, 'path': str(rel), 'type': 'file', 'size': 0}


def rename_entry(path: str, new_name: str) -> dict[str, Any]:
    ensure_source_library()
    source = safe_source_path(path)
    rel = _safe_rel(path)
    if not source.exists():
        raise FileNotFoundError(path)
    safe_name = Path(str(new_name).strip()).name
    if not safe_name or safe_name in ('.', '..') or '/' in safe_name or '\\' in safe_name:
        raise ValueError('Invalid new name')
    target = source.with_name(safe_name)
    root = source_root().resolve()
    resolved = target.resolve()
    if root not in resolved.parents:
        raise ValueError('Target path escapes source library')
    if target.exists():
        raise ValueError('Target name already exists')
    source.rename(target)
    new_rel = target.relative_to(source_root())
    return {'ok': True, 'path': str(rel), 'new_path': str(new_rel), 'type': 'dir' if target.is_dir() else 'file'}


def delete_entry(path: str) -> dict[str, Any]:
    ensure_source_library()
    target = safe_source_path(path)
    rel = _safe_rel(path)
    if not target.exists():
        raise FileNotFoundError(path)
    if target.is_dir():
        shutil.rmtree(target)
        entry_type = 'dir'
    else:
        target.unlink()
        entry_type = 'file'
    return {'ok': True, 'path': str(rel), 'type': entry_type}

def _packaged_version() -> str:
    version_file = packaged_root() / 'VERSION'
    if version_file.exists():
        return version_file.read_text(encoding='utf-8').strip() or 'dev'
    return 'dev'

def make_archive() -> Path:
    ensure_source_library()
    archive = pacp_path('cache', 'pac-sources.tar.gz')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'w:gz') as tf:
        tf.add(source_root(), arcname='pac-sources')
    return archive



def _safe_name(value: str) -> str:
    name = re.sub(r'[^a-zA-Z0-9_.-]+', '-', value.strip()).strip('-').lower()
    if not name:
        raise ValueError('A source folder name is required')
    return name


def _artifact_version(name: str, fallback: str | None = None) -> str:
    match = re.search(r'(?:^|[-_])v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)(?=$|[-_])', name or '')
    return match.group(1) if match else (fallback or 'unversioned')


def _version_sort_key(version: str) -> tuple[Any, ...]:
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)(.*)$', version or '')
    if match:
        return (1, int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4) or '')
    return (0, version or '')


def _find_containerfile(folder: Path) -> Path:
    for name in ('Containerfile', 'Dockerfile', 'containerfile', 'dockerfile'):
        candidate = folder / name
        if candidate.exists() and candidate.is_file():
            return candidate
    raise ValueError('Container source folder needs a Containerfile or Dockerfile at the folder root')


def build_container(folder_path: str, runtime: str = 'auto', tag: str | None = None) -> dict[str, Any]:
    ensure_source_library()
    rel = _safe_rel(folder_path)
    if not rel.parts or rel.parts[0] != 'containers':
        raise ValueError('Container builds must be started from a folder under containers/')
    folder = safe_source_path(rel)
    if not folder.is_dir():
        raise FileNotFoundError(str(rel))
    containerfile = _find_containerfile(folder)
    image_name = tag or f'localhost/{_safe_name(folder.name)}:latest'
    selected_runtime = None
    if runtime in ('podman', 'docker'):
        selected_runtime = runtime
    else:
        selected_runtime = shutil.which('podman') and 'podman' or (shutil.which('docker') and 'docker')
    if not selected_runtime:
        raise RuntimeError('No container runtime found. Install podman or docker on the PAC controller.')
    cmd = [selected_runtime, 'build', '-t', image_name, '-f', str(containerfile), str(folder)]
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(cmd, cwd=str(folder), capture_output=True, text=True, timeout=1800, check=False)
    return {
        'ok': proc.returncode == 0,
        'kind': 'container',
        'folder': str(rel),
        'image': image_name,
        'runtime': selected_runtime,
        'command': cmd,
        'exit_code': proc.returncode,
        'stdout': proc.stdout[-20000:],
        'stderr': proc.stderr[-20000:],
        'started_at': started,
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }


def build_binary(folder_path: str, targets: list[str] | None = None, runtime: str = 'auto') -> dict[str, Any]:
    ensure_source_library()
    rel = _safe_rel(folder_path)
    if not rel.parts or rel.parts[0] != 'binaries':
        raise ValueError('Binary builds must be started from a folder under binaries/')
    folder = safe_source_path(rel)
    if not folder.is_dir():
        raise FileNotFoundError(str(rel))
    if not (folder / 'go.mod').exists():
        raise ValueError('Binary folder needs a Go module at its root')
    containerfile = _find_containerfile(folder)
    selected_runtime = None
    if runtime in ('podman', 'docker'):
        selected_runtime = runtime
    else:
        selected_runtime = shutil.which('podman') and 'podman' or (shutil.which('docker') and 'docker')
    if not selected_runtime:
        raise RuntimeError('No container runtime found. Install podman or docker on the PAC controller.')
    target_list = targets or ['linux/amd64', 'linux/arm64', 'windows/amd64', 'darwin/amd64', 'darwin/arm64']
    out_root = pacp_path('source-builds', 'binaries', folder.name)
    out_root.mkdir(parents=True, exist_ok=True)
    # Rootless Podman/Docker builds can map container root to a host subuid that
    # cannot write to a 0755 host-owned output directory. The output directory
    # contains generated artifacts only, so make it explicitly writable before
    # mounting it as /out. This keeps user config/credentials untouched while
    # preventing "permission denied" during `go build -o /out/...`.
    try:
        out_root.chmod(0o777)
    except OSError:
        # Continue and let the container export step surface the exact mount/write
        # error in the UI event output.
        pass
    version = _read_version_file(folder) or _packaged_version()
    project_name = 'pac-zed' if folder.name == 'zed-binary' else folder.name
    compiled_server_url = os.environ.get("PAC_BUILD_SERVER_URL", os.environ.get("PAC_PUBLIC_URL", "")).strip().rstrip('/')
    target_csv = ','.join(target_list)
    image_name = f'localhost/pac-binary-builder-{_safe_name(folder.name)}:{version}'
    build_cmd = [selected_runtime, 'build', '-t', image_name, '-f', str(containerfile), str(folder)]
    volume_suffix = ':Z' if selected_runtime == 'podman' else ''
    run_cmd = [
        selected_runtime, 'run', '--rm',
        '-v', f'{out_root}:/out{volume_suffix}',
        '-e', f'PAC_VERSION={version}',
        '-e', f'PAC_SOURCE_VERSION={version}',
        '-e', f'PAC_CONTROLLER_VERSION={_packaged_version()}',
        '-e', f'PAC_COMPILED_SERVER_URL={compiled_server_url}',
        '-e', f'PAC_BINARY_NAME={project_name}',
        '-e', f'PAC_TARGETS={target_csv}',
        image_name,
    ]
    started = datetime.now(timezone.utc).isoformat()
    build_proc = subprocess.run(build_cmd, cwd=str(folder), capture_output=True, text=True, timeout=1800, check=False)
    run_proc = None
    if build_proc.returncode == 0:
        run_proc = subprocess.run(run_cmd, capture_output=True, text=True, timeout=1800, check=False)
    exit_code = build_proc.returncode if build_proc.returncode != 0 else (run_proc.returncode if run_proc else 1)
    artifacts = []
    for item in sorted(out_root.glob(f'{project_name}-*')):
        if item.is_file():
            artifacts.append({'name': item.name, 'size': item.stat().st_size, 'path': str(item), 'download_url': f'/v1/sources/binary-artifacts/{folder.name}/{item.name}'})
    stdout = '[container build]\n' + (build_proc.stdout or '')
    stderr = '[container build]\n' + (build_proc.stderr or '')
    if run_proc is not None:
        stdout += '\n[binary export]\n' + (run_proc.stdout or '')
        stderr += '\n[binary export]\n' + (run_proc.stderr or '')
    return {
        'ok': exit_code == 0,
        'kind': 'binary',
        'folder': str(rel),
        'runtime': selected_runtime,
        'containerfile': str(containerfile.relative_to(folder)),
        'builder_image': image_name,
        'targets': target_list,
        'version': version,
        'source_version': version,
        'controller_version': _packaged_version(),
        'compiled_server_url': compiled_server_url,
        'command': {'build': build_cmd, 'run': run_cmd},
        'exit_code': exit_code,
        'stdout': stdout[-20000:],
        'stderr': stderr[-20000:],
        'artifacts': artifacts,
        'started_at': started,
        'completed_at': datetime.now(timezone.utc).isoformat(),
    }


def list_binary_artifacts(project: str | None = None) -> dict[str, Any]:
    ensure_source_library()
    base = pacp_path('source-builds', 'binaries')
    base.mkdir(parents=True, exist_ok=True)
    source_base = source_root() / 'binaries'
    source_base.mkdir(parents=True, exist_ok=True)

    def _project_names() -> list[str]:
        if project:
            return [_safe_name(project)]
        names = {p.name for p in source_base.iterdir() if p.is_dir() and not p.name.startswith('.')}
        names.update(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith('.'))
        return sorted(names, key=str.lower)

    projects = []
    for name in _project_names():
        root = base / name
        source_dir = source_base / name
        source_version = _read_version_file(source_dir)
        artifacts = []
        versions: dict[str, dict[str, Any]] = {}
        if root.exists():
            for item in sorted(root.iterdir()):
                if item.is_file():
                    version = _artifact_version(item.name, source_version)
                    artifact = {
                        'name': item.name,
                        'size': item.stat().st_size,
                        'version': version,
                        'download_url': f'/v1/sources/binary-artifacts/{name}/{item.name}',
                        'delete_url': f'/v1/sources/binary-artifacts/{name}/{item.name}',
                    }
                    artifacts.append(artifact)
                    group = versions.setdefault(version, {'version': version, 'artifact_count': 0, 'bytes': 0})
                    group['artifact_count'] += 1
                    group['bytes'] += artifact['size']
        version_list = sorted(versions.values(), key=lambda r: _version_sort_key(r['version']), reverse=True)
        projects.append({
            'project': name,
            'source_path': f'binaries/{name}',
            'source_version': source_version,
            'has_source': source_dir.is_dir(),
            'artifacts': artifacts,
            'versions': version_list,
            'artifact_count': len(artifacts),
        })
    return {'projects': projects}


def binary_artifact_path(project: str, filename: str) -> Path:
    project = _safe_name(project)
    filename = Path(filename).name
    target = (pacp_path('source-builds', 'binaries', project) / filename).resolve()
    root = pacp_path('source-builds', 'binaries', project).resolve()
    if root not in target.parents or not target.is_file():
        raise FileNotFoundError(filename)
    return target


def delete_binary_artifact(project: str, filename: str) -> dict[str, Any]:
    target = binary_artifact_path(project, filename)
    size = target.stat().st_size
    target.unlink()
    return {'ok': True, 'project': _safe_name(project), 'deleted': target.name, 'bytes': size}


def prune_binary_artifacts(project: str | None = None, keep_versions: int = 1, dry_run: bool = False) -> dict[str, Any]:
    ensure_source_library()
    keep_versions = max(1, int(keep_versions or 1))
    inventory = list_binary_artifacts(project).get('projects', [])
    deleted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for proj in inventory:
        version_order = [v['version'] for v in proj.get('versions', [])]
        keep = set(version_order[:keep_versions])
        for artifact in proj.get('artifacts', []):
            record = {'project': proj['project'], 'name': artifact['name'], 'version': artifact.get('version'), 'size': artifact.get('size', 0)}
            if artifact.get('version') in keep:
                kept.append(record)
                continue
            if not dry_run:
                try:
                    binary_artifact_path(proj['project'], artifact['name']).unlink()
                except FileNotFoundError:
                    continue
            deleted.append(record)
    return {'ok': True, 'dry_run': dry_run, 'keep_versions': keep_versions, 'deleted_count': len(deleted), 'deleted_bytes': sum(int(r.get('size') or 0) for r in deleted), 'deleted': deleted, 'kept_count': len(kept)}

# --- Online source/package update discovery ---------------------------------------

_DEFAULT_PACKAGES_MANIFEST = "https://raw.githubusercontent.com/pac-labs/packages/main/packages.json"



def _component_content_hash(folder: Path) -> str | None:
    """Return a stable hash for package source content, ignoring generated/cache files."""
    if not folder.exists() or not folder.is_dir():
        return None
    digest = hashlib.sha256()
    ignored_dirs = {'.git', '__pycache__', 'node_modules', 'dist', 'build', '.pytest_cache'}
    files: list[Path] = []
    for item in folder.rglob('*'):
        if not item.is_file():
            continue
        rel = item.relative_to(folder)
        if any(part in ignored_dirs or part.startswith('.') for part in rel.parts):
            continue
        if item.suffix in {'.pyc', '.pyo', '.swp'} or item.name.endswith('~'):
            continue
        files.append(item)
    for item in sorted(files, key=lambda p: p.relative_to(folder).as_posix()):
        rel = item.relative_to(folder).as_posix()
        digest.update(rel.encode('utf-8'))
        digest.update(b'\0')
        try:
            digest.update(item.read_bytes())
        except Exception:
            continue
        digest.update(b'\0')
    return 'sha256:' + digest.hexdigest()

def _component_identity_from_path(path: str | None) -> str:
    return str(path or '').strip().strip('/').replace('\\', '/')


def _component_version_tuple(value: str | None) -> tuple[int, int, int, str] | None:
    if not value:
        return None
    match = re.search(r'(\d+)\.(\d+)\.(\d+)(.*)', str(value).strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4) or '')


def _version_is_newer(remote: str | None, local: str | None) -> bool:
    rv = _component_version_tuple(remote)
    lv = _component_version_tuple(local)
    if rv and lv:
        return rv > lv
    if remote and not local:
        return True
    return bool(remote and local and str(remote) != str(local))


def _local_component_inventory() -> dict[str, dict[str, Any]]:
    ensure_source_library()
    inventory: dict[str, dict[str, Any]] = {}
    for root_name in sorted(_FEATURE_TOP_LEVEL):
        base = source_root() / root_name
        if not base.exists():
            continue
        candidates = [base] if root_name in {'scripts', 'docs'} else [p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')]
        for folder in candidates:
            try:
                rel = folder.relative_to(source_root()).as_posix()
            except Exception:
                continue
            meta = _read_component_metadata(folder, Path(rel)) or {}
            version = _read_version_file(folder) or meta.get('version')
            identity = _component_identity_from_path(meta.get('source_path') or rel)
            inventory[identity] = {
                'id': meta.get('id') or identity.replace('/', ':'),
                'source_path': identity,
                'title': meta.get('title') or folder.name.replace('-', ' ').title(),
                'description': meta.get('description'),
                'kind': meta.get('kind') or root_name,
                'version': version,
                'content_hash': _component_content_hash(folder),
                'component': meta,
            }
    return inventory


def fetch_online_package_updates(manifest_url: str | None = None, timeout_seconds: int = 10) -> dict[str, Any]:
    """Fetch pac-labs/packages manifest and compare with the local source library."""
    import urllib.request
    url = (manifest_url or _DEFAULT_PACKAGES_MANIFEST).strip()
    if not url:
        url = _DEFAULT_PACKAGES_MANIFEST
    started = datetime.now(timezone.utc).isoformat()
    req = urllib.request.Request(url, headers={'User-Agent': 'PAC-source-update-check/1'})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read(2 * 1024 * 1024)
            status = getattr(response, 'status', 200)
    except Exception as exc:
        return {'ok': False, 'status': 'failed', 'manifest_url': url, 'checked_at': started, 'error': str(exc), 'updates': [], 'update_count': 0}
    try:
        manifest = json.loads(raw.decode('utf-8', errors='replace'))
    except Exception as exc:
        return {'ok': False, 'status': 'failed', 'manifest_url': url, 'checked_at': started, 'error': f'Invalid packages manifest JSON: {exc}', 'updates': [], 'update_count': 0}
    local = _local_component_inventory()
    updates: list[dict[str, Any]] = []
    components = manifest.get('components') if isinstance(manifest, dict) else []
    if not isinstance(components, list):
        components = []
    for remote in components:
        if not isinstance(remote, dict):
            continue
        source_path = _component_identity_from_path(remote.get('source_path') or remote.get('path') or remote.get('id'))
        if not source_path:
            continue
        local_record = local.get(source_path)
        remote_version = str(remote.get('version') or '').strip() or None
        local_version = local_record.get('version') if local_record else None
        remote_hash = str(remote.get('content_hash') or remote.get('sha256') or '').strip() or None
        local_hash = local_record.get('content_hash') if local_record else None
        if not local_record:
            status_text = 'new'
        elif remote_hash and local_hash:
            status_text = 'update' if remote_hash != local_hash else 'current'
        elif remote_version or local_version:
            status_text = 'update' if _version_is_newer(remote_version, local_version) else 'current'
        else:
            # The repository-level package version changes on every controller release.
            # Do not treat that as a module update when the module has no explicit
            # version/hash of its own.
            status_text = 'current'
        if status_text in {'new', 'update'}:
            updates.append({
                'status': status_text,
                'source_path': source_path,
                'id': remote.get('id') or source_path.replace('/', ':'),
                'title': remote.get('title') or (local_record or {}).get('title') or Path(source_path).name.replace('-', ' ').title(),
                'description': remote.get('description') or (local_record or {}).get('description'),
                'kind': remote.get('kind') or source_path.split('/', 1)[0],
                'local_version': local_version,
                'remote_version': remote_version,
                'local_hash': local_hash,
                'remote_hash': remote_hash,
                'repository': remote.get('repository') or manifest.get('repository'),
                'homepage': remote.get('homepage'),
                'maintainers': remote.get('maintainers') or [],
                'tags': remote.get('tags') or [],
            })
    return {
        'ok': True,
        'status': 'ok',
        'schema': 'pac.source-updates.v1',
        'manifest_url': url,
        'repository': manifest.get('repository') if isinstance(manifest, dict) else None,
        'packages_version': manifest.get('version') if isinstance(manifest, dict) else None,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'generated_at': manifest.get('generated_at') if isinstance(manifest, dict) else None,
        'local_count': len(local),
        'remote_count': len(components),
        'update_count': len(updates),
        'updates': sorted(updates, key=lambda r: (r['status'] != 'update', r.get('source_path') or '')),
    }

