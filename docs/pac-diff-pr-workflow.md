# PAC diff pull-request workflow

PAC supports a small patch-based handoff flow for changes produced outside GitHub.

## Repository flow

1. Create a branch from `main`.
2. Add exactly one git-style patch file under:

   ```text
   .pac/diffs/<short-name>.diff
   ```

3. Open a pull request to `main`.
4. Add the label:

   ```text
   pac-apply-diff
   ```

5. The `Apply PAC diff PR` workflow checks out `main`, reads only the supplied diff from the PR branch, validates it, applies it to `main`, runs lightweight validation, and pushes the result to `main`.

## Why this exists

This lets ChatGPT or another PAC assistant provide a normal `.diff` artifact after a build. The user can place that diff in a PR without manually applying every changed file.

## Safety model

The workflow uses `pull_request_target`, so it is intentionally conservative:

- the PR author must be an owner, member, or collaborator;
- the PR must carry the `pac-apply-diff` label unless run manually;
- exactly one `.diff` or `.patch` file may be supplied under `.pac/diffs/`;
- binary patches are rejected;
- path traversal is rejected;
- secret-like env files are rejected;
- the workflow cannot update itself through `.github/workflows/apply-diff-pr.yml`.

The workflow does not execute code from the PR branch. It only reads the diff file and applies it to a fresh checkout of `main`.

## Diff artifact naming

PAC release builds also generate:

```text
PAC_UPDATE_DIFF-<version>.diff
```

That file is suitable for placing under `.pac/diffs/` in a PR.
