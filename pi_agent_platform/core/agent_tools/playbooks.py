from __future__ import annotations

import json
from typing import Any

from ..config import AppConfig
from ..controller_component_context import get_controller_store
from ..models import Session, Task
from ..playbooks.catalog import get_playbook, load_playbooks
from ..playbooks.io import export_playbook_yaml, import_playbook_yaml
from ..playbooks.runner import advance_run, approve_run, cancel_run, create_run, run_summary_json
from ..playbooks.state import list_runs, load_run

_PLAYBOOK_TOOLS = {
    "playbook_list",
    "playbook_start",
    "playbook_status",
    "playbook_resume",
    "playbook_approve",
    "playbook_cancel",
    "playbook_export",
    "playbook_import",
}


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, sort_keys=True)[:20000]


async def try_execute_playbook_tool(
    session: Session,
    task: Task,
    tool: str,
    inp: dict[str, Any],
    config: AppConfig,
    run_agent_loop: Any,
) -> tuple[str, bool] | None:
    if tool not in _PLAYBOOK_TOOLS:
        return None
    store = get_controller_store()
    if store is None:
        return "DENIED: playbook tools require controller store access", False
    try:
        if tool == "playbook_list":
            playbooks, errors = load_playbooks(config)
            return _json({"playbooks": [pb.model_dump(mode="json") for pb in playbooks.values()], "errors": errors}), False
        if tool == "playbook_status":
            run_id = str(inp.get("run_id") or "").strip()
            if run_id:
                run = load_run(run_id)
                if not run:
                    return _json({"ok": False, "error": f"Unknown playbook run: {run_id}"}), False
                return run_summary_json(run), False
            return _json({"runs": [run.model_dump(mode="json") for run in list_runs(limit=int(inp.get("limit") or 20))]}), False
        if tool == "playbook_start":
            playbook_id = str(inp.get("playbook_id") or inp.get("id") or "").strip()
            playbook = get_playbook(config, playbook_id)
            run = create_run(playbook, dict(inp.get("parameters") or {}), session=session, task=task)
            if inp.get("wait") is not False:
                run = await advance_run(run, config, store, run_agent_loop)
            return run_summary_json(run), False
        if tool == "playbook_resume":
            run_id = str(inp.get("run_id") or "").strip()
            run = load_run(run_id)
            if not run:
                return _json({"ok": False, "error": f"Unknown playbook run: {run_id}"}), False
            run = await advance_run(run, config, store, run_agent_loop)
            return run_summary_json(run), False
        if tool == "playbook_approve":
            run = await approve_run(str(inp.get("run_id") or ""), config, store, run_agent_loop, note=inp.get("note"))
            return run_summary_json(run), False
        if tool == "playbook_cancel":
            run = cancel_run(str(inp.get("run_id") or ""), store, note=inp.get("note"))
            return run_summary_json(run), False
        if tool == "playbook_export":
            return export_playbook_yaml(config, str(inp.get("playbook_id") or inp.get("id") or "")), False
        if tool == "playbook_import":
            playbook = import_playbook_yaml(config, str(inp.get("yaml") or ""), overwrite=bool(inp.get("overwrite")))
            return _json({"ok": True, "playbook": playbook.model_dump(mode="json")}), False
    except Exception as exc:
        return _json({"ok": False, "tool": tool, "error": str(exc)}), False
    return None
