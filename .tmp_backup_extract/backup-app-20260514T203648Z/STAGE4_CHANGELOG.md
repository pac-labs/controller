# Stage 4 Changelog

## Added

- Agent profiles with model/context/permission/tool defaults.
- Permission profiles with allow/ask/deny rules and command patterns.
- Workspace profiles for local and git workspaces.
- `/v1/profiles` API.
- Optional dev-token bearer authentication.
- Web UI upgraded to create sessions from profiles, run tasks, approve/reject and inspect diffs/events.
- VS Code extension scaffold upgraded to select agent/workspace profiles and show session output.
- MCP bridge upgraded with profile listing, profile-based session creation and optional bearer token.
- Zed MCP configuration example.
- Packaging via `pyproject.toml`.

## Still intentionally incomplete

- Real LLM agent loop.
- Container worker isolation.
- OIDC validation.
- Secrets broker / Vault/OpenBao integration.
