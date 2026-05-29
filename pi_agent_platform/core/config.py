from __future__ import annotations

from pathlib import Path
import os
from uuid import uuid4
from typing import Any, Literal

from .platform_home import ensure_pacp_layout, pacp_path

import yaml
from pydantic import BaseModel, Field, model_validator

from .profiles import DEFAULT_PROFILE_INSTRUCTIONS


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 443
    public_url: str = "https://admin.pac.local"
    data_dir: str = "~/.pacp"
    default_workspace_root: str = "~/.pacp/workspaces"


class TlsConfig(BaseModel):
    enabled: bool = True
    ca_days: int = 10950
    server_days: int = 825
    endpoint_days: int = 825
    ca_cert_file: str = "~/.pacp/config/tls/pac-root-ca.crt"
    ca_key_file: str = "~/.pacp/config/tls/private/pac-root-ca.key"
    server_cert_file: str = "~/.pacp/config/tls/pac-server.crt"
    server_key_file: str = "~/.pacp/config/tls/private/pac-server.key"
    letsencrypt_cert_file: str = "~/.pacp/config/letsencrypt/cert.pem"
    letsencrypt_key_file: str = "~/.pacp/config/letsencrypt/key.pem"
    details_file: str = "~/.pacp/config/tls/ca-details.yaml"
    install_ca_into_system: bool = True
    subject: str = "/CN=PAC Local Root CA/O=PAC/C=NL"
    server_subject: str = "/CN=localhost/O=PAC/C=NL"
    sans: list[str] = Field(default_factory=lambda: ["DNS:localhost", "DNS:admin.pac.local", "DNS:pac.local", "IP:127.0.0.1", "IP:::1"])


class MdnsConfig(BaseModel):
    enabled: bool = True
    hostname: str = "admin.pac.local"
    service_name: str = "PAC Admin"
    service_type: str = "_https._tcp.local."


class ServiceConfig(BaseModel):
    mode: Literal["user", "host"] = "user"
    name: str = "pacp"
    preferred_port: int = 443
    fallback_port: int = 8443
    allow_privileged_port: bool = True


class AuthConfig(BaseModel):
    enabled: bool = False
    mode: Literal["dev-token", "user-password", "oidc-placeholder"] = "user-password"
    dev_token: str = "change-me"
    token_ttl_hours: int = 720
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None


class ProviderDeviceConfig(BaseModel):
    category: Literal["unknown", "cpu", "gpu", "tpu", "remote-cluster", "hybrid"] = "unknown"
    vendor: str | None = None
    model: str | None = None
    memory_gb: float | None = None
    shared: bool = False


class ProviderHostConfig(BaseModel):
    kind: Literal["unknown", "desktop", "server", "vm", "container", "kubernetes", "edge", "cloud"] = "unknown"
    os: str | None = None
    arch: str | None = None


class ProviderRuntimeConfig(BaseModel):
    execution_type: Literal["unknown", "local", "remote", "proxied", "distributed"] = "unknown"
    provider_class: str | None = None
    device: ProviderDeviceConfig = Field(default_factory=ProviderDeviceConfig)
    host: ProviderHostConfig = Field(default_factory=ProviderHostConfig)
    accelerators: list[str] = Field(default_factory=list)


class ProviderConfig(BaseModel):
    type: Literal["openai", "openai-codex", "openai-compatible", "anthropic", "anthropic-compatible", "minimax", "gemini", "ollama", "lmstudio", "vllm", "groq", "openrouter", "deepseek", "mistral", "cohere"] = "openai-compatible"
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 30
    default_headers: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None
    enabled: bool = False
    status: Literal["disabled", "connected", "failed", "unknown"] = "disabled"
    last_error: str | None = None
    last_checked_at: str | None = None
    cached_models: list[dict[str, Any]] = Field(default_factory=list)
    runtime: ProviderRuntimeConfig = Field(default_factory=ProviderRuntimeConfig)


class ModelCapability(BaseModel):
    supports_chat: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json: bool = False
    supports_streaming: bool = True
    reasoning: Literal["none", "low", "medium", "high"] = "none"


class ModelConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"model-{uuid4().hex}")
    display_name: str | None = None
    provider: str
    model: str | None = None
    endpoint: str | None = None  # legacy alias; prefer providers.<name>.base_url
    runs_on: str | None = None
    context_window: int = 32768
    max_output_tokens: int = 4096
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    capabilities: ModelCapability = Field(default_factory=ModelCapability)
    extra: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False  # if True, cannot be deleted


class ContextProfile(BaseModel):
    budget_tokens: int = 32768
    reserve_output_tokens: int = 4096
    history_tokens: int = 8192
    file_context_tokens: int = 16384
    summarization: Literal["off", "rolling", "model", "basic-placeholder"] = "rolling"
    compaction_threshold: float = 0.82
    batch_chunk_tokens: int = 1200
    batch_overlap_tokens: int = 80


class ProxyRoute(BaseModel):
    target: str  # e.g. "http://localhost:9000"
    allowed: list[str] = Field(default_factory=list)  # permission profile names, empty = all allowed
    description: str = ""


class ToolConfig(BaseModel):
    enabled: bool = True
    description: str | None = None
    approval_required_patterns: list[str] = Field(default_factory=list)
    binaries: list[str] = Field(default_factory=list)
    socket: str | None = None
    package: str | None = None
    install_hint: str | None = None
    argument_schema: dict[str, Any] = Field(default_factory=dict)
    permission_class: str | None = None
    read_only: bool | None = None
    mutating: bool | None = None
    path_scoped: bool | None = None
    path_fields: list[str] = Field(default_factory=list)
    cache_policy: Literal["auto", "read_only", "disabled"] = "auto"
    schema_version: str | None = None
    schema_source: str | None = None
    schema_signature: str | None = None
    schema_last_seen_at: str | None = None
    schema_stale: bool = False
    pre_hooks: list[str] = Field(default_factory=list)
    post_hooks: list[str] = Field(default_factory=list)


class ToolPackageConfig(BaseModel):
    enabled: bool = True
    description: str | None = None
    tools: list[str] = Field(default_factory=list)


class PluginConfig(BaseModel):
    enabled: bool = True
    description: str | None = None
    kind: Literal["python", "shell", "docs", "other"] = "python"
    entrypoint: str | None = None
    code: str | None = None
    documentation: str | None = None
    requires_tools: list[str] = Field(default_factory=list)
    tools: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PermissionRule(BaseModel):
    shell: Literal["deny", "ask", "allow"] = "ask"
    file_read: Literal["deny", "ask", "allow"] = "allow"
    file_write: Literal["deny", "ask", "allow"] = "ask"
    git_push: Literal["deny", "ask", "allow"] = "ask"
    git_write: Literal["deny", "ask", "allow"] = "ask"
    network: Literal["deny", "ask", "allow"] = "ask"
    pac_control_plane_write: Literal["deny", "ask", "allow"] = "ask"
    cluster_write: Literal["deny", "ask", "allow"] = "ask"
    secrets: Literal["deny", "ask", "allow"] = "ask"
    dangerous: Literal["deny", "ask", "allow"] = "deny"
    command_deny_patterns: list[str] = Field(default_factory=list)
    command_ask_patterns: list[str] = Field(default_factory=list)


MAIN_PI_DEV_PROFILE = "main-pi-dev"
AGENT_CONTROL_WORKSPACE = "agent-control"
MODEL_NOT_SELECTED = "__pac_model_not_selected__"
CODING_SESSION_PERMISSION_PROFILE = "coding-session"
MAIN_PI_DEV_PROFILE_TOOLS = [
    "printing_press",
    "shell",
    "shell_bg",
    "shell_bg_result",
    "shell_bg_stop",
    "log_tail",
    "podman_ps",
    "wait_for",
    "git",
    "ripgrep",
    "fd",
    "jq",
    "podman",
    "web_search",
    "web_fetch",
    "artifacts",
    "consult_model",
    "remote_memory",
    "query_workspace_index",
    "find_code_paths",
    "code_intelligence_report",
    "code_symbol_search",
    "code_definition",
    "code_references",
    "code_diagnostics",
    "code_language_servers",
    "code_project_metadata",
    "code_call_hierarchy",
    "code_type_hierarchy",
    "code_module_index",
    "code_blast_radius",
    "code_lsp_status",
    "code_lsp_document_symbols",
    "code_lsp_definition",
    "code_lsp_references",
    "code_lsp_hover",
    "code_lsp_call_hierarchy",
    "code_lsp_type_hierarchy",
    "code_lsp_shutdown",
    "code_lsp_rename_plan",
    "code_lsp_rename_apply",
    "code_lsp_endpoint_prepare",
    "code_roslyn_analysis",
    "batch_tools",
    "pac_list_components",
    "pac_create_provider",
    "pac_create_model",
    "pac_create_endpoint",
    "pac_create_workspace_profile",
    "pac_create_session",
    "local_inference_discover",
    "local_inference_health",
    "local_inference_register",
    "slash_command",
    "lessons",
    "resume_task",
    "spawn_subagent",
    "run_subagent_chain",
    "import_subagent_summary",
    "playbook_list",
    "playbook_start",
    "playbook_status",
    "playbook_resume",
    "playbook_approve",
    "playbook_cancel",
    "playbook_export",
    "playbook_import",
    "list_task_checkpoints",
    "clear_checkpoints",
    "auto_approve",
    "pty_shell",
    "pty_read",
    "pty_write",
    "pty_resize",
    "pty_close",
    "auto_commit",
    "git_changes",
]
MAIN_PI_DEV_SYSTEM_PROMPT = (
    "You are PAC's main pi.dev coding and operations agent. "
    "Act like a pragmatic code-focused runtime, not a generic assistant. "
    "Assume PAC-domain terms such as PAC RAM, workspaces, endpoints, wrappers, sessions, tools, plugins, providers, pi.dev, and profiles refer to this PAC installation unless the user clearly means something else. "
    "When a request refers to the PAC codebase, workspace contents, configuration, logs, or runtime behavior, "
    "default to inspecting the available files, commands, and state directly before asking clarifying questions. "
    "Use the PAC controller workspace and PAC configuration as the source of truth, prefer local inspection over web research for PAC-domain questions, "
    "keep changes scoped to the requested task, surface build/update/runtime diagnostics clearly, and move the task forward with tool use instead of narration whenever the next step is obvious. "
    "If the user asks to change PAC itself, you are allowed to read and rewrite PAC application files and PAC configuration directly. "
    "For broad PAC questions, start by inspecting the local PAC workspace, config, or runtime state instead of responding like a generic assistant. "
    "For source-code understanding, prefer code_intelligence_report, code_language_servers, code_project_metadata, code_symbol_search, code_definition, code_references, code_call_hierarchy, code_type_hierarchy, code_blast_radius, code_lsp_definition, code_lsp_references, code_lsp_rename_plan, code_lsp_rename_apply, and code_diagnostics before hand-rolled grep when the request needs symbols, diagnostics, or cross-file impact. Use playbook_list, playbook_start, playbook_status, playbook_resume, playbook_approve, playbook_cancel, playbook_export, and playbook_import for repeatable gated workflows. Use local_inference_discover, local_inference_health, and local_inference_register to find and register LM Studio local inference providers instead of asking users to type local provider details by hand. Use /model or the slash_command tool with /model to switch models mid-session; after a switch, respect the new active model, capability warnings, and fallback chain."
)


class AgentProfile(BaseModel):
    display_name: str | None = None
    description: str | None = None
    instructions: str = DEFAULT_PROFILE_INSTRUCTIONS
    context_profile: str | None = None
    planner_context_profile: str | None = None
    permission_profile: str = "ask-first"
    output_preferences: dict[str, Any] = Field(default_factory=dict)
    allowed_groups: list[str] = Field(default_factory=list)
    visibility: Literal["private", "group", "global"] | None = None
    max_agent_steps: int | None = None
    max_runtime_minutes: int = 60
    model: str | None = None
    planner_model: str | None = None
    context_mode: Literal["low", "medium", "high", "max"] = "medium"
    tools: list[str] = Field(default_factory=list)
    system_prompt: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_aliases(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        if not str(data.get("instructions") or "").strip() and str(data.get("system_prompt") or "").strip():
            data["instructions"] = data.get("system_prompt")
        if not str(data.get("context_profile") or "").strip() and str(data.get("context_mode") or "").strip():
            data["context_profile"] = data.get("context_mode")
        if not data.get("visibility"):
            data["visibility"] = "group" if data.get("allowed_groups") else "global"
        return data

    @model_validator(mode="after")
    def _sync_legacy_fields(self) -> "AgentProfile":
        if not (self.instructions or "").strip():
            self.instructions = DEFAULT_PROFILE_INSTRUCTIONS
        if not (self.system_prompt or "").strip():
            self.system_prompt = self.instructions
        if not (self.context_profile or "").strip():
            self.context_profile = self.context_mode
        if not self.visibility:
            self.visibility = "group" if self.allowed_groups else "global"
        return self


class WorkspaceProfile(BaseModel):
    description: str | None = None
    type: Literal["local", "git", "container"] = "local"
    path: str | None = None
    url: str | None = None
    branch: str | None = None
    shared_storage_id: str | None = None
    storage_subpath: str | None = None
    storage_mount_path: str | None = None
    default_agent_profile: str | None = None
    endpoint_id: str | None = None
    endpoint_selector: str | None = None
    runtime: Literal["any", "local", "container"] = "any"
    container_image: str | None = None
    data_bundle_url: str | None = None
    data_bundle_path: str | None = None
    data_mount_path: str | None = None
    ephemeral: bool = False
    ttl_hours: int | None = None
    delete_on_expire: bool = True
    is_default: bool = False


class SourceContextConfig(BaseModel):
    description: str | None = None
    path_prefix: str
    customer_id: str | None = None
    user_scope: str | None = None
    workspace_profile: str | None = None
    preferred_endpoint: str | None = None
    container_image: str | None = None
    profile: str | None = None
    config_vars: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class SourceUpdateConfig(BaseModel):
    enabled: bool = True
    packages_manifest_url: str = "https://raw.githubusercontent.com/pac-labs/packages/main/packages.json"
    repository: str = "https://github.com/pac-labs/packages"
    check_on_startup: bool = True
    cache_minutes: int = 30


class RuntimeConfig(BaseModel):
    mode: str = "local"
    command_timeout_seconds: int = 300
    max_task_seconds: int = 3600
    request_intent_enabled: bool = True
    request_intent_for_work_requests: bool = True
    request_intent_model: str | None = None


class ControllerHarnessConfig(BaseModel):
    enabled: bool = True
    runtime: Literal["pi.dev"] = "pi.dev"
    deployment_mode: Literal["controller", "endpoint"] = "controller"
    wrapper: str = "PAC controller wrapper"
    session_name: str = "PAC controller pi.dev"
    workspace_profile: str = AGENT_CONTROL_WORKSPACE
    agent_profile: str | None = MAIN_PI_DEV_PROFILE
    model: str | None = None
    permission_profile: str = "ask-first"
    context_mode: str = "medium"
    runner_id: str = "local-PAC"
    auto_create_session: bool = True
    keep_single_active_session: bool = True
    expose_platform_tools: bool = True
    auto_bootstrap: bool = True
    auto_build_wrapper: bool = True
    auto_install_pi_dev: bool = True
    forward_events_enabled: bool = True
    forward_events_sink: Literal["none", "pi.dev"] = "pi.dev"
    forward_scope: Literal["controller", "pi_dev_sessions", "all_sessions"] = "controller"
    forward_event_types: list[str] = Field(default_factory=lambda: [
        "user_message",
        "task_queued",
        "task_started",
        "tool_call",
        "tool_result",
        "agent_intent",
        "agent_plan",
        "result",
        "task_failed",
    ])
    forward_file: str = "pi-agent-artifacts/agent-forwarding.jsonl"
    wrapper_binary_project: str = "pac-endpoint"
    wrapper_binary_name: str = "pac-endpoint"
    wrapper_install_dir: str = "~/.pacp/bin"
    service_token: str | None = None
    required_tools: list[str] = Field(default_factory=lambda: ["git", "python3", "podman"] )


class LetsEncryptConfig(BaseModel):
    enabled: bool = False
    email: str = ""
    domain: str = ""
    cert_file: str = "~/.pacp/config/letsencrypt/cert.pem"
    key_file: str = "~/.pacp/config/letsencrypt/key.pem"
    dns_provider: Literal["cloudflare"] = "cloudflare"
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""
    auto_enable: bool = True
    staging: bool = False


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tls: TlsConfig = Field(default_factory=TlsConfig)
    letsencrypt: LetsEncryptConfig = Field(default_factory=LetsEncryptConfig)
    mdns: MdnsConfig = Field(default_factory=MdnsConfig)
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    context_profiles: dict[str, ContextProfile] = Field(default_factory=dict)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    tool_packages: dict[str, ToolPackageConfig] = Field(default_factory=dict)
    proxy_routes: dict[str, ProxyRoute] = Field(default_factory=dict)
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)
    permission_profiles: dict[str, PermissionRule] = Field(default_factory=dict)
    agent_profiles: dict[str, AgentProfile] = Field(default_factory=dict)
    workspaces: dict[str, WorkspaceProfile] = Field(default_factory=dict)
    source_contexts: dict[str, SourceContextConfig] = Field(default_factory=dict)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    source_updates: SourceUpdateConfig = Field(default_factory=SourceUpdateConfig)
    controller_harness: ControllerHarnessConfig = Field(default_factory=ControllerHarnessConfig)


def _packaged_example_config() -> Path | None:
    candidates = [
        Path.cwd() / "config" / "example.config.yaml",
        Path(__file__).resolve().parents[2] / "config" / "example.config.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None



def prune_packaged_demo_entries(cfg: AppConfig) -> bool:
    """Remove packaged demo session presets/model placeholders from persisted configs.

    These were useful examples in early builds, but in a real install they create
    selectable-looking profiles for models that may not exist on the live
    provider. Only known packaged names are touched.
    """
    changed = False
    demo_profiles = {"safe-coder", "infra-admin", "full-control-coder", "tiny-local-coder"}
    demo_models = {"gpt-remote", "lmstudio-qwen-coder", "ollama-small", "vllm-coder"}
    for name in list(cfg.agent_profiles.keys()):
        if name in demo_profiles:
            del cfg.agent_profiles[name]
            changed = True
    for name in list(cfg.models.keys()):
        model = cfg.models.get(name)
        provider = cfg.providers.get(model.provider) if model else None
        if name in demo_models and (not provider or provider.enabled is False or provider.status in {"disabled", "unknown", "failed"}):
            del cfg.models[name]
            changed = True
    for name, workspace in list(cfg.workspaces.items()):
        if name == "local-demo" and (workspace.default_agent_profile in demo_profiles or workspace.path == "/tmp/pi-agent-demo"):
            del cfg.workspaces[name]
            changed = True
    # Make sure new installs and upgraded installs always have a usable workspace choice.
    if not cfg.workspaces:
        cfg.workspaces["scratch"] = WorkspaceProfile(description="Default local workspace", type="local", path=None)
        changed = True

    # v1.0.96: the controller-local pi.dev profile and workspace are first-class defaults.
    # "pi", "agent" and "harness" all mean the pi.dev runtime. PAC glue around it
    # should be named wrapper/tooling, not another runtime concept.
    harness_cfg = getattr(cfg, "controller_harness", ControllerHarnessConfig())
    if harness_cfg.workspace_profile == "pac-controller":
        harness_cfg.workspace_profile = AGENT_CONTROL_WORKSPACE
        changed = True
    if harness_cfg.runner_id in {"controller-pi-dev", "pac-controller", "controller"}:
        harness_cfg.runner_id = "local-PAC"
        changed = True
    if not harness_cfg.agent_profile:
        harness_cfg.agent_profile = MAIN_PI_DEV_PROFILE
        changed = True

    preferred_model = harness_cfg.model or next(iter(cfg.models.keys()), MODEL_NOT_SELECTED)
    profile = cfg.agent_profiles.get(MAIN_PI_DEV_PROFILE)
    if not profile:
        cfg.agent_profiles[MAIN_PI_DEV_PROFILE] = AgentProfile(
            display_name="PAC controller",
            description="Main pi.dev profile for the PAC controller runtime. Select its model in Settings when no model is configured yet.",
            context_profile="high" if "high" in cfg.context_profiles else None,
            planner_context_profile="high" if "high" in cfg.context_profiles else None,
            permission_profile=harness_cfg.permission_profile or "ask-first",
            instructions=MAIN_PI_DEV_SYSTEM_PROMPT,
            max_runtime_minutes=120,
        )
        changed = True
    else:
        if not (profile.display_name or "").strip():
            profile.display_name = "PAC controller"
            changed = True
        desired_context_profile = "high" if "high" in cfg.context_profiles else profile.context_profile
        if desired_context_profile and profile.context_profile != desired_context_profile:
            profile.context_profile = desired_context_profile
            changed = True
        if not profile.planner_context_profile and desired_context_profile:
            profile.planner_context_profile = desired_context_profile
            changed = True
        if (profile.permission_profile or "") != (harness_cfg.permission_profile or profile.permission_profile or "ask-first"):
            profile.permission_profile = harness_cfg.permission_profile or profile.permission_profile or "ask-first"
            changed = True
        if (profile.max_runtime_minutes or 0) < 120:
            profile.max_runtime_minutes = 120
            changed = True
        if (profile.instructions or "").strip() != MAIN_PI_DEV_SYSTEM_PROMPT.strip():
            profile.instructions = MAIN_PI_DEV_SYSTEM_PROMPT
            changed = True
        if (profile.system_prompt or "").strip() != MAIN_PI_DEV_SYSTEM_PROMPT.strip():
            profile.system_prompt = MAIN_PI_DEV_SYSTEM_PROMPT
            changed = True

    harness_ws = harness_cfg.workspace_profile or AGENT_CONTROL_WORKSPACE
    platform_root = str(Path(__file__).resolve().parents[2])
    workspace = cfg.workspaces.get(harness_ws)
    if not workspace:
        cfg.workspaces[harness_ws] = WorkspaceProfile(
            description="Agent control workspace: the PAC controller application/source tree used by the main pi.dev runtime.",
            type="local",
            path=platform_root,
            default_agent_profile=harness_cfg.agent_profile or MAIN_PI_DEV_PROFILE,
            runtime="local",
            endpoint_id=harness_cfg.runner_id,
            endpoint_selector="controller",
            ephemeral=False,
            is_default=True,
        )
        changed = True
    else:
        if not workspace.path:
            workspace.path = platform_root; changed = True
        if not workspace.default_agent_profile:
            workspace.default_agent_profile = harness_cfg.agent_profile or MAIN_PI_DEV_PROFILE; changed = True
        if not workspace.endpoint_id:
            workspace.endpoint_id = harness_cfg.runner_id; changed = True
        if not workspace.endpoint_selector:
            workspace.endpoint_selector = "controller"; changed = True
        if workspace.runtime == "any":
            workspace.runtime = "local"; changed = True
        if not workspace.description:
            workspace.description = "Agent control workspace: the PAC controller application/source tree used by the main pi.dev runtime."; changed = True
    return changed

def default_config_path() -> Path:
    ensure_pacp_layout()
    return pacp_path("config", "config.yaml")


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        example = _packaged_example_config()
        if example and example.exists():
            config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            config_path.write_text(yaml.safe_dump(AppConfig().model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cfg = AppConfig.model_validate(raw)
    changed = prune_packaged_demo_entries(cfg)
    current_public_url = str(cfg.server.public_url or '').rstrip('/')
    packaged_default_urls = {
        'https://admin.pac.local',
        'https://admin.pac.local:443',
        'https://admin.pac.local:8443',
        'https://localhost:443',
        'https://localhost:8443',
        'https://127.0.0.1:443',
        'https://127.0.0.1:8443',
    }
    env_port = os.environ.get('PAC_PORT')
    if env_port:
        try:
            cfg.server.port = int(env_port)
            if current_public_url in packaged_default_urls or not current_public_url:
                cfg.server.public_url = 'https://admin.pac.local' if int(env_port) == 443 else f'https://admin.pac.local:{int(env_port)}'
        except ValueError:
            pass
    # Migrate packaged defaults only; explicit custom ports are preserved unless PAC_PORT is set.
    elif int(cfg.server.port) == 8443 and str(cfg.server.public_url).rstrip('/') in (
        'https://admin.pac.local:8443',
        'https://localhost:8443',
        'https://127.0.0.1:8443',
    ):
        cfg.server.port = 443
        cfg.server.public_url = 'https://admin.pac.local'
        changed = True
    # Normalize legacy/local defaults into PAC home so launching from a different directory is safe.
    home = ensure_pacp_layout()
    if cfg.server.data_dir in ("./data", "data", "~/.pacp"):
        cfg.server.data_dir = str(home)
        changed = True
    if cfg.server.default_workspace_root in ("/tmp/pi-agent-workspaces", "./workspaces", "~/.pacp/workspaces"):
        cfg.server.default_workspace_root = str(home / "workspaces")
        changed = True
    ask_first = cfg.permission_profiles.get("ask-first")
    if ask_first and ask_first.network == "ask":
        ask_first.network = "allow"
        changed = True
    if CODING_SESSION_PERMISSION_PROFILE not in cfg.permission_profiles:
        cfg.permission_profiles[CODING_SESSION_PERMISSION_PROFILE] = PermissionRule(
            shell="allow",
            file_read="allow",
            file_write="allow",
            git_push="ask",
            network="ask",
            cluster_write="deny",
            secrets="ask",
            dangerous="deny",
        )
        changed = True
    if "consult_model" not in cfg.tools:
        cfg.tools["consult_model"] = ToolConfig(
            enabled=True,
            description="Ask one or more configured PAC models for planning or review help during an agent run.",
        )
        changed = True
    if "remote_memory" not in cfg.tools:
        cfg.tools["remote_memory"] = ToolConfig(
            enabled=True,
            description="Read PAC RAM profile, user, and workspace memory from the controller during an agent run.",
        )
        changed = True
    if "printing_press" not in cfg.tools:
        cfg.tools["printing_press"] = ToolConfig(
            enabled=True,
            description="Run the Printing Press CLI for optimization, formatting, or content preparation work inside the workspace.",
            binaries=["printing-press", "printing_press", "printingpress", "press"],
            install_hint="Install the Printing Press CLI and make sure one of its binary names is available on PATH.",
        )
        changed = True
    pac_component_tools = {
        "pac_list_components": "List PAC providers, models, endpoints, workspace profiles, and recent sessions for the built-in controller model.",
        "pac_create_provider": "Create or replace a model provider in PAC configuration from the built-in controller model.",
        "pac_create_model": "Create or replace a model entry attached to an existing PAC provider from the built-in controller model.",
        "pac_create_endpoint": "Create a pending endpoint registration record from the built-in controller model.",
        "pac_create_workspace_profile": "Create or replace a reusable PAC workspace profile from the built-in controller model.",
        "pac_create_session": "Create a PAC session from the built-in controller model using configured models and workspaces.",
        "run_subagent_chain": "Run Explore, Plan, Coder, and Verify sub-agents as a structured chain for larger code-change requests.",
        "import_subagent_summary": "Import completed child sub-agent summaries into the current parent task context.",
        "find_code_paths": "Locate likely PAC code files for a concept or intent across the controller workspace before opening files directly.",
        "code_intelligence_report": "Detect project languages, LSP/tool availability, project markers, and a cross-language symbol index for the workspace.",
        "code_symbol_search": "Search the static symbol index across Python, TypeScript, Go, Rust, and C# source files.",
        "code_definition": "Find likely definitions for a named symbol across supported source languages.",
        "code_references": "Find workspace references to a named symbol across supported source languages.",
        "code_diagnostics": "Prepare or run safe language diagnostics such as cargo check JSON, compileall, go test, tsc, or dotnet build when binaries are available.",
        "code_language_servers": "Check language-server and compiler availability for Python, TypeScript, Go, Rust, and C# in the current workspace or endpoint container.",
        "code_project_metadata": "Collect project metadata such as cargo metadata, go list, package.json summaries, Python markers, and dotnet project lists.",
        "code_call_hierarchy": "Build a static caller list for a symbol using cross-file references and function ranges.",
        "code_type_hierarchy": "Build a static type hierarchy across Python, TypeScript, Rust, and C# inheritance/impl patterns.",
        "code_module_index": "Build a language-aware module/file index for Python, TypeScript, Go, Rust, and C# projects.",
        "code_blast_radius": "Estimate affected files, definitions, references, and validation commands for a symbol change.",
        "code_lsp_status": "Inspect persistent JSON-RPC language-server clients and server availability for the workspace.",
        "code_lsp_document_symbols": "Use a persistent language server to return exact document symbols for a source file.",
        "code_lsp_definition": "Use a persistent language server to resolve go-to-definition at a file position.",
        "code_lsp_references": "Use a persistent language server to resolve references at a file position.",
        "code_lsp_hover": "Use a persistent language server to return hover/type information at a file position.",
        "code_lsp_call_hierarchy": "Use a persistent language server call hierarchy provider at a file position when available.",
        "code_lsp_type_hierarchy": "Use a persistent language server type hierarchy provider at a file position when available.",
        "code_lsp_shutdown": "Stop persistent language-server clients for the workspace or language.",
        "code_lsp_rename_plan": "Ask a persistent language server for a safe rename workspace-edit preview without changing files.",
        "code_lsp_rename_apply": "Apply a language-server rename workspace edit after approval and file-write permission checks.",
        "code_lsp_endpoint_prepare": "Prepare endpoint/container LSP metadata and verify endpoint-side language server availability.",
        "code_roslyn_analysis": "Inspect C# project structure, static symbols, relationships, dotnet availability, and optional build diagnostics.",
        "batch_tools": "Run a bounded group of read-only tool calls in parallel through the same tool pipeline.",
        "spawn_subagent": "Spawn a locked specialist sub-agent such as Explore, Plan, Coder, Verify, or General-purpose.",
        "playbook_list": "List built-in and configured YAML playbooks with typed parameters and steps.",
        "playbook_start": "Start a gated playbook run with typed parameters for repeatable workflows.",
        "playbook_status": "Inspect recent playbook runs or one playbook run in detail.",
        "playbook_resume": "Resume a paused or failed playbook run from its last checkpoint.",
        "playbook_approve": "Approve the current Confirm, Review, or Approve gate for a waiting playbook run.",
        "playbook_cancel": "Cancel a waiting or active playbook run and mark child tasks for cancellation.",
        "playbook_export": "Export a playbook definition as YAML.",
        "playbook_import": "Import or update a custom playbook YAML definition.",
        "local_inference_discover": "Probe common local/network LM Studio endpoints and report discovered local inference providers.",
        "local_inference_health": "Run an LM Studio local inference health check against a candidate base URL.",
        "local_inference_register": "Register a discovered LM Studio server as a PAC local provider and optionally create model entries from its inventory.",
        "slash_command": "Execute supported PAC session slash commands such as /model, /compact, /subagent, and endpoint helper commands from inside an agent loop.",
    }
    for tool_name, description in pac_component_tools.items():
        existing_tool = cfg.tools.get(tool_name)
        if not existing_tool:
            cfg.tools[tool_name] = ToolConfig(enabled=True, description=description, package="pac-control-plane")
            changed = True
        elif not (existing_tool.description or "").strip():
            existing_tool.description = description
            changed = True
    main_profile = cfg.agent_profiles.get(MAIN_PI_DEV_PROFILE)
    if main_profile is not None:
        desired_tools = [tool for tool in MAIN_PI_DEV_PROFILE_TOOLS if tool in cfg.tools]
        merged_tools = list(dict.fromkeys([*(main_profile.tools or []), *desired_tools]))
        if merged_tools != list(main_profile.tools or []):
            main_profile.tools = merged_tools
            changed = True
    if changed:
        config_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
    return cfg


def save_config(config: AppConfig, path: str | Path | None = None) -> None:
    config_path = Path(path).expanduser() if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json", exclude_none=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
