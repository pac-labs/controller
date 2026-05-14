#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts
cd /workspace
echo "[go-dev] workspace initialized at $(date)"
echo "[go-dev] go version: $(go version)"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[go-dev] task=${PI_AGENT_TASK}"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=go-dev
workspace=/workspace
go_version=$(go version 2>/dev/null || echo 'not found')
SUMMARY
