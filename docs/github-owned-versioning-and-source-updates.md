# GitHub-owned versioning and source module updates

PAC no longer relies on manually named local artifacts as the version authority.
The controller repository is the source of code, but GitHub Releases provide the
release version.

## Controller releases

The `PAC release` workflow resolves the next release version from GitHub tags:

1. If a workflow-dispatch version is provided, that version is used.
2. Otherwise the workflow finds the latest `vX.Y.Z` tag and bumps the patch
   number.
3. The workflow writes that generated version into `VERSION` and
   `VERSION_CURRENT.md` inside the build workspace only.
4. Release artifacts use stable filenames:
   - `pac-full.zip`
   - `pac-patch.zip`
   - `pac-packages-seed.zip`
   - `PAC_RELEASE_MANIFEST.json`
   - `PAC_UPDATE_DIFF.diff`

The tag and manifest identify the version. Stable artifact names avoid local file
version skew.

## Source module update discovery

The Settings updates panel can check the online package repository manifest:

```text
https://raw.githubusercontent.com/pac-labs/packages/main/packages.json
```

The controller compares every online component in `packages.json` with the local
Source Library by `source_path`, component content hash, and component version. It reports:

- new components that are online but not installed locally
- updated components where the online content hash differs or, when hashes are unavailable, the online component version is newer
- current state when component hashes match, even if the PAC controller release version changed

The packages repository remains a tiny source-module repository. It mirrors the
PAC source roots:

- `binaries/`
- `containers/`
- `plugins/`
- `scripts/`
- `docs/`

Each component should include `pac-component.json` for title, description,
maintainers, tags, and version metadata.

## Component version ownership

The package repository records `pac_release_version` for traceability, but component versions are owned by each component source. A PAC controller release must not automatically bump unchanged binary, container, script, or docs component versions. See `docs/github-release-binary-version-policy-20260529.md`.
