# Workspace command live streaming

Date: 2026-05-29
Version: 1.0.422

PAC workspace commands now support live stdout/stderr streaming while still keeping command history centralized in PAC.

## Flow

```text
pacctl workspace exec WORKSPACE --stream -- COMMAND
  -> POST /v1/workspaces/{workspace_id}/commands
  -> pacctl opens GET /v1/workspaces/{workspace_id}/commands/{command_id}/stream
  -> pac-endpoint workspace run claims the command
  -> pac-endpoint posts incremental stdout/stderr chunks
  -> PAC stores ordered command events and aggregated output/error
  -> pacctl prints events as they arrive
  -> pac-endpoint posts command completion and exit code
  -> stream closes with final command status
```

The workspace container still only needs outbound HTTPS access to PAC. PAC remains the source of truth for command state, output history, and command events. When a container stops, the workspace goes offline through heartbeat timeout, but previous command output remains available in PAC.

## Controller APIs

```text
POST /v1/workspace-agents/{workspace_id}/commands/{command_id}/events
GET  /v1/workspaces/{workspace_id}/commands/{command_id}/stream
```

The stream endpoint emits newline-delimited JSON records. Event records include `seq`, `stream`, `data`, and `created_at`. The terminal record includes the final `status` and `exit_code`.

## Endpoint behavior

`pac-endpoint workspace run` now executes claimed commands with stdout/stderr pipes. It forwards each line as a command event and then posts completion with the final exit code. Final stdout/stderr are still included in the completion payload so history remains complete even if an event post is missed.

## pacctl behavior

`pacctl workspace exec` now supports:

```sh
pacctl workspace exec WORKSPACE --stream -- COMMAND...
```

`--stream` implies wait mode. stdout records print to stdout, stderr and system/status records print to stderr, and the process exits with the workspace command exit code.

`--wait` remains available for polling-only environments and prints the aggregated output after the command completes.

## Event model follow-up

Live terminal output currently uses the command record as the event carrier. The missing durable/high-volume event details are tracked in `docs/workspace-command-event-model-followup-20260529.md`.

## 2026-05-29 update: durable event replay

Live streaming now reads from the append-only `workspace_agent_command_events` store. The command record keeps a bounded recent event tail and aggregate stdout/stderr fields, but replay and history use the event table. This keeps command history centralized in PAC even when a workspace container exits and prevents large terminal output from growing the command row without bound.
