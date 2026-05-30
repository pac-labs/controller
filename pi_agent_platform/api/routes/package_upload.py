from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from pi_agent_platform.core.models import Event
from pi_agent_platform.core.housekeeping_service import run_housekeeping_once


def create_package_upload_router(
    *,
    require_auth: Callable[..., Any],
    ensure_pacp_layout: Callable[[], Path],
    pacp_path: Callable[..., Path],
    store: Any,
    safe_zip_members: Callable[[zipfile.ZipFile], list[str]],
    find_package_root: Callable[[Path], Path],
    app_dir: Callable[[], Path],
    build_backup_archive: Callable[[Path, Path], dict[str, Any]],
    compare_trees: Callable[..., dict[str, Any]],
    copy_package_tree: Callable[[Path, Path], list[str]],
    pip_install_editable: Callable[[Path], dict[str, Any]],
    write_runtime_run_script: Callable[[Path], dict[str, Any]],
    schedule_local_restart: Callable[[BackgroundTasks, str], None],
    debug_bundle_root: Callable[[], Path] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post('/v1/admin/stage-package')
    @router.post('/v1/update/upload')
    @router.post('/v1/admin/upload-stage-package')
    async def upload_stage_package(background_tasks: BackgroundTasks, file: UploadFile = File(...), apply_update: bool = Query(default=True), restart_after_update: bool = Query(default=True), _auth: None = Depends(require_auth)) -> dict[str, Any]:
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
                members = safe_zip_members(zf)
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail='Uploaded file is not a valid PAC zip package') from exc

        package_root = find_package_root(extract_dir)
        if not apply_update:
            store.add_event(Event(session_id='system', type='package_uploaded', message=f'Version package uploaded: {filename}', data={'upload_path': str(upload_path), 'package_root': str(package_root)}))
            return {'status': 'uploaded', 'filename': filename, 'upload_path': str(upload_path), 'package_root': str(package_root), 'members': len(members)}

        current_app_dir = app_dir()
        backup_dir = updates_dir / f'backup-app-{stamp}'
        preservation_dir = pacp_path('backups', stamp)
        archive_meta: dict[str, Any] | None = None
        diff_meta: dict[str, Any] | None = None
        if current_app_dir.exists():
            shutil.copytree(current_app_dir, backup_dir, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc'))
            archive_meta = build_backup_archive(current_app_dir, preservation_dir / 'backup.tar.gz')
            diff_summary = compare_trees(
                installed_root=current_app_dir,
                incoming_root=package_root,
                diff_path=preservation_dir / f'{Path(filename).stem}-user.diff',
                summary_path=preservation_dir / 'change-summary.json',
            )
            diff_meta = {
                'summary': diff_summary,
                'diff_path': str(preservation_dir / f'{Path(filename).stem}-user.diff'),
                'summary_path': str(preservation_dir / 'change-summary.json'),
            }
        copied = copy_package_tree(package_root, current_app_dir)
        pip_result = pip_install_editable(current_app_dir)
        run_script_result = write_runtime_run_script(current_app_dir)
        marker = pacp_path('run', 'restart-required')
        marker.write_text(f'PAC update applied at {stamp}\nsource={upload_path}\nbackup={backup_dir}\n', encoding='utf-8')
        housekeeping = None
        try:
            housekeeping = run_housekeeping_once(app_root=current_app_dir, debug_bundle_root=(debug_bundle_root() if callable(debug_bundle_root) else pacp_path('debug-bundles')), dry_run=False)
        except Exception as exc:
            housekeeping = {'ok': False, 'error': str(exc)}
        store.add_event(Event(session_id='system', type='package_applied', message=f'Version package applied: {filename}. Restart required.', data={'upload_path': str(upload_path), 'backup_dir': str(backup_dir), 'copied': copied, 'pip': pip_result, 'run_script': run_script_result, 'restart_after_update': restart_after_update, 'preservation_archive': archive_meta, 'preservation_diff': diff_meta, 'housekeeping': housekeeping}))
        status = 'installed_restarting' if restart_after_update else 'installed_restart_required'
        if restart_after_update:
            schedule_local_restart(background_tasks, f'PAC local restart scheduled after applying version package: {filename}')
        return {
            'status': status,
            'filename': filename,
            'pacp_home': str(home),
            'app_dir': str(current_app_dir),
            'backup_dir': str(backup_dir),
            'copied': copied,
            'pip': pip_result,
            'run_script': run_script_result,
            'restart_required': True,
            'restart_scheduled': restart_after_update,
            'preservation_archive': archive_meta,
            'preservation_diff': diff_meta,
            'housekeeping': housekeeping,
        }

    return router
