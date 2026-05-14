#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACP_HOME="${PACP_HOME:-$HOME/.pacp}"
OUT_DIR="${PACP_HOME}/mcp/bin"
STATUS_DIR="${PACP_HOME}/mcp"
STATUS_FILE="${STATUS_DIR}/build-status.json"
IMAGE="${PAC_MCP_BUILDER_IMAGE:-pac-mcp-builder:1.0.55}"
RUNTIME="${PAC_CONTAINER_RUNTIME:-}"
log(){ printf '[pac-mcp-build] %s\n' "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
json_status(){ mkdir -p "$STATUS_DIR"; python3 - "$STATUS_FILE" "$1" "$2" <<'PY'
import json, sys, datetime
path,status,msg=sys.argv[1:4]
data={"status":status,"message":msg,"updated_at":datetime.datetime.utcnow().isoformat()+"Z"}
open(path,'w').write(json.dumps(data, indent=2))
PY
}
if [ -z "$RUNTIME" ]; then
  if have podman; then RUNTIME=podman; elif have docker; then RUNTIME=docker; else json_status failed "No podman or docker found"; exit 1; fi
fi
mkdir -p "$OUT_DIR" "$STATUS_DIR"
json_status running "Building pac-mcp binaries with $RUNTIME"
log "building container image $IMAGE"
if ! "$RUNTIME" build --pull=missing -t "$IMAGE" -f "$SRC_DIR/containers/mcp-builder/Dockerfile" "$SRC_DIR" >"$STATUS_DIR/build.log" 2>&1; then
  tail_msg=$(tail -n 80 "$STATUS_DIR/build.log" 2>/dev/null || true)
  json_status failed "Container image build failed: $tail_msg"
  exit 1
fi
mount_arg="${OUT_DIR}:/out"
if [ "$RUNTIME" = "podman" ]; then mount_arg="${OUT_DIR}:/out:Z"; fi
log "running builder container"
if ! "$RUNTIME" run --rm -v "$mount_arg" "$IMAGE" >"$STATUS_DIR/run.log" 2>&1; then
  tail_msg=$(tail -n 80 "$STATUS_DIR/run.log" 2>/dev/null || true)
  json_status failed "Builder container failed: $tail_msg"
  exit 1
fi
json_status completed "MCP binaries built"
log "completed: $OUT_DIR"
