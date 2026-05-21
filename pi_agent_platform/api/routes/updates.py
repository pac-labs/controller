from __future__ import annotations

import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from pi_agent_platform.core.models import Event
from pi_agent_platform.core.platform_home import pacp_path
from pi_agent_platform.core.update_preservation import TRACKED_ROOTS, build_backup_archive, generate_local_diff, list_generated_diffs
from pi_agent_platform.updates import download_release_package, fetch_latest_release_metadata


def create_updates_router(
    *,
    require_auth: Any,
    pac_version: str,
    store: Any,
    app_dir: Any,
    list_update_archives: Any,
    load_pac_changelog: Any,
    update_backups_root: Any,
    local_diffs_root: Any,
    current_release_package: Any,
    compose_release_notes_body: Any,
    changelog_delta: Any,
    read_version_from_tree: Any,
    suggest_next_version: Any,
    apply_version_package_from_path: Any,
    pip_install_editable: Any,
    write_runtime_run_script: Any,
    schedule_local_restart: Any,
) -> APIRouter:
    """PAC update, package archive, and local diff routes.

    This keeps release/update HTTP handlers out of the controller bootstrap while
    preserving the current update implementation and backup semantics. The
    injected callables are still owned by main.py for this checkpoint; a later
    pass can move them into a dedicated update service.
    """
    router = APIRouter()

    def _restore_tracked_backup_archive(archive_path: Path, target_app_dir: Path) -> dict[str, Any]:
        if not archive_path.is_file():
            raise HTTPException(status_code=404, detail='Backup archive file not found')
        members: list[tarfile.TarInfo] = []
        with tarfile.open(archive_path, 'r:gz') as archive:
            for member in archive.getmembers():
                name = str(member.name or '').strip()
                if not name or name.startswith('/') or '..' in Path(name).parts:
                    raise HTTPException(status_code=400, detail='Backup archive contains unsafe paths')
                members.append(member)
            for root_name in TRACKED_ROOTS:
                target = target_app_dir / root_name
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink(missing_ok=True)
            archive.extractall(target_app_dir, members=members)
        return {'restored_files': len([member for member in members if member.isfile()])}

    @router.get('/v1/updates/status')
    def get_updates_status(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        archives = list_update_archives()
        changelog = load_pac_changelog()
        return {
            'current_version': pac_version,
            'archive_count': len(archives),
            'latest_archive': archives[0] if archives else None,
            'archives': archives[:12],
            'changelog_current_version': changelog.get('current_version') or pac_version,
        }

    @router.get('/v1/updates/check')
    def check_for_updates(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        meta = fetch_latest_release_metadata(pac_version)
        store.add_event(Event(session_id='system', type='update_checked', message=meta.get('has_update') and f"Update available: v{meta.get('latest_version')}" or 'PAC release channel checked', data=meta))
        return meta

    @router.get('/v1/updates/archives')
    def list_archives(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return {'archives': list_update_archives()}

    @router.get('/v1/updates/archives/{stamp}')
    def get_update_archive(stamp: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        target = update_backups_root() / stamp
        if not target.is_dir():
            raise HTTPException(status_code=404, detail='Update archive not found')
        archive = next((item for item in list_update_archives() if item['stamp'] == stamp), None)
        if not archive:
            raise HTTPException(status_code=404, detail='Update archive not found')
        return archive

    @router.get('/v1/updates/archives/{stamp}/download')
    def download_update_archive(stamp: str, kind: str = 'archive', _auth: None = Depends(require_auth)) -> FileResponse:
        target = update_backups_root() / stamp
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

    @router.post('/v1/updates/archives/{stamp}/restore')
    def restore_update_archive(stamp: str, background_tasks: BackgroundTasks, restart_after_restore: bool = Query(default=True), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        target = update_backups_root() / stamp
        archive_path = target / 'backup.tar.gz'
        if not target.is_dir() or not archive_path.is_file():
            raise HTTPException(status_code=404, detail='Update archive not found')
        target_app_dir = app_dir()
        restore_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        preservation_dir = pacp_path('backups', f'restore-{restore_stamp}')
        current_archive: dict[str, Any] | None = None
        if target_app_dir.exists():
            current_archive = build_backup_archive(target_app_dir, preservation_dir / 'backup.tar.gz')
        restore_meta = _restore_tracked_backup_archive(archive_path, target_app_dir)
        pip_result = pip_install_editable(target_app_dir)
        run_script_result = write_runtime_run_script(target_app_dir)
        marker = pacp_path('run', 'restart-required')
        marker.write_text(f'PAC backup restored at {restore_stamp}\nsource={archive_path}\n', encoding='utf-8')
        result = {
            'status': 'restored_restarting' if restart_after_restore else 'restored_restart_required',
            'stamp': stamp,
            'archive_path': str(archive_path),
            'current_preservation_archive': current_archive,
            'restore': restore_meta,
            'pip': pip_result,
            'run_script': run_script_result,
            'restart_required': True,
            'restart_scheduled': restart_after_restore,
            'restart_marker': str(marker),
        }
        store.add_event(Event(session_id='system', type='backup_restored', message=f'PAC backup restored from {stamp}. Restart required.', data=result))
        if restart_after_restore:
            schedule_local_restart(background_tasks, f'PAC local restart scheduled after restoring backup: {stamp}')
        return result

    @router.get('/v1/updates/release-notes')
    def get_update_release_notes(from_version: str | None = None, to_version: str | None = None, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        target_from = (from_version or pac_version or '').strip().lstrip('v') or pac_version
        target_to = (to_version or (load_pac_changelog().get('current_version') or pac_version) or '').strip().lstrip('v') or pac_version
        entries = changelog_delta(target_from, target_to)
        meta: dict[str, Any] | None = None
        try:
            meta = fetch_latest_release_metadata(target_from)
        except Exception:
            meta = None
        compare_changes: list[str] = []
        body = None
        release_url = None
        if meta and meta.get('ok') and str(meta.get('latest_version') or '').strip().lstrip('v') == target_to:
            compare_changes = list(meta.get('compare_changes') or [])
            body = meta.get('body')
            release_url = meta.get('release_url')
        if not entries and compare_changes:
            entries = [{
                'title': f'PAC v{target_to}',
                'version': target_to,
                'changes': compare_changes,
            }]
        composed_body = compose_release_notes_body(entries, compare_changes, body)
        return {
            'from_version': target_from,
            'to_version': target_to,
            'entries': entries,
            'compare_changes': compare_changes,
            'body': composed_body or body,
            'release_url': release_url,
        }

    @router.get('/v1/updates/local-diffs')
    def get_generated_local_diffs(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        version = read_version_from_tree(app_dir()) or pac_version
        return {
            'current_version': version,
            'suggested_version': suggest_next_version(version),
            'diffs': list_generated_diffs(local_diffs_root()),
        }

    @router.post('/v1/updates/generate-local-diff')
    def create_generated_local_diff(version: str = Query(..., description='Version for the diff, e.g. 1.0.107'), _auth: None = Depends(require_auth)) -> dict[str, Any]:
        clean_version = str(version or '').strip().lstrip('v')
        if not clean_version:
            raise HTTPException(status_code=400, detail='Version is required')
        result = generate_local_diff(app_dir(), clean_version, local_diffs_root())
        store.add_event(Event(
            session_id='system',
            type='local_diff_generated',
            message=f'Local diff {("generated" if result.get("status") == "written" else "checked")}: v{clean_version}.diff',
            data=result,
        ))
        return result

    @router.get('/v1/updates/diff/{version}')
    def download_generated_local_diff(version: str, _auth: None = Depends(require_auth)) -> FileResponse:
        clean_version = str(version or '').strip().lstrip('v')
        diff_path = (local_diffs_root() / f'v{clean_version}.diff').resolve()
        if not diff_path.exists():
            raise HTTPException(status_code=404, detail=f'Diff not found: v{clean_version}.diff')
        return FileResponse(path=str(diff_path), filename=f'v{clean_version}.diff', media_type='text/plain')

    @router.post('/v1/updates/apply')
    def apply_release_update(
        background_tasks: BackgroundTasks,
        restart_after_update: bool = Query(default=True),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        meta = fetch_latest_release_metadata(pac_version)
        if not meta.get('ok'):
            raise HTTPException(status_code=503, detail=meta.get('error') or 'The PAC release feed is unavailable')
        if not meta.get('has_update'):
            return {'ok': False, 'current_version': pac_version, 'latest_version': meta.get('latest_version'), 'message': 'PAC is already up to date'}
        download_url = str(meta.get('download_url') or '').strip()
        if not download_url:
            raise HTTPException(status_code=404, detail='Latest PAC release does not provide pac-full.zip')
        downloads_dir = pacp_path('updates', 'downloads')
        downloads_dir.mkdir(parents=True, exist_ok=True)
        target = downloads_dir / f"pac-full-{meta.get('latest_version') or 'latest'}.zip"
        download = download_release_package(download_url, target)
        if not download.get('ok'):
            raise HTTPException(status_code=502, detail=f"Release download failed: {download.get('error')}")
        result = apply_version_package_from_path(target, target.name, restart_after_update=restart_after_update)
        result.update({'ok': True, 'current_version': pac_version, 'latest_version': meta.get('latest_version'), 'release_url': meta.get('release_url'), 'download_url': download_url, 'download': download})
        if restart_after_update:
            schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying release {meta.get("latest_version")}')
        return result

    @router.get('/v1/admin/current-package')
    def download_current_package(_auth: None = Depends(require_auth)) -> FileResponse:
        try:
            package = current_release_package()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return FileResponse(package, filename='pac-full.zip')

    return router
