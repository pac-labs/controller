# Workspace command event model follow-up

The first durable command-event store is now implemented through `workspace_agent_command_events`.

## Implemented

- Append-only command events are stored outside the workspace command payload.
- Stream replay reads from the event table by monotonic sequence cursor.
- Command payloads retain only a bounded recent tail plus aggregate stdout/stderr summaries.
- UI terminal history can replay prior command events after a workspace disconnects.

## Still needed later

- Retention and archival policy for high-volume command output.
- Byte length and truncation metadata for very large chunks.
- Agent-emitted timestamp distinct from controller receive timestamp.
- Actor/source fields normalized beyond the current metadata payload.
- Search/filter UI for command history across workspaces.
- Optional export path for command event history into external observability/log storage.
