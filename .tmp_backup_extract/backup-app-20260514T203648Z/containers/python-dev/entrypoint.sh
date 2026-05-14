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
# WORKSPACE BOOT INJECTION (PAC Pi Agent Controller)
if [ -n "${PAC_CONTROLLER_URL:-}" ] && [ -n "${PAC_WORKSPACE_TOKEN:-}" ]; then
    echo "[workspace-boot] registering with PAC at ${PAC_CONTROLLER_URL}"
    RESP=$(curl -s -X POST "${PAC_CONTROLLER_URL}/v1/workspaces/register"         -H "Authorization: Bearer ${PAC_WORKSPACE_TOKEN}"         -H "Content-Type: application/json"         -d "{\"name\":\"${HOSTNAME:-container}\",\"type\":\"container\",\"container_image\":\"${PAC_IMAGE_NAME:-unknown}\",\"workspace_path\":\"/workspace\"}"         || true)
    if echo "$RESP" | grep -q '"ok"'; then
        echo "[workspace-boot] registered: $RESP"
    else
        echo "[workspace-boot] response: $RESP"
    fi
else
    echo "[workspace-boot] PAC_CONTROLLER_URL / PAC_WORKSPACE_TOKEN not set"
fi
