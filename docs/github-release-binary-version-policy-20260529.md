# GitHub release binary and component version policy

PAC release generation now separates controller release versioning from buildable component versioning.

## Release order

The GitHub release workflow performs release work in this order:

1. Resolve the PAC controller release version from the requested input or the latest `vX.Y.Z` tag.
2. Write controller-owned release markers: `VERSION`, `VERSION_CURRENT.md`, and `pyproject.toml`.
3. Set up Go.
4. Compile every Go binary component under `binaries/*` with `scripts/compile-release-binaries.py`.
5. Generate the PAC release zips with `scripts/generate-pac-release.py` using the already compiled binary output.
6. Publish `pac-full.zip`, `pac-patch.zip`, `pac-packages-seed.zip`, `pac-binaries.zip`, the release manifest, and the update diff.
7. Sync the generated `pac-labs/packages` source repository.

The release artifact generator now requires `dist/release-binaries/RELEASE_BINARIES.json`. This makes missing binary compilation a release failure instead of silently producing incomplete release packages.

## Component-owned versions

Binary and source package components do not inherit the PAC controller release version.

Each component version is read from the component itself:

1. `<component>/VERSION`
2. `<component>/pac-component.json` `version`
3. `dev` only as a local fallback when no component version exists

This means a PAC controller release can move from `1.0.415` to `1.0.416` without renaming or re-versioning `pac-endpoint`, `pacctl`, or workspace containers when their sources did not change.

## Source update detection

The generated packages manifest records a stable `content_hash` for every component. PAC source update checks now treat content hash as the strongest signal:

- same component hash: current, even when the controller release version changed
- different component hash: update, even if the component version was not bumped yet
- missing hash: fall back to component version comparison

The packages manifest still records the PAC release version as `pac_release_version` for traceability, but individual component versions remain component-owned.
