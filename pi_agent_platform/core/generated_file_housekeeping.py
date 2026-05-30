from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .platform_home import pacp_path


def _utc_from_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _file_record(path: Path, *, category: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        'category': category,
        'path': str(path),
        'name': path.name,
        'size': stat.st_size,
        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _remove_path(path: Path, *, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except FileNotFoundError:
        return False


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
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    candidates: list[Path] = []
    for path in root.glob('*.zip'):
        try:
            if path.is_file():
                candidates.append(path)
        except OSError:
            continue
    candidates.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    keep = set(candidates[:keep_latest])
    deleted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for path in candidates:
        try:
            record = _file_record(path, category='debug_bundle')
            too_old = _utc_from_mtime(path) < cutoff
            if path in keep and not too_old:
                kept.append(record)
                continue
            if _remove_path(path, dry_run=dry_run):
                deleted.append(record)
        except OSError:
            continue
    return {
        'ok': True,
        'dry_run': dry_run,
        'root': str(root),
        'keep_latest': keep_latest,
        'max_age_hours': max_age_hours,
        'deleted_count': len(deleted),
        'deleted_bytes': sum(int(item.get('size') or 0) for item in deleted),
        'deleted': deleted,
        'kept_count': len(kept),
    }


def prune_update_temp_files(
    *,
    keep_latest_backups: int = 3,
    max_age_hours: int = 48,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune update downloads/extractions and old backup log directories.

    Update backups are useful for rollback, so keep a few of the newest backup
    directories. Everything else in update downloads/extractions is generated
    temp/cache material.
    """
    updates = pacp_path('updates')
    updates.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(max_age_hours or 48)))
    deleted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []

    direct_temp_dirs = ['downloads', 'uploads', 'release-assets']
    temp_prefixes = ['extracted-']
    for name in direct_temp_dirs:
        path = updates / name
        if not path.exists():
            continue
        try:
            record = _file_record(path, category='update_temp') if path.is_file() else {
                'category': 'update_temp', 'path': str(path), 'name': path.name, 'size': 0,
                'modified_at': _utc_from_mtime(path).isoformat(),
            }
            if _remove_path(path, dry_run=dry_run):
                deleted.append(record)
        except OSError:
            continue
    for path in updates.iterdir() if updates.exists() else []:
        try:
            if path.is_dir() and any(path.name.startswith(prefix) for prefix in temp_prefixes):
                record = {'category': 'update_extract', 'path': str(path), 'name': path.name, 'size': 0, 'modified_at': _utc_from_mtime(path).isoformat()}
                if _remove_path(path, dry_run=dry_run):
                    deleted.append(record)
        except OSError:
            continue

    backups = [p for p in updates.glob('backup-app-*') if p.is_dir()]
    backups.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    keep_backups = set(backups[:max(0, int(keep_latest_backups or 0))])
    for path in backups:
        try:
            record = {'category': 'update_backup', 'path': str(path), 'name': path.name, 'size': 0, 'modified_at': _utc_from_mtime(path).isoformat()}
            if path in keep_backups and _utc_from_mtime(path) >= cutoff:
                kept.append(record)
                continue
            if _remove_path(path, dry_run=dry_run):
                deleted.append(record)
        except OSError:
            continue
    return {
        'ok': True,
        'dry_run': dry_run,
        'root': str(updates),
        'keep_latest_backups': keep_latest_backups,
        'max_age_hours': max_age_hours,
        'deleted_count': len(deleted),
        'deleted': deleted,
        'kept_count': len(kept),
    }


def run_generated_file_housekeeping(
    *,
    debug_bundle_root: Path,
    dry_run: bool = False,
    keep_debug_bundles: int = 1,
    debug_bundle_max_age_hours: int = 24,
    keep_update_backups: int = 3,
    update_temp_max_age_hours: int = 48,
) -> dict[str, Any]:
    debug_result = prune_debug_bundles(
        debug_bundle_root,
        keep_latest=keep_debug_bundles,
        max_age_hours=debug_bundle_max_age_hours,
        dry_run=dry_run,
    )
    update_result = prune_update_temp_files(
        keep_latest_backups=keep_update_backups,
        max_age_hours=update_temp_max_age_hours,
        dry_run=dry_run,
    )
    return {
        'ok': True,
        'dry_run': dry_run,
        'debug_bundles': debug_result,
        'update_temp': update_result,
        'deleted_count': int(debug_result.get('deleted_count') or 0) + int(update_result.get('deleted_count') or 0),
    }
