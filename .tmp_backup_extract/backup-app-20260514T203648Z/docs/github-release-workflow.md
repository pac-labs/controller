# PAC GitHub release workflow

PAC publishes version packages through `.github/workflows/pac-release.yml`.

The workflow reads the version from `VERSION`, validates `VERSION_CURRENT.md`, generates release artifacts, creates a Git tag when manually requested, and publishes a GitHub Release.

Generated assets:

- `pac-full-<version>.zip`
- `pac-patch-<version>.zip`
- `PAC_CHANGELOG.json`
- `PAC_RELEASE_MANIFEST.json`

The patch zip is intentionally a complete PAC application update package. PAC's local updater replaces project-owned directories from the package root, so partial application zips can be unsafe when they include only part of `pi_agent_platform/`. The manifest still records the changed file delta for display and audit purposes.

## Manual release

1. Update `VERSION` and `VERSION_CURRENT.md`.
2. Add `changed_<version>.txt` or update `PAC_CHANGELOG.json`.
3. Push to `main`.
4. Run **PAC release** from GitHub Actions.
5. Confirm release assets are attached to tag `v<version>`.

## Online update source

PAC can use GitHub Releases as the online version source. The important URLs are the latest release metadata and the release assets named above. `PAC_CHANGELOG.json` gives the version delta shown in the update preview.
