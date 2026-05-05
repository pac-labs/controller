from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceSpec(BaseModel):
    type: Literal["local", "git", "profile"] = "local"
    profile: str | None = None
    path: str | None = None
    url: str | None = None
    branch: str | None = None


class SessionCreate(BaseModel):
    name: str | None = None
    agent_profile: str | None = None
    permission_profile: str | None = None
    workspace: WorkspaceSpec = Field(default_factory=WorkspaceSpec)
    model: str | None = None
    context_mode: str | None = None
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionStatus(str, Enum):
    created = "created"
    running = "running"
    closed = "closed"
    failed = "failed"


class Session(BaseModel):
    id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:12]}")
    name: str | None = None
    agent_profile: str | None = None
    permission_profile: str = "ask-first"
    context_mode: str = "medium"
    workspace: WorkspaceSpec
    workspace_path: str
    model: str
    tools: list[str]
    status: SessionStatus = SessionStatus.created
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    def touch(self) -> None:
        self.updated_at = now_utc()


class TaskCreate(BaseModel):
    prompt: str
    command: str | None = None
    require_approval: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskStatus(str, Enum):
    queued = "queued"
    approval_required = "approval_required"
    running = "running"
    completed = "completed"
    failed = "failed"


class RunnerJobStatus(str, Enum):
    queued = "queued"
    claimed = "claimed"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:12]}")
    session_id: str
    prompt: str
    command: str | None = None
    status: TaskStatus = TaskStatus.queued
    exit_code: int | None = None
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    def touch(self) -> None:
        self.updated_at = now_utc()


class Event(BaseModel):
    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    session_id: str
    task_id: str | None = None
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)

class RunnerStatus(str, Enum):
    pending = "pending"
    online = "online"
    offline = "offline"
    disabled = "disabled"


class RunnerExecutionMode(str, Enum):
    host = "host"
    container = "container"
    pi_container = "pi_container"
    mixed = "mixed"


class RunnerRegisterRequest(BaseModel):
    name: str
    labels: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    api_key: str | None = None
    allow_host_execution: bool = True
    allow_container_execution: bool = True
    agent_enabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    csr_pem: str | None = None
    certificate_sans: list[str] = Field(default_factory=list)


class RunnerHeartbeat(BaseModel):
    runner_id: str
    status: RunnerStatus = RunnerStatus.online
    version: str | None = None
    labels: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    containers: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Runner(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:12]}")
    name: str
    status: RunnerStatus = RunnerStatus.pending
    labels: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    api_key: str | None = None
    allow_host_execution: bool = True
    allow_container_execution: bool = True
    capabilities: dict[str, Any] = Field(default_factory=dict)
    containers: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    last_seen_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = now_utc()


class RunnerCreateRequest(BaseModel):
    name: str
    labels: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    allow_host_execution: bool = True
    allow_container_execution: bool = True
    agent_enabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunnerJobCreate(BaseModel):
    prompt: str
    command: str | None = None
    execution_mode: RunnerExecutionMode = RunnerExecutionMode.host
    container_image: str | None = None
    container_runtime: Literal["auto", "podman", "docker"] = "auto"
    workspace_path: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunnerJob(BaseModel):
    id: str = Field(default_factory=lambda: f"rjob_{uuid4().hex[:12]}")
    runner_id: str
    prompt: str
    command: str | None = None
    execution_mode: RunnerExecutionMode = RunnerExecutionMode.host
    container_image: str | None = None
    container_runtime: Literal["auto", "podman", "docker"] = "auto"
    workspace_path: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    status: RunnerJobStatus = RunnerJobStatus.queued
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    def touch(self) -> None:
        self.updated_at = now_utc()


class RunnerJobUpdate(BaseModel):
    status: RunnerJobStatus
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunnerJobLog(BaseModel):
    stream: Literal["stdout", "stderr", "system"] = "system"
    message: str
