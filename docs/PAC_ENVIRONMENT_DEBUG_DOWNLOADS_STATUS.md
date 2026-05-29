# PAC Environment Debug Downloads Status

## Current state

The global Downloads area can generate a redacted platform support bundle before exposing it as a downloadable artifact. The bundle is intended for troubleshooting platform-level behavior without requiring users to paste large shell commands into a session.

## Bundle contents

A generated environment bundle includes:

- `support-summary.md` as the first file to inspect.
- `environment/runtime.json` with process/runtime basics.
- `environment/sessions.json` with redacted recent session metadata.
- `environment/tasks.json` and `environment/active-tasks.json` with redacted task metadata.
- `environment/recent-events.json` with redacted recent platform/session events.
- `latest-session/diagnostics.json` when a latest session can be inspected.
- `platform/*.txt` snapshots for process, port, container, and service state.
- `logs/*.tail.txt` with recent redacted PAC log tails.
- `generation/errors.json` with collector/digest warnings.

## Reliability contract

Bundle generation should be best-effort and section-safe:

- A failing collector must not prevent the zip from being created.
- A single incompatible session/task/event record must not prevent the relevant list from being written.
- Optional session fields such as provider, endpoint, and profile must be read defensively because older Session models may not expose them as direct attributes.
- Digest errors are recorded as redacted entries in `generation/errors.json`.

## Remaining useful improvements

- Add progress polling for very large debug bundles.
- Add selectable scopes: session-only, platform, endpoint, logs, or deep support.
- Pull endpoint-side logs for remote/container-only failures.
- Add a visible warning in the Downloads UI when the generated bundle contains `generation/errors.json` entries.
