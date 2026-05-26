#!/usr/bin/env bash
set -euo pipefail
RUNTIME="${CONTAINER_RUNTIME:-podman}"
IMAGE="${1:-localhost/pi-agent-harness:stage11}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_CONTAINER_VERSION="$(tr -d '\r\n' < "$ROOT/containers/pi-agent-harness/VERSION" 2>/dev/null || echo dev)"
if ! command -v "$RUNTIME" >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1; then RUNTIME=docker; else echo "Install podman or docker first" >&2; exit 1; fi
fi
"$RUNTIME" build \
  --build-arg "PI_CONTAINER_VERSION=$PI_CONTAINER_VERSION" \
  -t "$IMAGE" \
  -f "$ROOT/containers/pi-agent-harness/Dockerfile" \
  "$ROOT"
echo "Built $IMAGE with $RUNTIME"
