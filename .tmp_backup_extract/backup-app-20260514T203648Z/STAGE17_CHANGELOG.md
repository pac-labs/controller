# Stage 17 - Self update upload

- Added Settings > Self update / stage package panel.
- Added `/v1/admin/stage-package` to upload PAC stage zip files through the Web UI.
- Validates stage zip layout before installing.
- Copies only project-owned files into `~/.pacp/app`.
- Creates backups in `~/.pacp/updates/backup-app-*`.
- Reinstalls the package into the existing virtualenv when possible.
- Adds `/v1/admin/restart` to exit PAC so systemd/container restart policies can restart it.
- Added `python-multipart` dependency for browser file uploads.
