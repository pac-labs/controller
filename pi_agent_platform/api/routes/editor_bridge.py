from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from pi_agent_platform.core.editor_session_context import editor_session_summary
from pi_agent_platform.core.models import Event, Session


class EditorStatePayload(BaseModel):
    editor: str | None = None
    workspace_root: str | None = None
    active_file: str | None = None
    open_files: list[str] = Field(default_factory=list)
    selected_text: str | None = None
    selection_start_line: int | None = None
    selection_end_line: int | None = None
    language_id: str | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EditorBootstrapPayload(EditorStatePayload):
    origin: str = "zed"
    context_id: str | None = None
    workspace_id: str | None = None


def create_editor_bridge_router(
    *,
    require_auth: Callable[..., Any],
    store: Any,
    session_resource_ref: Callable[[Session], tuple[str, str]],
    require_resource_access: Callable[..., None],
    can_use_agent_context: Callable[[Any, Any], bool],
    ensure_agent_context_session: Callable[[Any, Any], Session],
    workspace_owner: Callable[[Any], tuple[str, str]],
    can_resource_access: Callable[..., bool],
    ensure_user_workspace_session: Callable[[Any, Any], Session],
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/editor/bootstrap")
    def bootstrap_editor_session(payload: EditorBootstrapPayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        session: Session | None = None
        context_payload: dict[str, Any] | None = None
        workspace_payload: dict[str, Any] | None = None

        if payload.context_id:
            item = store.get_agent_context(payload.context_id)
            if not item:
                raise HTTPException(status_code=404, detail="Agent context not found")
            if not can_use_agent_context(item, _auth):
                raise HTTPException(status_code=403, detail="Agent context not available")
            session = ensure_agent_context_session(item, _auth)
            context_payload = {"id": item.id, "name": item.name, "kind": item.kind}
        elif payload.workspace_id:
            workspace = store.get_user_workspace(payload.workspace_id)
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            owner_id, _ = workspace_owner(_auth)
            if not can_resource_access(_auth, "workspace", f"user:{workspace.id}", "use", owner_id=workspace.owner_id):
                raise HTTPException(status_code=403, detail="Workspace not available")
            session = ensure_user_workspace_session(workspace, _auth)
            workspace_payload = {"id": workspace.id, "name": workspace.name}
        else:
            raise HTTPException(status_code=400, detail="context_id or workspace_id is required")

        _apply_editor_state(session, payload, payload.origin, store)
        return {
            "ok": True,
            "session": session.model_dump(mode="json"),
            "context": context_payload,
            "workspace": workspace_payload,
            "summary": editor_session_summary(session.metadata),
        }

    @router.post("/v1/editor/sessions/{session_id}/state")
    def update_editor_session_state(session_id: str, payload: EditorStatePayload, _auth: Any = Depends(require_auth)) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        resource_type, resource_id = session_resource_ref(session)
        require_resource_access(_auth, resource_type, resource_id, "write", reason="Update editor session state", session_id=session.id)
        origin = str(session.metadata.get("session_origin") or payload.editor or "editor").strip() or "editor"
        _apply_editor_state(session, payload, origin, store)
        return {"ok": True, "session": session.model_dump(mode="json"), "summary": editor_session_summary(session.metadata)}

    return router


def _apply_editor_state(session: Session, payload: EditorStatePayload, origin: str, store: Any) -> None:
    state = {
        "editor": payload.editor or origin,
        "workspace_root": payload.workspace_root,
        "active_file": payload.active_file,
        "open_files": [str(item).strip() for item in (payload.open_files or []) if str(item).strip()],
        "selected_text": payload.selected_text,
        "selection_start_line": payload.selection_start_line,
        "selection_end_line": payload.selection_end_line,
        "language_id": payload.language_id,
        "diagnostics": [item for item in (payload.diagnostics or []) if isinstance(item, dict)],
        "metadata": dict(payload.metadata or {}),
    }
    metadata = dict(session.metadata or {})
    metadata["session_origin"] = origin
    metadata["editor_state"] = state
    metadata["editor_attached"] = True
    if state["open_files"]:
        metadata["open_files"] = state["open_files"]
    session.metadata = metadata
    session.touch()
    store.add_session(session)
    store.add_event(
        Event(
            session_id=session.id,
            type="editor_state_updated",
            message=editor_session_summary(session.metadata),
            data={
                "origin": origin,
                "active_file": state["active_file"],
                "open_files": state["open_files"],
                "language_id": state["language_id"],
            },
        )
    )
