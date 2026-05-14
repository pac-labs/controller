#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts
cd /workspace
echo "[c-dev] workspace initialized at $(date)"
echo "[c-dev] GCC version: $(gcc --version 2>/dev/null | head -1 || echo 'not found')"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[c-dev] task=${PI_AGENT_TASK}"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=c-dev
workspace=/workspace
gcc_version=$(gcc --version 2>/dev/null | head -1 || echo 'not found')
SUMMARY
