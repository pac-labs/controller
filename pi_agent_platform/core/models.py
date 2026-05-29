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
    stream_seq: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunnerJobLog(BaseModel):
    stream: Literal["stdout", "stderr", "system"] = "system"
    message: str


class WorkspaceAgentStatus(str, Enum):
    online = "online"
    degraded = "degraded"
    offline = "offline"


class WorkspaceAgentCommandStatus(str, Enum):
    queued = "queued"
    claimed = "claimed"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class WorkspaceAgent(BaseModel):
    id: str = Field(default_factory=lambda: f"wsa_{uuid4().hex[:12]}")
    workspace_id: str
    name: str
    status: WorkspaceAgentStatus = WorkspaceAgentStatus.online
    endpoint_id: str | None = None
    root: str | None = None
    lifetime: Literal["persistent", "ephemeral"] = "persistent"
    labels: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    last_seen_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = now_utc()


class WorkspaceAgentCommand(BaseModel):
    id: str = Field(default_factory=lambda: f"wcmd_{uuid4().hex[:12]}")
    workspace_id: str
    command: str
    status: WorkspaceAgentCommandStatus = WorkspaceAgentCommandStatus.queued
    workspace_path: str | None = None
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    stream_seq: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = now_utc()


class WorkspaceAgentCommandEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"wce_{uuid4().hex[:12]}")
    workspace_id: str
    command_id: str
    seq: int
    stream: Literal["stdout", "stderr", "system", "status"] = "system"
    data: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class User(BaseModel):
    id: str
    username: str
    password_hash: str | None = None
    display_name: str | None = None
    role: Literal["admin", "user", "readonly"] = "user"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_utc()

    def verify_password(self, password: str) -> bool:
        import hashlib
        import secrets

        if not self.password_hash:
            return False
        if "::" in self.password_hash:
            salt_hex, stored_hash_hex = self.password_hash.split("::", 1)
            salt = bytes.fromhex(salt_hex)
            computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000).hex()
            return secrets.compare_digest(computed, stored_hash_hex)
        if self.password_hash.startswith("pbkdf2:"):
            parts = self.password_hash.split("$")
            if len(parts) >= 3:
                salt, stored_pw = parts[1], parts[2]
                computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
                return secrets.compare_digest(computed, stored_pw)
            return False
        return False

    def set_password(self, password: str) -> None:
        import hashlib
        import secrets

        salt = secrets.token_bytes(32)
        self.password_hash = salt.hex() + "::" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000).hex()


class DirectoryPrincipal(BaseModel):
    id: str
    kind: Literal["user", "group", "service_account", "endpoint", "provider", "certificate_identity"] = "user"
    name: str
    display_name: str | None = None
    description: str | None = None
    status: Literal["active", "disabled", "locked"] = "active"
    source: Literal["local", "pac", "ldap", "oidc", "external"] = "local"
    system_managed: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_utc()


class ResourceGrant(BaseModel):
    resource_type: Literal[
        "workspace",
        "source_context",
        "secret",
        "session",
        "profile",
        "agent_context",
        "endpoint",
        "provider",
        "model",
        "plugin",
        "tool_package",
        "shared_storage",
        "diagnostics",
        "system",
    ] = "workspace"
    pattern: str
    access: Literal["read", "write", "use", "execute", "manage"] = "read"


class DirectoryMember(BaseModel):
    kind: Literal["user", "group", "service_account", "endpoint", "provider", "certificate_identity"] = "user"
    id: str


class DirectoryCredential(BaseModel):
    id: str = Field(default_factory=lambda: f"cred_{uuid4().hex[:12]}")
    principal_id: str
    kind: Literal["password", "api_token", "certificate", "endpoint_token", "provider_token"] = "api_token"
    name: str
    status: Literal["active", "revoked", "expired"] = "active"
    secret_hash: str | None = None
    fingerprint: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Group(BaseModel):
    id: str
    name: str
    description: str | None = None
    members: list[DirectoryMember] = Field(default_factory=list)
    grants: list[ResourceGrant] = Field(default_factory=list)
    source: Literal["local", "pac", "ldap", "oidc", "external"] = "local"
    system_managed: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_utc()


class AccessRequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AccessRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"acc_{uuid4().hex[:12]}")
    user_id: str
    username: str
    resource_type: Literal["workspace", "source_context", "secret", "session"] = "workspace"
    resource_id: str
    access: Literal["read", "write"] = "read"
    reason: str | None = None
    status: AccessRequestStatus = AccessRequestStatus.pending
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_utc()


class UserWorkspace(BaseModel):
    id: str = Field(default_factory=lambda: f"uws_{uuid4().hex[:12]}")
    owner_id: str
    owner_username: str
    name: str
    description: str | None = None
    template_id: str | None = None
    workspace_type: Literal["local", "git", "profile"] = "local"
    workspace_profile: str | None = None
    path: str | None = None
    url: str | None = None
    branch: str | None = None
    shared_storage_id: str | None = None
    storage_subpath: str | None = None
    storage_mount_path: str | None = None
    endpoint_id: str | None = None
    endpoint_selector: str | None = None
    container_image: str | None = None
    agent_profile: str | None = None
    permission_profile: str | None = None
    model: str | None = None
    context_mode: str | None = None
    open_files: list[str] = Field(default_factory=list)
    last_session_id: str | None = None
    pinned: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_utc()


class AgentContext(BaseModel):
    id: str = Field(default_factory=lambda: f"ctx_{uuid4().hex[:12]}")
    owner_id: str
    owner_username: str
    name: str
    description: str | None = None
    kind: Literal["coding", "controller", "research", "operations"] = "coding"
    workspace_id: str | None = None
    workspace_template_id: str | None = None
    controller_workdir: str | None = None
    shared_storage_id: str | None = None
    storage_subpath: str | None = None
    storage_mount_path: str | None = None
    endpoint_id: str | None = None
    endpoint_selector: str | None = None
    container_image: str | None = None
    requires_container: bool = True
    agent_profile: str | None = None
    permission_profile: str | None = None
    context_mode: str | None = None
    executor_model: str | None = None
    planner_model: str | None = None
    reviewer_model: str | None = None
    retrieval_model: str | None = None
    tools: list[str] = Field(default_factory=list)
    use_groups: list[str] = Field(default_factory=list)
    editor_groups: list[str] = Field(default_factory=list)
    last_session_id: str | None = None
    pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    def touch(self) -> None:
        self.updated_at = now_utc()
