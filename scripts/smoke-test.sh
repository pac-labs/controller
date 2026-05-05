#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-https://localhost}"
AUTH_HEADER=()
if [[ -n "${PI_AGENT_TOKEN:-}" ]]; then AUTH_HEADER=(-H "Authorization: Bearer ${PI_AGENT_TOKEN}"); fi
curl -fsS "${AUTH_HEADER[@]}" "$BASE/healthz"; echo
curl -fsS "${AUTH_HEADER[@]}" "$BASE/v1/profiles" | python -m json.tool | head -40
SESSION=$(curl -fsS "${AUTH_HEADER[@]}" -H 'content-type: application/json' "$BASE/v1/sessions" -d '{"name":"smoke","agent_profile":"local-coder","workspace":{"type":"profile","profile":"scratch"}}' | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "session=$SESSION"
TASK=$(curl -fsS "${AUTH_HEADER[@]}" -H 'content-type: application/json' "$BASE/v1/sessions/$SESSION/tasks?wait=true" -d '{"prompt":"smoke","command":"pwd && echo ok"}' | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "task=$TASK"
curl -fsS "${AUTH_HEADER[@]}" "$BASE/v1/sessions/$SESSION/events/snapshot" | python -m json.tool | tail -40
