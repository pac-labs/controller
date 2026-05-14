#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/pi-agent-artifacts /workspace/repos /workspace/index
cd /workspace
echo "[docs-search] workspace initialized at $(date)"
echo "Usage: clone <url> [branch] — clone a git repo into /workspace/repos"
echo "Usage: search <term> [path] — ripgrep search across repos"
echo "Usage: index <path>          — build ripgrep index for fast searches"
if [ -n "${PI_AGENT_TASK:-}" ]; then
    echo "[docs-search] task=${PI_AGENT_TASK}"
fi
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=docs-search
workspace=/workspace
SUMMARY
