# PAC Design-Aligned Refactor Plan

Version target: `1.0.267`

This document is the first conservative update for splitting the current PAC source into smaller modules that match the PAC design ethos. It is intentionally planning-first: it records the current pressure points, target ownership boundaries, split sequence, and guardrails before any runtime source movement starts.

## Current Source Snapshot

Measured against the attached `1.0.266` source package.

| Area | File | Current size | Role today | Refactor target |
|---|---:|---:|---|---|
| Web UI logic | `pi_agent_platform/web/app.js` | 9,303 lines | Most client state, API calls, rendering, page behavior, modal behavior, source browser behavior, and admin behavior | Thin boot/router plus feature modules under `pi_agent_platform/web/app/` |
| API/controller | `pi_agent_platform/api/main.py` | 7,283 lines | FastAPI bootstrap, route definitions, controller runtime, setup, TLS, updates, sessions, endpoints, providers, source APIs | Thin app bootstrap plus route modules and core services |
| Web styling | `pi_agent_platform/web/styles.css` | 5,119 lines | Tokens, layout, page components, themes, source editor styling, session styling, admin styling | Split stylesheet set under `pi_agent_platform/web/styles/` |
| Agent runtime | `pi_agent_platform/core/agent_loop.py` | 2,179 lines | Prompt/context assembly, model loop, tool parsing, tool execution, controller guidance, checkpointing | Agent package with explicit planner, parser, executor, tool router, and result normalizer modules |
| Source library | `pi_agent_platform/core/source_library.py` | 984 lines | Safe paths, tree browsing, file editing, archives, feature packs, builds, binaries, package update checks | Source library package with tree, files, archives, feature packs, builds, binaries, and update modules |

## PAC Design Ethos

PAC is a local-first distributed agent orchestration platform. The refactor must make the code follow that architecture instead of merely reducing line counts.

### Controller

The controller coordinates, persists state, registers routes, exposes visibility, and dispatches work. It should not own every domain implementation detail.

Target ownership:

- application bootstrap
- route registration
- configuration loading
- state persistence boundaries
- endpoint/session/workspace orchestration
- audit/event visibility

Avoid:

- direct heavy execution
- endpoint-local tool behavior embedded in controller routes
- feature logic appended to `api/main.py`

### Agents

Agents decide how to perform work. They interpret tasks, assemble context, call model providers, route tool calls, and iterate over results.

Target ownership:

- planning loop
- context assembly
- model provider request/response handling
- tool-call parsing
- tool routing decisions
- result normalization
- checkpoint and resume behavior

Avoid:

- treating endpoint-local tools as controller-local tools by default
- mixing source-library filesystem behavior into the agent loop
- placing provider discovery or endpoint discovery logic inside `agent_loop.py`

### Endpoints

Endpoints are execution environments. They expose local capabilities, host workspaces, and run commands through the endpoint wrapper/runner.

Target ownership:

- endpoint registration
- capability discovery
- local tool inventory
- local tool package inventory
- runner availability
- endpoint-side command execution
- endpoint health and status

Avoid:

- hardcoded endpoint tool lists as the final discovery model
- silently assuming controller-local execution
- confusing endpoint wrappers with model providers

### Workspaces

Workspaces are bounded execution contexts that can be persistent or ephemeral. They are selected and materialized for a session or task.

Target ownership:

- workspace identity
- lifecycle state
- persistence policy
- endpoint binding
- materialization path
- cleanup policy
- allowed source/context attachments

Avoid:

- treating workspace paths as unstructured strings passed through unrelated services
- hiding lifecycle behavior in session startup code

### Tools

Tools are binaries or executable capabilities installed locally on endpoints. They are versioned, discoverable by PAC, and can be grouped into packages.

Target ownership:

- endpoint-local tool metadata
- tool version and availability
- tool package membership
- execution mode and safety policy
- workspace requirements

Avoid:

- storing tool selection on profiles as the primary model
- assuming tools are globally available because the controller knows about them

### Plugins

Plugins extend agent capability. They are contextual logic, scripts, skills, or processors loaded by agents. They are not endpoint-local binaries.

Target ownership:

- agent-side capability extension
- documentation or workflow helpers
- contextual parsing/processing
- optional runtime behavior used by a profile or session

Avoid:

- using plugin terminology for endpoint binaries
- hiding endpoint tool execution inside plugin configuration

### Model Providers

Model providers are external systems that provide model access. PAC connects agents to providers; PAC does not host or manage the models themselves.

Target ownership:

- provider registration
- provider health
- model inventory as advertised by the provider
- model selection at agent/session/runtime context level

Avoid:

- configuring models as profile-owned tools
- implying that profiles are provider connections

### Profiles

Profiles define how an agent should behave. They should not be the primary owner of model/provider or endpoint tool configuration.

Target ownership:

- purpose
- description
- instruction preset/system guidance
- context policy and context size override
- permission profile
- runtime limits
- preferred execution style
- group access policy

Model/provider selection belongs to the agent/session/runtime context. Tool availability belongs to endpoint/workspace capability resolution. During migration, old profile fields can remain as deprecated compatibility fields, but the UI should stop presenting profiles as the place where models and tools are configured.

## Target Module Boundaries

### API Layer

`pi_agent_platform/api/main.py` should become a wiring layer only.

Proposed structure:

```text
pi_agent_platform/api/main.py
pi_agent_platform/api/dependencies.py
pi_agent_platform/api/routes/auth.py
pi_agent_platform/api/routes/users.py
pi_agent_platform/api/routes/workspaces.py
pi_agent_platform/api/routes/agent_contexts.py
pi_agent_platform/api/routes/shared_storage.py
pi_agent_platform/api/routes/providers.py
pi_agent_platform/api/routes/models.py
pi_agent_platform/api/routes/sessions.py
pi_agent_platform/api/routes/tasks.py
pi_agent_platform/api/routes/events.py
pi_agent_platform/api/routes/source_library.py
pi_agent_platform/api/routes/endpoints.py
pi_agent_platform/api/routes/updates.py
pi_agent_platform/api/routes/controller_runtime.py
pi_agent_platform/api/routes/service.py
pi_agent_platform/api/routes/tls.py
pi_agent_platform/api/routes/letsencrypt.py
pi_agent_platform/api/routes/proxy.py
```

Core behavior should move behind route modules:

```text
pi_agent_platform/core/controller_runtime.py
pi_agent_platform/core/endpoint_registry.py
pi_agent_platform/core/endpoint_jobs.py
pi_agent_platform/core/session_factory.py
pi_agent_platform/core/workspace_lifecycle.py
pi_agent_platform/core/update_service.py
pi_agent_platform/core/auth_service.py
```

Acceptance criteria:

- `api/main.py` imports routers and starts the app.
- No new feature route should be added directly to `api/main.py`.
- Route modules should delegate domain behavior to core services.
- Runtime behavior remains compatible while routes are moved.

### Agent Runtime Layer

Proposed structure:

```text
pi_agent_platform/core/agent/
  __init__.py
  loop.py
  context.py
  prompts.py
  parser.py
  tool_router.py
  tool_execution.py
  model_consult.py
  checkpointing.py
  controller_guidance.py
  result_normalizer.py
```

Acceptance criteria:

- `execute_tool` no longer carries controller-local, endpoint-local, source-library, and model behavior in one function.
- `run_agent_loop` becomes orchestration around smaller functions.
- Tool execution is routed through explicit execution modes.
- Endpoint execution is distinguishable from controller-local execution.

### Source Library Layer

Proposed structure:

```text
pi_agent_platform/core/source_library/
  __init__.py
  paths.py
  tree.py
  files.py
  archives.py
  feature_packs.py
  builds.py
  binaries.py
  updates.py
  inventory.py
```

Acceptance criteria:

- safe path and tree behavior is isolated from builds and archives
- feature pack apply/inspect logic is isolated
- binary artifact and package update logic is isolated
- existing API behavior remains compatible during extraction

### Web UI Layer

Proposed JavaScript structure:

```text
pi_agent_platform/web/app/
  boot.js
  state.js
  api.js
  router.js
  setup/wizard.js
  sessions/list.js
  sessions/timeline.js
  sessions/composer.js
  sessions/approvals.js
  sessions/thinking.js
  profiles/cards.js
  profiles/editor.js
  workspaces/list.js
  workspaces/editor.js
  endpoints/list.js
  endpoints/detail.js
  endpoints/tools.js
  providers/list.js
  providers/models.js
  providers/health.js
  sources/tree.js
  sources/editor.js
  sources/builds.js
  sources/downloads.js
  admin/settings.js
  admin/updates.js
  admin/events.js
  ui/modals.js
  ui/toasts.js
  ui/nav.js
```

Proposed CSS structure:

```text
pi_agent_platform/web/styles/
  tokens.css
  base.css
  layout.css
  nav.css
  cards.css
  forms.css
  modals.css
  sessions.css
  profiles.css
  workspaces.css
  endpoints.css
  providers.css
  sources.css
  admin.css
  themes-light.css
  themes-dark.css
```

Acceptance criteria:

- the first UI split should preserve the current browser loading model unless a dedicated module-loader change is planned
- feature rendering should move by page area, not by arbitrary function batches
- shared helpers should be explicit imports or explicit global namespaces during transition
- no new major page should be added directly to `app.js`

## Sequenced Implementation Plan

### Phase 0: Guardrails and Documentation

Status for `1.0.267`: this package.

Tasks:

- record current pressure points
- document design-aligned ownership boundaries
- add a script to measure pressure points on demand
- update the migration plan with current measurements
- append changelog

No runtime behavior should change in this phase.

### Phase 1: API Route Extraction

Expected effort: 4 to 7 working days.

Order:

1. extract updates routes and update service
2. extract source-library routes while keeping existing source-library core behavior
3. extract endpoint routes and endpoint jobs
4. extract sessions/tasks/events routes
5. extract provider/model routes
6. leave `api/main.py` as bootstrap and router registration only

### Phase 2: Profile Semantics Cleanup

Expected effort: 2 to 4 working days.

Tasks:

1. introduce explicit profile purpose/context/permission fields in the docs and UI
2. mark old profile `model`, `planner_model`, and `tools` fields as compatibility-only
3. move model selection UI to agent/session/runtime context
4. move tool selection UI toward endpoint/workspace capabilities
5. add group access policy shape for profile visibility/use

### Phase 3: Endpoint, Tool, and Workspace Capability Model

Expected effort: 1 to 2 working weeks.

Tasks:

1. add endpoint capability schema
2. add endpoint tool and tool package metadata
3. add workspace lifecycle state
4. add session execution plan that binds agent, provider/model, endpoint, workspace, and resolved tools
5. update endpoint binaries to report discovered capabilities instead of only hardcoded tool specs

### Phase 4: Agent Runtime Split

Expected effort: 5 to 8 working days.

Tasks:

1. split prompt/context assembly
2. split tool-call parsing
3. split model consulting
4. split tool routing and execution
5. split checkpointing/result normalization
6. preserve existing public function compatibility while callers migrate

### Phase 5: Source Library Split

Expected effort: 2 to 3 working days.

Tasks:

1. extract safe path helpers
2. extract tree browsing
3. extract read/write file operations
4. extract archive creation
5. extract feature pack inspect/apply
6. extract builds/binaries/update checks

### Phase 6: Web UI and CSS Split

Expected effort: 1 to 2 working weeks.

Tasks:

1. add explicit app shell, state, API, and router modules
2. move source library UI first because it is already a bounded page area
3. move sessions/timeline/composer next
4. move profiles/workspaces/endpoints/providers after their data ownership is cleaned up
5. split CSS by tokens, layout, components, page areas, and themes

### Phase 7: Enforcement

Expected effort: 1 to 2 working days.

Tasks:

1. run `scripts/check-codebase-pressure-points.py` in CI or release checks
2. reject new feature blocks added to existing pressure point files without an extraction plan
3. keep file size budgets visible in release notes
4. maintain this document as the active refactor map

## File Size Budgets

These are guidance budgets, not immediate hard blockers.

| Layer | Preferred max | Temporary migration max |
|---|---:|---:|
| API route module | 350 lines | 600 lines |
| Core service module | 350 lines | 700 lines |
| Web feature module | 350 lines | 700 lines |
| CSS page/component file | 350 lines | 700 lines |
| Agent runtime module | 350 lines | 700 lines |

Large files can exist temporarily during migration, but new work should move toward the target boundaries.

## Non-Goals for the First Implementation Package

The `1.0.267` package must not:

- move runtime behavior
- change API responses
- change the UI loading model
- change profile persistence shape
- alter endpoint execution
- change source-library file operations

The purpose is to create a shared map and guardrails before invasive source movement.

## Update 2 implementation checkpoint: API route extraction (v1.0.268)

This checkpoint begins the API split with low-risk, low-dependency routes before moving large domain routes out of `pi_agent_platform/api/main.py`. The goal is to prove the extraction pattern without changing endpoint behavior.

Extracted route modules:

- `pi_agent_platform/api/routes/version.py` owns `/v1/version`.
- `pi_agent_platform/api/routes/mcp.py` owns the Zed MCP bridge build, status, and download routes.
- `pi_agent_platform/api/routes/ui.py` owns `/ui`, `/ui/`, `/ui/index.html`, and the static UI mount registration.

The new route modules use factory functions that receive their dependencies from the controller application instead of importing the full `main.py` module. This keeps the direction compatible with the PAC design ethos: main registers capabilities, while route modules own their bounded HTTP surface.

This is intentionally not the final API layout. Larger domains such as sessions, endpoints, source library, providers, workspaces, auth, and updates still need extraction into route modules backed by service objects. The acceptance rule for follow-up API work is that `main.py` should keep shrinking and should not regain route-specific business logic after a route has been extracted.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.267 | v1.0.268 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 7,283 lines | 7,230 lines | -53 |
| `pi_agent_platform/api/routes/*.py` | marketplace only | marketplace + version + mcp + ui | split started |

Next API split candidates:

1. Extract `/v1/auth/*`, `/v1/users/*`, and group/access-request routes into `api/routes/auth.py` and `core/auth_service.py`.
2. Extract `/v1/workspaces/*`, `/v1/agent-contexts/*`, and shared storage routes into dedicated route modules.
3. Extract endpoint/runner routes only after the endpoint capability model is introduced, so the route split does not preserve the current runner/endpoint naming confusion.



## Update 3 implementation checkpoint: system/status route extraction (v1.0.269)

This checkpoint continues the API split with read-only controller status and configuration routes. These routes are useful early extraction candidates because they expose controller state without owning mutations or session execution side effects.

Extracted route module:

- `pi_agent_platform/api/routes/system.py`

Routes now owned by the system route factory:

- `/healthz`
- `/v1/metrics/summary`
- `/v1/config`
- `/v1/ide/config`
- `/v1/session-slash-commands`
- `/v1/setup/status`

The extraction keeps the same dependency-injection pattern introduced in v1.0.268. The route module receives controller state readers, auth dependencies, and helper functions from `main.py` rather than importing the controller application directly. This preserves behavior while making `main.py` more clearly responsible for application bootstrap and route registration.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.268 | v1.0.269 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 7,230 lines | 7,149 lines | -81 |
| `pi_agent_platform/api/routes/*.py` | version, mcp, ui, marketplace | version, mcp, ui, system, marketplace | split continued |

Next API split candidates:

1. Extract update/archive routes into an `api/routes/updates.py` module backed by an update service object.
2. Extract proxy route management separately from raw configuration updates.
3. Extract auth/user/group routes after the user/group store interactions are wrapped in a small auth service.

Avoid extracting endpoint/runner routes until the endpoint capability model is introduced, otherwise the route split will preserve current runner/endpoint naming and ownership confusion.


## Update 4 implementation checkpoint: endpoint/runner route extraction (v1.0.270)

This checkpoint moves the endpoint and runner HTTP surface out of `pi_agent_platform/api/main.py` while preserving the existing controller-owned endpoint runtime helpers.

Extracted route module:

- `pi_agent_platform/api/routes/endpoints.py`

Routes now owned by the endpoint route factory include:

- `/v1/runners` and `/v1/endpoints` list/create/update/delete aliases
- endpoint self-registration and heartbeat routes
- local endpoint discovery and onboarding kit generation
- endpoint command queueing
- endpoint Node.js and pi.dev harness install routes
- endpoint maintenance and update queueing
- runner job list/create/claim/log/update routes

The module intentionally receives helpers such as endpoint metadata normalization, default workspace selection, certificate issuing, source build status, and local harness installation from `main.py`. That keeps this package behavior-preserving and avoids pretending the deeper endpoint capability service already exists. The next endpoint refactor should move those helpers into a dedicated endpoint service once the capability, tool-package, and workspace lifecycle models are formalized.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.269 | v1.0.270 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 7,149 lines | 6,574 lines | -575 |
| `pi_agent_platform/api/routes/endpoints.py` | n/a | 685 lines | new bounded route module |

This is the first larger API reduction. `main.py` still owns too much controller behavior, but it is now closer to being an application bootstrap plus service wiring file.

Next API split candidates:

1. Extract update/archive/self-update routes into `api/routes/updates.py`.
2. Extract proxy route management into `api/routes/proxy.py`.
3. Extract auth/user/group/access-request routes into `api/routes/auth.py`.
4. Extract source library routes into `api/routes/sources.py` only after the source-library service split is planned.


## Update 5 implementation checkpoint: provider/model/profile route extraction (v1.0.271)

This checkpoint moves the provider, model, profile, tool catalog, and artifact HTTP surface out of `pi_agent_platform/api/main.py` while preserving the current configuration-backed behavior.

Extracted route module:

- `pi_agent_platform/api/routes/providers.py`

Routes now owned by the provider route factory include:

- `/v1/models` and model card/test/effective-context endpoints
- `/v1/providers` provider CRUD, model discovery, health, and LM Studio management endpoints
- `/v1/context-profiles`
- `/v1/tool-packages`, `/v1/plugins`, and `/v1/tools` read endpoints
- `/v1/artifacts` upload/download/list endpoints
- `/v1/profiles` and `/v1/agent-profiles` endpoints

The module receives provider/model/artifact helpers from `main.py` rather than importing the controller bootstrap. This keeps dependency direction clean and leaves behavior unchanged. The next design-aligned step is to move the provider/profile/artifact rules into services so the route module remains a thin HTTP boundary.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.270 | v1.0.271 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 6,574 lines | 6,131 lines | -443 |
| `pi_agent_platform/api/routes/providers.py` | n/a | 520 lines | new bounded route module |

Cumulative API entrypoint movement from the v1.0.266 baseline is now 1,152 lines removed from `main.py`. The file still owns sessions, source library, auth/user/group, updates, proxy, TLS, and Let's Encrypt routes, so it remains over the migration budget, but it is steadily moving toward bootstrap plus router wiring.

Next API split candidates:

1. Extract source library routes into `api/routes/sources.py`, ideally with a small build-state adapter.
2. Extract session/task/event routes into `api/routes/sessions.py`.
3. Extract auth/user/group/access-request routes into `api/routes/auth.py`.
4. Extract update/archive/self-update routes into `api/routes/updates.py`.


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


## Update 7 implementation checkpoint: source/IDE storage route extraction (v1.0.273)

This checkpoint moves the source-library, IDE context, source variable, PAC RAM, secret, and binary artifact HTTP surface out of `pi_agent_platform/api/main.py` while preserving the existing backing stores and access checks.

Extracted route module:

- `pi_agent_platform/api/routes/sources.py`

Routes now owned by the source route factory include:

- `/v1/sources` tree, content, entry create/rename/delete, archive, feature-pack inspect/apply, online update check, container build, binary build, and binary artifact endpoints
- `/v1/source-contexts` and `/v1/ide/contexts`
- `/v1/source-variables` and `/v1/ide/variables`
- `/v1/pac-ram` and `/v1/ide/pac-ram`
- `/v1/secrets` and `/v1/ide/secrets`

The module receives authentication helpers, resource access checks, source build state adapters, config accessors, package-apply restart helpers, and the event store from `main.py`. This keeps behavior unchanged while making the source/IDE boundary explicit. The next design-aligned step is to split `core/source_library.py` itself into path, tree, file, archive, feature-pack, build, binary artifact, and update services.

Measured pressure-point result after this checkpoint:

| Pressure point | v1.0.272 | v1.0.273 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/api/main.py` | 5,938 lines | 5,250 lines | -688 |
| `pi_agent_platform/api/routes/sources.py` | n/a | 720 lines | new bounded route module |

Cumulative API entrypoint movement from the v1.0.266 baseline is now 2,033 lines removed from `main.py`. The remaining high-value extraction candidates are session/task/event routes, auth/user/group/access-request routes, proxy routes, TLS routes, and Let's Encrypt routes.

Next API split candidates:

1. Extract session/task/event/workspace-file routes into `api/routes/sessions.py`.
2. Extract auth/user/group/access-request/token routes into `api/routes/auth.py`.
3. Extract proxy and server connection routes into `api/routes/proxy.py` or an admin connectivity module.
4. Extract TLS and Let's Encrypt routes into certificate/admin modules.

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

PAC v1.0.278 begins the frontend split by moving low-risk, reusable JavaScript groups out of the monolithic `pi_agent_platform/web/app.js` while preserving the current classic script loading model.

New frontend modules:

* `pi_agent_platform/web/app/ui_helpers.js` for shared HTML escaping helpers.
* `pi_agent_platform/web/app/provider_presets.js` for provider preset definitions and preset loading behavior.
* `pi_agent_platform/web/app/session_commands.js` for session slash-command parsing and help text.
* `pi_agent_platform/web/app/setup_wizard.js` for setup wizard rendering, step wiring, and save/complete behavior.

This deliberately does not introduce ES module bundling yet. `index.html` loads the helper files before `/ui/app.js`, keeping existing global function behavior and reducing the risk of breaking the current web UI.

Measured result:

| File | v1.0.277 | v1.0.278 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 9,303 | 8,829 | -474 |
| `pi_agent_platform/web/app/ui_helpers.js` | 0 | 3 | +3 |
| `pi_agent_platform/web/app/provider_presets.js` | 0 | 26 | +26 |
| `pi_agent_platform/web/app/session_commands.js` | 0 | 64 | +64 |
| `pi_agent_platform/web/app/setup_wizard.js` | 0 | 379 | +379 |

Follow-up rules:

* New setup wizard behavior belongs in `web/app/setup_wizard.js`.
* New slash-command parsing/help behavior belongs in `web/app/session_commands.js`.
* New provider preset behavior belongs in `web/app/provider_presets.js`.
* Keep `web/app.js` as the transitional orchestrator until page modules are extracted.
* The next frontend split should target pure formatting/state/API helpers or one bounded page area, not a full UI rewrite.

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


## v1.0.281 update: session frontend boundary

The session UI is now a named frontend boundary. `web/app/sessions.js` owns session timeline rendering, composer actions, approvals, assistant reply affordances, session polling, and session wizard helpers. This matches the PAC design direction that session orchestration should be explicit and separate from provider/source/endpoint UI concerns.

`web/app.js` should no longer receive new session-specific rendering or composer helpers except temporary glue needed during the remaining classic-script transition.


## v1.0.282 update: endpoint/auth frontend boundaries

The web UI now has explicit endpoint and auth/admin frontend boundaries. `web/app/endpoints.js` owns endpoint inventory, runner/dashboard health, controller harness, service/TLS, endpoint connection, and endpoint command modal helpers. `web/app/auth_admin.js` owns login state, current-user display, user/group/admin access helpers, and token helper rendering.

This keeps the no-bundler classic script model for compatibility, but the design ownership is now clearer: endpoint UI behavior should not be reintroduced into the transitional `web/app.js`, and auth/user/group behavior should remain separate from session/source/provider UI behavior.


## v1.0.283 update: final app.js classic-script cleanup

PAC v1.0.283 completes the current safe frontend split wave for `pi_agent_platform/web/app.js`. The entrypoint is now treated as transitional bootstrap/glue instead of a feature bucket. Remaining feature-specific UI behavior was moved into classic-script modules loaded before `/ui/app.js`, avoiding a bundler or ES module conversion in this patch.

New frontend modules:

* `pi_agent_platform/web/app/events.js` for global event rail rendering, event normalization, event tones, and update confirmation overlay helpers.
* `pi_agent_platform/web/app/workspaces_contexts.js` for shared storage, IDE contexts, agent contexts, workspace templates, and workspace/session bridge UI helpers.
* `pi_agent_platform/web/app/profiles_config.js` for provider/model/profile/tool configuration forms, model sync helpers, and runtime form helpers.
* `pi_agent_platform/web/app/admin_updates.js` for proxy routes, update archive/diff/release controls, package upload, restart, MCP bridge build status, and admin update panels.
* `pi_agent_platform/web/app/marketplace.js` for marketplace search/detail/download helpers and source online update status rendering.
* `pi_agent_platform/web/app/personal_settings.js` for the personal settings modal.
* `pi_agent_platform/web/app/composer_status.js` for composer thinking state/status helpers.

Measured result:

| File | v1.0.282 | v1.0.283 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/app.js` | 3,596 | 969 | -2,627 |

Follow-up rules:

* `web/app.js` should now remain limited to global state, API/theme/tab bootstrapping, loading orchestration, remaining event binding, and transition glue.
* New feature UI behavior should go into the existing feature module that owns that area, not back into `web/app.js`.
* The next frontend cleanup should target oversized feature modules, especially `sessions.js`, `sources.js`, `workspaces_contexts.js`, and `endpoints.js`, or start splitting `styles.css`.
* A future ES module conversion can happen after the classic-script boundary has stabilized and browser behavior has been tested.


## v1.0.284 update: stylesheet module boundary

PAC v1.0.284 splits the largest remaining frontend pressure point, `pi_agent_platform/web/styles.css`, into ordered stylesheet modules under `pi_agent_platform/web/styles/`. The old file now acts as a compatibility loader that imports the modules in the same cascade order as the former monolith.

This aligns the UI layer with the same ownership model used for the recent JavaScript split: session styles, source workbench styles, endpoint styles, provider/admin styles, dashboard polish, light-mode surfaces, and mobile/release overlay behavior now have named homes.

Measured result:

| File | v1.0.283 | v1.0.284 | Movement |
|---|---:|---:|---:|
| `pi_agent_platform/web/styles.css` | 5,119 | 19 | -5,100 |

New style boundary rules:

* `web/styles.css` should remain import-only while the compatibility loader exists.
* Feature/page styles should live under `web/styles/` and keep their module under the pressure-point budget.
* The import order is part of the compatibility contract and should only change with visual regression testing.
* Future CSS cleanup can move from cascade-range modules to more semantic modules after the UI has been visually tested.
