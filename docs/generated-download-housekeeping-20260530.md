# Generated download housekeeping

Status: implemented in v1.0.427.

PAC treats generated downloads as cache, not as long-term source of truth. The Downloads modal can produce binaries and support bundles quickly, but those files should not accumulate forever inside `PACP_HOME`.

## Policy

### Binary downloads

Binary artifacts under `PACP_HOME/source-builds/binaries` are generated outputs. The only first-class release binaries are:

- `pac-endpoint`
- `pacctl`

The **Keep newest only** action now does real housekeeping instead of only comparing semantic versions. It:

- removes generated artifacts for deprecated/removed binary folders such as `pac-agent`, `zed-binary`, and `pac-endpoint-runner`;
- keeps the newest configured version group;
- collapses duplicate unversioned/current artifacts to the newest file per platform target;
- reports deleted bytes, deleted files, and notes about deprecated folders.

This fixes the old behavior where all files could be considered one `unversioned` group and nothing was deleted.

### Environment debug bundles

Environment debug bundles under `PACP_HOME/debug-bundles` are temporary support downloads. They are generated on demand, downloaded by the user, and can be regenerated later.

Current retention:

- keep the newest generated bundle;
- remove bundles older than 24 hours;
- expose a **Clear old bundles** action in the Downloads modal;
- automatically prune old bundles when listing or generating bundles.

### Update temp/cache files

Update downloads, extracted release assets, upload temp files, and old backup directories are generated update state. PAC now has an update housekeeping service that can remove:

- `PACP_HOME/updates/downloads`
- `PACP_HOME/updates/uploads`
- `PACP_HOME/updates/release-assets`
- `PACP_HOME/updates/extracted-*`
- old `PACP_HOME/updates/backup-app-*` folders beyond the newest rollback set

Rollback backups are not all deleted blindly. PAC keeps a small newest set by default.

## Debug bundle log filtering

Generated debug bundles no longer include log tails from old `updates/backup-app-*` directories. Those logs made support bundles noisy and stale because every backup copy of `pi-agent-artifacts` contributed another tail file.

Environment debug bundles now prefer recent current-runtime logs only.

## Follow-up

The Update Center can call update housekeeping through the API, but the UI should later add a dedicated "Clean generated update cache" action with a preview/detail drawer.
