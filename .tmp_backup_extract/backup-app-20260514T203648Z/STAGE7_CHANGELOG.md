# Stage 7 changelog

## Added

- Remote runner job queue persisted in SQLite.
- Runner job lifecycle: queued, claimed, running, completed, failed, cancelled.
- Runner pull loop: runners now poll `/v1/runners/{runner_id}/jobs/next`.
- Host execution mode: run commands directly on a registered Linux runner host.
- Container execution mode: run commands inside Podman/Docker containers on a runner host.
- Automatic container runtime selection: `auto`, `podman`, or `docker`.
- Runner job logs streamed back to the PAC as session events.
- Runner job result reporting updates the linked task status/output.
- Web UI can target a task to a selected runner and choose host/container execution.
- Runner CLI flags for workdir, job timeout, and disabling host/container modes.

## Safety notes

- Remote command execution now works. Keep `auth.enabled=true` when exposing the PAC outside a trusted LAN.
- Host execution mode is powerful and should be used only on machines you trust.
- Container execution mode is safer but still needs careful volume, network and image policy hardening for production.

## Still to do

- Real model-driven agent loop that calls selected LLMs and uses tools automatically.
- Proper per-runner API keys instead of shared bearer token.
- Job cancellation from UI.
- Network restrictions for container jobs.
- Artifact upload/download per job.
- OIDC/RBAC.
