# Endpoint telemetry and workspace-agent status

PAC uses two shipped binaries:

- `pac-endpoint` is the resident wrapper on hosts and workspace containers.
- `pacctl` is the client used by users, scripts, IDEs, and automation to talk to PAC.

This update makes `pac-endpoint` responsible for lightweight hardware inventory and runtime metrics forwarding. The telemetry is PAC-native first: the endpoint sends structured JSON in its heartbeat so PAC can show endpoint/workspace health even before an external VictoriaMetrics or log stack is configured.

## Host endpoint telemetry

`pac-endpoint` now collects and forwards:

- hostname, OS, architecture, and kernel/version information
- CPU model and logical core count where available
- total memory where available
- workspace/root disk usage via `df` on Unix-like systems
- network interface names, MAC addresses, flags, and addresses
- discovered endpoint tools and required tool readiness
- lightweight runtime metrics such as Linux load average and memory usage

The host daemon sends this information in `/v1/endpoints/heartbeat` under both capabilities and metadata. This keeps the controller-side endpoint record useful for scheduling, debugging, and UI display without adding another mandatory metrics service.

## Workspace container telemetry

`pac-endpoint workspace run` now refreshes inventory and metrics on every workspace heartbeat. PAC stores this in the workspace agent metadata and exposes it through:

- `GET /v1/workspaces`
- `GET /v1/workspaces/{workspace_id}`

The workspace side panel can show online/degraded/offline state plus recent metrics such as load or memory usage.

## Offline behavior

Workspace containers are still treated as ephemeral runtime. PAC remains the source of truth for registration state, command history, PAC RAM, events, and audit trail. When the container stops or loses its outbound connection, heartbeats stop and PAC marks the workspace degraded/offline based on heartbeat age.

## Future work

The next pass should add live command-output streaming and richer UI cards for endpoint hardware/metrics. The telemetry payload is intentionally JSON-shaped so it can later be forwarded to VictoriaMetrics/VictoriaLogs/VictoriaTraces without changing the basic endpoint contract.
