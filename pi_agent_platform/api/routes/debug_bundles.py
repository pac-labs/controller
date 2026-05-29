from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from pi_agent_platform.core.config import AppConfig
from pi_agent_platform.core.models import Event
from pi_agent_platform.core.environment_debug_bundle import build_environment_debug_zip
from pi_agent_platform.core.platform_debug_bundle import _json_bytes, _redact_text

AuthDependency = Callable[..., Any]


def _bundle_root(config: AppConfig) -> Path:
    root = Path(config.server.data_dir).expanduser() / 'debug-bundles'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_bundle_path(root: Path, bundle_id: str) -> Path:
    name = Path(str(bundle_id)).name
    if not name.endswith('.zip'):
        name += '.zip'
    path = (root / name).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise HTTPException(status_code=400, detail='Invalid debug bundle id')
    return path


def _bundle_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        'id': path.name,
        'name': path.name,
        'size': stat.st_size,
        'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        'download_url': f'/v1/debug-bundles/{path.name}/download',
    }


def create_debug_bundles_router(
    *,
    require_auth: AuthDependency,
    store: Any,
    config: AppConfig,
) -> APIRouter:
    router = APIRouter()

    @router.get('/v1/debug-bundles')
    def list_debug_bundles(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        root = _bundle_root(config)
        candidates = []
        for path in root.glob('*.zip'):
            try:
                if path.is_file():
                    candidates.append(path)
            except OSError:
                continue
        bundles = sorted(candidates, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
        records = []
        for path in bundles[:30]:
            try:
                records.append(_bundle_record(path))
            except OSError:
                continue
        return {'bundles': records}

    @router.post('/v1/debug-bundles/environment')
    def generate_environment_debug_bundle(
        include_events: int = Query(default=2000, ge=100, le=10000),
        include_sessions: int = Query(default=30, ge=1, le=200),
        _auth: Any = Depends(require_auth),
    ) -> dict[str, Any]:
        root = _bundle_root(config)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        path = root / f'pac-environment-debug-{stamp}.zip'
        generation_error: str | None = None
        try:
            data = build_environment_debug_zip(
                store=store,
                config=config,
                include_events=include_events,
                include_sessions=include_sessions,
            )
        except Exception as exc:  # Keep the support workflow usable even when one collector breaks.
            generation_error = _redact_text(str(exc), limit=4000)
            import io
            import traceback
            import zipfile

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('README.md', '# PAC environment debug bundle\n\nBundle generation hit an unexpected top-level error, but PAC still produced this downloadable fallback bundle.\n')
                zf.writestr('support-summary.md', f'# PAC environment debug support summary\n\nGeneration failed before normal collectors completed.\n\nError: {generation_error}\n')
                zf.writestr('generation/top-level-error.txt', _redact_text(''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)), limit=20000))
                zf.writestr('environment/runtime.json', _json_bytes({'generated_at': datetime.now(timezone.utc).isoformat(), 'error': generation_error}))
            data = buf.getvalue()
        path.write_bytes(data)
        record = _bundle_record(path)
        event_type = 'environment_debug_bundle_generated' if generation_error is None else 'environment_debug_bundle_generated_with_errors'
        store.add_event(Event(
            session_id='system',
            type=event_type,
            message=f'Environment debug bundle generated: {path.name}',
            data={'bundle': record, 'generation_error': generation_error},
        ))
        return {'bundle': record, 'ready': True, 'generation_error': generation_error}

    @router.get('/v1/debug-bundles/{bundle_id}/download')
    def download_debug_bundle(bundle_id: str, _auth: Any = Depends(require_auth)) -> FileResponse:
        root = _bundle_root(config)
        path = _safe_bundle_path(root, bundle_id)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail='Debug bundle has not been generated yet')
        return FileResponse(path, filename=path.name, media_type='application/zip')

    @router.delete('/v1/debug-bundles/{bundle_id}')
    def delete_debug_bundle(bundle_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        root = _bundle_root(config)
        path = _safe_bundle_path(root, bundle_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail='Debug bundle not found')
        path.unlink()
        return {'deleted': path.name}

    return router
