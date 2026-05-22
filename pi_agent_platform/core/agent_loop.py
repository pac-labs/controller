from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .config import AppConfig
from .models import Session, SessionStatus, Task, TaskStatus
from .providers import chat_complete, effective_context
from .agent_plans import generate_plan
from .runtime import ensure_workspace
from .store import store
from .agent_run_lifecycle import AgentRunLifecycle
from .agent_context_manager import AgentContextManager
from .agent_events import AgentEvents
from .agent_prompt_context import build_agent_prompt_context
from .profiles import profile_context_name, profile_planner_context_name
from .agent_response_parser import (
    _extract_json,
    _looks_like_wrapped_tool_markup,
)
from .agent_action_recovery import _summarize_model_action
from .agent_final_answer_policy import (
    AcceptFinal,
    ConvertToToolCall,
    RejectAndContinue,
    evaluate as evaluate_final_answer,
)


from .agent_tools import execute_tool


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
    planning_model = task.metadata.get('planner_model') or task.metadata.get('model') or session.model
    decision_model = task.metadata.get('model') or session.model
    ctx = effective_context(config, decision_model, context_name)
    context_manager = AgentContextManager(session, task, config, model_name=decision_model, context_profile=context_name)
    full_control = session.permission_profile == "full-control"
    events = AgentEvents(session, task)
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

    prompt_context = build_agent_prompt_context(session, task, config, agent=agent)
    messages = prompt_context.messages
    controller_guidance = prompt_context.controller_guidance
    controller_context = prompt_context.controller_runtime_context
    index_briefing = prompt_context.workspace_index_briefing
    task.metadata["workspace_index"] = prompt_context.workspace_index
    store.add_task(task)
    events.workspace_indexed(prompt_context.workspace_index_event_data)

    if task.metadata.get("always_plan", True) and not task.metadata.get("plan_generated"):
        plan = await generate_plan(
            config,
            model=planning_model,
            prompt=task.prompt,
            extra_context=[controller_guidance or "", controller_context or "", index_briefing or ""],
        )
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
        observation, paused = await execute_tool(session, task, pending.get("tool", ""), pending.get("input", {}), config)
        if paused:
            return task
        messages.append({"role": "assistant", "content": json.dumps(pending)})
        messages.append({"role": "user", "content": "Tool result:\n" + observation})
    max_runtime_minutes = max(1, int(task.metadata.get("max_runtime_minutes") or (getattr(agent, "max_runtime_minutes", 60) if agent else 60)))
    deadline = time.monotonic() + (max_runtime_minutes * 60)
    transcript: list[dict[str, Any]] = task.metadata.get("agent_transcript") or []
    lifecycle = AgentRunLifecycle(session, task, config, transcript)
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
        messages = await context_manager.maybe_compact(messages, source="threshold")

        remaining_seconds = max(0, int(deadline - time.monotonic()))
        if step == 1 or step % 10 == 0:
            events.agent_thinking(
                step=step,
                input_tokens=context_manager.estimate_messages(messages),
                input_budget_tokens=context_manager.input_budget_tokens,
                remaining_seconds=remaining_seconds,
            )
        try:
            raw = await asyncio.to_thread(chat_complete, config, decision_model, messages, max_tokens=min(ctx["reserve_output_tokens"], 4096))
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
            observation, paused = await execute_tool(session, task, tool, inp, config)
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
            messages.append({"role": "user", "content": "Tool result:\n" + observation})
            messages = context_manager.keep_recent_window(messages)
            continue

        messages.append({"role": "user", "content": "Invalid action. Return either a final answer or a valid tool_call JSON object."})
