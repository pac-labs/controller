# PAC Engineering Rules

This file defines the default engineering rules for changes in this repository.

## Core Rule

When adapting or extending PAC, prefer structural cleanup over local patch growth.

Always adhere to these rules:

1. Aim for files that are roughly `150` to `350` lines long.
2. Each file or class should handle exactly one specific responsibility.
3. Group files into logically named, purpose-focused directories.
4. Use clear naming and isolate complex logic.
5. If a function, route block, service, or UI component grows into a large or convoluted block, extract that block into its own dedicated module.
6. When adding new code, check whether adjacent code in the same file should be split at the same time rather than extending an already oversized file.

## Preferred Adaptation Style

Prefer:

- extracting cohesive logic into a service, helper, router, or component module
- moving feature-specific code out of general entrypoint files
- keeping orchestration code thin and delegating heavy logic downward
- naming modules after one responsibility, not after vague buckets like `misc`, `helpers`, or `utils2`

Avoid:

- appending new feature blocks to already oversized files
- mixing API routes, domain logic, persistence logic, and formatting logic in one file
- leaving large UI files as one continuously growing script or stylesheet
- hiding feature logic inside generic catch-all modules

## Practical Exceptions

These are targets, not blind hard limits.

Acceptable exceptions:

- generated files
- manifest-like files
- tightly related schema/model files where splitting would reduce clarity
- short-term transitional files during an active refactor

Even in those cases, keep responsibilities explicit and avoid unnecessary growth.

## Refactor Expectation

When touching a large file, prefer one of these outcomes:

- extract one coherent subsystem
- reduce branching and nested logic in place
- create a thin facade and move heavy logic into a dedicated module

Do not wait for a "big rewrite" before improving structure. Clean up incrementally as features are touched.

## Planning Reference

Use [docs/codebase-migration-plan.md](docs/codebase-migration-plan.md) as the current migration roadmap for bringing the repository into this structure.

## Remote Development Preference

When PAC is running on a reachable host during development:

1. Prefer end-to-end verification against the real host, not only local syntax checks.
2. Use `ssh` and PAC HTTP APIs directly for runtime validation.
3. If `pacctl` is available locally, prefer it for PAC-native smoke tests and operational inspection instead of inventing ad hoc request flows.
4. When changing session, model, endpoint, provider, or workspace behavior, verify the live host path after the code change whenever feasible.
