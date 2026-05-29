from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator, ConfigDict

from ..models import now_utc

GateType = Literal["confirm", "review", "approve"]
StepAction = Literal["tool", "agent_task", "subagent_chain", "note", "checkpoint"]
RunStatus = Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]
StepStatus = Literal["pending", "skipped", "running", "waiting", "completed", "failed"]


class PlaybookParameter(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "object", "array"] = "string"
    required: bool = False
    default: Any | None = None
    description: str | None = None
    enum: list[Any] = Field(default_factory=list)


class PlaybookGate(BaseModel):
    type: GateType
    message: str | None = None
    require_note: bool = False


class PlaybookCondition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    param: str | None = None
    output: str | None = None
    equals: Any | None = None
    not_equals: Any | None = None
    contains: Any | None = None
    present: str | None = None
    absent: str | None = None
    status: dict[str, str] | None = None
    all: list["PlaybookCondition"] = Field(default_factory=list)
    any: list["PlaybookCondition"] = Field(default_factory=list)
    not_condition: "PlaybookCondition | None" = Field(default=None, alias="not")


class PlaybookStep(BaseModel):
    id: str
    title: str | None = None
    action: StepAction = "note"
    tool: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    when: PlaybookCondition | None = None
    gate: PlaybookGate | None = None
    timeout_seconds: int | None = None
    target_session_from: str | None = None
    export: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_action(self) -> "PlaybookStep":
        if self.action == "tool" and not self.tool:
            raise ValueError(f"playbook step {self.id} uses action=tool but has no tool")
        if self.action in {"agent_task", "subagent_chain"} and not (self.prompt or "").strip():
            raise ValueError(f"playbook step {self.id} uses {self.action} but has no prompt")
        return self


class Playbook(BaseModel):
    id: str
    title: str
    description: str | None = None
    version: str = "1"
    parameters: list[PlaybookParameter] = Field(default_factory=list)
    steps: list[PlaybookStep]
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_graph(self) -> "Playbook":
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate playbook step id: {step.id}")
            seen.add(step.id)
        missing = sorted({dep for step in self.steps for dep in step.depends_on if dep not in seen})
        if missing:
            raise ValueError(f"unknown playbook step dependencies: {missing}")
        return self


class PlaybookRunStep(BaseModel):
    id: str
    title: str | None = None
    status: StepStatus = "pending"
    message: str | None = None
    output: str | None = None
    task_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlaybookRun(BaseModel):
    id: str = Field(default_factory=lambda: f"pbr_{uuid4().hex[:12]}")
    playbook_id: str
    title: str
    session_id: str | None = None
    task_id: str | None = None
    status: RunStatus = "queued"
    parameters: dict[str, Any] = Field(default_factory=dict)
    steps: list[PlaybookRunStep] = Field(default_factory=list)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    waiting_step_id: str | None = None
    waiting_gate: PlaybookGate | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    cancelled_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = now_utc()
