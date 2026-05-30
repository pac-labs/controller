# Automatic generated-file housekeeping

PAC now treats generated downloads, debug bundles, update extractions, rollback copies, stale binary cache, and local build/cache output as managed temporary resources.

## Why

Long local development and repeated update tests can leave many gigabytes of generated files under the PAC runtime home. The largest growth categories observed on a development host were:

- `updates/backup-app-*` rollback copies
- `updates/downloads/pac-full-*.zip` release downloads
- `updates/extracted-*` unpacked update trees
- old `release-binaries/` folders from previous packaging behavior
- Python cache files under app/update trees

These should not require manual host cleanup.

## Runtime policy

PAC runs generated-file housekeeping:

1. on controller startup,
2. after applying a GitHub release update,
3. when triggered from Update Center.

Default retention:

| Resource | Retention |
|---|---:|
| Environment/debug bundles | newest 1 and max 24 hours |
| Update downloads | newest 1 full zip |
| Extracted updates | removed after apply/startup cleanup |
| Rollback backups | newest 2 `backup-app-*` directories |
| Release asset cache | newest cache generation |
| Old logs | older than 7 days |
| Binary cache | newest per current binary/platform; removed transitional binaries are deleted |
| Source tree generated files | `dist/`, `build/`, `release-binaries/`, `__pycache__`, `.pyc`, test/coverage caches |

## API

```text
GET  /v1/updates/housekeeping
POST /v1/updates/housekeeping
```

`GET` returns storage roots, sizes, counts, running state, and the last housekeeping result.

`POST` accepts:

```json
{
  "dry_run": true,
  "keep_debug_bundles": 1,
  "debug_bundle_max_age_hours": 24,
  "keep_update_backups": 2,
  "keep_update_downloads": 1,
  "keep_release_assets": 1,
  "update_temp_max_age_hours": 24,
  "log_max_age_days": 7,
  "keep_binary_versions": 1
}
```

The Update Center exposes both **Preview cleanup** and **Clean now**.

## Safety boundaries

Housekeeping does not remove:

- `.git`
- virtual environments
- `node_modules`
- configured PAC data stores
- current config files
- PAC RAM/session stores
- source files

Debug bundles are treated as temporary generated downloads. Command/session history remains in PAC stores, not in generated debug zip files.
