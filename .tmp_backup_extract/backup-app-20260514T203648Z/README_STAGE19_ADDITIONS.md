# Stage 19 additions — for insertion into the main README

This file documents what Stage 19 adds. Merge these sections into the main README at the appropriate places.

---

## Version header (update)

**Current version:** 1.0.106 | **Stage:** 19

(Replace `v1.0.105` / `Stage 18` with the values above)

---

## Stage 19 summary (add after Stage 18 in the version history)

```text
## Stage 19: pacctl container control

Stage 19 adds the `pacctl` Go binary for persistent container control and rebuilds the pi-agent-harness image with container-as-runner support.

### pacctl binary (new)

`pacctl` is a multi-command Go tool that runs as a server inside containers and as a client from any host:

- **Server** — inside pi-agent-harness containers, listens on TCP port 9123 for JSON-RPC commands
- **Client** — on the PAC host or any machine, sends commands to running containers

Cross-platform binaries (5 targets):
- `pacctl-linux-amd64` / `pacctl-linux-arm64`
- `pacctl.exe` (Windows)
- `pacctl-darwin-amd64` / `pacctl-darwin-arm64`

Stored in `~/.pacp/sources/binaries/pacctl/`, served via the binary-artifacts API.

Client commands:
```bash
pacctl in <container-ip> <command>   # exec in container
pacctl status <container-ip>         # get status
pacctl pause <container-ip>           # pause container
pacctl resume <container-ip>         # resume container
```

### New pi-agent-harness:stage11 image

Rebuilt `localhost/pi-agent-harness:stage11` now includes:
- `pacctl` binary at `/usr/local/bin/pacctl`
- `entrypoint.sh` that starts `pacctl server` in background before the pi.dev agent
- Proper `/tmp/pacctl` runtime directory (user-writable, owned by `piagent`)
- `PI_AGENT_CONTAINER_MODE=daemon` support for persistent keepalive

Protocol: JSON-RPC over TCP port 9123 (platform agnostic).

### Endpoint update (Stage 18 carryover)

- UI calls remote workers **Endpoints** (not runners)
- `/v1/endpoints` added as aliases for `/v1/runners`
- Endpoints report their PAC endpoint version in heartbeat metadata
- Per-endpoint update actions; control plane builds update packages
```

---

## Documentation files (add to index table)

| Doc | What it covers |
|-----|---------------|
| `STAGE19_CHANGELOG.md` | Full Stage 19 changelog |
| `sources/containers/pi-agent-harness/README.md` | pi-agent-harness container documentation |
| `sources/binaries/pacctl/README.md` | pacctl binary documentation |
