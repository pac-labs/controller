# PAC debug bundle download status

PAC exposes a session-scoped platform debug bundle for support workflows where a
session appears stuck, a provider stream does not stop, a coding workspace fails
to attach, tool pipeline validation behaves unexpectedly, or UI timeline events do
not explain what happened.

## Implemented

- `GET /v1/sessions/{session_id}/debug-bundle.zip` creates a redacted support zip.
- The thought/details modal includes **Generate and download debug** next to
  **Close** so the bundle can be downloaded from the place where the failure is
  being inspected.
- The bundle includes session diagnostics, events, task metadata, active task
  details, model/provider/context configuration, workspace git/file state,
  runtime process/port/container/service snapshots, and recent PAC log tails.
- Obvious tokens, API keys, cookies, bearer values, passwords, and secrets are
  redacted before being written to the bundle.

## Bundle contents

- `support-summary.md` — quick human-readable overview.
- `session/diagnostics.json` — combined session diagnostic payload.
- `session/events.json` — sanitized timeline events.
- `session/tasks.json` — task state and transcript metadata.
- `session/active-tasks.json` — running/queued/approval task subset.
- `session/workspace.json` — workspace existence, git state, and file sample.
- `platform/*.txt` — process, port, container, and service snapshots.
- `logs/*.tail.txt` — recent PAC log tails from app/data/workspace roots.

## Remaining improvements

- Add a progress toast while the debug zip is being generated.
- Add selectable scopes such as session-only, platform, endpoint, or include
  larger log history.
- Add server-side audit events for debug bundle generation.
- Add explicit endpoint log pull support for remote/container-only endpoint
  failures.
