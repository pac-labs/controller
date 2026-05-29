# PAC binary, release, and workspace agent architecture

Date: 2026-05-29  
Status: implementation design, first cleanup pass

## Goal

PAC should ship a small, understandable binary surface:

- `pac-endpoint`: the installed endpoint/workspace wrapper that runs where work happens.
- `pacctl`: the client used by humans, scripts, IDEs, containers, and automation to talk to PAC.

The source/update zip must not bundle compiled binaries. GitHub Releases are the binary distribution point. PAC installation and updates download the matching release asset on demand and may build locally only as a fallback when explicitly allowed.

## Binary taxonomy

| Binary | Final status | Responsibility |
|---|---|---|
| `pac-endpoint` | Primary release binary | Host daemon, workspace container agent, telemetry forwarder, job executor, self-update wrapper. |
| `pacctl` | Primary release binary | PAC client, API/catalog caller, provider/model sender, workspace/endpoint command client, MCP/editor bridge. |
| `pac-agent` | Removed | Worker behavior belongs to `pac-endpoint`. |
| `zed-binary` | Removed | MCP/editor behavior belongs to `pacctl mcp serve`. |
| `pac-endpoint-runner` | Removed | The runner is embedded in `pac-endpoint`; keeping a separate runner creates installation and release confusion. |

## Release workflow

GitHub Actions owns compiled binary production.

1. Resolve the PAC controller release version.
2. Compile release binaries for supported targets.
3. Publish direct release assets for `pac-endpoint` and `pacctl`.
4. Publish `RELEASE_BINARIES.json` as the manifest.
5. Publish source/update zips that contain no compiled binaries.
6. Optionally publish `pac-binaries.zip` as an offline/debug mirror, but it is not used as the source zip payload.

Default targets:

- `linux/amd64`
- `linux/arm64`
- `darwin/amd64`
- `darwin/arm64`
- `windows/amd64`

Later targets can add `windows/arm64` and `linux/ppc64le` when dependency builds are validated.

## Release asset names

Direct asset names should be stable and human-downloadable:

```text
pac-endpoint-linux-amd64
pac-endpoint-linux-arm64
pac-endpoint-darwin-amd64
pac-endpoint-darwin-arm64
pac-endpoint-windows-amd64.exe

pacctl-linux-amd64
pacctl-linux-arm64
pacctl-darwin-amd64
pacctl-darwin-arm64
pacctl-windows-amd64.exe

RELEASE_BINARIES.json
pac-full.zip
pac-patch.zip
```

The manifest includes `component_id`, `component_version`, `goos`, `goarch`, `asset_name`, `sha256`, `size`, `required`, `role`, and lifecycle/deprecation metadata.

## Versioning rule

PAC controller version and component binary versions are independent.

- PAC controller: `VERSION`, `VERSION_CURRENT.md`, `PAC_CHANGELOG.json`, source/update zips.
- `pac-endpoint`: `binaries/pac-endpoint/VERSION` or `pac-component.json`.
- `pacctl`: `binaries/pacctl/VERSION` or `pac-component.json`.

A controller-only UI/doc/API patch must not force a component binary version bump.

## Install/update resolution

The controller or installer resolves binaries in this order:

1. Existing installed/cached binary with matching component, target, and checksum.
2. Direct GitHub Release asset from `RELEASE_BINARIES.json`.
3. Local build from source, only when fallback builds are allowed.

Source/update zips remain code-only. They may contain scripts and manifests, but not compiled binary payloads.

## `pac-endpoint` modes

`pac-endpoint` is the wrapper that runs where work happens.

```text
pac-endpoint daemon
  Long-running host process or service. Registers an endpoint, reports heartbeat, forwards metrics/hardware inventory, polls/runs jobs, and handles self-update.

pac-endpoint workspace run
  Container/workspace foreground process. Reads config/env, registers the workspace, opens an outbound command channel, keeps the container alive, and executes PAC-routed workspace commands.

pac-endpoint workspace register
  One-shot debug/inspection registration. It does not keep the container alive unless called through workspace run.

pac-endpoint probe hardware|tools|workspace
  Local inspection helpers.
```

`workspace run` replaces ad-hoc container keepalive commands such as `sleep infinity` or `tail -f /dev/null`.

## Workspace registration model

A workspace container can be configured through JSON and/or environment variables.

Default config paths:

```text
/etc/pac/workspace.json
/pac/workspace.json
./workspace.pac.json
```

Environment overrides:

```text
PAC_URL or PAC_CONTROLLER_URL
PAC_TOKEN or PAC_WORKSPACE_TOKEN
PAC_WORKSPACE_ID
PAC_WORKSPACE_NAME
PAC_WORKSPACE_ROOT
PAC_WORKSPACE_LIFETIME=persistent|ephemeral
PAC_WORKSPACE_LABELS=dev,python,customer-a
```

Precedence:

```text
CLI flags
ENV variables
workspace JSON
safe defaults
```

`workspace run` lifecycle:

1. Read config and environment.
2. Register or refresh workspace registration in PAC.
3. Mark the workspace online.
4. Start heartbeat and command polling/streaming over outbound HTTPS.
5. Execute only PAC-routed commands authorized for that workspace.
6. When the container stops or loses connectivity, PAC marks the workspace degraded/offline after heartbeat timeout.

No inbound container port is required. Internet/NAT operation is supported by outbound HTTPS or later outbound WebSocket.

## Storage and history

Workspace containers are runtime surfaces, not the source of truth for history.

- Durable storage should be centralized or mounted.
- Command history, command output, session history, audit data, and PAC RAM live in the PAC controller.
- If a workspace disappears while a command runs, PAC marks the command interrupted and preserves the last received output/events.

## `pacctl` role

`pacctl` communicates with PAC, not directly with endpoints by default.

```text
user/script/IDE -> pacctl -> PAC controller -> pac-endpoint -> host/workspace/container
```

`pacctl` should support:

- polling PAC state and events;
- endpoint/workspace command requests routed through PAC;
- provider/model registration and sync;
- generic catalog/schema-driven API calls;
- MCP/editor bridge behavior exposed through `pacctl mcp serve`.

Near-term commands:

```text
pacctl api get PATH
pacctl api post PATH --file payload.json
pacctl poll events|endpoints|workspaces
pacctl provider send --file provider.json
pacctl workspace exec WORKSPACE [--wait] [--timeout SECONDS] -- COMMAND...
pacctl workspace status WORKSPACE
```

`pacctl` may have friendly typed commands, but PAC remains the source of truth for schemas, permissions, and supported operations.

## Controller API expectations

Existing endpoint APIs continue to support host daemon behavior. New/normalized APIs should be added around workspace agents:

```text
POST /v1/workspace-agents/register
POST /v1/workspace-agents/heartbeat
GET  /v1/workspace-agents/{id}/commands/next
POST /v1/workspace-agents/{id}/commands/{command_id}/events
POST /v1/workspace-agents/{id}/commands/{command_id}/complete
```

During migration, `pac-endpoint workspace run` can fall back to endpoint registration/job APIs so the binary can be introduced before the full workspace-agent API exists.

## Cleanup plan

1. Remove `pac-endpoint-runner` from source and release builds.
2. Restrict release binary compilation to primary binaries: `pac-endpoint`, `pacctl`.
4. Add `pac-endpoint workspace run` as the container foreground command.
5. Add `pacctl` generic API, provider send, and polling commands.
6. Continue hardening `pac-endpoint` daemon/workspace modes and `pacctl mcp serve`; the obsolete source folders are already deleted.
8. Update install/UI docs so users see two installable binaries only.

## 2026-05-29 implementation pass: workspace-agent APIs and binary source removal

This pass moves the architecture from design-only into a usable controller/runtime path.

Implemented controller APIs:

```text
POST /v1/workspace-agents/register
POST /v1/workspace-agents/heartbeat
GET  /v1/workspace-agents/{workspace_id}/commands/next
POST /v1/workspace-agents/{workspace_id}/commands/{command_id}/complete
GET  /v1/workspaces
GET  /v1/workspaces/{workspace_id}
POST /v1/workspaces/{workspace_id}/commands
```

`pac-endpoint workspace run` now has a matching controller queue. Containers can register over outbound HTTPS, stay online through heartbeat, receive PAC-routed commands, and become offline automatically when heartbeats stop. Command history and output are stored in PAC, not in the container.

The source tree now keeps only two Go binary products:

```text
binaries/pac-endpoint
binaries/pacctl
```

Removed source folders:

```text
binaries/pac-agent
binaries/zed-binary
binaries/pac-endpoint-runner
```

MCP/editor integration is exposed by `pacctl mcp serve`. Installation and updates download `pac-endpoint` and `pacctl` from GitHub Release assets through the binary installer helper or through controller release-asset resolution. Source/update packages still do not bundle compiled binaries.


## 2026-05-29 implementation pass: main-change binary-first release and command wait

The release workflow now exists in the GitHub-native `.github/workflows/pac-release.yml` path and is mirrored in `github/workflows/pac-release.yml` for packaged visibility. It runs automatically on source pushes to `main` and ignores release metadata-only commits to avoid a release loop.

The workflow compiles `pac-endpoint` and `pacctl` before release packaging, validates that order with `scripts/validate-release-binary-pipeline.py`, and then publishes direct binary assets alongside source/update packages. `scripts/generate-pac-release.py` still fails if `dist/release-binaries/RELEASE_BINARIES.json` is missing, so packaging cannot silently proceed without binary output.

`pacctl workspace exec` now supports `--wait` and `--timeout SECONDS`. With `--wait`, pacctl queues the command through PAC, polls `GET /v1/workspaces/{workspace_id}/commands/{command_id}`, prints captured stdout/stderr, and returns the workspace command exit code. This keeps the command path routed through PAC and the workspace agent rather than direct container access.

## 2026-05-29 implementation pass: live workspace command streaming

Workspace command execution now supports live streaming without bypassing PAC. `pacctl workspace exec WORKSPACE --stream -- COMMAND` queues a command through PAC and then reads a newline-delimited stream from `GET /v1/workspaces/{workspace_id}/commands/{command_id}/stream`.

`pac-endpoint workspace run` claims commands from PAC, executes them with stdout/stderr pipes, and posts ordered command events back to PAC while the command is running. PAC stores those events on the command record together with aggregated stdout/stderr, so history is centralized and remains available after the workspace container stops or goes offline.

The streaming path keeps the existing outbound-only workspace model:

```text
pacctl -> PAC controller -> workspace command queue -> pac-endpoint workspace run -> PAC command events -> pacctl stream
```

No direct `pacctl` connection into the container is required.

## 2026-05-29 live terminal and interrupt update

The workspace-agent command path now supports UI and CLI interruption. PAC owns the command record, stores ordered command events for immediate replay, and exposes a cancel API that marks queued commands interrupted or signals claimed commands for the workspace agent to terminate. `pac-endpoint workspace run` checks PAC while a command runs and reports `interrupted` with exit code `130` when cancellation is requested.

Endpoint detail pages should use the inventory and metrics sent by `pac-endpoint` heartbeats as first-class hardware/health cards, not just raw metadata.

The current command event storage remains intentionally bounded on the command payload. The missing high-volume event-table design is tracked in `docs/workspace-command-event-model-followup-20260529.md`.

## Workspace command event retention

Workspace command output is now appended to a dedicated PAC event store. `pac-endpoint workspace run` posts stdout/stderr/status chunks to PAC, PAC stores them by workspace id, command id, and sequence number, and both the UI terminal and `pacctl workspace exec --stream` replay the same ordered event stream. The command record remains the summary object; event replay is no longer dependent on the command payload.

## Update orchestration follow-up

The Update Center now runs a controller-side environment orchestration phase after applying a PAC release. This keeps the source zip free of bundled binaries while still making the runtime environment ready:

- resolve `pac-endpoint` and `pacctl` from GitHub Release direct assets;
- verify release-manifest checksums;
- install them into the local PAC binary cache;
- regenerate PAC/pi.dev tool instruction files;
- verify the pi.dev runtime after the update.

The GitHub release workflow validates that macOS/OSX binaries are part of the first-class target matrix by requiring both `darwin/amd64` and `darwin/arm64` in the binary build script.
