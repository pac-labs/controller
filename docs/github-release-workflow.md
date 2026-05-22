# PAC GitHub release workflow

PAC uses GitHub as the release authority. The local/webUI patch flow should only
submit source changes or a source diff; GitHub creates the release version, tag,
release assets, and package repository update.

## Supported release paths

### 1. Release the latest `main`

Use **PAC release current main** from GitHub Actions.

The workflow:

1. checks out `main`;
2. resolves the release version:
   - an explicit workflow input wins;
   - otherwise the latest `vX.Y.Z` tag is read and the patch number is bumped;
3. writes `VERSION` and `VERSION_CURRENT.md`;
4. runs `scripts/generate-pac-release.py`;
5. commits release metadata back to `main`;
6. creates the annotated `vX.Y.Z` tag;
7. publishes the GitHub Release assets;
8. syncs `pac-labs/packages`.

Generated assets:

- `pac-full.zip`
- `pac-patch.zip`
- `pac-packages-seed.zip`
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
