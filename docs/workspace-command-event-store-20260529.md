# Workspace command event store

PAC now stores workspace command output in a dedicated append-only event table instead of relying only on the command payload.

## Purpose

Workspace agents can stream high-volume stdout/stderr chunks while PAC keeps command history available after the workspace container stops. The command record remains the summary object, while the event table is the replay source for live terminal, `pacctl --stream`, and history views.

## Data model

`workspace_agent_command_events` stores:

- event id
- workspace id
- command id
- monotonic per-command sequence number
- stream name: `stdout`, `stderr`, `system`, or `status`
- event payload as JSON
- creation timestamp

`WorkspaceAgentCommand.events` is now only a small recent tail for compatibility/debug display. `output` and `error` remain aggregated command summaries.

## APIs

- `POST /v1/workspace-agents/{workspace_id}/commands/{command_id}/events`
  - appends an event from a workspace agent
- `GET /v1/workspaces/{workspace_id}/commands/{command_id}/events?cursor=N&limit=500`
  - replays durable stored events after a cursor
- `GET /v1/workspaces/{workspace_id}/commands/{command_id}/stream?cursor=N`
  - streams stored events live as newline-delimited JSON

## UI behavior

The workspace live terminal now has a command history rail. Selecting a previous command replays its stored event history without requiring the workspace container to still be online.

## Remaining work

This pass adds the durable store. Later work should add retention/archive controls, byte-count/truncation metadata, and a richer command history browser that can filter by actor, workspace, status, and time range.
