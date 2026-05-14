# Stage 12 changelog

## Added

- Persistent PAC home directory at `~/.pacp` by default.
- `PACP_HOME=/path/to/.pacp` override for all server state and configuration.
- Config now lives at `~/.pacp/config/config.yaml`.
- SQLite state now lives at `~/.pacp/state.db`.
- Workspace, session, artifact, log, cache and runtime lock directories are created under `~/.pacp`.
- Single-instance PAC lock at `~/.pacp/run/server.lock` to prevent two servers from using the same state directory.
- Installer now defaults the application install to `~/.pacp/app` and the service name to `pacp`.
- Web UI now has top navigation tabs: Dashboard, Sessions, Runners, Models, Approvals and Settings.
- Dashboard now shows PAC home/config/lock paths and runner summary.
- Settings tab shows persistent paths and keeps the raw config editor.

## Changed

- The UI keeps the dark purple/sharp-corner theme but is organized more like a dashboard instead of one long page.
- Launching the server from a different directory now uses the same PAC home and config by default.
- Development script also uses `~/.pacp` instead of local `./config` / `./data`.

## Notes

The project keeps the historical package name for now, but the runtime identity is now PACP: Pi Agent Control.
