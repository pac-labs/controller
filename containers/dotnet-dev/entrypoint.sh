#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts
cd /workspace
echo "[dotnet-dev] workspace initialized at $(date)"
echo "[dotnet-dev] dotnet version: $(dotnet --version 2>/dev/null || echo 'not found')"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[dotnet-dev] task=${PI_AGENT_TASK}"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=dotnet-dev
workspace=/workspace
dotnet_version=$(dotnet --version 2>/dev/null || echo 'not found')
SUMMARY
