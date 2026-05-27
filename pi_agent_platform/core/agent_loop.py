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
from .agent_model_selection import resolve_agent_models, resolve_fallback_model
from .profiles import profile_context_name, profile_planner_context_name
from .agent_response_parser import (
    _extract_json,
    _looks_like_wrapped_tool_markup,
)
from .agent_action_recovery import _summarize_model_action
from .agent_model_calls import run_blocking_provider_call
from .agent_final_answer_policy import (
    AcceptFinal,
    ConvertToToolCall,
    RejectAndContinue,
    evaluate as evaluate_final_answer,
)


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
    ensure_workspace(session)
    if session.metadata.get("agent_enabled") and "printing_press" in config.tools and "printing_press" not in (session.tools or []):
        session.tools = [*(session.tools or []), "printing_press"]
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
    messages = prompt_context.messages
    controller_guidance = prompt_context.controller_guidance
    controller_context = prompt_context.controller_runtime_context
    index_briefing = prompt_context.workspace_index_briefing or ""
    task.metadata["workspace_index"] = prompt_context.workspace_index
    store.add_task(task)
    if prompt_context.workspace_index_event_data and prompt_context.workspace_index_source == "fresh":
        events.workspace_indexed(prompt_context.workspace_index_event_data)

    if resolved_request_intent and resolved_request_intent.should_bootstrap_work:
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
        try:
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
    deadline = time.monotonic() + (max_runtime_minutes * 60)
    empty_model_retries = 0
    step = 0
    while True:
        step += 1
        # Auto-checkpoint every 10 steps
        if step % 10 == 0:
            await lifecycle.checkpoint(
                step=step,
                messages=messages,
                rolling_summary=context_manager.rolling_summary,
                emit_event=True,
            )
        latest_task = store.get_task(task.id) or task
        stop_requested = bool((latest_task.metadata or {}).get("stop_requested"))
        if stop_requested:
            task = await lifecycle.stop(
                latest_task=latest_task,
                reason="user_stop",
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
            "context_compaction_check",
            "Context compaction/check was slow",
            context_manager.maybe_compact(messages, source="threshold"),
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
                    timeout_seconds=int(task.metadata.get("decision_timeout_seconds") or 0) or None,
                    on_abandoned=lambda: events.model_call_abandoned(
                        model=decision_model,
                        call_type="decision",
                        timeout_seconds=int(task.metadata.get("decision_timeout_seconds") or 0),
                    ),
                    on_late_completed=lambda success: events.model_call_late_completed(
                        model=decision_model,
                        call_type="decision",
                        success=success,
                    ),
                ),
                {"model": decision_model, "step": step},
            )
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
            if (latest_task.metadata or {}).get("stop_requested"):
                task = await lifecycle.stop(
                    latest_task=latest_task,
                    reason="user_stop",
                    step=step,
                    messages=messages,
                    rolling_summary=context_manager.rolling_summary,
                )
                return task
            if context_manager.consume_compact_now_request():
                messages = await context_manager.maybe_compact(
                    messages,
                    source="agent_slash_command",
                    force=True,
                )
            messages.append({"role": "assistant", "content": json.dumps(action)})
            recovery_prompt = _tool_observation_requires_recovery(tool, inp, observation, task)
            if recovery_prompt:
                messages.append({"role": "user", "content": recovery_prompt})
            else:
                messages.append({"role": "user", "content": _tool_result_message(str(action.get("tool") or ""), observation)})
            messages = context_manager.keep_recent_window(messages)
            continue

        messages.append({"role": "user", "content": "Invalid action. Return either a final answer or a valid tool_call JSON object."})
