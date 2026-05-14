# Stage 14

- Added a Runners tab delete action for pending/stale runners.
- Added `POST /v1/runners/local` to add/refresh the PAC host as a first-class local runner entry.
- Local PAC runner reports host capabilities and Podman/Docker containers.
- Selecting the local PAC runner falls back to direct in-process PAC execution instead of waiting for a remote runner daemon.
