# PAC diff pull-request workflow

PAC supports a patch-based handoff flow for changes produced outside GitHub,
such as patches created by the PAC webUI or ChatGPT.

## Recommended flow

1. Download the latest PAC source `.diff`.
2. Run the local submit helper to place it in a PR as:

   ```text
   .pac/diffs/vX.Y.Z.diff
   ```

3. Open the PR to `main`.
4. The **PAC expand diff pull request** workflow validates and expands the diff
   into normal source changes on the PR branch.
5. Review the expanded source changes.
6. Approve the PR.
7. The approved-PR release workflow merges the PR and triggers the main release
   workflow.

## Why expansion happens before approval

The diff file is only an input artifact. Reviewers should approve normal source
changes, not a hidden patch blob. Expanding the diff into source changes makes
GitHub review, checks, and release notes easier to understand.

## Accepted diff formats

The validator accepts:

- git-style patches from `git diff`;
- `diff -ruN` patches with `pac_orig/` and `pac_work/` prefixes.

Binary patches and generated assets are rejected.

## Versioning

The filename version is used only as workflow input context. GitHub release tags
are authoritative. The release workflow resolves the actual next version from
the latest `vX.Y.Z` tag unless an operator explicitly supplies a version in the
manual release workflow.

## Release-owned files

Diff expansion strips release-owned metadata hunks by default:

- `VERSION`
- `VERSION_CURRENT.md`
- `MANIFEST.json`
- `PAC_CHANGELOG.json`
- `pyproject.toml`

These files are regenerated or updated by the release workflow so local patch
versions do not conflict with GitHub tags.
