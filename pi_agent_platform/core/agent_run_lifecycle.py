from __future__ import annotations

from typing import Any

from .checkpoint import save_checkpoint
from .config import AppConfig
from .models import Session, SessionStatus, Task, TaskStatus
from .agent_events import AgentEvents
from .store import store
from .workspace_lessons import save_lesson


def _status_value(status: Any) -> str:
    return str(status.value) if hasattr(status, "value") else str(status)


class AgentRunLifecycle:
    """Shared checkpoint, completion, stop, timeout, and failure handling for agent runs."""

    def __init__(self, session: Session, task: Task, config: AppConfig, transcript: list[dict[str, Any]]):
        self.session = session
        self.task = task
        self.config = config
        self.transcript = transcript
        self.events = AgentEvents(session, task)

    async def checkpoint(
        self,
        *,
        step: int,
        messages: list[dict[str, str]],
        rolling_summary: str | None = None,
        transcript: list[dict[str, Any]] | None = None,
        output: str | None = None,
        task_status: str | None = None,
        emit_event: bool = False,
    ) -> str | None:
        """Persist resumable run state without letting checkpoint failures break execution."""
        active_transcript = transcript if transcript is not None else self.transcript
        try:
            checkpoint_path = save_checkpoint(
                session_id=self.session.id,
                task_id=self.task.id,
                step=step,
                rolling_summary=rolling_summary or "",
                messages=messages[-20:],
                transcript=active_transcript[-20:],
                workspace_path=self.session.workspace_path or "",
                agent_profile=self.session.agent_profile or "",
                model=self.session.model or "",
                prompt=self.task.prompt or "",
                output=output if output is not None else (self.task.output or ""),
                task_status=task_status or _status_value(self.task.status),
                session_status=_status_value(self.session.status),
                metadata=self.task.metadata or {},
            )
            if emit_event:
                self.events.checkpoint_saved(step=step, path=checkpoint_path)
            return checkpoint_path
        except Exception:
            return None

    async def maybe_auto_commit(self) -> None:
        """Auto-commit workspace changes when enabled and available."""
        try:
            from .auto_commit import auto_commit, get_git_changes

            if self.task.status != TaskStatus.completed or not self.session.workspace_path:
                return
            changes = get_git_changes(self.session.workspace_path)
            if not changes.get("has_changes"):
                return
            result = auto_commit(self.session.workspace_path, self.task.prompt or "", self.task.id)
            if result.get("committed"):
                self.events.auto_committed(result)
        except Exception:
            pass

    async def complete(
        self,
        output: str,
        *,
        reason: str = "final",
        step: int | None = None,
        messages: list[dict[str, str]] | None = None,
        rolling_summary: str | None = None,
        checkpoint_output: str | None = None,
        result_model: str | None = None,
        save_lesson: bool = True,
    ) -> Task:
        if step is not None and messages is not None:
            await self.checkpoint(
                step=step,
                messages=messages,
                rolling_summary=rolling_summary,
                output=checkpoint_output if checkpoint_output is not None else output[:2000],
                task_status="completed",
            )
        self.task.status = TaskStatus.completed
        self.task.output = output
        self.task.metadata["agent_transcript"] = self.transcript[-20:]
        if save_lesson:
            self._save_task_lesson()
        store.add_task(self.task)
        self.events.final_result(output=output, data=self._result_event_data(result_model=result_model, reason=reason))
        self.session.status = SessionStatus.created
        store.add_session(self.session)
        await self.maybe_auto_commit()
        return self.task

    async def stop(
        self,
        *,
        latest_task: Task | None = None,
        reason: str = "user_stop",
        output: str = "Agent stopped by user.",
        step: int | None = None,
        messages: list[dict[str, str]] | None = None,
        rolling_summary: str | None = None,
    ) -> Task:
        if latest_task is not None:
            self.task = latest_task
            self.events = AgentEvents(self.session, self.task)
        return await self.complete(
            output,
            reason=reason,
            step=step,
            messages=messages,
            rolling_summary=rolling_summary,
            checkpoint_output=output,
        )

    async def timeout(
        self,
        *,
        max_runtime_minutes: int,
        step: int,
        messages: list[dict[str, str]],
        rolling_summary: str | None = None,
    ) -> Task:
        output = (
            f"Agent stopped after reaching the runtime limit of {max_runtime_minutes} minute(s). "
            "Check the timeline and diff for partial work."
        )
        return await self.complete(
            output,
            reason="runtime_limit",
            step=step,
            messages=messages,
            rolling_summary=rolling_summary,
        )

    async def fail(
        self,
        error: str,
        *,
        step: int | None = None,
        messages: list[dict[str, str]] | None = None,
        rolling_summary: str | None = None,
    ) -> Task:
        if step is not None and messages is not None:
            await self.checkpoint(
                step=step,
                messages=messages,
                rolling_summary=rolling_summary,
                output="",
                task_status="failed",
            )
        self.task.status = TaskStatus.failed
        self.task.error = error
        self.task.metadata["agent_transcript"] = self.transcript[-20:]
        self._save_task_lesson()
        store.add_task(self.task)
        self.events.task_failed(error)
        self.session.status = SessionStatus.created
        store.add_session(self.session)
        return self.task

    def _result_event_data(self, *, result_model: str | None = None, reason: str = "final") -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": "assistant",
            "model": result_model or self.session.model,
            "endpoint_id": self.task.metadata.get("runner_id"),
            "agent_profile": self.session.agent_profile,
            "permission_profile": self.session.permission_profile,
            "reason": reason,
        }
        if reason in {"user_stop", "runtime_limit"}:
            data["stop_reason"] = reason
        return data

    def _save_task_lesson(self) -> None:
        if not self.session.workspace_path:
            return
        category = "task_result"
        title = self.task.prompt[:80] if self.task.prompt else "untitled task"
        files_touched: list[str] = []
        for entry in self.transcript:
            inp = entry.get("input", {})
            if isinstance(inp, dict):
                path = inp.get("path") or inp.get("file") or ""
                if path and path not in files_touched:
                    files_touched.append(path)
            elif isinstance(inp, str) and inp not in files_touched:
                files_touched.append(inp[:200])
        tool_calls = [
            {
                "tool": entry.get("tool"),
                "input": entry.get("input", {}),
                "observation": entry.get("observation", "")[:500],
            }
            for entry in self.transcript[-12:]
        ]
        body_parts: list[str] = []
        if self.task.output:
            body_parts.append(f"Outcome: {self.task.output[:1000]}")
        if self.task.error:
            body_parts.append(f"Error: {self.task.error[:500]}")
        idx = self.task.metadata.get("workspace_index", {})
        if idx:
            body_parts.append(
                f"Workspace: {idx.get('project_type', 'unknown')} project, "
                f"{idx.get('tree', {}).get('file_count', 0)} files indexed"
            )
            projects = idx.get("projects", [])
            if projects:
                body_parts.append(f"Projects: {', '.join(project.get('type', '') for project in projects)}")
        try:
            save_lesson(
                workspace_path=self.session.workspace_path,
                category=category,
                title=title,
                body="\n".join(body_parts) or title,
                tags=["task", self.session.agent_profile or "pi-dev"],
                tool_calls=tool_calls,
                files_touched=files_touched[:20],
            )
        except Exception:
            pass
