from __future__ import annotations

import fnmatch
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .platform_home import pacp_path


_DEPRECATED_BINARY_PROJECTS = {'pac-agent', 'zed-binary', 'pac-endpoint-runner'}
_SOURCE_GENERATED_DIR_NAMES = {
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.parcel-cache',
    '.vite', '.next', 'htmlcov', 'coverage', 'dist', 'build', 'release-binaries',
}
_SOURCE_GENERATED_FILE_PATTERNS = {'*.pyc', '*.pyo', '*.tmp', '*.part', 'coverage.out', '*.test'}


@dataclass(frozen=True)
class CleanupPolicy:
    keep_debug_bundles: int = 1
    debug_bundle_max_age_hours: int = 24
    keep_update_backups: int = 2
    keep_update_downloads: int = 1
    keep_release_assets: int = 1
    update_temp_max_age_hours: int = 24
    log_max_age_days: int = 7
    keep_binary_versions: int = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_from_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _path_size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return int(path.stat().st_size)
        total = 0
        for child in path.rglob('*'):
            try:
                if child.is_file() or child.is_symlink():
                    total += int(child.stat().st_size)
            except OSError:
                continue
        return total
    except OSError:
        return 0


def _file_record(path: Path, *, category: str, size: int | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        'category': category,
        'path': str(path),
        'name': path.name,
        'size': int(size if size is not None else (stat.st_size if path.is_file() else _path_size(path))),
        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        'kind': 'directory' if path.is_dir() else 'file',
    }


def _remove_path(path: Path, *, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except FileNotFoundError:
        return False


def _append_deleted(deleted: list[dict[str, Any]], path: Path, *, category: str, dry_run: bool) -> None:
    try:
        record = _file_record(path, category=category)
        if _remove_path(path, dry_run=dry_run):
            deleted.append(record)
    except OSError:
        return


def _newest(paths: Iterable[Path]) -> list[Path]:
    return sorted(list(paths), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
        return resolved == resolved_root or resolved_root in resolved.parents
    except OSError:
        return False


def _category_summary(deleted: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for item in deleted:
        category = str(item.get('category') or 'unknown')
        entry = categories.setdefault(category, {'count': 0, 'bytes': 0})
        entry['count'] += 1
        entry['bytes'] += int(item.get('size') or 0)
    return categories


def _result(root: Path, *, dry_run: bool, deleted: list[dict[str, Any]], kept_count: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        'ok': True,
        'dry_run': dry_run,
        'root': str(root),
        'deleted_count': len(deleted),
        'deleted_bytes': sum(int(item.get('size') or 0) for item in deleted),
        'deleted': deleted[:250],
        'deleted_truncated': max(0, len(deleted) - 250),
        'categories': _category_summary(deleted),
        'kept_count': kept_count,
        **extra,
    }


def prune_debug_bundles(
    root: Path,
    *,
    keep_latest: int = 1,
    max_age_hours: int = 24,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune generated environment/support debug bundles.

    Debug bundles are temporary download resources. They can be regenerated and
    should not linger as a long-term artifact store.
    """
    root.mkdir(parents=True, exist_ok=True)
    keep_latest = max(0, int(keep_latest or 0))
    max_age_hours = max(1, int(max_age_hours or 24))
    cutoff = _now() - timedelta(hours=max_age_hours)
    candidates = _newest(path for path in root.glob('*.zip') if path.is_file())
    keep = set(candidates[:keep_latest])
    deleted: list[dict[str, Any]] = []
    kept_count = 0
    for path in candidates:
        try:
            too_old = _utc_from_mtime(path) < cutoff
            if path in keep and not too_old:
                kept_count += 1
                continue
            _append_deleted(deleted, path, category='debug_bundle', dry_run=dry_run)
        except OSError:
            continue
    return _result(root, dry_run=dry_run, deleted=deleted, kept_count=kept_count, keep_latest=keep_latest, max_age_hours=max_age_hours)


def _prune_keep_newest_files(root: Path, pattern: str, keep_latest: int, *, category: str, dry_run: bool) -> tuple[list[dict[str, Any]], int]:
    if not root.exists():
        return [], 0
    candidates = _newest(path for path in root.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern))
    keep = set(candidates[:max(0, keep_latest)])
    deleted: list[dict[str, Any]] = []
    kept_count = 0
    for path in candidates:
        if path in keep:
            kept_count += 1
            continue
        _append_deleted(deleted, path, category=category, dry_run=dry_run)
    return deleted, kept_count


def prune_update_temp_files(
    *,
    keep_latest_backups: int = 2,
    keep_downloads: int = 1,
    keep_release_assets: int = 1,
    max_age_hours: int = 24,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune update downloads/extractions and old rollback backups.

    Rollback backups are useful, so a small newest set is kept. Downloads,
    release-asset cache, uploads, and extracted folders are generated resources
    and are pruned aggressively after updates.
    """
    updates = pacp_path('updates')
    updates.mkdir(parents=True, exist_ok=True)
    cutoff = _now() - timedelta(hours=max(1, int(max_age_hours or 24)))
    deleted: list[dict[str, Any]] = []
    kept_count = 0

    downloads = updates / 'downloads'
    if downloads.exists():
        removed, kept = _prune_keep_newest_files(downloads, 'pac-full-*.zip', max(0, int(keep_downloads or 0)), category='update_download', dry_run=dry_run)
        deleted.extend(removed)
        kept_count += kept
        for path in list(downloads.iterdir()):
            try:
                if path.is_file() and (path.suffix in {'.tmp', '.part'} or _utc_from_mtime(path) < cutoff):
                    _append_deleted(deleted, path, category='update_download_temp', dry_run=dry_run)
            except OSError:
                continue

    uploads = updates / 'uploads'
    if uploads.exists():
        for path in list(uploads.iterdir()):
            try:
                if _utc_from_mtime(path) < cutoff:
                    _append_deleted(deleted, path, category='update_upload_temp', dry_run=dry_run)
            except OSError:
                continue

    release_assets = updates / 'release-assets'
    if release_assets.exists():
        asset_dirs = _newest(path for path in release_assets.iterdir() if path.is_dir())
        keep_asset_dirs = set(asset_dirs[:max(0, int(keep_release_assets or 0))])
        for path in asset_dirs:
            try:
                if path in keep_asset_dirs and _utc_from_mtime(path) >= cutoff:
                    kept_count += 1
                    continue
                _append_deleted(deleted, path, category='release_asset_cache', dry_run=dry_run)
            except OSError:
                continue
        for path in list(release_assets.iterdir()):
            try:
                if path.is_file() and _utc_from_mtime(path) < cutoff:
                    _append_deleted(deleted, path, category='release_asset_cache', dry_run=dry_run)
            except OSError:
                continue

    for path in list(updates.iterdir()) if updates.exists() else []:
        try:
            if path.is_dir() and (path.name.startswith('extracted-') or path.name.startswith('pac-update-extract-')):
                _append_deleted(deleted, path, category='update_extract', dry_run=dry_run)
        except OSError:
            continue

    backups = _newest(p for p in updates.glob('backup-app-*') if p.is_dir())
    keep_backups = set(backups[:max(0, int(keep_latest_backups or 0))])
    for path in backups:
        try:
            if path in keep_backups:
                kept_count += 1
                continue
            _append_deleted(deleted, path, category='update_backup', dry_run=dry_run)
        except OSError:
            continue

    return _result(
        updates,
        dry_run=dry_run,
        deleted=deleted,
        kept_count=kept_count,
        keep_latest_backups=keep_latest_backups,
        keep_downloads=keep_downloads,
        keep_release_assets=keep_release_assets,
        max_age_hours=max_age_hours,
    )


def prune_binary_cache(*, keep_versions: int = 1, dry_run: bool = False) -> dict[str, Any]:
    """Prune generated binary cache and removed transitional binary outputs."""
    roots = [
        pacp_path('source-builds', 'binaries'),
        pacp_path('generated-binaries'),
        pacp_path('bin'),
    ]
    deleted: list[dict[str, Any]] = []
    kept_count = 0
    keep_versions = max(1, int(keep_versions or 1))
    for root in roots:
        if not root.exists():
            continue
        for deprecated in _DEPRECATED_BINARY_PROJECTS:
            for path in list(root.glob(f'{deprecated}*')):
                _append_deleted(deleted, path, category='deprecated_binary_cache', dry_run=dry_run)
        project_dirs = [p for p in root.iterdir() if p.is_dir() and p.name not in _DEPRECATED_BINARY_PROJECTS]
        for project_dir in project_dirs:
            artifacts = _newest(p for p in project_dir.iterdir() if p.is_file())
            by_platform: dict[str, list[Path]] = {}
            for artifact in artifacts:
                platform_key = _binary_platform_key(artifact.name, project_dir.name)
                by_platform.setdefault(platform_key, []).append(artifact)
            for platform_artifacts in by_platform.values():
                for index, artifact in enumerate(platform_artifacts):
                    if index < keep_versions:
                        kept_count += 1
                    else:
                        _append_deleted(deleted, artifact, category='stale_binary_cache', dry_run=dry_run)
    return _result(pacp_path('source-builds'), dry_run=dry_run, deleted=deleted, kept_count=kept_count, keep_versions=keep_versions)


def _binary_platform_key(name: str, project: str) -> str:
    text = name
    if text.startswith(project + '-'):
        text = text[len(project) + 1:]
    parts = text.replace('.exe', '').split('-')
    if len(parts) >= 2:
        return '-'.join(parts[-2:])
    return text


def prune_source_tree_generated_files(app_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove generated build/cache files inside the installed PAC app tree.

    This intentionally avoids .git, venvs, and node_modules. Directory matches are
    deleted as a whole so dry-run output stays readable and does not list every
    pyc inside a removed __pycache__ directory.
    """
    root = app_root.resolve()
    deleted: list[dict[str, Any]] = []
    if not root.exists():
        return _result(root, dry_run=dry_run, deleted=deleted, skipped='app_root_missing')
    skip_names = {'.git', '.venv', 'venv', 'node_modules'}
    for path in list(root.rglob('*')):
        try:
            if not _is_inside(path, root):
                continue
            if any(part in skip_names for part in path.relative_to(root).parts):
                continue
            if path.is_dir() and path.name in _SOURCE_GENERATED_DIR_NAMES:
                _append_deleted(deleted, path, category='source_generated_dir', dry_run=dry_run)
                continue
            if path.is_file() and any(fnmatch.fnmatch(path.name, pattern) for pattern in _SOURCE_GENERATED_FILE_PATTERNS):
                if any(parent.name in _SOURCE_GENERATED_DIR_NAMES for parent in path.parents if _is_inside(parent, root)):
                    continue
                _append_deleted(deleted, path, category='source_generated_file', dry_run=dry_run)
        except OSError:
            continue
    return _result(root, dry_run=dry_run, deleted=deleted)


def prune_logs(*, max_age_days: int = 7, dry_run: bool = False) -> dict[str, Any]:
    root = pacp_path('logs')
    root.mkdir(parents=True, exist_ok=True)
    cutoff = _now() - timedelta(days=max(1, int(max_age_days or 7)))
    deleted: list[dict[str, Any]] = []
    kept_count = 0
    for path in root.rglob('*'):
        try:
            if not path.is_file():
                continue
            if not (path.name.endswith('.log') or '.log.' in path.name or path.suffix in {'.out', '.err'}):
                continue
            if _utc_from_mtime(path) < cutoff:
                _append_deleted(deleted, path, category='old_log', dry_run=dry_run)
            else:
                kept_count += 1
        except OSError:
            continue
    return _result(root, dry_run=dry_run, deleted=deleted, kept_count=kept_count, max_age_days=max_age_days)


def housekeeping_status(*, app_root: Path | None = None, debug_bundle_root: Path | None = None) -> dict[str, Any]:
    roots = {
        'pacp_home': pacp_path(),
        'updates': pacp_path('updates'),
        'update_downloads': pacp_path('updates', 'downloads'),
        'update_extracts': pacp_path('updates'),
        'binary_cache': pacp_path('source-builds', 'binaries'),
        'release_assets': pacp_path('updates', 'release-assets'),
        'logs': pacp_path('logs'),
    }
    if debug_bundle_root:
        roots['debug_bundles'] = debug_bundle_root
    if app_root:
        roots['app_root'] = app_root
    entries: dict[str, Any] = {}
    for key, path in roots.items():
        exists = path.exists()
        entries[key] = {
            'path': str(path),
            'exists': exists,
            'size_bytes': _path_size(path) if exists else 0,
            'modified_at': _utc_from_mtime(path).isoformat() if exists else None,
        }
        if key == 'updates' and exists:
            entries[key]['backup_count'] = len(list(path.glob('backup-app-*')))
            entries[key]['extracted_count'] = len([p for p in path.iterdir() if p.is_dir() and p.name.startswith('extracted-')])
        if key == 'update_downloads' and exists:
            entries[key]['zip_count'] = len(list(path.glob('*.zip')))
    return {'ok': True, 'generated_at': _now().isoformat(), 'roots': entries}


def run_generated_file_housekeeping(
    *,
    debug_bundle_root: Path,
    app_root: Path | None = None,
    dry_run: bool = False,
    policy: CleanupPolicy | None = None,
    keep_debug_bundles: int | None = None,
    debug_bundle_max_age_hours: int | None = None,
    keep_update_backups: int | None = None,
    update_temp_max_age_hours: int | None = None,
) -> dict[str, Any]:
    base = policy or CleanupPolicy()
    if keep_debug_bundles is not None or debug_bundle_max_age_hours is not None or keep_update_backups is not None or update_temp_max_age_hours is not None:
        base = CleanupPolicy(
            keep_debug_bundles=base.keep_debug_bundles if keep_debug_bundles is None else int(keep_debug_bundles),
            debug_bundle_max_age_hours=base.debug_bundle_max_age_hours if debug_bundle_max_age_hours is None else int(debug_bundle_max_age_hours),
            keep_update_backups=base.keep_update_backups if keep_update_backups is None else int(keep_update_backups),
            keep_update_downloads=base.keep_update_downloads,
            keep_release_assets=base.keep_release_assets,
            update_temp_max_age_hours=base.update_temp_max_age_hours if update_temp_max_age_hours is None else int(update_temp_max_age_hours),
            log_max_age_days=base.log_max_age_days,
            keep_binary_versions=base.keep_binary_versions,
        )
    debug_result = prune_debug_bundles(debug_bundle_root, keep_latest=base.keep_debug_bundles, max_age_hours=base.debug_bundle_max_age_hours, dry_run=dry_run)
    update_result = prune_update_temp_files(keep_latest_backups=base.keep_update_backups, keep_downloads=base.keep_update_downloads, keep_release_assets=base.keep_release_assets, max_age_hours=base.update_temp_max_age_hours, dry_run=dry_run)
    binary_result = prune_binary_cache(keep_versions=base.keep_binary_versions, dry_run=dry_run)
    log_result = prune_logs(max_age_days=base.log_max_age_days, dry_run=dry_run)
    source_result = prune_source_tree_generated_files(app_root, dry_run=dry_run) if app_root else {'ok': True, 'dry_run': dry_run, 'deleted_count': 0, 'deleted_bytes': 0, 'categories': {}, 'deleted': []}
    results = {
        'debug_bundles': debug_result,
        'update_temp': update_result,
        'binary_cache': binary_result,
        'logs': log_result,
        'source_tree': source_result,
    }
    deleted_count = sum(int(item.get('deleted_count') or 0) for item in results.values())
    deleted_bytes = sum(int(item.get('deleted_bytes') or 0) for item in results.values())
    categories: dict[str, dict[str, Any]] = {}
    for result in results.values():
        for category, entry in (result.get('categories') or {}).items():
            target = categories.setdefault(category, {'count': 0, 'bytes': 0})
            target['count'] += int(entry.get('count') or 0)
            target['bytes'] += int(entry.get('bytes') or 0)
    return {
        'ok': True,
        'dry_run': dry_run,
        'generated_at': _now().isoformat(),
        'policy': base.__dict__,
        'deleted_count': deleted_count,
        'deleted_bytes': deleted_bytes,
        'categories': categories,
        **results,
    }
