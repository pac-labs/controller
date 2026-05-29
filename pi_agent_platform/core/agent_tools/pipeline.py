from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..agent_events import AgentEvents
from ..artifacts import write_artifact
from ..config import AppConfig
from ..models import Session, Task
from ..workspace_index_cache import clear_workspace_index
from .permission_guard import PermissionGuard
from .pipeline_approval import approval_message, should_pause_for_approval
from .pipeline_hooks import run_post_hooks, run_pre_hooks
from .pipeline_metrics import pipeline_stage, record_pipeline_stage
from .pipeline_schema import describe_tool_schema, validate_tool_input
from .pipeline_policy import (
    cache_enabled_for_tool,
    is_enabled_in_session,
    is_mutating_tool,
    is_path_scoped_tool,
    path_keys_for_tool,
    is_plan_mode,
    is_read_only_tool,
    path_problem,
    permission_class_for_tool,
    required_fields,
)

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]


@dataclass(slots=True)
class PipelineDecision:
    observation: str
    paused: bool = False


@dataclass(slots=True)
class ToolCallContext:
    session: Session
    task: Task
    tool: str
    input: dict[str, Any]
    config: AppConfig
    permission: Any

    @property
    def events(self) -> AgentEvents:
        return AgentEvents(self.session, self.task)


@dataclass(slots=True)
class ToolCacheEntry:
    created_at: float
    value: tuple[str, bool]


_CACHE: dict[str, ToolCacheEntry] = {}
_CACHE_TTL_SECONDS = 20
_ARTIFACT_THRESHOLD = 60_000


def _cache_key(context: ToolCallContext) -> str:
    raw = json.dumps(
        {
            "session_id": context.session.id,
            "workspace": context.session.workspace_path,
            "tool": context.tool,
            "input": context.input,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ToolPipeline:
    """Shared guardrail pipeline for every agent tool execution.

    Handlers still own tool-specific behavior, but every tool call now passes
    through the same outer contract for argument normalization, schema checks,
    path sanity, plan-mode guardrails, capability checks, cache/artifact policy,
    and post-execution invalidation.
    """

    def __init__(self, context: ToolCallContext) -> None:
        self.context = context
        self.events = context.events

    async def execute(self, executor: ToolExecutor) -> tuple[str, bool]:
        started = time.perf_counter()
        try:
            if decision := self._run_stage("parse", self._parse_arguments):
                return decision.observation, decision.paused
            if decision := self._run_stage("schema", self._validate_schema):
                return decision.observation, decision.paused
            if decision := self._run_stage("path_sanity", self._sanity_check_paths):
                return decision.observation, decision.paused
            if decision := self._run_stage("plan_mode", self._plan_mode_guard):
                return decision.observation, decision.paused
            if decision := self._run_stage("capability", self._capability_check):
                return decision.observation, decision.paused
            if decision := self._run_stage("approval", self._approval_check):
                return decision.observation, decision.paused
            if cached := self._run_stage("cache", self._cache_lookup):
                return cached

            self._run_stage("pre_hook", self._pre_hook)
            with pipeline_stage(self.context.tool, "execute"):
                result = await executor(self.context.tool, self.context.input)
            result = self._run_stage("post_hook", lambda: self._post_hook(result))
            self._run_stage("cache_write", lambda: self._cache_write(result))
            self._run_stage("invalidation", self._invalidate_if_needed)
            return result
        finally:
            total_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            record_pipeline_stage(self.context.tool, "total", total_ms)

    def _run_stage(self, name: str, callback):
        with pipeline_stage(self.context.tool, name):
            return callback()

    def _parse_arguments(self) -> PipelineDecision | None:
        if isinstance(self.context.input, dict):
            return None
        return PipelineDecision("DENIED: tool input must be a JSON object", False)

    def _validate_schema(self) -> PipelineDecision | None:
        missing = [key for key in required_fields(self.context.tool, self.context.config) if key not in self.context.input]
        problems = validate_tool_input(self.context.tool, self.context.input, self.context.config)
        if missing:
            legacy_missing = f"missing required input field(s): {', '.join(missing)}"
            if legacy_missing not in problems:
                problems.insert(0, legacy_missing)
        if problems:
            schema_summary = describe_tool_schema(self.context.tool, self.context.config)
            self.events.emit(
                "tool_pipeline_schema_invalid",
                f"Tool input schema rejected: {self.context.tool}",
                {
                    "tool": self.context.tool,
                    "problems": problems,
                    "expected": schema_summary,
                    "timeline": {
                        "title": f"Invalid input for {self.context.tool}",
                        "summary": "; ".join(problems),
                        "fields": {
                            "tool": self.context.tool,
                            "required": ", ".join(schema_summary.get("required") or []) or "none",
                        },
                        "steps": [
                            {"status": "error", "label": problem, "detail": "The tool call was stopped before execution."}
                            for problem in problems[:6]
                        ],
                    },
                },
            )
            expected = ", ".join(schema_summary.get("required") or []) or "see tool schema"
            return PipelineDecision(
                f"DENIED: {self.context.tool} input schema violation: {'; '.join(problems)}. Expected required fields: {expected}",
                False,
            )
        return None

    def _sanity_check_paths(self) -> PipelineDecision | None:
        if not is_path_scoped_tool(self.context.tool, self.context.config):
            return None
        path_keys = path_keys_for_tool(self.context.tool, self.context.config)
        for key, value in self.context.input.items():
            if key not in path_keys:
                continue
            if problem := path_problem(value):
                return PipelineDecision(f"DENIED: invalid {key} for {self.context.tool}: {problem}", False)
        return None

    def _plan_mode_guard(self) -> PipelineDecision | None:
        if is_plan_mode(self.context.session, self.context.task) and is_mutating_tool(self.context.tool, self.context.config):
            return PipelineDecision(f"DENIED: {self.context.tool} cannot run while this session is in plan mode", False)
        return None

    def _capability_check(self) -> PipelineDecision | None:
        tool_config = self.context.config.tools.get(self.context.tool)
        if tool_config is not None and not tool_config.enabled:
            return PipelineDecision(f"DENIED: {self.context.tool} is disabled in PAC configuration", False)
        enabled_tools = set(self.context.session.tools or [])
        if not is_enabled_in_session(self.context.tool, enabled_tools):
            return PipelineDecision(f"DENIED: {self.context.tool} is not enabled for this session", False)
        guard = PermissionGuard(self.context.permission)
        permission_class = permission_class_for_tool(self.context.tool, self.context.config)
        if permission_class:
            if denied := guard.require(permission_class):
                return PipelineDecision(*denied)
        if is_read_only_tool(self.context.tool, self.context.config) and self.context.tool not in {"web_search", "web_fetch", "consult_model", "remote_memory", "lessons", "pac_list_components"}:
            if denied := guard.require("file_read"):
                return PipelineDecision(*denied)
        return None


    def _approval_check(self) -> PipelineDecision | None:
        paused, reason, data = should_pause_for_approval(
            self.context.tool,
            self.context.input,
            self.context.session,
            self.context.task,
            self.context.config,
            self.context.permission,
        )
        if reason and reason.startswith("DENIED:"):
            self.events.emit(
                "tool_pipeline_denied",
                f"Tool pipeline denied {self.context.tool}",
                {"tool": self.context.tool, "reason": reason},
            )
            return PipelineDecision(reason, False)
        if data.get("auto_approved"):
            self.events.auto_approved(reason=reason or "pipeline auto-approval", data={"tool": self.context.tool, **data})
            return None
        if paused:
            message = approval_message(self.context.tool, self.context.input, reason)
            self.events.approval_required(message=message, data=data)
            return PipelineDecision("APPROVAL_REQUIRED", True)
        return None

    def _cache_lookup(self) -> tuple[str, bool] | None:
        if not cache_enabled_for_tool(self.context.tool, self.context.config):
            return None
        key = _cache_key(self.context)
        entry = _CACHE.get(key)
        if not entry or time.time() - entry.created_at > _CACHE_TTL_SECONDS:
            return None
        self.events.emit("tool_pipeline_cache_hit", f"Tool cache hit: {self.context.tool}", {"tool": self.context.tool})
        return entry.value

    def _pre_hook(self) -> None:
        self.events.emit(
            "tool_pipeline_started",
            f"Tool pipeline started: {self.context.tool}",
            {
                "tool": self.context.tool,
                "stages": [
                    "parse",
                    "schema",
                    "path_sanity",
                    "plan_mode",
                    "capability",
                    "approval",
                    "cache",
                    "pre_hook",
                    "execute",
                    "post_hook",
                    "artifact_storage",
                    "cache_write",
                    "invalidation",
                ],
            },
        )
        for result in run_pre_hooks(self.context.config, self.context.tool, self.context.input):
            self.events.emit(
                "tool_pipeline_hook",
                result.message or f"Pre-hook completed for {self.context.tool}",
                {"tool": self.context.tool, "phase": "pre", "ok": result.ok, **(result.data or {})},
            )
            if not result.ok:
                raise RuntimeError(result.message or f"Pre-hook failed for {self.context.tool}")

    def _post_hook(self, result: tuple[str, bool]) -> tuple[str, bool]:
        observation, paused = result
        if isinstance(observation, str) and len(observation) > _ARTIFACT_THRESHOLD:
            digest = hashlib.sha256(observation.encode("utf-8", errors="replace")).hexdigest()[:12]
            artifact_name = f"tool-results/{self.context.tool}-{digest}.txt"
            metadata = write_artifact(
                self.context.config.server.data_dir,
                self.context.session.id,
                self.context.task.id,
                artifact_name,
                observation.encode("utf-8", errors="replace"),
            )
            self.events.emit("tool_pipeline_artifact_stored", f"Stored large {self.context.tool} result as an artifact", metadata)
            summary = {
                "tool": self.context.tool,
                "artifact": metadata,
                "preview": observation[:4000],
                "truncated": True,
                "original_chars": len(observation),
            }
            observation = json.dumps(summary, indent=2)
        for hook_result in run_post_hooks(self.context.config, self.context.tool, self.context.input, str(observation or ""), paused):
            self.events.emit(
                "tool_pipeline_hook",
                hook_result.message or f"Post-hook completed for {self.context.tool}",
                {"tool": self.context.tool, "phase": "post", "ok": hook_result.ok, **(hook_result.data or {})},
            )
            if not hook_result.ok:
                observation = f"DENIED: post-hook failed for {self.context.tool}: {hook_result.message}"
                paused = False
        self.events.emit(
            "tool_pipeline_completed",
            f"Tool pipeline completed: {self.context.tool}",
            {"tool": self.context.tool, "paused": paused, "result_chars": len(str(observation or ""))},
        )
        return observation, paused

    def _cache_write(self, result: tuple[str, bool]) -> None:
        if not cache_enabled_for_tool(self.context.tool, self.context.config):
            return
        _CACHE[_cache_key(self.context)] = ToolCacheEntry(created_at=time.time(), value=result)

    def _invalidate_if_needed(self) -> None:
        if not is_mutating_tool(self.context.tool, self.context.config):
            return
        _CACHE.clear()
        try:
            clear_workspace_index(Path(self.context.session.workspace_path))
        except Exception:
            pass
        self.events.emit("tool_pipeline_invalidated", f"Invalidated workspace caches after {self.context.tool}", {"tool": self.context.tool})
