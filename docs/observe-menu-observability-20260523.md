# Observe menu observability placement

PAC already has a top-level **Observe** navigation group. Controller-local observability must live there instead of creating another System/Config observability area.

## Rule

- **Observe** is for runtime evidence: events, logs, metrics, traces, model usage, endpoint job evidence, and diagnostics.
- **Config** is for configuration values and setup state.
- Endpoint action details may link to observability, but should not become the primary observability surface.

## Implemented in v1.0.334

- Added an **Observability** tab under the existing Observe menu.
- Kept **Events** as the event rail action under the same Observe menu.
- Added controller log tailing for controller and audit logs.
- Added lightweight metric/model usage snapshots.
- Kept the existing rotating log API as the backend source.
