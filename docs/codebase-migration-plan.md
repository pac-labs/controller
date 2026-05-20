# Codebase Migration Plan

This document is the current refactor roadmap for bringing PAC toward smaller, purpose-focused modules.

## Goals

- keep most implementation files in the `150` to `350` line range
- keep each file or class focused on one responsibility
- reduce "god files" in API, UI, and orchestration layers
- make feature work land in feature modules instead of general entrypoints
- make testing and reasoning about changes cheaper

## Current Pressure Points

Measured on `2026-05-20`:

- `pi_agent_platform/api/main.py`: `6558` lines
- `pi_agent_platform/web/app.js`: `7948` lines
- `pi_agent_platform/web/styles.css`: `4834` lines
- `pi_agent_platform/core/agent_loop.py`: `2113` lines
- `pi_agent_platform/core/source_library.py`: `984` lines
- `pi_agent_platform/web/index.html`: `968` lines

These are the primary migration targets.

## Migration Principles

1. Extract by cohesive responsibility, not by arbitrary line count alone.
2. Prefer thin orchestration modules at the top and heavier feature modules underneath.
3. Keep route definitions, service logic, persistence logic, and formatting/rendering logic separate.
4. Do not append new feature blocks to oversized files unless the same change also reduces structural debt.
5. Preserve behavior first; refactor shape second; improve naming and boundaries third.

## Target Structure

### API

Target direction:

- `pi_agent_platform/api/main.py`
  - app bootstrap only
  - shared dependency wiring
  - router registration
- `pi_agent_platform/api/routes/`
  - one router module per feature area

Suggested route modules:

- `auth.py`
- `sessions.py`
- `tasks.py`
- `models.py`
- `providers.py`
- `workspaces.py`
- `endpoints.py`
- `updates.py`
- `ide.py`
- `admin.py`
- `observe.py`

### Core Services

Target direction:

- `pi_agent_platform/core/`
  - domain services only
  - logic grouped by feature area

Suggested service modules:

- `marketplace.py`
- `controller_harness.py`
- `workspace_sessions.py`
- `coding_sessions.py`
- `provider_health.py`
- `metrics_store.py`
- `alerts.py`
- `session_history.py`
- `session_timeline.py`

### Web UI

Target direction:

- `pi_agent_platform/web/app/`
  - state, actions, rendering, and feature modules separated
- `pi_agent_platform/web/styles/`
  - tokens, layout, sessions, ide, admin, and light/dark overrides separated

Suggested JavaScript split:

- `boot.js`
- `state/store.js`
- `api/client.js`
- `sessions/timeline.js`
- `sessions/composer.js`
- `sessions/thoughts.js`
- `ide/workspaces.js`
- `ide/editor.js`
- `ide/coding-session.js`
- `models/marketplace.js`
- `admin/settings.js`
- `observe/events.js`
- `ui/nav.js`
- `ui/modals.js`

Suggested stylesheet split:

- `tokens.css`
- `layout.css`
- `nav.css`
- `sessions.css`
- `ide.css`
- `models.css`
- `admin.css`
- `observe.css`
- `themes-dark.css`
- `themes-light.css`

## Phased Plan

### Phase 1: Immediate Extractions

Goal: remove the easiest cohesive blocks from oversized files without changing architecture.

Completed or started:

- marketplace logic extracted from `api/main.py`

Next:

- extract `updates` API and service logic from `api/main.py`
- extract `IDE/workspace file` API endpoints from `api/main.py`
- extract `controller pi.dev` diagnostics and wrapper lifecycle logic from `api/main.py`
- extract session thought/composer logic from `web/app.js`
- extract reply actions and timeline rendering from `web/app.js`

### Phase 2: Router and UI Moduleization

Goal: convert entrypoint-heavy files into thin wiring layers.

Tasks:

- reduce `api/main.py` to bootstrap, dependency wiring, and router registration
- add `api/routes/` modules for all major feature areas
- split `web/app.js` into feature modules under `web/app/`
- keep global state access explicit instead of implicit shared mutation

### Phase 3: Domain Service Cleanup

Goal: make core behavior easier to test and reason about.

Tasks:

- split `core/agent_loop.py` into:
  - prompt/context assembly
  - tool-call parsing
  - execution loop
  - result normalization
  - controller-session specialization
- split `core/source_library.py` into:
  - tree/file access
  - archive/build features
  - feature-pack handling
  - binary artifact management
- isolate session history/timeline logic from runtime execution logic

### Phase 4: UI System Cleanup

Goal: remove monolithic script and stylesheet pressure.

Tasks:

- split `styles.css` by area and theme
- split `index.html` into clearer shell sections and smaller template fragments where practical
- reduce hidden cross-feature coupling in `app.js`
- make each major page render from a dedicated module

### Phase 5: Hardening and Enforcement

Goal: prevent regression into oversized mixed-responsibility files.

Tasks:

- add lightweight review guidance for new files and refactors
- keep new feature areas out of `main.py` and `app.js`
- add optional CI checks or review scripts for:
  - very large files
  - route count per module
  - unused dead modules after migrations

## Feature-by-Feature Extraction Order

Recommended order for future work:

1. `api/main.py`
   - updates
   - IDE/workspace file APIs
   - sessions/tasks
   - endpoints
2. `web/app.js`
   - sessions
   - IDE
   - models/marketplace
   - nav/admin
3. `core/agent_loop.py`
   - parsing
   - planning
   - execution
   - controller specialization
4. `core/source_library.py`
   - file tree
   - artifacts/builds
   - feature packs
5. `web/styles.css`
   - tokens/layout
   - feature areas
   - theme overlays

## Refactor Acceptance Criteria

A refactor is considered successful when:

- the extracted module has one clear responsibility
- the parent file becomes visibly simpler
- names become clearer, not more abstract
- behavior is preserved
- new code for that feature lands in the new module, not back in the old file

## Operational Rule

For all future changes:

- if a file is already oversized and a change touches one coherent subsystem inside it, extract that subsystem instead of extending the monolith
- if a function or UI component is hard to read because of length or branching, isolate it before adding more logic
- if a directory mixes unrelated concerns, split it into clearer feature-oriented subdirectories
