from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


IndexRenderer = Callable[[], HTMLResponse]



UI_PAGE_ROUTES = (
    'dashboard', 'atlas', 'sessions', 'playbooks',
    'ide', 'workspaces', 'tools', 'contexts', 'models', 'profiles',
    'providers', 'endpoints', 'credentials', 'users-groups', 'approvals-policy',
    'updates', 'runtime', 'service-mode', 'network-security', 'proxy-routes', 'raw-config',
    'observability', 'events',
)

def register_ui_routes(app: FastAPI, *, render_index: IndexRenderer, web_dir: Path) -> None:
    """Register the browser UI routes and static asset mount."""

    @app.get('/ui')
    def web_ui_root() -> HTMLResponse:
        return render_index()

    @app.get('/ui/')
    def web_ui_root_slash() -> HTMLResponse:
        return render_index()

    @app.get('/ui/index.html')
    def web_ui_index() -> HTMLResponse:
        return render_index()

    for route in UI_PAGE_ROUTES:
        app.add_api_route(f'/ui/{route}', lambda render_index=render_index: render_index(), methods=['GET'], include_in_schema=False)

    app.mount('/ui', StaticFiles(directory=web_dir, html=True), name='ui')
