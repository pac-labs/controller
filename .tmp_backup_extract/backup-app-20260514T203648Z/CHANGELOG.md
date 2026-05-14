# Changelog

All notable changes to PAC are documented here. PAC uses a two-part version number: the **controller version** (`1.0.x`) and the **stage number** (Stage N). The controller version lives in `app/VERSION` and `app/VERSION_CURRENT.md`. The stage number is the milestone tag for a set of features and fixes.

---

## [Stage 19] — 1.0.106

**pacctl binary (new)**

`pacctl` is a multi-command Go tool that runs as a server inside containers and as a client from any host.

- **Server** — inside pi-agent-harness containers, listens on TCP port 9123 for JSON-RPC commands
- **Client** — on the PAC host or any machine, sends commands to running containers
- **Methods:** `status`, `exec`, `file_write`, `file_read`, `pause`, `resume`, `metadata`
- **Protocol:** JSON-RPC over TCP port 9123 (platform agnostic)

Cross-platform binaries (5 targets):
- `pacctl-linux-amd64` / `pacctl-linux-arm64`
- `pacctl.exe` (Windows x86_64)
- `pacctl-darwin-amd64` / `pacctl-darwin-arm64`

Stored in `~/.pacp/sources/binaries/pacctl/`, served via the binary-artifacts API.

Client commands:
```bash
pacctl in <container-ip> <command>   # exec in container
pacctl status <container-ip>          # get status, PID, paused flag
pacctl pause <container-ip>           # pause container
pacctl resume <container-ip>          # resume paused container
```

**New pi-agent-harness:stage11 image**

- `pacctl` binary at `/usr/local/bin/pacctl`
- New `entrypoint.sh` starts `pacctl server` in background before the pi.dev agent
- Proper `/tmp/pacctl` runtime directory (user-writable, owned by `piagent`)
- `PI_AGENT_CONTAINER_MODE=daemon` support for persistent container keepalive
- Container stays alive in eternal pause after task completion

**Endpoint terminology (Stage 18 carryover)**

- UI calls remote workers **Endpoints** (not runners)
- `/v1/endpoints` added as aliases for `/v1/runners`
- Endpoints report PAC endpoint version in heartbeat metadata
- Per-endpoint update actions; control plane builds update packages

---

## [Stage 18] — 1.0.105

### Endpoint terminology
- UI now calls remote workers **Endpoints** instead of runners.
- Added `/v1/endpoints` aliases while keeping `/v1/runners` for backwards compatibility.

### Endpoint versioning and updates
- Endpoints report their PAC endpoint version in heartbeat metadata.
- Endpoint cards show version and update status.
- Added **Update endpoint** action per online remote endpoint.
- Added **Update all online endpoints** action.
- Control plane can build a current PAC package via `/v1/admin/current-package`.
- Endpoint update jobs download that package, backup the endpoint app dir, install the new app files, and mark restart-required.

### Fixes
- Fixed endpoint service CLI argument parsing: `--control-plane` and legacy `--PAC` now both work.

---

## [Stage 17] — 1.0.104

*(No major new features — minor release)*

---

## [Stage 16] — 1.0.103

- Renamed visible product to **PAC — Pi Agent Control**.
- Added persistent right-side **Events rail** for a dashboard-like control room experience.
- Runtime/config state still lives under `~/.pacp` by default.

---

## [Stage 15] — 1.0.102

*(Content not available in source)*

---

## [Stage 14] — 1.0.101

*(Content not available in source)*

---

## [Stage 13] — 1.0.100

*(Content not available in source)*

---

## [Stage 12] — 1.0.99

### PAC home and dashboard tabs
PACP now uses a persistent home directory by default:

```
~/.pacp/
  config/config.yaml
  state.db
  workspaces/
  sessions/
  artifacts/
  logs/
  cache/
  run/server.lock
  app/
```

Override with `PACP_HOME=/data/pacp ./install.sh`. A lock file at `~/.pacp/run/server.lock` prevents two servers from running against the same state.

The web UI now has top-level tabs for Dashboard, Sessions, Runners, Models, Approvals and Settings.

---

## [Stage 11] — 1.0.98

Added a real `pi_container` execution mode. The Python runner can now start a disposable container that contains Node and pi.dev, stream logs back to the PAC, and upload artifacts from the workspace.

### Build the pi.dev image
```bash
podman build -t localhost/pi-agent-harness:stage11 containers/pi-agent-harness
```

---

## [Stages 1–10]

See `VERSION_1.md` for the consolidated v1.0 baseline history.

---

## CSS/styling changes (1.0.108)

*These changes are tracked in `changed_1.0.108.txt` and represent the latest styling update pending formal staging:*

- Flat slate panels (`rgba(15,23,42,.70)`) replaced all purple-gradient card backgrounds
- Page background `#08070d → #0c0f14` (dark gray slate)
- All buttons: `border-radius: 0` (square corners)
- Active tab: removed inset purple glow underline (kept purple bg)
- Events rail, modal cards, session chat cards, runtime panel, workspace cards: all flat slate
- Pac-icon.svg: `rx="10" → rx="0"` (square icon)
- Version badge: plain text → purple pill with border
- Models tab: new 2-column layout (configured | live server models)
- Providers tab: new 2-column layout (provider grid | live models)
- Profiles tab: inline form → modal-based create/edit (`profilemodal`)
- Workspaces tab: inline form → modal-based
- Tools tab: inline form → modal-based
- New CSS layout classes: `.models-overview-layout`, `.providers-overview-layout`, `.profiles-overview-layout`, `.workspaces-overview-layout`, `.tools-overview-layout`
- Sticky right panels for providers, profiles, workspaces, and tools tabs

---

## [Stage 20] — 1.0.107

**pacctl binary**

New `pacctl` Go binary for persistent container control.

- Server inside containers (TCP port 9123, JSON-RPC)
- Client mode for pause/resume/exec from any host
- 5 platform binaries: linux amd64/arm64, darwin amd64/arm64, windows
- Deployed to `~/.pacp/bin/pacctl` on PAC updates

**Source library — binary build system**

- `scripts/generate-changelog.py` — generates per-version change entries from changed_*.txt fragments
- `scripts/generate-local-diff.py` — generates a local diff against a git tag
- `binaries/pacctl/` — new source folder (Go module)
- `binaries/pacctl/Containerfile` — multi-stage Docker build
- `binaries/pacctl/main.go` — JSON-RPC server + client implementation
- Binary build artifacts tracked and downloadable via the Source Library UI

**UI — flat slate design refresh**

- New `web/styles.css.v107` — flat slate panel design replacing purple gradient cards
- Page background `#08070d` to `#0c0f14` (dark gray-blue slate)
- Panel background `rgba(15,23,42,.70)` — flat dark slate with border
- `--border` token unified: `rgba(148,163,184,.2)`; `--border-strong: #241a3b`
- `--radius` base `4px` to `6px`; buttons: `border-radius: 0` (square)
- Active tab: removed inset purple glow, kept purple background
- Removed box-shadow drop-shadow filters from brand-logo, pac-loader, hero-mark
- Status strip background to `rgba(15,23,42,.4)`

**UI — endpoint/source library**

- Tab bar: Source and Endpoints tabs added to the main navigation rail
- Source Library: tabbed by source type (docs, scripts, configs, containers, etc.)
- Binary build and artifact management in Source Library
- Endpoint cards show version and update status
- "Update endpoint" / "Update all online endpoints" actions

