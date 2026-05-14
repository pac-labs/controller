#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test -f pyproject.toml
test -d pi_agent_platform
test -f install.sh
test -f containers/pi-agent-harness/Dockerfile
test -f containers/mcp-builder/Dockerfile
test -f mcp/pac-mcp-go/main.go
python3 -m compileall -q pi_agent_platform
bash -n install.sh
bash -n scripts/install-runner.sh
bash -n scripts/build-pi-container.sh
bash -n scripts/build-mcp-bridge.sh
echo "package validation ok"
