# Codebase Migration Plan

This document is the current refactor roadmap for bringing PAC toward smaller, purpose-focused modules.

## Goals

- keep most implementation files in the `150` to `350` line range
- keep each file or class focused on one responsibility
- reduce "god files" in API, UI, and orchestration layers
- make feature work land in feature modules instead of general entrypoints
- make testing and reasoning about changes cheaper

## Current Pressure Points

Measured on `2026-05-21` against package `1.0.266`:

- `pi_agent_platform/web/app.js`: `9303` lines
- `pi_agent_platform/api/main.py`: `7283` lines
- `pi_agent_platform/web/styles.css`: `5119` lines
- `pi_agent_platform/core/agent_loop.py`: `2179` lines
- `pi_agent_platform/core/source_library.py`: `984` lines

Use `scripts/check-codebase-pressure-points.py` to refresh these measurements when a new package is cut.

These are the primary migration targets. The detailed design-aligned split plan is maintained in `docs/pac-design-aligned-refactor-plan.md`.

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

## v1.0.268 API split checkpoint

The second refactor checkpoint extracts the first stable route modules from `api/main.py`:

- `/v1/version` moved to `api/routes/version.py`.
- `/v1/mcp/build`, `/v1/mcp/build/status`, and `/v1/mcp/download/{filename}` moved to `api/routes/mcp.py`.
- UI index/static registration moved to `api/routes/ui.py`.

This reduces `api/main.py` from 7,283 lines to 7,230 lines. The reduction is small by design: this pass establishes the route factory pattern before touching high-coupling domains. Future route extractions should follow the same dependency-injection style instead of importing the full controller module from route modules.



## v1.0.269 API split checkpoint

The third refactor checkpoint extracts the low-coupling system/status API routes from `api/main.py`:

- `/healthz`
- `/v1/metrics/summary`
- `/v1/config`
- `/v1/ide/config`
- `/v1/session-slash-commands`
- `/v1/setup/status`

These routes now live in `api/routes/system.py` and are registered through `create_system_router(...)`. The module keeps dependency direction clean by accepting controller readers and helper functions from `main.py`, rather than importing the controller module.

This reduces `api/main.py` from 7,230 lines to 7,149 lines. The next safe extraction area is update/archive handling or proxy-route management. Endpoint/runner extraction should wait until endpoint capabilities and tool discovery are formalized.


## v1.0.270 endpoint/runner route split checkpoint

The fourth refactor checkpoint extracts the endpoint and runner route family from `api/main.py` into `api/routes/endpoints.py`. This is a larger movement than the earlier route extractions and removes endpoint registration, heartbeat, queued command, maintenance, update, onboarding, and runner-job HTTP handlers from the main controller bootstrap file.

The extraction deliberately keeps the existing endpoint helper functions in `main.py` for now and passes them into the route factory. This keeps the change behavior-preserving while making the next boundary clearer: endpoint capability normalization, default workspace creation, local endpoint refresh, and endpoint install/maintenance commands should become a dedicated endpoint service in a later package.

Measured result:

| File | v1.0.269 | v1.0.270 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 7,149 lines | 6,574 lines | -575 |
| `pi_agent_platform/api/routes/endpoints.py` | n/a | 685 lines | new module |

Follow-up rules:

- New endpoint HTTP routes should be added to `api/routes/endpoints.py`, not `api/main.py`.
- Endpoint business logic should not grow inside the route module indefinitely; it should move into an endpoint service once the capability and workspace lifecycle models are introduced.
- Route modules should keep using dependency injection from the application bootstrap until services are stable enough to import directly.


## v1.0.271 provider/model/profile route split checkpoint

The fifth refactor checkpoint extracts the provider/model/profile surface from `api/main.py` into `api/routes/providers.py`. This moves the HTTP ownership for configured providers, discovered provider models, model cards/tests, LM Studio management actions, context profile lookup, tool/plugin catalog reads, artifact upload/download, and agent profile CRUD into a bounded route module.

The extraction keeps current behavior by passing the existing config object, store, provider helper functions, model helper functions, and artifact helper functions into `create_providers_router(...)`. This deliberately avoids changing the persistence model in the same patch as the route movement. A later service pass should introduce explicit provider/profile/artifact services so the route module does not become the next monolith.

Measured result:

| File | v1.0.270 | v1.0.271 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 6,574 lines | 6,131 lines | -443 |
| `pi_agent_platform/api/routes/providers.py` | n/a | 520 lines | new module |

Follow-up rules:

- New provider/model/profile HTTP routes should be added to `api/routes/providers.py`, not `api/main.py`.
- Provider/model/profile business rules should move into services before the route module grows much further.
- The next large extraction candidates are source library routes and session/task/event routes.


## Update 6 implementation checkpoint: update/archive route extraction (v1.0.272)

This checkpoint moves the PAC update, release archive, generated-diff, and current-package HTTP surface out of `pi_agent_platform/api/main.py` while preserving the current update implementation.

Extracted route module:

- `pi_agent_platform/api/routes/updates.py`

Routes now owned by the update route factory include:

- `/v1/updates/status`
- `/v1/updates/check`
- `/v1/updates/archives` and archive detail/download/restore endpoints
- `/v1/updates/release-notes`
- `/v1/updates/local-diffs`
- `/v1/updates/generate-local-diff`
- `/v1/updates/diff/{version}`
- `/v1/updates/apply`
- `/v1/admin/current-package`

The module keeps update behavior unchanged by receiving archive roots, package application, restart scheduling, changelog, and local-diff helpers from `main.py`. This keeps dependency direction clean while making the next step clearer: update preservation, package application, backup restore, and local diff generation should become an explicit update service instead of remaining bootstrap helpers.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.271 | v1.0.272 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 6,131 lines | 5,938 lines | -193 |
| `pi_agent_platform/api/routes/updates.py` | n/a | 247 lines | new bounded route module |

Cumulative API entrypoint movement from the v1.0.266 baseline is now 1,345 lines removed from `main.py`. The remaining high-value extraction candidates are source library routes, session/task/event routes, auth/user/group routes, proxy routes, TLS routes, and Let's Encrypt routes.

Next API split candidates:

1. Extract source library routes into `api/routes/sources.py`, with source build state still injected from `main.py`.
2. Extract session/task/event routes into `api/routes/sessions.py`.
3. Extract auth/user/group/access-request routes into `api/routes/auth.py`.
4. Extract proxy and server/TLS management routes into smaller administrative modules.


## v1.0.273 source/IDE storage route split checkpoint

The seventh refactor checkpoint extracts source-library and IDE storage routes from `api/main.py` into `api/routes/sources.py`. This moves source browsing/editing, source contexts, source variables, PAC RAM, secrets, feature-pack inspect/apply, source builds, source online update checks, source archives, and binary artifact routes into a bounded module.

The extraction keeps current behavior by passing the existing config accessor, config setter, auth helpers, resource access helpers, runner/admin auth checks, source build-state adapter, package-apply helper, restart scheduler, and event store into `create_sources_router(...)`. Source build state still lives in `main.py` for now because bootstrap and endpoint install flows share the same blocker, but the source route module now owns the HTTP shape for source/IDE storage operations.

Measured result:

| File | v1.0.272 | v1.0.273 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 5,938 lines | 5,250 lines | -688 |
| `pi_agent_platform/api/routes/sources.py` | n/a | 720 lines | new module |

Follow-up rules:

- New source-library, source-context, source-variable, PAC RAM, secret, feature-pack, and binary artifact HTTP routes should be added to `api/routes/sources.py`, not `api/main.py`.
- `api/routes/sources.py` is intentionally a transition route module, not the final service boundary. The underlying `core/source_library.py` file is still too large and should be split into smaller services next.
- The source build-state adapter should eventually move into a controller build/update coordination service so route modules no longer depend on mutable bootstrap state.

## v1.0.274 session route split checkpoint

PAC v1.0.274 moves the session/task/timeline/session-file HTTP surface into `pi_agent_platform/api/routes/sessions.py`. This keeps controller route ownership closer to the design ethos: `api/main.py` now wires dependencies and startup behavior, while the session route module owns session lifecycle, task creation/approval/stop, event streaming, session file browsing/editing, diffs, git status, and deletion endpoints.

Pressure point update: `pi_agent_platform/api/main.py` is now 4,554 lines, down from 5,250 in v1.0.273 and 7,283 in the v1.0.266 baseline.



## v1.0.275 auth/user route split checkpoint

PAC v1.0.275 moves authentication, user, group, access-request, and token HTTP routes into `pi_agent_platform/api/routes/auth.py`. This keeps identity and access-control route ownership out of the controller entrypoint while preserving the existing store-backed auth behavior.

The checkpoint also fixes the internal compatibility path introduced by the earlier session route split: workspace and agent-context helpers still need to materialize sessions. `api/routes/sessions.py` now publishes the registered session creation callable for internal reuse, and `api/main.py` calls that bridge instead of relying on an old in-file route function.

Measured result:

| File | v1.0.274 | v1.0.275 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 4,554 lines | 4,237 lines | -324 |
| `pi_agent_platform/api/routes/auth.py` | n/a | 336 lines | new module |

Follow-up rules:

- New auth, user, group, access request, and token routes should be added to `api/routes/auth.py`, not `api/main.py`.
- Identity/business rules are still store-backed and should later move into an explicit auth/access service.
- The session creation bridge is transitional; the next service extraction should introduce a session factory/service so route modules and workspace helpers do not depend on route-local callables.

## v1.0.276 workspace/context route split checkpoint

PAC v1.0.276 moves workspace-template, personal workspace, agent-context, shared-storage, and legacy workspace profile HTTP routes into `pi_agent_platform/api/routes/workspaces.py`.

This continues the design-aligned API split by putting workspace and context route ownership behind a dedicated route factory while leaving deeper lifecycle/session helper extraction for a later service-layer pass. The controller entrypoint still owns bootstrap, auth setup scaffolding, and shared helper wiring, but no longer directly declares these workspace/context endpoints.

| File | v1.0.275 | v1.0.276 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 4,237 | 3,923 | -314 |
| `pi_agent_platform/api/routes/workspaces.py` | 0 | 389 | +389 |

Routes moved in this checkpoint:

* `/v1/workspace-templates`
* `/v1/my-workspaces` and personal workspace session creation
* `/v1/agent-contexts` and agent-context session creation
* `/v1/shared-storages`
* `/v1/workspaces/{workspace_name}` legacy workspace profile save/delete routes

The next API split targets are server/proxy/TLS/Let's Encrypt operations, followed by the remaining package upload/restart flow.


## v1.0.277 server/proxy/runtime route split checkpoint

PAC v1.0.277 moves the remaining controller-edge HTTP handlers out of `pi_agent_platform/api/main.py` and into bounded route modules.

New route modules:

* `pi_agent_platform/api/routes/proxy.py` for proxy route CRUD, test, and reverse proxy forwarding.
* `pi_agent_platform/api/routes/server_config.py` for raw config update and endpoint controller connection settings.
* `pi_agent_platform/api/routes/package_upload.py` for PAC package upload/stage/apply routes.
* `pi_agent_platform/api/routes/service_runtime.py` for restart, service mode, TLS CA/certificate, and Let's Encrypt DNS-01 operations.

This keeps the PAC controller entrypoint closer to the design ethos: `api/main.py` is now mostly bootstrap, startup wiring, shared transitional helpers, and route factory registration. Runtime behavior remains dependency-injected from `main.py` so this is still a behavior-preserving route split rather than a deeper service-layer rewrite.

Measured result:

| File | v1.0.276 | v1.0.277 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 3,923 | 3,527 | -396 |
| `pi_agent_platform/api/routes/proxy.py` | 0 | 127 | +127 |
| `pi_agent_platform/api/routes/server_config.py` | 0 | 67 | +67 |
| `pi_agent_platform/api/routes/package_upload.py` | 0 | 110 | +110 |
| `pi_agent_platform/api/routes/service_runtime.py` | 0 | 192 | +192 |

Follow-up rules:

* New proxy routes belong in `api/routes/proxy.py`.
* New server connection/config mutation routes belong in `api/routes/server_config.py`.
* New package upload/apply route behavior belongs in `api/routes/package_upload.py`; deeper update/archive behavior remains in `api/routes/updates.py`.
* New restart/service/TLS/Let's Encrypt routes belong in `api/routes/service_runtime.py`.
* `api/main.py` should not receive new HTTP route decorators except startup/shutdown hooks or a deliberately documented bootstrap exception.

The next cleanup step should remove unused imports and then begin extracting the remaining shared helper groups from `main.py` into services: auth/access helpers, workspace/session factory helpers, TLS/service helpers, and package update helpers.

## v1.0.278 frontend app split checkpoint

PAC v1.0.278 starts reducing the largest remaining monolith, `pi_agent_platform/web/app.js`, by extracting behavior-preserving frontend helper files loaded before the existing application script.

New files:

* `pi_agent_platform/web/app/ui_helpers.js`
* `pi_agent_platform/web/app/provider_presets.js`
* `pi_agent_platform/web/app/session_commands.js`
* `pi_agent_platform/web/app/setup_wizard.js`

`index.html` now loads those files before `/ui/app.js`. This preserves the current no-bundler browser runtime while allowing future frontend work to move toward feature modules.

Measured result:

| File | v1.0.277 | v1.0.278 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 9,303 | 8,829 | -474 |

Next candidates:

1. Extract frontend API/auth helpers.
2. Extract general formatting/render helpers.
3. Extract session timeline helpers.
4. Extract source library UI helpers.
5. Split page-specific CSS after the JavaScript boundaries are clearer.

## v1.0.279 provider/model frontend split checkpoint

PAC v1.0.279 continues the frontend split by moving provider and model catalog helpers out of `pi_agent_platform/web/app.js` into `pi_agent_platform/web/app/providers.js`.

New frontend module:

* `pi_agent_platform/web/app/providers.js` for provider/model availability helpers, provider status rendering, provider health summaries, LM Studio provider actions, configured/live model rendering, model recommendation panels, and provider/model draft helpers.

This remains a behavior-preserving classic-script split. `index.html` now loads `providers.js` after `provider_presets.js` and before `/ui/app.js`, so the existing global function call sites continue to work while the main UI entrypoint shrinks.

Measured result:

| File | v1.0.278 | v1.0.279 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 8,829 | 8,172 | -657 |
| `pi_agent_platform/web/app/providers.js` | 0 | 660 | +660 |

Follow-up rules:

* New provider/model catalog UI behavior belongs in `web/app/providers.js`.
* New provider preset defaults still belong in `web/app/provider_presets.js`.
* `web/app.js` should keep shrinking toward orchestration, page activation, and temporary glue only.
* The next frontend split should target either auth/user UI, source-library UI, or session timeline/composer UI.


## v1.0.280 source-library frontend split checkpoint

PAC v1.0.280 continues the frontend split by moving source-library, IDE source coding, source context, source secret/variable, source build, binary artifact, feature-pack, and marketplace helper functions out of `pi_agent_platform/web/app.js` into `pi_agent_platform/web/app/sources.js`.

New frontend module:

* `pi_agent_platform/web/app/sources.js` for source tree rendering, source tab/file actions, source build panels, source context and secret/variable forms, PAC RAM helpers, source coding helpers, binary artifact downloads, feature-pack actions, and marketplace search/detail helpers that are coupled to source workflows.

This remains a behavior-preserving classic-script split. `index.html` loads `sources.js` before `/ui/app.js`, so existing global function call sites continue to work while the main UI entrypoint shrinks.

Measured result:

| File | v1.0.279 | v1.0.280 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 8,172 | 6,721 | -1,451 |
| `pi_agent_platform/web/app/sources.js` | 0 | 1,451 | +1,451 |

Follow-up rules:

* New source-library UI behavior belongs in `web/app/sources.js`.
* New source context, source secret, source variable, PAC RAM, feature-pack, binary artifact, and source build UI behavior belongs in `web/app/sources.js` until deeper page modules are introduced.
* `web/app.js` should keep shrinking toward orchestration, page activation, state bootstrap, and temporary glue only.
* The next frontend split should target session timeline/composer UI or auth/user UI.


## v1.0.281 session frontend split checkpoint

PAC v1.0.281 continues reducing the frontend monolith by moving session timeline, composer, approval, assistant reply, session wizard, and session workspace helper functions out of `pi_agent_platform/web/app.js` into `pi_agent_platform/web/app/sessions.js`.

New frontend module:

* `pi_agent_platform/web/app/sessions.js` for session timeline rendering, thinking/approval rows, session snapshots and polling, composer send/task creation helpers, assistant reply actions, prompt context insertion, session wizard helpers, container destination selection, and session git diff modal helpers.

This remains a behavior-preserving classic-script split. `index.html` loads `sessions.js` before `/ui/app.js`, keeping the current no-bundler runtime while making the main entrypoint substantially smaller.

Measured result:

| File | v1.0.280 | v1.0.281 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 6,721 | 4,951 | -1,770 |
| `pi_agent_platform/web/app/sessions.js` | 0 | 1,843 | +1,843 |

Follow-up rules:

* New session timeline, thinking, approval, composer, and session-file behavior belongs in `web/app/sessions.js` while the classic-script transition remains in place.
* `web/app.js` should now be treated as transitional glue for page activation, remaining admin/auth/workspace/endpoint UI, and bootstrapping.
* The next frontend split should target endpoint/workspace/auth/admin helpers or begin splitting `styles.css` once JavaScript ownership is stable.


## v1.0.282 endpoint/auth frontend split checkpoint

PAC v1.0.282 continues the frontend refactor by moving endpoint/dashboard/controller-runtime helpers and auth/user/group helpers out of `pi_agent_platform/web/app.js`.

New frontend modules:

* `pi_agent_platform/web/app/endpoints.js` for endpoint inventory rendering, runner health/dashboard metrics, endpoint modals, endpoint command modal behavior, service/TLS/controller harness panels, and endpoint connection settings.
* `pi_agent_platform/web/app/auth_admin.js` for login/auth state helpers, header user chip rendering, user/group/admin access rendering, token helpers, and personal auth data loading helpers.

This remains a behavior-preserving classic-script split. `index.html` loads these modules before `/ui/app.js`, preserving existing global function call sites while reducing the transitional entrypoint.

Measured result:

| File | v1.0.281 | v1.0.282 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 4,951 | 3,596 | -1,355 |
| `pi_agent_platform/web/app/endpoints.js` | 0 | 954 | +954 |
| `pi_agent_platform/web/app/auth_admin.js` | 0 | 409 | +409 |

Follow-up rules:

* New endpoint, runner, service/TLS, and controller harness UI behavior belongs in `web/app/endpoints.js` while the classic-script transition remains in place.
* New auth/user/group/token UI behavior belongs in `web/app/auth_admin.js`.
* `web/app.js` should now be mostly transitional glue: boot, events rail, settings navigation, workspace/profile leftovers, update helpers, and remaining form wiring.
* One more frontend split should target workspace/profile/admin update helpers before considering `app.js` stable enough to leave for a later ES module conversion.


## v1.0.283 final app.js classic-script cleanup checkpoint

PAC v1.0.283 finishes the current `web/app.js` slimming wave without changing the no-bundler browser model. The remaining large UI domains were extracted into feature-owned classic scripts and loaded before `/ui/app.js`.

New files:

* `pi_agent_platform/web/app/events.js`
* `pi_agent_platform/web/app/workspaces_contexts.js`
* `pi_agent_platform/web/app/profiles_config.js`
* `pi_agent_platform/web/app/admin_updates.js`
* `pi_agent_platform/web/app/marketplace.js`
* `pi_agent_platform/web/app/personal_settings.js`
* `pi_agent_platform/web/app/composer_status.js`

Measured result:

| File | v1.0.282 | v1.0.283 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 3,596 | 969 | -2,627 |

Ownership rules after this checkpoint:

* Global event rail/update confirmation helpers belong in `web/app/events.js`.
* Shared storage, workspace template, user workspace, IDE context, and agent context UI helpers belong in `web/app/workspaces_contexts.js`.
* Provider/model/profile/tool configuration form behavior belongs in `web/app/profiles_config.js` unless it is provider catalog rendering, which remains in `web/app/providers.js`.
* Proxy/update/archive/package/restart/MCP bridge admin helpers belong in `web/app/admin_updates.js`.
* Marketplace helpers belong in `web/app/marketplace.js`.
* Personal settings modal behavior belongs in `web/app/personal_settings.js`.
* Composer thinking status helpers belong in `web/app/composer_status.js`.

`web/app.js` is now small enough to leave as transitional boot/glue until the project is ready for either a deeper page-module split or an ES module/bundler migration.


## v1.0.284 CSS split checkpoint

PAC v1.0.284 starts the stylesheet cleanup by replacing the historical monolithic `pi_agent_platform/web/styles.css` with a small compatibility stylesheet that imports ordered CSS modules from `pi_agent_platform/web/styles/`.

This is intentionally behavior-preserving. The imported files are ordered by the original cascade ranges from the former stylesheet, so selector precedence remains stable while ownership becomes clearer. The split does not introduce a CSS preprocessor, bundler, or runtime theme rewrite.

New stylesheet modules:

* `pi_agent_platform/web/styles/foundation.css`
* `pi_agent_platform/web/styles/dashboard-system.css`
* `pi_agent_platform/web/styles/endpoints.css`
* `pi_agent_platform/web/styles/sources-builds.css`
* `pi_agent_platform/web/styles/sessions-layout.css`
* `pi_agent_platform/web/styles/sessions-composer.css`
* `pi_agent_platform/web/styles/control-plane.css`
* `pi_agent_platform/web/styles/source-workbench.css`
* `pi_agent_platform/web/styles/source-tree-icons.css`
* `pi_agent_platform/web/styles/providers-discovery.css`
* `pi_agent_platform/web/styles/admin-components.css`
* `pi_agent_platform/web/styles/header-theme.css`
* `pi_agent_platform/web/styles/dashboard-polish.css`
* `pi_agent_platform/web/styles/light-surfaces.css`
* `pi_agent_platform/web/styles/release-mobile.css`

Measured result:

| File | v1.0.283 | v1.0.284 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/styles.css` | 5,119 | 19 | -5,100 |

Largest new stylesheet module:

| File | Lines |
|---|---:|
| `pi_agent_platform/web/styles/sessions-composer.css` | 646 |
| `pi_agent_platform/web/styles/source-workbench.css` | 491 |
| `pi_agent_platform/web/styles/light-surfaces.css` | 465 |

Ownership rules after this checkpoint:

* Keep `pi_agent_platform/web/styles.css` as an ordered compatibility loader unless the UI moves to direct stylesheet links later.
* New CSS should be added to the module that owns the visible area, not back into the compatibility loader.
* Keep individual stylesheet modules below roughly 700 lines. If a module grows beyond that, split it before adding unrelated rules.
* Do not reorder the imports casually; their order currently preserves the original stylesheet cascade.
