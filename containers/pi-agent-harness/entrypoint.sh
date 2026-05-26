#!/usr/bin/env bash
set -euo pipefail

mkdir -p /workspace/pi-agent-artifacts
PI_AGENT_LOG="/workspace/pi-agent-artifacts/pi-agent.log"
PACCTL_LOG="/workspace/pi-agent-artifacts/pacctl.log"
touch "$PI_AGENT_LOG" "$PACCTL_LOG"
exec > >(tee -a "$PI_AGENT_LOG") 2>&1

log() {
  echo "[pi-agent-container] $*"
}

cd /workspace

TASK="${PI_AGENT_TASK:-${*:-}}"
if [[ -z "${TASK}" ]]; then
  TASK="Inspect the workspace and summarize what you find."
fi

if [[ "${PI_AGENT_DAEMON:-}" == "1" || "${PI_AGENT_MODE:-}" == "daemon" ]]; then
  log "daemon mode active"
  if command -v pacctl >/dev/null 2>&1; then
    echo "pacctl present: $(command -v pacctl)" >> "$PACCTL_LOG"
  else
    echo "pacctl not installed in this image" >> "$PACCTL_LOG"
  fi
  echo "status=running" > pi-agent-artifacts/daemon-status.txt
  echo "started_at=$(date -Iseconds)" >> pi-agent-artifacts/daemon-status.txt
  trap 'echo "status=stopping" > pi-agent-artifacts/daemon-status.txt; exit 0' TERM INT
  while true; do
    echo "heartbeat=$(date -Iseconds)" > pi-agent-artifacts/daemon-heartbeat.txt
    sleep "${PI_AGENT_DAEMON_HEARTBEAT_SECONDS:-30}"
  done
fi

log "job=${PI_AGENT_RUNNER_JOB_ID:-unknown} mode=${PI_AGENT_EXECUTION_MODE:-pi_container}"
log "workspace=$(pwd)"
log "task=${TASK}"

# Prefer a real Pi binary if installed. The package/binary name may differ between pi.dev releases,
# so this entrypoint tries common names and then falls back to a deterministic shell summary.
# Blind npx fallback is disabled by default because the published npm package may not expose a CLI.
if command -v pi >/dev/null 2>&1; then
  log "launching: pi"
  pi "${TASK}"
elif command -v pi-agent >/dev/null 2>&1; then
  log "launching: pi-agent"
  pi-agent "${TASK}"
elif [[ "${PI_AGENT_ALLOW_NPX:-0}" == "1" ]] && command -v npx >/dev/null 2>&1; then
  log "Pi binary not found; trying explicit npx fallback"
  npx --yes pi-coding-agent "${TASK}" || {
    log "npx fallback failed; writing workspace summary artifact."
    find . -maxdepth 3 -type f | sed 's#^./##' | sort | tee pi-agent-artifacts/workspace-files.txt
  }
else
  log "no runnable pi.dev binary available; writing workspace summary artifact."
  find . -maxdepth 3 -type f | sed 's#^./##' | sort | tee pi-agent-artifacts/workspace-files.txt
fi

# Always leave a small marker artifact for the PAC.
cat > pi-agent-artifacts/job-summary.txt <<SUMMARY
job=${PI_AGENT_RUNNER_JOB_ID:-unknown}
mode=${PI_AGENT_EXECUTION_MODE:-pi_container}
task=${TASK}
workspace=/workspace
SUMMARY
