from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig
from .models import Session, Task
from .agent_action_recovery import (
    _consult_prompt_from_final_message,
    _infer_tool_call_from_action_narration,
    _looks_like_unexecuted_consult_request,
    _should_reject_unformatted_action,
)
from .agent_inspection_policy import (
    has_meaningful_codebase_inspection,
    inspection_depth_score,
    is_broad_codebase_request,
    looks_like_generic_ready_response,
    prompt_requests_codebase_inspection,
)


@dataclass(slots=True)
class AcceptFinal:
    message: str
    reason: str = "final"


@dataclass(slots=True)
class RejectAndContinue:
    reason: str
    corrective_prompt: str
    event_type: str = "final_answer_rejected"
    event_message: str = "Final answer rejected by policy."
    event_data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConvertToToolCall:
    tool: str
    input: dict[str, Any]
    reason: str
    event_type: str = "final_answer_converted"
    event_message: str = "Final answer converted into a tool call by policy."
    event_data: dict[str, Any] = field(default_factory=dict)


FinalAnswerDecision = AcceptFinal | RejectAndContinue | ConvertToToolCall


_ACTION_NARRATION_CORRECTIVE_PROMPT = (
    "Your previous final answer was an intention to do work, not the completed answer. "
    "Convert that intention into exactly ONE structured tool_call JSON object now, "
    "or return a final answer only if the work is already complete."
)


_UNSTRUCTURED_ACTION_CORRECTIVE_PROMPT = (
    "You described an action you intend to take, but PAC can only execute actions from structured tool calls. "
    "Return exactly ONE valid JSON object now. If you intend to act, use "
    '{"type":"tool_call","tool":"...","input":{...}}. '
    'Only return {"type":"final","message":"..."} when no further action is needed.'
)


_CODEBASE_INSPECTION_CORRECTIVE_PROMPT = (
    "Before answering this codebase/workspace question, inspect the workspace more deeply. "
    "A shallow response is not acceptable. Use one or more of workspace_manifest, read_file, "
    "read_file_chunk, batch_analyze_file, git_diff, git_status, or shell/rg to gather concrete evidence first."
)


_BROAD_INSPECTION_CORRECTIVE_PROMPT = (
    "This request is still too broad to answer from a shallow scan. "
    "Inspect more deeply before answering: use workspace_manifest or a focused shell search (rg/find), "
    "then read concrete source files that are likely to implement the relevant behavior. "
    "Do not stop after a README or top-level listing."
)


_GENERIC_READY_CORRECTIVE_PROMPT = (
    "Do not give a generic readiness or acknowledgement reply. "
    "Answer the current PAC question directly from the local evidence you already gathered, "
    "or keep inspecting with a concrete tool call if the answer is still incomplete."
)


_WORK_REQUEST_CORRECTIVE_PROMPT = (
    "This request is a work request. Do not stop with a summary yet. "
    "Return exactly one tool_call JSON object that performs the next concrete inspection or execution step."
)


def _tool_decision(action: dict[str, Any], *, reason: str, event_type: str, event_message: str, event_data: dict[str, Any] | None = None) -> ConvertToToolCall:
    return ConvertToToolCall(
        tool=str(action.get("tool") or ""),
        input=action.get("input") or {},
        reason=reason,
        event_type=event_type,
        event_message=event_message,
        event_data={**(event_data or {}), "action": action},
    )


def _consult_tool_call(task: Task, message: str, reserve_output_tokens: int) -> dict[str, Any]:
    return {
        "type": "tool_call",
        "tool": "consult_model",
        "input": {
            "prompt": _consult_prompt_from_final_message(task.prompt or "", message),
            "include_recent_context": True,
            "max_tokens": min(1600, max(800, int(reserve_output_tokens or 1200))),
        },
    }


def _workspace_manifest_tool_call() -> dict[str, Any]:
    return {"type": "tool_call", "tool": "workspace_manifest", "input": {"max_files": 300}}


def evaluate(
    *,
    session: Session,
    task: Task,
    message: str,
    transcript: list[dict[str, Any]],
    workspace_index: dict[str, Any] | None = None,
    config: AppConfig | None = None,
    reserve_output_tokens: int = 1200,
    unstructured: bool = False,
) -> FinalAnswerDecision:
    """Decide whether a model final answer is acceptable.

    The agent loop should not embed final-answer quality gates inline. This
    policy centralizes the cases where a model attempts to stop before doing
    the required work, narrates an action instead of emitting a tool call, or
    asks for another model instead of executing the consult_model tool.
    """
    del workspace_index  # Reserved for richer workspace-aware policies.
    final_message = str(message or "")
    final_tail = final_message[-1000:]

    if _looks_like_unexecuted_consult_request(final_message):
        return _tool_decision(
            _consult_tool_call(task, final_message, reserve_output_tokens),
            reason="unexecuted_consult_model_request",
            event_type="model_routing_issue",
            event_message="Model returned consult_model as a final answer; converting it into an actual consult/fallback step.",
            event_data={"final_message": final_tail},
        )

    request_intent = task.metadata.get("request_intent") if isinstance(task.metadata, dict) else None
    transcript_has_tool_work = any(isinstance(entry, dict) and entry.get("tool") for entry in transcript)
    if (
        isinstance(request_intent, dict)
        and str(request_intent.get("intent") or "").lower() == "work"
        and not transcript_has_tool_work
    ):
        bootstrap_tool = str(request_intent.get("tool") or "").strip()
        bootstrap_input = request_intent.get("input") if isinstance(request_intent.get("input"), dict) else {}
        if bootstrap_tool and bootstrap_tool != "none":
            return _tool_decision(
                {"type": "tool_call", "tool": bootstrap_tool, "input": bootstrap_input},
                reason="work_request_bootstrap_required",
                event_type="final_answer_converted",
                event_message="Work request was answered too early; PAC converted it into the resolved bootstrap tool step.",
                event_data={"final_message": final_tail},
            )
        return RejectAndContinue(
            reason="work_request_requires_action",
            corrective_prompt=_WORK_REQUEST_CORRECTIVE_PROMPT,
            event_type="final_answer_rejected",
            event_message="Final answer rejected because this work request still needs an execution step.",
            event_data={"final_message": final_tail},
        )

    if _should_reject_unformatted_action(session, task, final_message, transcript):
        inferred_action = _infer_tool_call_from_action_narration(final_message, session, task, config) if config else None
        if inferred_action:
            return _tool_decision(
                inferred_action,
                reason="final_unformatted_action_intent",
                event_type="action_narration_converted",
                event_message="Model returned an intended action as a final answer; PAC converted it into the safest matching tool step.",
                event_data={"final_message": final_tail},
            )

        rejected_count = int(task.metadata.get("action_narration_rejections") or 0) + 1
        if rejected_count >= 2 and session.workspace_path:
            return _tool_decision(
                _workspace_manifest_tool_call(),
                reason="repeated_unformatted_action_intent",
                event_type="action_narration_converted",
                event_message="Model repeated an unformatted intention; PAC started with a safe workspace scan.",
                event_data={"final_message": final_tail, "count": rejected_count},
            )

        return RejectAndContinue(
            reason="unformatted_action_intent",
            corrective_prompt=_UNSTRUCTURED_ACTION_CORRECTIVE_PROMPT if unstructured else _ACTION_NARRATION_CORRECTIVE_PROMPT,
            event_type="action_narration_rejected",
            event_message=(
                "Model described an intended action instead of returning a structured tool call; requesting the executable instruction."
                if unstructured else
                "Model returned an intended action as a final answer; requesting a structured tool call instead."
            ),
            event_data={"final_message": final_tail, "count": rejected_count},
        )

    if prompt_requests_codebase_inspection(task.prompt) and not has_meaningful_codebase_inspection(transcript):
        return RejectAndContinue(
            reason="missing_codebase_inspection",
            corrective_prompt=_CODEBASE_INSPECTION_CORRECTIVE_PROMPT,
            event_type="final_answer_rejected",
            event_message="Final answer rejected because the workspace/codebase was not inspected deeply enough.",
        )

    if is_broad_codebase_request(task.prompt) and inspection_depth_score(transcript) < 2.5:
        return RejectAndContinue(
            reason="shallow_broad_codebase_inspection",
            corrective_prompt=_BROAD_INSPECTION_CORRECTIVE_PROMPT,
            event_type="final_answer_rejected",
            event_message="Final answer rejected because the broad codebase request only had shallow inspection evidence.",
            event_data={"depth_score": inspection_depth_score(transcript)},
        )

    if session.metadata.get("controller_harness") and looks_like_generic_ready_response(final_message):
        return RejectAndContinue(
            reason="generic_ready_response",
            corrective_prompt=_GENERIC_READY_CORRECTIVE_PROMPT,
            event_type="final_answer_rejected",
            event_message="Final answer rejected because it was a generic readiness acknowledgement.",
        )

    return AcceptFinal(final_message)
