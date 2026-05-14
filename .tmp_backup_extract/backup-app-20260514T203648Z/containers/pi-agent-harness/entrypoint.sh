#!/usr/bin/env bash
set -euo pipefail

mkdir -p /workspace/pi-agent-artifacts
cd /workspace

TASK="${PI_AGENT_TASK:-${*:-}}"
if [[ -z "${TASK}" ]]; then
  TASK="Inspect the workspace and summarize what you find."
fi

if [[ "${PI_AGENT_DAEMON:-}" == "1" || "${PI_AGENT_MODE:-}" == "daemon" ]]; then
  echo "[pi-agent-container] daemon mode active"
  echo "status=running" > pi-agent-artifacts/daemon-status.txt
  echo "started_at=$(date -Iseconds)" >> pi-agent-artifacts/daemon-status.txt
  trap 'echo "status=stopping" > pi-agent-artifacts/daemon-status.txt; exit 0' TERM INT
  while true; do
    echo "heartbeat=$(date -Iseconds)" > pi-agent-artifacts/daemon-heartbeat.txt
    sleep "${PI_AGENT_DAEMON_HEARTBEAT_SECONDS:-30}"
  done
fi

echo "[pi-agent-container] job=${PI_AGENT_RUNNER_JOB_ID:-unknown} mode=${PI_AGENT_EXECUTION_MODE:-pi_container}"
echo "[pi-agent-container] workspace=$(pwd)"
echo "[pi-agent-container] task=${TASK}"

# Prefer a real Pi binary if installed. The package/binary name may differ between pi.dev releases,
# so this entrypoint tries common names and then falls back to a deterministic shell summary.
if command -v pi >/dev/null 2>&1; then
  echo "[pi-agent-container] launching: pi"
  pi "${TASK}"
elif command -v pi-agent >/dev/null 2>&1; then
  echo "[pi-agent-container] launching: pi-agent"
  pi-agent "${TASK}"
elif command -v npx >/dev/null 2>&1; then
  echo "[pi-agent-container] Pi binary not found; trying npx pi-coding-agent"
  npx --yes pi-coding-agent "${TASK}" || {
    echo "[pi-agent-container] npx fallback failed; writing workspace summary artifact."
    find . -maxdepth 3 -type f | sed 's#^./##' | sort | tee pi-agent-artifacts/workspace-files.txt
  }
else
  echo "[pi-agent-container] no pi.dev binary available; writing workspace summary artifact."
  find . -maxdepth 3 -type f | sed 's#^./##' | sort | tee pi-agent-artifacts/workspace-files.txt
fi

# Always leave a small marker artifact for the PAC.
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=${PI_AGENT_EXECUTION_MODE:-pi_container}
task=${TASK}
workspace=/workspace
SUMMARY
