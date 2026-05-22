from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Event, Session, Task
from .store import store


@dataclass(slots=True)
class AgentEvents:
    """Typed event emitter for agent runtime timeline events.

    Keep exact event type strings here so UI-facing event names and payload
    shapes do not drift across agent_loop, lifecycle, context, and policy code.
    """

    session: Session
    task: Task

    @property
    def endpoint_id(self) -> Any:
        return self.task.metadata.get("runner_id")

    def emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        store.add_event(
            Event(
                session_id=self.session.id,
                task_id=self.task.id,
                type=event_type,
                message=message,
                data=data or {},
            )
        )

    def assistant_data(self, *, model: str | None = None, step: int | None = None, **extra: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": "assistant",
            "model": model or self.session.model,
            "session_model": self.session.model,
            "endpoint_id": self.endpoint_id,
        }
        if step is not None:
            data["step"] = step
        data.update(extra)
        return data

    def agent_started(
        self,
        *,
        model: str,
        decision_model: str,
        planning_model: str,
        permission_profile: str | None,
        full_control: bool,
        effective_context: dict[str, Any],
        planner_context_profile: str | None,
        endpoint_id: str | None,
        endpoint_locked: Any,
        agent_enabled: bool,
        requested_command: str | None,
        routing: str,
    ) -> None:
        self.emit(
            "agent_loop_started",
            "Agent loop started",
            {
                "model": model,
                "decision_model": decision_model,
                "planning_model": planning_model,
                "permission_profile": permission_profile,
                "full_control": full_control,
                "effective_context": effective_context,
                "planner_context_profile": planner_context_profile,
                "endpoint_id": endpoint_id,
                "endpoint_locked": endpoint_locked,
                "agent_enabled": agent_enabled,
                "requested_command": requested_command,
                "routing": routing,
            },
        )

    def full_control_enabled(self) -> None:
        self.emit(
            "full_control_enabled",
            "FULL CONTROL MODE ENABLED: approvals are bypassed, but every tool action is logged.",
        )

    def workspace_indexed(self, data: dict[str, Any]) -> None:
        self.emit("workspace_indexed", "Workspace indexed", data)

    def agent_plan(self, *, summary: str | None, steps: list[Any], model: str) -> None:
        self.emit(
            "agent_plan",
            summary or "Plan ready",
            {"summary": summary, "steps": steps, "model": model},
        )

    def tool_resumed(self, pending: dict[str, Any]) -> None:
        self.emit("tool_resumed", f"Resuming approved tool: {pending.get('tool')}", pending)

    def agent_thinking(self, *, step: int, input_tokens: int, input_budget_tokens: int, remaining_seconds: int) -> None:
        self.emit(
            "agent_thinking",
            "Thinking",
            {
                "step": step,
                "input_tokens": input_tokens,
                "input_budget_tokens": input_budget_tokens,
                "remaining_seconds": remaining_seconds,
            },
        )

    def model_response_empty(self, *, model: str, step: int, retry: int) -> None:
        self.emit(
            "model_response_empty",
            "Model returned an empty response",
            self.assistant_data(model=model, step=step, retry=retry),
        )

    def model_response(self, *, raw: str, model: str, step: int) -> None:
        self.emit("model_response", raw[-4000:], self.assistant_data(model=model, step=step))

    def tool_call_parse_failed(self, *, raw: str, model: str) -> None:
        self.emit(
            "tool_call_parse_failed",
            "Model returned malformed tool-call markup; requesting a corrected tool call.",
            self.assistant_data(model=model, raw=raw[-4000:]),
        )

    def final_answer_policy_decision(
        self,
        *,
        event_type: str,
        message: str,
        reason: str,
        model: str,
        step: int | None = None,
        raw: str | None = None,
        data: dict[str, Any] | None = None,
        include_session_model: bool = True,
    ) -> None:
        payload = self.assistant_data(model=model, step=step, reason=reason, **(data or {}))
        if not include_session_model:
            payload.pop("session_model", None)
            payload.pop("endpoint_id", None)
        if raw is not None:
            payload["raw"] = raw[-4000:]
        self.emit(event_type, message, payload)

    def agent_intent(self, *, summary: str, model: str, step: int, metadata: dict[str, Any]) -> None:
        self.emit(
            "agent_intent",
            summary,
            self.assistant_data(model=model, step=step, **metadata),
        )

    def tool_call(self, *, tool: str, input: dict[str, Any]) -> None:
        self.emit("tool_call", tool, {"tool": tool, "input": input})


    def tool_started(self, *, tool: str, message: str, data: dict[str, Any] | None = None) -> None:
        payload = {"tool": tool, **(data or {})}
        self.emit("tool_started", message, payload)

    def tool_result(self, *, tool: str, message: str, data: dict[str, Any] | None = None) -> None:
        payload = {"tool": tool, **(data or {})}
        self.emit("tool_result", message, payload)

    def batch_result(self, *, message: str, data: dict[str, Any] | None = None) -> None:
        self.emit("batch_result", message, data or {})

    def approval_required(self, *, message: str, data: dict[str, Any] | None = None) -> None:
        self.emit("approval_required", message, data or {})

    def auto_approved(self, *, reason: str, data: dict[str, Any] | None = None) -> None:
        self.emit("auto_approved", f"Auto-approved: {reason}", data or {})

    def artifact_saved(self, *, name: str, metadata: dict[str, Any]) -> None:
        self.emit("artifact_saved", f"Saved artifact {name}", metadata)

    def runner_job_queued(self, *, tool: str, runner_name: str, data: dict[str, Any]) -> None:
        self.emit("runner_job_queued", f"Queued {tool} on runner {runner_name}", data)

    def model_routing_issue(self, *, message: str, data: dict[str, Any]) -> None:
        self.emit("model_routing_issue", message, data)

    def model_consult(self, *, model_count: int, ok: int, failed: int, models: list[str]) -> None:
        self.emit("model_consult", f"Consulted {model_count} model(s)", {"models": models, "ok": ok, "failed": failed})

    def pty_opened(self, *, pty_session: str, command: str, pid: int) -> None:
        self.emit("pty_opened", f"PTY shell opened: {pty_session}", {"pty_session": pty_session, "command": command, "pid": pid})

    def pty_read(self, *, pty_session: str, bytes_read: int) -> None:
        self.emit("pty_read", f"PTY read {pty_session}: {bytes_read} bytes", {"pty_session": pty_session, "bytes": bytes_read})

    def pty_closed(self, *, pty_session: str, result: dict[str, Any]) -> None:
        self.emit("pty_closed", f"PTY closed: {pty_session}", result)

    def web_fetch(self, *, url: str, source: Any, title: Any) -> None:
        self.emit("web_fetch", f"Fetched {url}", {"url": url, "source": source, "title": title})

    def web_search(self, *, query: str, result_count: int) -> None:
        self.emit("web_search", f"Searched web: {query}", {"query": query, "results": result_count})

    def auto_approve_rule_added(self, rule: dict[str, Any]) -> None:
        self.emit("auto_approve_rule_added", f"Added auto-approve rule: {rule}", rule)

    def checkpoint_saved(self, *, step: int, path: str) -> None:
        self.emit("checkpoint_saved", f"Checkpoint {step} steps", {"step": step, "path": path})

    def final_result(self, *, output: str, data: dict[str, Any]) -> None:
        self.emit("result", output[-4000:], data)

    def task_failed(self, error: str) -> None:
        self.emit("task_failed", error)

    def auto_committed(self, result: dict[str, Any]) -> None:
        self.emit(
            "auto_committed",
            f"Auto-committed: {result.get('sha', '')[:12]}",
            {
                "sha": result.get("sha"),
                "message": result.get("message"),
                "changed_files": result.get("changed_files"),
            },
        )

    def context_compacted(
        self,
        *,
        before_tokens: int,
        after_tokens: int,
        budget_tokens: int,
        input_budget_tokens: int,
        source: str,
        forced: bool = False,
    ) -> None:
        data: dict[str, Any] = {
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "budget_tokens": budget_tokens,
            "input_budget_tokens": input_budget_tokens,
            "source": source,
        }
        if forced:
            data["forced"] = True
        self.emit(
            "context_compacted",
            f"Compacted context from ~{before_tokens} tokens to ~{after_tokens} tokens",
            data,
        )
