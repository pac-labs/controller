#!/usr/bin/env bash
set -euo pipefail
RUNTIME="${CONTAINER_RUNTIME:-podman}"
IMAGE="${1:-localhost/pi-agent-harness:stage11}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v "$RUNTIME" >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1; then RUNTIME=docker; else echo "Install podman or docker first" >&2; exit 1; fi
fi
"$RUNTIME" build -t "$IMAGE" "$ROOT/containers/pi-agent-harness"
echo "Built $IMAGE with $RUNTIME"
