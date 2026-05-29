from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse


AuthDependency = Callable[..., Any]
StatusPathProvider = Callable[[], Path]
ArtifactProvider = Callable[[], list[dict[str, Any]]]
McpDirProvider = Callable[[], Path]
StatusWriter = Callable[[str, str, list[dict[str, Any]] | None, list[str] | None], None]
BuildEventWriter = Callable[..., None]
Builder = Callable[[str | None, str | None], None]


def create_mcp_router(
    *,
    require_auth: AuthDependency,
    pac_version: str,
    status_file: StatusPathProvider,
    artifacts: ArtifactProvider,
    mcp_dir: McpDirProvider,
    write_status: StatusWriter,
    build_event: BuildEventWriter,
    run_builder: Builder,
) -> APIRouter:
    """Routes for the Zed MCP bridge build/download workflow."""
    router = APIRouter()

    @router.post('/v1/mcp/build')
    def build_mcp_bridge(background_tasks: BackgroundTasks, runtime: str | None = None, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        build_id = uuid.uuid4().hex[:12]
        write_status('queued', 'pacctl MCP build queued from Sources / binaries / pacctl', None, None)
        build_event(build_id, 'mcp_build_queued', 'pacctl MCP build queued from Sources')
        background_tasks.add_task(run_builder, runtime, build_id)
        return {'ok': True, 'status': 'queued', 'build_id': build_id, 'status_url': '/v1/mcp/build/status'}

    @router.get('/v1/mcp/build/status')
    def mcp_build_status(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        path = status_file()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                data = {'status': 'unknown', 'message': 'Status file could not be parsed'}
        else:
            data = {'status': 'not_built', 'message': 'No pacctl MCP build has run yet.'}
        data['artifacts'] = artifacts()
        data['version'] = pac_version
        return data

    @router.get('/v1/mcp/download/{filename}')
    def mcp_download(filename: str, _auth: Any = Depends(require_auth)) -> FileResponse:
        if '/' in filename or '\\' in filename or filename.startswith('.'):
            raise HTTPException(status_code=400, detail='Invalid filename')
        root = mcp_dir().resolve()
        path = (root / 'bin' / filename).resolve()
        if root not in path.parents:
            raise HTTPException(status_code=400, detail='Invalid path')
        if not path.is_file():
            raise HTTPException(status_code=404, detail='MCP binary not found')
        return FileResponse(path, filename=filename, media_type='application/octet-stream')

    return router
