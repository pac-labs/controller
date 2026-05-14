# PAC — Pi Agent Controller

> A lightweight agent control system. Manage sessions, route to local or remote models, execute tasks on endpoints, and monitor everything from a single Web UI.

**Current version:** 1.0.106 | **Stage:** 19

---

## What PAC does

```
You (Web UI / API / MCP)
        │
        ▼
PAC controller (Python/FastAPI)
        │
   ┌────┴────────────────────┐
   ▼                         ▼
local-PAC              Remote endpoints
· pi.dev runtime       · pac-endpoint binary
· pacctl control       · register via heartbeat
· container jobs       · host + container execution
```

- **Sessions** — chat sessions with configurable models, context budgets, and permission profiles
- **Model routing** — connect to LM Studio, Ollama, vLLM, OpenAI-compatible providers
- **Endpoints** — remote hosts running `pac-endpoint`. Execute host or container jobs.
- **pi.dev runtime** — Node.js-based agent. Runs in a `pi-agent-harness` container.
- **pacctl** — Go binary for persistent container control. Built for 5 platforms.
- **Artifacts** — upload/download job output files

---

## Quick start

```bash
# Install (creates Python venv, installs service, starts Web UI)
./install.sh

# Open the UI
https://localhost
```

Override the home directory or port:

```bash
PACP_HOME=/data/pacp ./install.sh
```

---

## Concepts

### Sessions

A session is a conversation with a selected model. Each session has:
- A **context profile** (budget for history, output, file context)
- A **permission profile** (network access, tool permissions)
- A **workspace** (local directory or endpoint workspace)
- An optional **agent loop** (pi.dev or direct model)

### Models and providers

```yaml
# config/config.yaml
providers:
  lmstudio-local:
    type: lmstudio
    base_url: http://192.168.1.50:1234/v1

models:
  my-coder:
    provider: lmstudio-local
    model: qwen2.5-coder-32b-instruct
    context_window: 32768
    max_output_tokens: 8192
```

PAC does not run the model — it routes requests to your model provider. LM Studio, Ollama, and vLLM must be reachable from the PAC host.

### Endpoints

An **endpoint** is a remote Linux host with `pac-endpoint` installed. Register it:

```bash
sudo CONTROL_PLANE=https://your-pac.example.nl \
  PI_AGENT_TOKEN=change-me \
  PI_CONTAINER_IMAGE=localhost/pi-agent-harness:stage11 \
  ./scripts/install-runner.sh
```

Endpoints appear in the Web UI under **Endpoints**. From there you can:
- See online/offline status and version
- Run **host** mode jobs (direct shell on the endpoint)
- Run **container** mode jobs (inside a `pi-agent-harness` container)
- Update endpoint packages remotely
- Enable/disable the embedded command runner

### pi.dev runtime

The controller can run a built-in pi.dev session (`main-pi-dev` profile). It uses:
- The `main-pi-dev` profile
- The configured default model
- The `agent-control` workspace pointing at the PAC app/source tree

Enable it in **Settings → Controller pi.dev → Enable**.

The pi.dev runtime runs inside a `pi-agent-harness` container. Build it:

```bash
podman build -t localhost/pi-agent-harness:stage11 \
  -f containers/pi-agent-harness/pacctl/Dockerfile.harness \
  .
```

Control running containers with `pacctl`:

```bash
pacctl status <container-ip>       # container PID, platform, paused flag
pacctl in <container-ip> <cmd>      # exec in container
pacctl pause <container-ip>          # pause container
pacctl resume <container-ip>         # resume paused container
```

### Execution modes

| Mode | Description |
|------|-------------|
| `direct_model` | No agent loop. Sends prompt directly to model, returns response. |
| `pi.dev` | Routes to pi.dev container via pacctl for agentic execution. |
| `host` | Runs command directly on the endpoint host. |
| `pi_container` | Runs command inside a pi-agent-harness container on the endpoint. |

---

## Architecture

```
~/.pacp/
  config/config.yaml       ← provider and model definitions
  state.db                 ← sessions, tasks, artifacts metadata
  workspaces/             ← per-session workspaces
  sessions/               ← session history and event logs
  artifacts/              ← uploaded/downloaded files
  logs/                    ← PAC server and job logs
  run/server.lock          ← prevents accidental double-server startups
  app/                    ← the PAC Python application
  sources/                 ← source library (scripts, containers, plugins, docs)
  binaries/                ← compiled binary downloads (served via API)
  updates/                 ← staged update archives
```

---

## Documentation

| Document | What it covers |
|----------|---------------|
| [CHANGELOG.md](./CHANGELOG.md) | Version history and changes |
| [docs/controller-pi-dev-bootstrap.md](./docs/controller-pi-dev-bootstrap.md) | Controller pi.dev bootstrap flow |
| [docs/controller-local-pi-dev-endpoint.md](./docs/controller-local-pi-dev-endpoint.md) | local-PAC endpoint and readiness checks |
| [docs/pi-dev-runtime-terminology.md](./docs/pi-dev-runtime-terminology.md) | pi/agent/harness → pi.dev terminology rule |
| [docs/main-pi-dev-profile-and-agent-control-workspace.md](./docs/main-pi-dev-profile-and-agent-control-workspace.md) | `main-pi-dev` profile and `agent-control` workspace |
| [docs/endpoint-embedded-runner.md](./docs/endpoint-embedded-runner.md) | `pac-endpoint` embedded runner feature pack |
| [docs/endpoint-tool-execution-bridge.md](./docs/endpoint-tool-execution-bridge.md) | Named tool execution via endpoint |
| [docs/purpose-built-binaries.md](./docs/purpose-built-binaries.md) | Compiling server URL into binaries |
| [sources/README.md](./sources/README.md) | Source library index |
| [sources/containers/pi-agent-harness/README.md](./sources/containers/pi-agent-harness/README.md) | pi-agent-harness container docs |
| [sources/binaries/pacctl/README.md](./sources/binaries/pacctl/README.md) | pacctl binary docs |

---

## API reference

```text
GET  /v1/config              ← current configuration
GET  /v1/providers           ← configured providers
POST /v1/providers/{name}/test
GET  /v1/models               ← configured models
GET  /v1/models/{name}/card
POST /v1/models/{name}/test
GET  /v1/sessions             ← active sessions
POST /v1/sessions             ← create session
POST /v1/sessions/{id}/tasks  ← queue a task
GET  /v1/sessions/{id}/events
GET  /v1/endpoints            ← registered endpoints
POST /v1/endpoints/register
POST /v1/endpoints/heartbeat
POST /v1/endpoints/{id}/jobs
GET  /v1/artifacts
GET  /v1/tasks/pending-approvals
POST /v1/admin/current-package ← build update package from control plane
```

---

## Source library

The `sources/` directory holds buildable source packages:

- `scripts/` — install scripts, build scripts, utility helpers
- `containers/pi-agent-harness/` — Node.js + pi.dev container image source
- `containers/mcp-builder/` — MCP bridge builder
- `binaries/pac-endpoint/` — endpoint binary source (Go)
- `binaries/pac-agent/` — agent worker binary source (Go)
- `binaries/zed-binary/` — Zed connector binary source (Go)
- `plugins/` — agent skills, scripts, documentation

Select a source folder in the **Source Library** UI and use **Build binary** to produce platform-specific downloads.
