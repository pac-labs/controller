#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts
cd /workspace
echo "[node-dev] workspace initialized at $(date)"
echo "[node-dev] node version: $(node --version)"
echo "[node-dev] npm version: $(npm --version)"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[node-dev] task=${PI_AGENT_TASK}"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=node-dev
workspace=/workspace
node_version=$(node --version)
npm_version=$(npm --version)
SUMMARY
