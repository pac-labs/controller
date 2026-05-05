from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Literal

from .platform_home import ensure_pacp_layout, pacp_path

import yaml
from pydantic import BaseModel, Field


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
    mode: Literal["dev-token", "oidc-placeholder"] = "dev-token"
    dev_token: str = "change-me"
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None


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


class ModelCapability(BaseModel):
    supports_chat: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json: bool = False
    supports_streaming: bool = True
    reasoning: Literal["none", "low", "medium", "high"] = "none"


class ModelConfig(BaseModel):
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


class ContextProfile(BaseModel):
    budget_tokens: int = 32768
    reserve_output_tokens: int = 4096
    history_tokens: int = 8192
    file_context_tokens: int = 16384
    summarization: Literal["off", "rolling", "model", "basic-placeholder"] = "rolling"
    compaction_threshold: float = 0.82
    batch_chunk_tokens: int = 1200
    batch_overlap_tokens: int = 80


class ToolConfig(BaseModel):
    enabled: bool = True
    description: str | None = None
    approval_required_patterns: list[str] = Field(default_factory=list)
    binaries: list[str] = Field(default_factory=list)
    socket: str | None = None
    package: str | None = None
    install_hint: str | None = None


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


class PermissionRule(BaseModel):
    shell: Literal["deny", "ask", "allow"] = "ask"
    file_read: Literal["deny", "ask", "allow"] = "allow"
    file_write: Literal["deny", "ask", "allow"] = "ask"
    git_push: Literal["deny", "ask", "allow"] = "ask"
    network: Literal["deny", "ask", "allow"] = "ask"
    cluster_write: Literal["deny", "ask", "allow"] = "ask"
    secrets: Literal["deny", "ask", "allow"] = "ask"
    dangerous: Literal["deny", "ask", "allow"] = "deny"
    command_deny_patterns: list[str] = Field(default_factory=list)
    command_ask_patterns: list[str] = Field(default_factory=list)


MAIN_PI_DEV_PROFILE = "main-pi-dev"
AGENT_CONTROL_WORKSPACE = "agent-control"
MODEL_NOT_SELECTED = "__pac_model_not_selected__"


class AgentProfile(BaseModel):
    description: str | None = None
    model: str
    context_mode: Literal["low", "medium", "high", "max"] = "medium"
    context_profile: str | None = None
    permission_profile: str = "ask-first"
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = "You are a careful remote coding and infrastructure agent."
    max_runtime_minutes: int = 60


class WorkspaceProfile(BaseModel):
    description: str | None = None
    type: Literal["local", "git", "container"] = "local"
    path: str | None = None
    url: str | None = None
    branch: str | None = None
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


class RuntimeConfig(BaseModel):
    mode: str = "local"
    command_timeout_seconds: int = 300
    max_task_seconds: int = 3600


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
    wrapper_binary_project: str = "pac-endpoint"
    wrapper_binary_name: str = "pac-endpoint"
    wrapper_install_dir: str = "~/.pacp/bin"
    required_tools: list[str] = Field(default_factory=lambda: ["git", "python3", "podman"] )


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tls: TlsConfig = Field(default_factory=TlsConfig)
    mdns: MdnsConfig = Field(default_factory=MdnsConfig)
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    context_profiles: dict[str, ContextProfile] = Field(default_factory=dict)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    tool_packages: dict[str, ToolPackageConfig] = Field(default_factory=dict)
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)
    permission_profiles: dict[str, PermissionRule] = Field(default_factory=dict)
    agent_profiles: dict[str, AgentProfile] = Field(default_factory=dict)
    workspaces: dict[str, WorkspaceProfile] = Field(default_factory=dict)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
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
        profile = cfg.agent_profiles.get(name)
        if name in demo_profiles and (not profile or profile.model in demo_models or profile.model not in cfg.models):
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
            description="Main pi.dev profile for the PAC controller runtime. Select its model in Settings when no model is configured yet.",
            model=preferred_model,
            context_mode="high",
            context_profile="high" if "high" in cfg.context_profiles else None,
            permission_profile=harness_cfg.permission_profile or "ask-first",
            tools=[name for name in ["shell", "git", "ripgrep", "fd", "jq", "podman", "artifacts"] if name in cfg.tools],
            system_prompt=(
                "You are the main pi.dev runtime for PAC. Use the PAC controller workspace as the source of truth, "
                "keep changes scoped to the requested task, and surface build/update diagnostics clearly."
            ),
            max_runtime_minutes=120,
        )
        changed = True
    elif profile.model == MODEL_NOT_SELECTED and harness_cfg.model:
        profile.model = harness_cfg.model
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
    env_port = os.environ.get('PAC_PORT')
    if env_port:
        try:
            cfg.server.port = int(env_port)
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
    if changed:
        config_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
    return cfg


def save_config(config: AppConfig, path: str | Path | None = None) -> None:
    config_path = Path(path).expanduser() if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json", exclude_none=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
