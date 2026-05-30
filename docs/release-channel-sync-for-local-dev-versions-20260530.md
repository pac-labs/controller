# Release channel sync for local development versions

PAC can be developed locally faster than GitHub Releases are produced. During those windows the running controller may report a semantic version that is equal to, or higher than, the latest published release. The updater must still allow the operator to sync the environment back to the official GitHub release channel.

## Problem

The previous updater used semantic version ordering as the only decision signal:

```text
latest GitHub version > local PAC version = update available
otherwise = current
```

That fails when local direct development bumps `VERSION` ahead of the latest release, or when GitHub publishes an official release build for the same semantic version after the local development build was created.

## Decision model

Release checks now return both semantic and release-channel identity:

- `version_comparison`
- `update_reason`
- `can_apply_update`
- `local_release_identity`

The updater treats these states as applyable:

| State | Meaning | Apply behavior |
| --- | --- | --- |
| `remote_newer` | GitHub semantic version is newer. | Normal update. |
| `local_version_ahead` | Local development version is higher than the latest GitHub release. | Release-channel sync is allowed. |
| `same_version_newer_release_build` | Same semantic version, but GitHub published a newer release build than the local manifest. | Release-channel sync is allowed. |
| `current` | Local install matches the release channel. | No update action. |

## Local identity

PAC reads `MANIFEST.json` from the running controller tree and uses:

- `version`
- `generated_at`
- file count for diagnostics

When the GitHub release `published_at` timestamp is newer than local `MANIFEST.generated_at` for the same version, PAC offers a sync even though the semantic version is equal.

## UI behavior

The Update Center no longer hides applyable releases just because the local semantic version is ahead. It shows this as a release-channel sync rather than a normal upgrade.

## Safety

The apply path still requires a valid GitHub release asset and still uses the normal preservation/update flow. This change only affects whether the Update Center considers a release applyable.
