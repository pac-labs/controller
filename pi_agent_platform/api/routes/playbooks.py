from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from pi_agent_platform.core.models import Session, Task
from pi_agent_platform.core.playbooks.catalog import get_playbook, load_playbooks
from pi_agent_platform.core.playbooks.io import export_playbook_yaml, import_playbook_yaml
from pi_agent_platform.core.playbooks.runner import advance_run, approve_run, cancel_run, create_run, run_summary
from pi_agent_platform.core.playbooks.state import list_runs, load_run


class PlaybookRunRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    task_id: str | None = None


class PlaybookGateRequest(BaseModel):
    note: str | None = None


class PlaybookImportRequest(BaseModel):
    yaml: str
    overwrite: bool = False


def create_playbooks_router(
    *,
    require_auth: Callable[..., Any],
    config: Any,
    store: Any,
    run_agent_loop: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.get('/v1/playbooks')
    def list_playbooks(_auth: Any = Depends(require_auth)) -> dict[str, Any]:
        playbooks, errors = load_playbooks(config)
        return {'playbooks': [pb.model_dump(mode='json') for pb in playbooks.values()], 'errors': errors}

    @router.post('/v1/playbooks/import')
    def import_playbook(payload: PlaybookImportRequest, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        try:
            playbook = import_playbook_yaml(config, payload.yaml, overwrite=payload.overwrite)
            return {'ok': True, 'playbook': playbook.model_dump(mode='json')}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get('/v1/playbooks/runs')
    def list_playbook_runs(limit: int = 100, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        return {'runs': [run_summary(run) for run in list_runs(limit=limit)]}

    @router.get('/v1/playbooks/{playbook_id}')
    def get_playbook_detail(playbook_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        try:
            return get_playbook(config, playbook_id).model_dump(mode='json')
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get('/v1/playbooks/{playbook_id}/export')
    def export_playbook(playbook_id: str, _auth: Any = Depends(require_auth)) -> Response:
        try:
            text = export_playbook_yaml(config, playbook_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=text, media_type='application/x-yaml', headers={'Content-Disposition': f'attachment; filename="{playbook_id}.yaml"'})

    @router.post('/v1/playbooks/{playbook_id}/runs')
    async def start_playbook(playbook_id: str, payload: PlaybookRunRequest, background_tasks: BackgroundTasks, wait: bool = False, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        try:
            playbook = get_playbook(config, playbook_id)
            session: Session | None = store.get_session(payload.session_id) if payload.session_id else None
            task: Task | None = store.get_task(payload.task_id) if payload.task_id else None
            run = create_run(playbook, payload.parameters, session=session, task=task)
            if wait:
                run = await advance_run(run, config, store, run_agent_loop)
            else:
                background_tasks.add_task(advance_run, run, config, store, run_agent_loop)
            return run_summary(run)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get('/v1/playbooks/runs/{run_id}')
    def get_playbook_run(run_id: str, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        run = load_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail='Playbook run not found')
        return run_summary(run)

    @router.post('/v1/playbooks/runs/{run_id}/resume')
    async def resume_playbook_run(run_id: str, background_tasks: BackgroundTasks, wait: bool = False, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        run = load_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail='Playbook run not found')
        if wait:
            run = await advance_run(run, config, store, run_agent_loop)
        else:
            background_tasks.add_task(advance_run, run, config, store, run_agent_loop)
        return run_summary(run)

    @router.post('/v1/playbooks/runs/{run_id}/approve')
    async def approve_playbook_run(run_id: str, payload: PlaybookGateRequest, background_tasks: BackgroundTasks, wait: bool = False, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        run = load_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail='Playbook run not found')
        if wait:
            run = await approve_run(run_id, config, store, run_agent_loop, note=payload.note)
        else:
            background_tasks.add_task(approve_run, run_id, config, store, run_agent_loop, payload.note)
        return run_summary(run)

    @router.post('/v1/playbooks/runs/{run_id}/cancel')
    def cancel_playbook_run(run_id: str, payload: PlaybookGateRequest, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        try:
            return run_summary(cancel_run(run_id, store, note=payload.note))
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
