from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


IndexRenderer = Callable[[], HTMLResponse]


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

    app.mount('/ui', StaticFiles(directory=web_dir, html=True), name='ui')
