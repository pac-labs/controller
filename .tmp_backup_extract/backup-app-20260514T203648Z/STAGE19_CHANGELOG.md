# Stage 19 — pacctl container control + pi.dev-as-runner

## pacctl binary

**Source version:** 1.0.0

New `pacctl` Go binary (`~/.pacp/bin/pacctl`) provides persistent container control for all pi-agent-harness containers.

**What it does:**
- Runs as a **server** inside containers (TCP port 9123), accepting JSON-RPC commands
- Runs as a **client** from any host, sending commands to running containers
- Enables pause/resume, bidirectional exec, and workspace file access from outside the container

**Binaries built (5 platforms):**
- `pacctl-linux-amd64` — Linux x86_64
- `pacctl-linux-arm64` — Linux ARM64
- `pacctl.exe` — Windows x86_64
- `pacctl-darwin-amd64` — macOS x86_64
- `pacctl-darwin-arm64` — macOS ARM64

Stored in `~/.pacp/sources/binaries/pacctl/`, served via PAC binary-artifacts endpoint.

**Protocol:** JSON-RPC over TCP port 9123 (platform-agnostic).

**Verified commands:**
- `pacctl status <host>` — container PID, platform, arch, paused flag
- `pacctl in <host> <cmd>` — exec in container, returns stdout+stderr+exit code
- `pacctl pause <host>` / `pacctl resume <host>` — pause/resume cycle works
- Daemon containers stay alive after task completion

## New pi-agent-harness:stage11 image

Rebuilt `localhost/pi-agent-harness:stage11` image now includes:
- `pacctl` binary at `/usr/local/bin/pacctl`
- New `entrypoint.sh` that starts `pacctl server` in background before the pi.dev agent
- Proper `/tmp/pacctl` directory (user-writable instead of `/run/pacctl`) owned by `piagent:10001`
- Support for `PI_AGENT_CONTAINER_MODE=daemon` for persistent container keepalive

**Image contents:**
- Node.js runtime (Debian-slim)
- pi.dev harness (`pi` or `pi-agent` npm package)
- pacctl binary (Linux amd64)
- `tini` as init process

## Terminology (confirmed)

- **pi.dev** = the runtime (was previously called pi, agent, harness)
- **pi-agent-harness** = the container image
- **pacctl** = the container control binary (new)
- **PAC wrapper/tooling** = software that wraps or controls pi.dev

## Endpoint terminology (Stage 18 carryover)

- UI calls remote workers **Endpoints** (not runners)
- `/v1/endpoints` added as aliases for `/v1/runners`
- Endpoints report PAC endpoint version in heartbeat metadata
- Per-endpoint update actions; control plane can build update packages
