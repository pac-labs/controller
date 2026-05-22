from __future__ import annotations

from typing import Any

from ..artifacts import list_artifacts, write_artifact
from ..config import AppConfig
from ..models import Session, Task
from ..agent_events import AgentEvents
from ..web_tools import as_json_text


async def try_execute_artifact_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
) -> tuple[str, bool] | None:
    events = AgentEvents(session, task)
    if tool == "save_artifact":
        name = str(inp.get("name") or "artifact.txt")
        content = str(inp.get("content") or "")
        meta = write_artifact(config.server.data_dir, session.id, task.id, name, content.encode("utf-8"))
        events.artifact_saved(name=name, metadata=meta)
        return as_json_text(meta), False

    if tool == "list_artifacts":
        return as_json_text({"artifacts": list_artifacts(config.server.data_dir, session.id, task.id)}), False

    return None
