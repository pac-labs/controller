# PAC GitHub release workflow

PAC uses GitHub as the release authority. The local/webUI patch flow should only
submit source changes or a source diff; GitHub creates the release version, tag,
release assets, and package repository update.

## Supported release paths

### 1. Release the latest `main`

**PAC release current main** runs automatically when `main` receives source changes. It can also be started manually from GitHub Actions. Release-owned metadata-only commits are ignored so the workflow does not loop after it writes `VERSION`, `PAC_CHANGELOG.json`, and related files.

The workflow:

1. checks out `main`;
2. resolves the release version:
   - an explicit workflow input wins;
   - otherwise the latest `vX.Y.Z` tag is read and the patch number is bumped;
3. writes `VERSION` and `VERSION_CURRENT.md`;
4. compiles the first-class Go release binaries with `scripts/compile-release-binaries.py`;
5. validates that the binary-first pipeline is intact with `scripts/validate-release-binary-pipeline.py`;
6. runs `scripts/generate-pac-release.py` against those compiled binaries;
7. commits release metadata back to `main`;
8. creates the annotated `vX.Y.Z` tag;
9. publishes the GitHub Release assets;
10. syncs `pac-labs/packages`.

Generated assets:

- `pac-full.zip`
- `pac-patch.zip`
- `pac-packages-seed.zip`
- `pac-binaries.zip`
- direct `pac-endpoint-*` binary assets
- direct `pacctl-*` binary assets
- `RELEASE_BINARIES.json`
- `PAC_RELEASE_MANIFEST.json`
- `PAC_UPDATE_DIFF.diff`

Artifact filenames are intentionally stable. The Git tag and manifest carry the
actual version.

### 2. Release an approved pull request

Use the normal pull-request review flow.

When a PR to `main` receives an approving review, **PAC release approved pull
request** checks that:

- the PR targets `main`;
- the PR is not a draft;
- GitHub reports the PR as approved;
- the PR is mergeable;
- no `.pac/diffs/` input file remains in the PR.

If the PR is ready, the workflow squash-merges it into `main` and dispatches
**PAC release current main**. Versioning, tag creation, release artifacts, and
package sync remain owned by the main release workflow.

This means regular source PRs do not need to edit `VERSION` manually.

### 3. Expand a supplied `.pac/diffs/vX.Y.Z.diff` pull request

Use this path for ChatGPT/PAC-generated patch handoffs.

A helper script or user places exactly one diff file under:

```text
.pac/diffs/vX.Y.Z.diff
```

When the PR is opened or updated, **PAC expand diff pull request**:

1. checks out trusted workflow tools from `main`;
2. checks out the PR branch;
3. validates the diff without executing PR code;
4. applies the diff to the PR branch;
5. strips release-owned metadata changes by default;
6. removes the `.pac/diffs/` input file;
7. commits the expanded source changes back to the PR branch.

After that, the PR is reviewed like a normal source PR. Once approved, the
approved-PR release workflow merges it and triggers the main release workflow.

## Release-owned metadata

The online release workflow owns these files:

- `VERSION`
- `VERSION_CURRENT.md`
- `PAC_CHANGELOG.json`
- `MANIFEST.json`
- `pyproject.toml`

Diff expansion strips these hunks by default so a ChatGPT-generated local
artifact version does not fight the GitHub-derived release version.

## Diff safety model

PAC diff expansion accepts source-only patches in either format:

- `git diff` style patches beginning with `diff --git`;
- unified `diff -ruN` patches generated from `pac_orig/` and `pac_work/` trees.

The validator rejects:

- binary patches;
- path traversal;
- absolute paths;
- `.env`-style secret files;
- changes to `.github/workflows/` through the auto-expansion path.

Workflow changes must be made as normal source changes or by a trusted operator,
not through a self-modifying PAC diff PR.

## Binary and component versions

Release binaries are compiled before release packaging. Binary versions come from each binary component, not from the PAC controller release version. See `docs/github-release-binary-version-policy-20260529.md`.


## Binary-first guarantee

Release packaging depends on `dist/release-binaries/RELEASE_BINARIES.json`. `scripts/generate-pac-release.py` exits before writing packages when that manifest is missing or empty. The GitHub workflow also runs `scripts/validate-release-binary-pipeline.py` before packaging to verify that binary compilation appears before release generation, that only `pac-endpoint` and `pacctl` are first-class release binaries, and that direct binary assets are uploaded.

The source/update zips remain source-only: they must not contain `release-binaries/` or compiled binaries. Installers and updates download `pac-endpoint-*` and `pacctl-*` from GitHub Release assets.
