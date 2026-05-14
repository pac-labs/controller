# PAC - Pi Agent Control

PAC is a lightweight agent control system with a Python control server, endpoint services, model/tool configuration, pi.dev container execution, artifacts, self-update support and a dark purple Web UI.

State and configuration live in `~/.pacp` by default, so the app can be launched from any directory without creating a second/confused instance.

## Install

```bash
./install.sh
```

Open the UI at the configured host/port, normally `https://admin.pac.local` or `https://localhost`.

## Version history

See `PAC_CHANGELOG.json` for release history. Version 1.0.57 separates endpoints as remote execution environments from pi.dev workloads. Endpoints can expose local binaries, Node.js-gated pi.dev enablement, default workspaces, and controller-queued command execution.

---

# PAC - Pi Agent Control - Stage 16

Stage 16 renames the visible product to **PAC - Pi Agent Control** and adds a persistent right-side Events rail for a more dashboard-like control room experience. Runtime/config state still lives under `~/.pacp` by default.

Stage 11 adds a real `pi_container` execution mode. The Python runner can now start a disposable container that contains Node and pi.dev, stream logs back to the PAC, and upload artifacts from the workspace.

## Stage 12: PAC home and dashboard tabs

PACP now uses a persistent home directory by default:

```text
~/.pacp/
  config/config.yaml
  state.db
  workspaces/
  sessions/
  artifacts/
  logs/
  cache/
  run/server.lock
  app/
```

This means you can start the server from a different directory and it will still use the same configuration, database, workspaces and artifacts. Override the location with:

```bash
PACP_HOME=/data/pacp ./install.sh
```

The PAC also uses a lock file at `~/.pacp/run/server.lock` so two servers do not accidentally run against the same state directory.

The web UI now has top-level tabs for Dashboard, Sessions, Runners, Models, Approvals and Settings.


## Python / uv installer note

The project requires Python 3.11+. The install scripts now use `uv` by default and will bootstrap a Python 3.11 virtual environment even on hosts where `/usr/bin/python3` is older, such as Python 3.9 on RHEL-like systems.

PAC:

```bash
./install.sh
```

Runner:

```bash
sudo CONTROL_PLANE=https://agent.example.nl PI_AGENT_TOKEN=change-me ./scripts/install-runner.sh
```

To disable uv and use an existing Python 3.11 manually:

```bash
PI_AGENT_USE_UV=0 PYTHON_BIN=python3.11 ./install.sh
```

## Build the pi.dev image

```bash
scripts/build-pi-container.sh localhost/pi-agent-harness:stage11
```

If the upstream pi.dev npm package name differs, override it:

```bash
podman build --build-arg PI_NPM_PACKAGE=<actual-package> -t localhost/pi-agent-harness:stage11 containers/pi-agent-harness
```

## Install a runner with Pi container support

```bash
sudo CONTROL_PLANE=https://agent.example.nl \
  PI_AGENT_TOKEN=change-me \
  PI_CONTAINER_IMAGE=localhost/pi-agent-harness:stage11 \
  scripts/install-runner.sh
```

In the Web UI, select a runner and choose execution mode **pi container**.

---

# PAC - Pi Agent Control — Stage 7

A small remote agent PAC for running Codex/OpenClaw-like sessions from a web UI, IDE clients, MCP bridges or HTTP automation.

Stage 7 focuses on **real mixed execution**: local PAC commands, remote host runners, and remote container execution through Podman/Docker.

## What this is

```text
Zed / VS Code / Web UI / CLI / OpenClaw
        |
        v
Pi Agent Control
        |
        ├─ providers: OpenAI, LM Studio, Ollama, vLLM, OpenAI-compatible
        ├─ models: context window, output budget, capabilities, where it runs
        ├─ context profiles: low / medium / high / max token budgets
        ├─ permission profiles: read-only / ask-first / full-dev
        ├─ sessions and workspaces
        ├─ approvals and audit events
        └─ worker command execution
```

The Pi does **not** need to run the model. It can simply route requests to LM Studio on your desktop, Ollama on another machine, vLLM on a GPU host, or a hosted API.

## Quick install on Linux

```bash
unzip pi-agent-platform-stage7.zip
cd pi-agent-platform-stage7
./install.sh
```

Then open:

```text
https://localhost
```

Override defaults:

```bash
PI_AGENT_DIR=/opt/pi-agent-platform PI_AGENT_PORT=443 ./install.sh
```

The installer creates a Python venv, installs the app, copies `config/example.config.yaml` to `config/config.yaml`, writes `run.sh`, and tries to enable a user-level systemd service.

## Manual dev run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp config/example.config.yaml config/config.yaml
uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port 443
```

## Configure your own models

Edit `config/config.yaml`:

```yaml
providers:
  lmstudio-desktop:
    type: lmstudio
    base_url: http://192.168.1.50:1234/v1

models:
  my-local-coder:
    provider: lmstudio-desktop
    model: qwen2.5-coder-32b-instruct
    runs_on: desktop-lmstudio
    context_window: 32768
    max_output_tokens: 8192
    capabilities:
      supports_chat: true
      supports_tools: false
      supports_json: true
      supports_streaming: true
```

For Ollama:

```yaml
providers:
  ollama-box:
    type: ollama
    base_url: http://192.168.1.60:11434

models:
  ollama-qwen:
    provider: ollama-box
    model: qwen2.5-coder:7b
    runs_on: ollama-box
    context_window: 16384
    max_output_tokens: 4096
```

## Context windows

Set the actual model server context in LM Studio/Ollama/vLLM, then declare the safe value here. The PAC uses the declared value to decide how much history and file context to send.

Effective context is calculated as:

```text
effective_context = min(model.context_window, selected_context_profile.budget_tokens)
```

Check it with:

```bash
curl https://localhost/v1/models/lmstudio-qwen-coder/effective-context?context_profile=medium
```

## Useful API endpoints

```text
GET  /v1/config
GET  /v1/providers
POST /v1/providers/{name}/test
GET  /v1/models/{name}/card
POST /v1/models/{name}/test
GET  /v1/models/{name}/effective-context?context_profile=medium
GET  /v1/sessions
POST /v1/sessions
POST /v1/sessions/{id}/tasks
GET  /v1/sessions/{id}/events
GET  /v1/tasks/pending-approvals
```

## Traefik

The `deploy/traefik` compose example is retained from Stage 3/4. For public exposure, put the Web UI and API behind Traefik with TLS and enable bearer auth or an external auth proxy.

## Standalone binary workflow

A GitHub Actions workflow is included at:

```text
.github/workflows/build-standalone.yml
```

It builds a single Linux binary with PyInstaller and packages it with config/deploy examples.

## Current limitation

The LLM planning loop is still an integration point. The platform manages providers, models, sessions, commands, permissions, approvals, remote runners, host execution and container execution. The next major feature should wire a real agent loop that calls the selected model and tools automatically.

## Stage 6: mixed execution and remote agent hosts

Stage 6 adds the foundation for using both container workers and direct host runners.

New concepts:

- **Runner / remote agent host**: a Linux machine that registers with the PAC.
- **Host execution mode**: run directly on the runner host, similar to a GitHub/Forgejo runner.
- **Container execution mode**: run inside Podman/Docker when available.
- **Mixed mode**: the runner reports what it can do, and the PAC can schedule accordingly.
- **Capability discovery**: the runner reports installed tools, GPU availability, and container runtimes.
- **Container inventory**: the runner reports currently running Podman/Docker containers back to the Web UI.

### Running the host runner

From a Linux host that should become an agent worker:

```bash
python -m pi_agent_platform.runner \
  --PAC https://agent.example.nl \
  --token "$PI_AGENT_TOKEN" \
  --name gpu-workstation-01 \
  --labels linux,gpu,nvidia,host-runner
```

For local development:

```bash
python -m pi_agent_platform.runner \
  --PAC https://127.0.0.1 \
  --name local-runner \
  --labels linux,local,host-runner
```

The runner sends heartbeats containing:

- hostname
- installed tools such as git, python3, node, podman, docker, kubectl, oc, helm, talosctl
- GPU status via `nvidia-smi` when available
- available container runtime(s)
- currently running containers

### Web UI

The Web UI now has a **Remote agent hosts / runners** section where you can:

- add a runner placeholder from the browser
- see registered runners
- see labels/capabilities
- see reported containers
- run local discovery on the PAC host

### API additions

```text
GET    /v1/runners
POST   /v1/runners
POST   /v1/runners/register
POST   /v1/runners/heartbeat
GET    /v1/runners/local/discover
GET    /v1/runners/{runner_id}
DELETE /v1/runners/{runner_id}
POST   /v1/runners/{runner_id}/jobs
```

`POST /v1/runners/{runner_id}/jobs` defines the scheduling contract. The runner pull/execution loop is intentionally kept as the next implementation step so the security model can be tightened before arbitrary remote command execution is enabled.

### Example runner job contract

```json
{
  "prompt": "Run tests on this host",
  "command": "pytest -q",
  "execution_mode": "host",
  "workspace_path": "/var/lib/pi-agent-runner/workspaces/example"
}
```

Container execution contract:

```json
{
  "prompt": "Run the repo checks inside a container",
  "command": "npm test",
  "execution_mode": "container",
  "container_image": "node:22-bookworm"
}
```


## Stage 7: execution options are implemented

You now have three practical execution paths:

```text
1. Control-plane/local execution
   Web/API task -> command runs on the Pi/PAC host workspace

2. Remote host runner execution
   Web/API task -> queued to registered runner -> command runs directly on that Linux host

3. Remote container execution
   Web/API task -> queued to registered runner -> runner starts Podman/Docker container -> command runs in /workspace
```

### Start a runner

```bash
python -m pi_agent_platform.runner \
  --PAC https://127.0.0.1 \
  --name local-runner \
  --labels linux,local,host-runner \
  --interval 5
```

With auth:

```bash
PI_AGENT_TOKEN=change-me python -m pi_agent_platform.runner \
  --PAC https://agent.example.nl \
  --token "$PI_AGENT_TOKEN" \
  --name gpu-workstation-01 \
  --labels linux,gpu,nvidia,host-runner
```

### Queue host execution

From Web UI: select a session, select a runner, choose `host`, enter a command, then run.

API example:

```bash
curl -X POST https://localhost/v1/runners/RUNNER_ID/jobs \
  -H 'content-type: application/json' \
  -d '{"prompt":"list workspace","command":"pwd && ls -la","execution_mode":"host"}'
```

### Queue container execution

```bash
curl -X POST https://localhost/v1/runners/RUNNER_ID/jobs \
  -H 'content-type: application/json' \
  -d '{"prompt":"run in python","command":"python --version && pwd","execution_mode":"container","container_image":"python:3.12-alpine"}'
```

The runner automatically reports installed tools, GPU visibility and running Podman/Docker containers back to the Web UI.

### Model selection vs execution location

Model location and execution location are separate:

```text
Selected model -> can run on OpenAI, LM Studio, Ollama, vLLM, etc.
Selected execution target -> can run on Pi, direct remote host, or a container on a remote host.
```

For example, a runner on your desktop can execute commands locally while the selected model points to `http://localhost:1234/v1` from that machine only after a later model-call runner proxy is added. Today, model calls are still made from the PAC, so LM Studio URLs should be reachable from the Pi/PAC.

## Stage 8: Agent loop

Stage 8 adds the first real agent loop. If you create a task with only a prompt and leave `command` empty, the PAC calls the selected model and lets it choose from workspace tools using JSON tool calls.

### Agent loop tools

- `list_files`
- `read_file`
- `write_file`
- `shell`
- `git_status`
- `git_diff`

The loop expects the model to return one JSON object at a time, for example:

```json
{"type":"tool_call","tool":"git_status","input":{}}
```

or:

```json
{"type":"final","message":"Done."}
```

### Full control

The `full-control` permission profile is included. It allows shell and file writes without approval prompts. Every tool call still appears in the event timeline.

Use it only for safe/disposable workspaces or trusted runners.

### Web UI style

The UI has moved toward the requested darker graphite/purple style with sharper corners. The next UX pass should turn this into a proper guided session wizard and better event timeline.

## Stage 9: small-context agent support

Stage 9 adds mechanisms to make small models useful, including 4k/8k context windows:

- rolling context compaction when the prompt history approaches the input budget
- estimated token budgeting per model/context profile
- `tiny-4k` context profile
- chunked file reads via `read_file_chunk`
- workspace overview via `workspace_manifest`
- batched map/reduce-style analysis via `batch_analyze_text` and `batch_analyze_file`
- task metadata fields for `rolling_context_summary` and context token estimates
- timeline events named `context_compacted` and `batch_result`

The effective context is still bounded by the real model server. A profile can tell the PAC to behave as if a model has 4096 tokens, but LM Studio/Ollama/vLLM must also be configured to actually serve that context window.

Example tiny profile:

```yaml
context_profiles:
  tiny-4k:
    budget_tokens: 4096
    reserve_output_tokens: 768
    history_tokens: 1400
    file_context_tokens: 1200
    summarization: rolling
    batch_chunk_tokens: 700
```

For small-context work, use an agent prompt like:

```text
Inspect this repository using workspace_manifest first. Use read_file_chunk and batch_analyze_file for large files. Keep a compact rolling summary and produce a final patch plan.
```

The agent loop now tries to compact automatically, but the new tools also let the agent intentionally process a large file in batches without stuffing the whole file into a single model call.

---

# Stage 10: internet tools and artifacts

Stage 10 adds text-first web access and artifact exchange between the PAC and runners.

## Agent web tools

The agent can now call:

```json
{"type":"tool_call","tool":"web_search","input":{"query":"OpenShift route TLS self signed ingress", "max_results":5}}
```

and:

```json
{"type":"tool_call","tool":"web_fetch","input":{"url":"https://example.com", "max_chars":12000}}
```

`web_fetch` prefers `lynx`, `links2`, or `w3m` when installed. If none are available, it uses the built-in HTML cleaner and strips script/style/noise before returning text.

Install optional text browsers on RHEL/Fedora-like hosts:

```bash
dnf install -y lynx links
```

or Debian/Ubuntu:

```bash
apt-get update && apt-get install -y lynx links2 w3m
```

## Network permissions

Web tools use the permission profile's `network` rule:

```yaml
permission_profiles:
  ask-first:
    network: ask
  full-dev:
    network: allow
  full-control:
    network: allow
```

With `ask`, the loop pauses and asks for approval before web access. With `full-control`, it proceeds and logs everything.

## Artifacts

Agents can save files for download:

```json
{"type":"tool_call","tool":"save_artifact","input":{"name":"analysis/notes.txt","content":"..."}}
```

List artifacts:

```bash
curl https://localhost/v1/artifacts
```

Upload an artifact manually:

```bash
curl -X PUT --data-binary @result.tar.gz \
  https://localhost/v1/artifacts/sess_x/task_y/result.tar.gz
```

Download:

```bash
curl -o result.tar.gz \
  https://localhost/v1/artifacts/sess_x/task_y/result.tar.gz
```

## Runner artifact sync

A remote runner automatically uploads a tarball if the job workspace contains either:

```text
artifacts/
pi-agent-artifacts/
```

This lets host/container jobs generate files without requiring shared storage.

Example job command:

```bash
mkdir -p artifacts
make test | tee artifacts/test-output.txt
```

After the job finishes, the runner uploads the bundle to the PAC.

## Stage 13: PAC brand integration

- Added PAC logo assets under `pi_agent_platform/web/assets/`.
- Added favicon and PAC node icon.
- Integrated the PAC logo into the top header.
- Added a five-node PAC loader/status mark for active PAC states.
- Added PAC footer branding: `PAC Control • Orchestrate • Execute`.
- Kept the dark purple, sharper-corner theme from Stage 12.


## Stage 17 self-update uploads

PAC can now update itself from the Web UI. Go to **Settings → Self update / stage package**, upload a PAC stage zip, and apply it. PAC will validate the archive, back up `~/.pacp/app`, copy the new app files, reinstall the editable package into the existing virtualenv, and mark the server as restart-required. Use the **Restart PAC** button when running under systemd or another restart policy. Manual runs will exit and need to be started again.

- Feature update packs: docs/feature-update-packs.md
