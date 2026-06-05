from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .config import AppConfig
from .models import Session, SessionStatus, Task, TaskStatus
from .providers import chat_complete, effective_context
from .agent_plans import fallback_plan, generate_plan
from .runtime import ensure_workspace
from .store import store
from .agent_run_lifecycle import AgentRunLifecycle
from .agent_context_manager import AgentContextManager
from .agent_loop_timing import AgentLoopTiming
from .agent_events import AgentEvents
from .agent_prompt_context import build_agent_prompt_context
from .agent_request_policy import classify_request
from .agent_request_intent import resolve_request_intent, should_resolve_request_intent
from .agent_work_contract import evaluate_tool_action as evaluate_work_contract_action
from .agent_model_selection import resolve_agent_models, resolve_fallback_model
from .agent_model_advisor import (
    build_model_upgrade_message,
    recommend_coding_model_upgrade,
    should_escalate_after_validation_failures,
    should_prompt_for_model_upgrade,
    validation_failure_count,
)
from .coding_model_upgrade import stash_pending_model_upgrade
from .agent_planning_policy import should_skip_model_planning
from .profiles import profile_context_name, profile_planner_context_name
from .agent_response_parser import (
    _extract_json,
    _looks_like_wrapped_tool_markup,
)
from .agent_doom_loop import evaluate_after_tool_result, evaluate_before_tool_action
from .agent_action_recovery import _summarize_model_action
from .agent_model_calls import AgentModelCallAborted, run_blocking_provider_call
from .agent_final_answer_policy import (
    AcceptFinal,
    ConvertToToolCall,
    RejectAndContinue,
    evaluate as evaluate_final_answer,
)
from .agent_resource_flow import build_resource_action_sequence, resource_completion_message
from .coding_session_readiness import CodingSessionReadinessError, is_coding_session, prepare_coding_session
from .subagent_chains import should_auto_start_code_chain, start_subagent_chain


from .agent_tools import execute_tool


def _tool_result_message(tool: str, observation: str) -> str:
    tool_name = str(tool or "").strip()
    text = str(observation or "")
    if tool_name == "workspace_manifest":
        summarized = _summarize_workspace_manifest(text)
        if summarized:
            return "Tool result:\n" + summarized
    if len(text) > 6000:
        text = text[:6000] + "\n...[truncated]..."
    return "Tool result:\n" + text


def _tool_observation_requires_recovery(tool: str, inp: dict[str, Any], observation: str, task: Task) -> str:
    text = str(observation or "").strip()
    if not text:
        return ""
    if tool == "read_file_chunk" and text.startswith("File not found:"):
        path = str(inp.get("path") or "").strip()
        missing = dict(task.metadata.get("missing_chunk_paths") or {})
        count = int(missing.get(path) or 0) + 1
        missing[path] = count
        task.metadata["missing_chunk_paths"] = missing
        store.add_task(task)
        return (
            f"The requested file path does not exist: {path or '(missing path)'}. "
            "Do not request more chunks for this same path. "
            "Use list_files, workspace_manifest, or read_file on a verified existing path first."
        )
    if tool == "read_file_chunk":
        try:
            payload = json.loads(text)
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get("error") == "chunk_index out of range":
            path = str(payload.get("path") or inp.get("path") or "").strip()
            return (
                f"Chunking is complete for {path or 'that file'}. "
                "Do not request a higher chunk_index for the same file. "
                "Summarize what you have or inspect a different file."
            )
    return ""


def _summarize_workspace_manifest(observation: str) -> str:
    try:
        payload = json.loads(str(observation or ""))
    except Exception:
        return ""
    parts: list[str] = []
    workspace = str(payload.get("workspace") or "").strip()
    if workspace:
        parts.append(f"workspace: {workspace}")
    project_type = str(payload.get("project_type") or "unknown").strip()
    parts.append(f"project_type: {project_type}")
    tree = payload.get("tree") if isinstance(payload.get("tree"), dict) else {}
    file_count = int(tree.get("file_count") or 0)
    total_bytes = int(tree.get("total_bytes") or 0)
    if file_count:
        parts.append(f"file_count: {file_count}")
    if total_bytes:
        parts.append(f"total_mb: {round(total_bytes / (1024 * 1024), 1)}")
    projects = payload.get("projects") if isinstance(payload.get("projects"), list) else []
    if projects:
        project_bits = []
        for item in projects[:6]:
            if not isinstance(item, dict):
                continue
            project_bits.append(f"{item.get('type') or 'unknown'}:{item.get('file') or item.get('root') or ''}")
        if project_bits:
            parts.append("projects: " + ", ".join(project_bits))
    key_files = payload.get("key_files") if isinstance(payload.get("key_files"), list) else []
    if key_files:
        key_paths = [str(item.get("path") or "") for item in key_files[:12] if isinstance(item, dict) and item.get("path")]
        if key_paths:
            parts.append("key_files: " + ", ".join(key_paths))
    flat_files = payload.get("flat_files") if isinstance(payload.get("flat_files"), list) else []
    if flat_files:
        top_paths = [str(item.get("path") or "") for item in flat_files[:40] if isinstance(item, dict) and item.get("path")]
        if top_paths:
            parts.append("sample_files:\n- " + "\n- ".join(top_paths))
    git_summary = payload.get("git_summary") if isinstance(payload.get("git_summary"), dict) else {}
    branch = str(git_summary.get("branch") or "").strip()
    if branch:
        parts.append(f"git_branch: {branch}")
    return "\n".join(parts)


async def run_agent_loop(session: Session, task: Task, config: AppConfig) -> Task:
    if not is_coding_session(session):
        ensure_workspace(session)
    if session.metadata.get("agent_enabled"):
        auto_tools = [tool for tool in ("printing_press", "spawn_subagent") if tool in config.tools and tool not in (session.tools or [])]
        if auto_tools:
            session.tools = [*(session.tools or []), *auto_tools]
            store.add_session(session)
    task.metadata["agent_loop"] = True
    task.status = TaskStatus.running
    session.status = SessionStatus.running
    store.add_session(session)
    store.add_task(task)

    agent = config.agent_profiles.get(session.agent_profile or "")
    context_name = profile_context_name(agent, session.context_mode) if agent else session.context_mode
    planner_context_name = profile_planner_context_name(agent, context_name) if agent else context_name
    full_control = session.permission_profile == "full-control"
    events = AgentEvents(session, task)
    timing = AgentLoopTiming(events)
    request_policy = classify_request(session, task)
    task.metadata["request_policy"] = {
        "prompt_kind": request_policy.prompt_kind,
        "needs_workspace_index": request_policy.needs_workspace_index,
        "needs_plan": request_policy.needs_plan,
        "needs_work_intent": request_policy.needs_work_intent,
        "prefer_local_inspection": request_policy.prefer_local_inspection,
        "reason": request_policy.reason,
    }
    if should_auto_start_code_chain(session, task, request_policy):
        started = await start_subagent_chain(
            session,
            task,
            task.prompt,
            config,
            run_agent_loop,
            chain_name="auto_code_change",
        )
        task.status = TaskStatus.running
        task.output = started.get("message") or "Started specialist chain."
        store.add_task(task)
        AgentEvents(session, task).emit(
            "subagent_chain_auto_selected",
            "Large code-change request routed to the specialist chain.",
            {
                "chain": started.get("chain"),
                "profiles": started.get("profiles"),
                "timeline": {
                    "title": "Specialist chain selected",
                    "summary": "PAC selected Explore → Plan → Coder → Verify for this larger code-change request.",
                    "fields": {"Chain": str(started.get("chain") or "auto_code_change")},
                },
            },
        )
        return task
    model_selection = resolve_agent_models(config, session, task, request_policy)
    planning_model = model_selection.planning_model
    decision_model = model_selection.decision_model
    decision_model_fallback_used = False
    if model_selection.switched_decision_model:
        task.metadata["effective_decision_model"] = decision_model
        task.metadata["decision_model_reason"] = model_selection.reason
        store.add_task(task)
        events.model_routing_issue(
            message=f"Using {decision_model} for agent decisions because {session.model} is not configured as a structured agent-work model.",
            data={"executor_model": session.model, "decision_model": decision_model, "reason": model_selection.reason},
        )
    ctx = effective_context(config, decision_model, context_name)
    context_manager = AgentContextManager(session, task, config, model_name=decision_model, context_profile=context_name)
    events.agent_started(
        model=session.model,
        decision_model=decision_model,
        planning_model=planning_model,
        permission_profile=session.permission_profile,
        full_control=full_control,
        effective_context=ctx,
        planner_context_profile=planner_context_name,
        endpoint_id=task.metadata.get("runner_id"),
        endpoint_locked=task.metadata.get("endpoint_locked"),
        agent_enabled=task.metadata.get("agent_enabled", True),
        requested_command=task.metadata.get("requested_command"),
        routing=task.metadata.get("routing", "agent"),
    )
    if full_control:
        events.full_control_enabled()

    if is_coding_session(session):
        try:
            readiness = prepare_coding_session(session, config, task=task)
            task.metadata["coding_readiness"] = readiness
            task.metadata["runner_id"] = task.metadata.get("runner_id") or session.metadata.get("preferred_endpoint")
            task.metadata["container_image"] = task.metadata.get("container_image") or session.metadata.get("container_image")
            store.add_task(task)
        except CodingSessionReadinessError as exc:
            task.status = TaskStatus.failed
            task.error = f"Coding session is not ready: {exc}"
            session.status = SessionStatus.failed
            store.add_session(session)
            store.add_task(task)
            events.final_result(
                output=task.error,
                data={
                    "role": "assistant",
                    "model": session.model,
                    "endpoint_id": session.metadata.get("preferred_endpoint"),
                    "agent_profile": session.agent_profile,
                    "coding_readiness": session.metadata.get("coding_readiness"),
                },
            )
            return task

    transcript: list[dict[str, Any]] = task.metadata.get("agent_transcript") or []
    lifecycle = AgentRunLifecycle(session, task, config, transcript)
    store.add_task(task)

    resolved_request_intent = None
    if should_resolve_request_intent(config, task, request_policy):
        try:
            resolved_request_intent = await timing.around_async(
                "request_intent_model",
                "Request-intent resolution was slow",
                resolve_request_intent(config, session, task, request_policy),
                {"model": session.model, "prompt_kind": request_policy.prompt_kind},
            )
        except Exception:
            resolved_request_intent = None
        task.metadata["request_intent_resolved"] = True
        if resolved_request_intent:
            task.metadata["request_intent"] = {
                "model": resolved_request_intent.model,
                "intent": resolved_request_intent.intent,
                "tool": resolved_request_intent.tool,
                "input": resolved_request_intent.input,
                "needs_plan": resolved_request_intent.needs_plan,
                "reason": resolved_request_intent.reason,
            }
        store.add_task(task)

    include_workspace_index = request_policy.needs_workspace_index and not bool(
        resolved_request_intent and resolved_request_intent.should_bootstrap_work
    )
    try:
        with timing.phase("prompt_context", "Agent prompt/context preparation was slow"):
            prompt_context = build_agent_prompt_context(
                session,
                task,
                config,
                agent=agent,
                include_workspace_index=include_workspace_index,
            )
    except Exception as exc:
        task = await lifecycle.fail(f"Agent prompt preparation failed: {exc}")
        return task
    messages = context_manager.restore_checkpoint_summary_into_messages(prompt_context.messages)
    controller_guidance = prompt_context.controller_guidance
    controller_context = prompt_context.controller_runtime_context
    index_briefing = prompt_context.workspace_index_briefing or ""
    task.metadata["workspace_index"] = prompt_context.workspace_index
    store.add_task(task)
    if prompt_context.workspace_index_event_data and prompt_context.workspace_index_source == "fresh":
        events.workspace_indexed(prompt_context.workspace_index_event_data)

    resource_actions = build_resource_action_sequence(task.prompt or "", transcript)
    if resource_actions:
        for resource_action in resource_actions:
            events.agent_intent(
                summary=f"PAC resource step: {resource_action.tool}",
                model=(resolved_request_intent.model if resolved_request_intent else "heuristic-fallback"),
                step=0,
                metadata={
                    "action_type": "pac_resource_flow",
                    "tool": resource_action.tool,
                    "input": resource_action.input,
                    "reason": resource_action.reason,
                },
            )
            events.tool_call(tool=resource_action.tool, input=resource_action.input)
            try:
                observation, paused = await timing.around_async(
                    "resource_flow_tool",
                    "PAC resource creation step was slow",
                    execute_tool(session, task, resource_action.tool, resource_action.input, config),
                    {"tool": resource_action.tool, "step": 0},
                )
            except Exception as exc:
                task = await lifecycle.fail(f"PAC resource step failed: {resource_action.tool}: {exc}", messages=messages)
                return task
            transcript.append({"step": 0, "tool": resource_action.tool, "input": resource_action.input, "observation": observation[-4000:]})
            task.metadata["agent_transcript"] = transcript[-20:]
            task.metadata["bootstrap_work_completed"] = True
            store.add_task(task)
            if paused:
                await lifecycle.checkpoint(
                    step=0,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                    output="",
                    task_status="approval_required",
                )
                return task
            lowered_observation = str(observation or "").lower()
            if '"ok": false' in lowered_observation or "denied:" in lowered_observation:
                task = await lifecycle.fail(
                    f"PAC resource step failed: {resource_action.tool}: {observation[:1200]}",
                    messages=messages,
                )
                return task
            messages.append({"role": "assistant", "content": json.dumps({"type": "tool_call", "tool": resource_action.tool, "input": resource_action.input})})
            messages.append({"role": "user", "content": _tool_result_message(resource_action.tool, observation)})

        completion_message = resource_completion_message(task.prompt or "", transcript)
        if completion_message:
            task = await lifecycle.complete(
                completion_message,
                reason="pac_resource_flow_completed",
                step=0,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
                checkpoint_output=completion_message[:2000],
            )
            return task

    elif resolved_request_intent and resolved_request_intent.should_bootstrap_work:
        events.agent_intent(
            summary=f"Bootstrap work step: {resolved_request_intent.tool}",
            model=resolved_request_intent.model,
            step=0,
            metadata={
                "action_type": "request_intent",
                "tool": resolved_request_intent.tool,
                "input": resolved_request_intent.input,
                "reason": resolved_request_intent.reason,
            },
        )
        events.tool_call(tool=resolved_request_intent.tool, input=resolved_request_intent.input)
        try:
            observation, paused = await timing.around_async(
                "request_intent_tool",
                "Request-intent bootstrap tool was slow",
                execute_tool(session, task, resolved_request_intent.tool, resolved_request_intent.input, config),
                {"tool": resolved_request_intent.tool, "step": 0},
            )
        except Exception as exc:
            task = await lifecycle.fail(f"Bootstrap work step failed: {resolved_request_intent.tool}: {exc}", messages=messages)
            return task
        transcript.append({"step": 0, "tool": resolved_request_intent.tool, "input": resolved_request_intent.input, "observation": observation[-4000:]})
        task.metadata["agent_transcript"] = transcript[-20:]
        task.metadata["bootstrap_work_completed"] = True
        store.add_task(task)
        if paused:
            await lifecycle.checkpoint(
                step=0,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
                output="",
                task_status="approval_required",
            )
            return task
        messages.append({"role": "assistant", "content": json.dumps({"type": "tool_call", "tool": resolved_request_intent.tool, "input": resolved_request_intent.input})})
        messages.append({"role": "user", "content": _tool_result_message(resolved_request_intent.tool, observation)})

    should_plan = bool(task.metadata.get("plan_only")) or (
        bool(task.metadata.get("always_plan")) if "always_plan" in task.metadata else (
            request_policy.needs_plan or bool((task.metadata.get("request_intent") or {}).get("needs_plan"))
        )
    )
    if should_plan and not task.metadata.get("plan_generated"):
        skip_model_plan, skip_reason = should_skip_model_planning(
            config,
            session,
            planning_model=planning_model,
            decision_model=decision_model,
        )
        try:
            if skip_model_plan:
                plan = fallback_plan(task.prompt)
                task.metadata["plan_generation_mode"] = "fallback_only"
                task.metadata["plan_generation_reason"] = skip_reason
                store.add_task(task)
                events.emit(
                    "agent_plan_skipped",
                    "Skipped the extra planning model call and used the deterministic fallback plan.",
                    {
                        "model": planning_model,
                        "reason": skip_reason,
                        "coding_session": bool(session.metadata.get("coding_session")),
                    },
                )
            else:
                planning_timeout_seconds = max(3, int(task.metadata.get("planning_timeout_seconds") or 12))
                try:
                    plan_abandoned = False

                    def plan_progress(update: dict[str, Any]) -> None:
                        events.model_stream_progress(
                            model=planning_model,
                            step=None,
                            call_type="plan",
                            chars=int(update.get("chars") or 0),
                            preview=str(update.get("preview") or ""),
                        )

                    def plan_abandoned_event() -> None:
                        nonlocal plan_abandoned
                        plan_abandoned = True
                        events.agent_plan_timeout(model=planning_model, timeout_seconds=planning_timeout_seconds, fallback=True)
                        events.model_call_abandoned(model=planning_model, call_type="plan", timeout_seconds=planning_timeout_seconds)

                    def plan_late_completed(success: bool) -> None:
                        events.model_call_late_completed(model=planning_model, call_type="plan", success=success)

                    plan = await timing.around_async(
                        "planning_model",
                        "Planning model call was slow",
                        generate_plan(
                            config,
                            model=planning_model,
                            prompt=task.prompt,
                            extra_context=[controller_guidance or "", controller_context or "", index_briefing or ""],
                            session_id=session.id,
                            task_id=task.id,
                            progress_callback=plan_progress,
                            timeout_seconds=planning_timeout_seconds,
                            on_abandoned=plan_abandoned_event,
                            on_late_completed=plan_late_completed,
                        ),
                        {"model": planning_model, "timeout_seconds": planning_timeout_seconds},
                    )
                    if plan_abandoned:
                        plan = fallback_plan(task.prompt)
                except asyncio.TimeoutError:
                    events.agent_plan_timeout(model=planning_model, timeout_seconds=planning_timeout_seconds, fallback=True)
                    plan = fallback_plan(task.prompt)
        except Exception as exc:
            task = await lifecycle.fail(f"Planning model call failed: {exc}", messages=messages)
            return task
        task.metadata["plan_generated"] = True
        task.metadata["current_plan"] = plan
        store.add_task(task)
        events.agent_plan(summary=plan.get("summary"), steps=plan.get("steps") or [], model=planning_model)
        if task.metadata.get("plan_only"):
            task.status = TaskStatus.completed
            task.output = json.dumps(plan, indent=2)
            store.add_task(task)
            events.final_result(output=task.output, data={"role": "assistant", "model": planning_model, "endpoint_id": task.metadata.get("runner_id"), "agent_profile": session.agent_profile, "permission_profile": session.permission_profile})
            session.status = SessionStatus.created
            store.add_session(session)
            return task

    pending = task.metadata.pop("pending_tool", None)
    if pending:
        events.tool_resumed(pending)
        try:
            observation, paused = await timing.around_async(
                "tool_execution",
                "Resumed tool execution was slow",
                execute_tool(session, task, pending.get("tool", ""), pending.get("input", {}), config),
                {"tool": pending.get("tool", "")},
            )
        except Exception as exc:
            task = await lifecycle.fail(f"Resumed tool failed before producing a result: {exc}", messages=messages)
            return task
        if paused:
            return task
        messages.append({"role": "assistant", "content": json.dumps(pending)})
        messages.append({"role": "user", "content": _tool_result_message(pending.get("tool", ""), observation)})
    max_runtime_minutes = max(1, int(task.metadata.get("max_runtime_minutes") or (getattr(agent, "max_runtime_minutes", 60) if agent else 60)))
    max_agent_steps = int(task.metadata.get("max_agent_steps") or session.metadata.get("max_agent_steps") or getattr(agent, "max_agent_steps", 0) or 0)
    deadline = time.monotonic() + (max_runtime_minutes * 60)
    empty_model_retries = 0
    step = 0
    while True:
        step += 1
        if max_agent_steps and step > max_agent_steps:
            reason = f"agent_step_budget_exhausted:{max_agent_steps}"
            task = await lifecycle.timeout(
                max_runtime_minutes=max_runtime_minutes,
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            task.error = f"Agent turn budget reached after {max_agent_steps} iteration(s)."
            task.metadata["stop_reason"] = reason
            store.add_task(task)
            events.emit(
                "agent_step_budget_exhausted",
                task.error,
                {
                    "step": step,
                    "max_agent_steps": max_agent_steps,
                    "subagent_profile": task.metadata.get("subagent_profile") or session.metadata.get("subagent_profile"),
                },
            )
            return task
        task.metadata["agent_step"] = step
        store.add_task(task)
        # Auto-checkpoint every 10 steps
        if step % 10 == 0:
            await lifecycle.checkpoint(
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
                emit_event=True,
            )
        latest_task = store.get_task(task.id) or task
        stop_requested = bool((latest_task.metadata or {}).get("stop_requested") or (latest_task.metadata or {}).get("cancel_requested"))
        if stop_requested:
            task = await lifecycle.stop(
                latest_task=latest_task,
                reason=str((latest_task.metadata or {}).get("stop_reason") or "user_stop"),
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        if bool((store.get_task(task.id) or task).metadata.get("stop_requested") or (store.get_task(task.id) or task).metadata.get("cancel_requested")):
            latest_task = store.get_task(task.id) or task
            task = await lifecycle.stop(
                latest_task=latest_task,
                reason=str((latest_task.metadata or {}).get("stop_reason") or "user_stop"),
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        if time.monotonic() >= deadline:
            task = await lifecycle.timeout(
                max_runtime_minutes=max_runtime_minutes,
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        messages = await timing.around_async(
            "context_pressure_check",
            "Context pressure/checkpoint/compaction check was slow",
            context_manager.manage_pressure(messages, source="threshold", step=step),
        )
        if context_manager.consume_checkpoint_request():
            await lifecycle.checkpoint(
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
                output=str(task.metadata.get("context_checkpoint_summary") or "")[:2000],
                task_status="running",
                emit_event=True,
            )

        remaining_seconds = max(0, int(deadline - time.monotonic()))
        if step == 1 or step % 10 == 0:
            events.agent_thinking(
                step=step,
                input_tokens=context_manager.estimate_messages(messages),
                input_budget_tokens=context_manager.input_budget_tokens,
                remaining_seconds=remaining_seconds,
            )
        try:
            def decision_progress(update: dict[str, Any]) -> None:
                events.model_stream_progress(
                    model=decision_model,
                    step=step,
                    call_type="decision",
                    chars=int(update.get("chars") or 0),
                    preview=str(update.get("preview") or ""),
                )

            decision_timeout_seconds = int(
                task.metadata.get("decision_timeout_seconds")
                or session.metadata.get("decision_timeout_seconds")
                or task.metadata.get("model_call_timeout_seconds")
                or session.metadata.get("model_call_timeout_seconds")
                or 180
            )

            def decision_should_abort() -> bool:
                latest = store.get_task(task.id) or task
                metadata = latest.metadata or {}
                return bool(
                    metadata.get("stop_requested")
                    or metadata.get("cancel_requested")
                    or latest.status in {TaskStatus.completed, TaskStatus.failed}
                )

            raw = await timing.around_async(
                "decision_model",
                "Decision model call was slow",
                run_blocking_provider_call(
                    lambda: chat_complete(
                        config,
                        decision_model,
                        messages,
                        max_tokens=min(ctx["reserve_output_tokens"], 4096),
                        telemetry={"session_id": session.id, "task_id": task.id, "call_type": "decision", "step": step},
                        progress_callback=decision_progress,
                    ),
                    timeout_seconds=decision_timeout_seconds,
                    on_abandoned=lambda: events.model_call_abandoned(
                        model=decision_model,
                        call_type="decision",
                        timeout_seconds=decision_timeout_seconds,
                    ),
                    on_aborted=lambda: events.emit(
                        "model_call_cancelled",
                        "Provider call was abandoned because the task was stopped.",
                        events.assistant_data(
                            model=decision_model,
                            step=step,
                            call_type="decision",
                            timeout_seconds=decision_timeout_seconds,
                        ),
                    ),
                    on_late_completed=lambda success: events.model_call_late_completed(
                        model=decision_model,
                        call_type="decision",
                        success=success,
                    ),
                    should_abort=decision_should_abort,
                ),
                {"model": decision_model, "step": step, "timeout_seconds": decision_timeout_seconds},
            )
        except AgentModelCallAborted:
            latest_task = store.get_task(task.id) or task
            task = await lifecycle.stop(
                latest_task=latest_task,
                reason=str((latest_task.metadata or {}).get("stop_reason") or "user_stop"),
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        except asyncio.TimeoutError:
            task = await lifecycle.fail(
                f"Model call timed out after {decision_timeout_seconds} seconds.",
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        except Exception as exc:
            task = await lifecycle.fail(
                f"Model call failed: {exc}",
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task

        transcript.append({"step": step, "model": raw})
        if not str(raw or "").strip():
            empty_model_retries += 1
            events.model_response_empty(model=decision_model, step=step, retry=empty_model_retries)
            if not decision_model_fallback_used:
                fallback_model = resolve_fallback_model(
                    config,
                    session,
                    task,
                    decision_model,
                    require_structured=bool(
                        request_policy.needs_plan
                        or request_policy.needs_workspace_index
                        or request_policy.needs_work_intent
                    ),
                )
                if fallback_model:
                    decision_model_fallback_used = True
                    empty_model_retries = 0
                    task.metadata["effective_decision_model"] = fallback_model
                    task.metadata["decision_model_reason"] = f"empty_response_fallback:{decision_model}->{fallback_model}"
                    store.add_task(task)
                    events.model_routing_issue(
                        message=f"{decision_model} returned an empty response; retrying with {fallback_model}.",
                        data={
                            "executor_model": session.model,
                            "decision_model": fallback_model,
                            "previous_decision_model": decision_model,
                            "reason": "empty_response_fallback",
                        },
                    )
                    decision_model = fallback_model
                    ctx = effective_context(config, decision_model, context_name)
                    context_manager = AgentContextManager(
                        session,
                        task,
                        config,
                        model_name=decision_model,
                        context_profile=context_name,
                    )
                    messages.append({
                        "role": "user",
                        "content": "Your previous model returned an empty response. Continue from the same context and return either one final answer or one valid tool_call JSON object now.",
                    })
                    continue
            if empty_model_retries <= 2:
                messages.append({"role": "user", "content": "Your previous response was empty. Based on the latest tool result or context, return either ONE final answer or ONE valid tool_call JSON object now."})
                continue
            task = await lifecycle.fail(
                "Model returned an empty response repeatedly.",
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
            )
            return task
        empty_model_retries = 0
        events.model_response(raw=raw, model=decision_model, step=step)
        try:
            action = _extract_json(raw)
        except Exception:
            if _looks_like_wrapped_tool_markup(raw):
                events.tool_call_parse_failed(raw=raw, model=decision_model)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": 'Your previous reply contained malformed tool-call markup. Return ONE valid JSON object only. If you intend to act, return {"type":"tool_call","tool":"...","input":{...}}. Do not include wrapper markers, pseudo-code, or explanatory narration.'})
                continue
            decision = evaluate_final_answer(
                session=session,
                task=task,
                message=raw,
                transcript=transcript,
                workspace_index=task.metadata.get("workspace_index"),
                config=config,
                reserve_output_tokens=int(ctx.get("reserve_output_tokens") or 1200),
                unstructured=True,
            )
            if isinstance(decision, ConvertToToolCall):
                if "count" in decision.event_data:
                    task.metadata["action_narration_rejections"] = int(decision.event_data.get("count") or 0)
                    store.add_task(task)
                action = {"type": "tool_call", "tool": decision.tool, "input": decision.input}
                events.final_answer_policy_decision(event_type=decision.event_type, message=decision.event_message, reason=decision.reason, model=decision_model, raw=raw, data=decision.event_data, include_session_model=False)
            elif isinstance(decision, RejectAndContinue):
                if decision.reason == "unformatted_action_intent":
                    rejected_count = int(task.metadata.get("action_narration_rejections") or 0) + 1
                    task.metadata["action_narration_rejections"] = rejected_count
                    store.add_task(task)
                    decision.event_data["count"] = rejected_count
                events.final_answer_policy_decision(event_type=decision.event_type, message=decision.event_message, reason=decision.reason, model=decision_model, raw=raw, data=decision.event_data, include_session_model=False)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": decision.corrective_prompt})
                continue
            elif isinstance(decision, AcceptFinal):
                task = await lifecycle.complete(
                    decision.message,
                    reason="unstructured_final",
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                    checkpoint_output=decision.message[:2000],
                )
                return task

        thought_summary, thought_meta = _summarize_model_action(action)
        events.agent_intent(summary=thought_summary, model=decision_model, step=step, metadata=thought_meta)

        if action.get("type") == "final":
            final_message = str(action.get("message") or "")
            decision = evaluate_final_answer(
                session=session,
                task=task,
                message=final_message,
                transcript=transcript,
                workspace_index=task.metadata.get("workspace_index"),
                config=config,
                reserve_output_tokens=int(ctx.get("reserve_output_tokens") or 1200),
            )
            if isinstance(decision, ConvertToToolCall):
                if "count" in decision.event_data:
                    task.metadata["action_narration_rejections"] = int(decision.event_data.get("count") or 0)
                    store.add_task(task)
                action = {"type": "tool_call", "tool": decision.tool, "input": decision.input}
                events.final_answer_policy_decision(event_type=decision.event_type, message=decision.event_message, reason=decision.reason, model=decision_model, step=step, data=decision.event_data)
                thought_summary, thought_meta = _summarize_model_action(action)
                events.agent_intent(summary=thought_summary, model=decision_model, step=step, metadata=thought_meta)
            elif isinstance(decision, RejectAndContinue):
                if decision.reason == "unformatted_action_intent":
                    rejected_count = int(task.metadata.get("action_narration_rejections") or 0) + 1
                    task.metadata["action_narration_rejections"] = rejected_count
                    store.add_task(task)
                    decision.event_data["count"] = rejected_count
                events.final_answer_policy_decision(event_type=decision.event_type, message=decision.event_message, reason=decision.reason, model=decision_model, step=step, data=decision.event_data)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": decision.corrective_prompt})
                continue
            elif isinstance(decision, AcceptFinal):
                task = await lifecycle.complete(
                    decision.message,
                    reason=decision.reason,
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                    checkpoint_output=decision.message[:2000],
                )
                return task

        if action.get("type") == "tool_call":
            contract_decision = evaluate_work_contract_action(task.prompt or "", transcript, action)
            if not contract_decision.allow:
                events.final_answer_policy_decision(
                    event_type="work_contract_enforced",
                    message=contract_decision.event_message or "Work contract enforced a safer next step.",
                    reason=contract_decision.reason,
                    model=decision_model,
                    step=step,
                    data=contract_decision.event_data,
                )
                if contract_decision.replacement_action:
                    action = contract_decision.replacement_action
                    thought_summary, thought_meta = _summarize_model_action(action)
                    events.agent_intent(summary=thought_summary, model=decision_model, step=step, metadata=thought_meta)
                else:
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": contract_decision.corrective_prompt})
                    continue

            doom_pre = evaluate_before_tool_action(task, prompt=task.prompt or "", action=action)
            if doom_pre.detected and doom_pre.replacement_action:
                events.doom_loop_detected(
                    message=doom_pre.message or "Doom-loop recovery enforced.",
                    data=doom_pre.data or {},
                )
                action = doom_pre.replacement_action
                thought_summary, thought_meta = _summarize_model_action(action)
                events.agent_intent(summary=thought_summary, model=decision_model, step=step, metadata=thought_meta)

            tool = str(action.get("tool") or "")
            inp = action.get("input") or {}
            events.tool_call(tool=tool, input=inp)
            try:
                observation, paused = await timing.around_async(
                    "tool_execution",
                    "Tool execution was slow",
                    execute_tool(session, task, tool, inp, config),
                    {"tool": tool, "step": step},
                )
            except Exception as exc:
                task = await lifecycle.fail(
                    f"Tool execution failed before producing a result: {tool}: {exc}",
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                )
                return task
            transcript.append({"step": step, "tool": tool, "input": inp, "observation": observation[-4000:]})
            task.metadata["agent_transcript"] = transcript[-20:]
            store.add_task(task)
            if paused:
                await lifecycle.checkpoint(
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                    output="",
                    task_status="approval_required",
                )
                return task
            latest_task = store.get_task(task.id) or task
            if (latest_task.metadata or {}).get("stop_requested") or (latest_task.metadata or {}).get("cancel_requested"):
                task = await lifecycle.stop(
                    latest_task=latest_task,
                    reason=str((latest_task.metadata or {}).get("stop_reason") or "user_stop"),
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                )
                return task
            if context_manager.consume_compact_now_request():
                messages = await context_manager.manage_pressure(
                    messages,
                    source="agent_slash_command",
                    step=step,
                    force_checkpoint=True,
                    force_compact=True,
                )
                if context_manager.consume_checkpoint_request():
                    await lifecycle.checkpoint(
                        step=step,
                        messages=messages,
                        rolling_summary=context_manager.rolling_summary,
                        output=str(task.metadata.get("context_checkpoint_summary") or "")[:2000],
                        task_status="running",
                        emit_event=True,
                    )
            messages.append({"role": "assistant", "content": json.dumps(action)})
            recovery_prompt = _tool_observation_requires_recovery(tool, inp, observation, task)
            if recovery_prompt:
                messages.append({"role": "user", "content": recovery_prompt})
            else:
                messages.append({"role": "user", "content": _tool_result_message(str(action.get("tool") or ""), observation)})

            doom_decision = evaluate_after_tool_result(
                task,
                prompt=task.prompt or "",
                step=step,
                tool=tool,
                inp=inp if isinstance(inp, dict) else {},
                observation=observation,
            )
            store.add_task(task)
            if doom_decision.detected:
                if (
                    is_coding_session(session)
                    and not decision_model_fallback_used
                    and should_escalate_after_validation_failures(task)
                ):
                    fallback_model = resolve_fallback_model(
                        config,
                        session,
                        task,
                        decision_model,
                        require_structured=True,
                        prefer_coding=True,
                    )
                    if fallback_model and fallback_model != decision_model:
                        previous_model = decision_model
                        decision_model = fallback_model
                        decision_model_fallback_used = True
                        task.metadata["effective_decision_model"] = fallback_model
                        task.metadata["decision_model_reason"] = f"coding_validation_fallback:{previous_model}->{fallback_model}"
                        store.add_task(task)
                        events.model_routing_issue(
                            message=f"{previous_model} repeated failed validation; retrying coding decisions with {fallback_model}.",
                            data={
                                "reason": "coding_validation_fallback",
                                "previous_decision_model": previous_model,
                                "decision_model": fallback_model,
                                "doom_loop_reason": doom_decision.reason,
                            },
                        )
                        ctx = effective_context(config, decision_model, context_name)
                        context_manager = AgentContextManager(
                            session,
                            task,
                            config,
                            model_name=decision_model,
                            context_profile=context_name,
                        )
                elif is_coding_session(session) and should_prompt_for_model_upgrade(
                    task,
                    fallback_used=decision_model_fallback_used,
                ):
                    current_models = [str(session.model or "").strip(), str(decision_model or "").strip()]
                    recommendation = recommend_coding_model_upgrade(
                        config,
                        session,
                        task,
                        current_models=current_models,
                    )
                    stash_pending_model_upgrade(
                        session,
                        recommendation,
                        current_models=[name for name in current_models if name],
                        failure_count=validation_failure_count(task, window=12),
                    )
                    store.add_session(session)
                    task.metadata["model_upgrade_prompted"] = True
                    task.metadata["model_upgrade_recommendation"] = recommendation
                    store.add_task(task)
                    message = build_model_upgrade_message(
                        recommendation,
                        current_models=[name for name in current_models if name],
                        failure_count=validation_failure_count(task, window=12),
                    )
                    task = await lifecycle.complete(
                        message,
                        reason="coding_model_upgrade_recommended",
                        step=step,
                        messages=messages,
                        rolling_summary=context_manager.rolling_summary,
                        checkpoint_output=message[:2000],
                    )
                    return task
                events.doom_loop_detected(
                    message=doom_decision.message or "Doom loop detected; switching strategy.",
                    data=doom_decision.data or {},
                )
                if doom_decision.replacement_action:
                    recovery_action = doom_decision.replacement_action
                    recovery_tool = str(recovery_action.get("tool") or "")
                    recovery_input = recovery_action.get("input") or {}
                    thought_summary, thought_meta = _summarize_model_action(recovery_action)
                    events.agent_intent(summary=thought_summary, model=decision_model, step=step, metadata={**thought_meta, "doom_loop_recovery": True})
                    events.tool_call(tool=recovery_tool, input=recovery_input)
                    try:
                        recovery_observation, recovery_paused = await timing.around_async(
                            "doom_loop_recovery_tool",
                            "Doom-loop recovery tool was slow",
                            execute_tool(session, task, recovery_tool, recovery_input, config),
                            {"tool": recovery_tool, "step": step, "reason": doom_decision.reason},
                        )
                    except Exception as exc:
                        task = await lifecycle.fail(
                            f"Doom-loop recovery failed before producing a result: {recovery_tool}: {exc}",
                            step=step,
                            messages=messages,
                            rolling_summary=context_manager.rolling_summary,
                        )
                        return task
                    transcript.append({"step": step, "tool": recovery_tool, "input": recovery_input, "observation": recovery_observation[-4000:], "doom_loop_recovery": True})
                    task.metadata["agent_transcript"] = transcript[-20:]
                    store.add_task(task)
                    messages.append({"role": "assistant", "content": json.dumps(recovery_action)})
                    messages.append({"role": "user", "content": _tool_result_message(recovery_tool, recovery_observation)})
                    if doom_decision.corrective_prompt:
                        messages.append({"role": "user", "content": doom_decision.corrective_prompt})
                    if recovery_paused:
                        await lifecycle.checkpoint(
                            step=step,
                            messages=messages,
                            rolling_summary=context_manager.rolling_summary,
                            output="",
                            task_status="approval_required",
                        )
                        return task
                elif doom_decision.corrective_prompt:
                    messages.append({"role": "user", "content": doom_decision.corrective_prompt})
            messages = context_manager.keep_recent_window(messages)
            continue

        messages.append({"role": "user", "content": "Invalid action. Return either a final answer or a valid tool_call JSON object."})
