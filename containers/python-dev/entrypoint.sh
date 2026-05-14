#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts
cd /workspace
echo "[python-dev] workspace initialized at $(date)"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[python-dev] task=${PI_AGENT_TASK}"
    python3 -c "${PI_AGENT_TASK}" || echo "[python-dev] task completed"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=python-dev
workspace=/workspace
SUMMARY
