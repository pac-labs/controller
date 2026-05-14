# GitHub push token and package synchronization

PAC uses two repositories:

- `pac-labs/controller` for the controller application and release workflow.
- `pac-labs/packages` for the generated package/source repository used by the Source Library.

The controller repository workflow expects a repository secret named `push_token`.

## What the token is used for

`push_token` is used by GitHub Actions when PAC needs to write outside the default workflow scope:

- creating or pushing release tags from `pac-labs/controller`;
- publishing release assets from the controller workflow;
- checking out and pushing generated package/source folders into `pac-labs/packages`;
- applying approved PAC diff PRs back onto `main`.

The token should have write access to both repositories. A fine-grained GitHub token should be limited to:

- `pac-labs/controller`: contents read/write, pull requests read;
- `pac-labs/packages`: contents read/write.

## Source package sync

The package sync workflow mirrors these controller folders into `pac-labs/packages`:

- `binaries/`
- `containers/`
- `plugins/`
- `scripts/`
- `docs/`

Each component can include `pac-component.json` metadata. The generated packages repository also gets a root `packages.json` manifest that PAC can read for online source-module update discovery.

## Naming

The controller keeps stable local artifact names to avoid local version skew:

- `pac-full.zip`
- `pac-patch.zip`
- `pac-packages-seed.zip`
- `PAC_RELEASE_MANIFEST.json`
- `PAC_UPDATE_DIFF.diff`

GitHub tags and release manifests are the version authority.
