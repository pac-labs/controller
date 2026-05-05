#!/usr/bin/env bash
set -euo pipefail
PREFIX=${PREFIX:-/opt/pi-agent-platform}
SERVICE_USER=${SERVICE_USER:-pi-agent}
CONTROL_PLANE=${CONTROL_PLANE:-https://127.0.0.1}
RUNNER_NAME=${RUNNER_NAME:-$(hostname)-runner}
RUNNER_LABELS=${RUNNER_LABELS:-linux,host-runner,pi-container}
TOKEN=${PI_AGENT_TOKEN:-}
PI_CONTAINER_IMAGE=${PI_CONTAINER_IMAGE:-localhost/pi-agent-harness:stage11}
BUILD_PI_CONTAINER=${BUILD_PI_CONTAINER:-auto}
PYTHON_VERSION=${PI_AGENT_PYTHON_VERSION:-3.11}

if [[ "${1:-}" == "--help" ]]; then
  cat <<HELP
Install the Python remote runner as a systemd service.

Environment variables:
  CONTROL_PLANE=https://agent.example.nl
  PI_AGENT_TOKEN=change-me
  RUNNER_NAME=$(hostname)-runner
  RUNNER_LABELS=linux,host-runner,pi-container
  PI_CONTAINER_IMAGE=localhost/pi-agent-harness:stage11
  BUILD_PI_CONTAINER=auto|1|0
  PI_AGENT_PYTHON_VERSION=3.11
HELP
  exit 0
fi

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1"; exit 1; }; }
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  if [ -x "$HOME/.local/bin/uv" ]; then
    echo "$HOME/.local/bin/uv"
    return 0
  fi
  if [ -x "/root/.local/bin/uv" ]; then
    echo "/root/.local/bin/uv"
    return 0
  fi

  echo "uv not found; installing uv with the standalone installer..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "Missing curl or wget. Install one first, for example: sudo dnf install -y curl" >&2
    exit 1
  fi

  export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  if [ -x "$HOME/.local/bin/uv" ]; then
    echo "$HOME/.local/bin/uv"
    return 0
  fi
  if [ -x "/root/.local/bin/uv" ]; then
    echo "/root/.local/bin/uv"
    return 0
  fi

  echo "uv installation completed, but uv was not found in PATH, ~/.local/bin, or /root/.local/bin" >&2
  exit 1
}

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$PREFIX" --shell /sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$PREFIX"
cp -a pi_agent_platform containers scripts pyproject.toml requirements.txt "$PREFIX/"
cd "$PREFIX"
UV_BIN="$(ensure_uv)"
"$UV_BIN" python install "$PYTHON_VERSION"
"$UV_BIN" venv --python "$PYTHON_VERSION" .venv
"$UV_BIN" pip install --upgrade pip wheel
"$UV_BIN" pip install -e .
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

if [[ "$BUILD_PI_CONTAINER" == "1" || "$BUILD_PI_CONTAINER" == "auto" ]]; then
  if command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
    echo "Building pi.dev container image: $PI_CONTAINER_IMAGE"
    (cd "$PREFIX" && CONTAINER_RUNTIME=${CONTAINER_RUNTIME:-podman} scripts/build-pi-container.sh "$PI_CONTAINER_IMAGE") || {
      if [[ "$BUILD_PI_CONTAINER" == "1" ]]; then exit 1; else echo "Pi container build failed/skipped; runner still installed."; fi
    }
  else
    echo "No podman/docker found; Pi container image build skipped."
  fi
fi

cat >/etc/systemd/system/pi-agent-runner.service <<EOF2
[Unit]
Description=Pi Agent Host/Container Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PREFIX
Environment=PYTHONPATH=$PREFIX
Environment=PYTHONUNBUFFERED=1
Environment=PI_AGENT_PI_CONTAINER_IMAGE=$PI_CONTAINER_IMAGE
ExecStart=$PREFIX/.venv/bin/python -m pi_agent_platform.runner --PAC $CONTROL_PLANE --name $RUNNER_NAME --labels $RUNNER_LABELS --pi-container-image $PI_CONTAINER_IMAGE ${TOKEN:+--token $TOKEN}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF2
systemctl daemon-reload
systemctl enable --now pi-agent-runner.service
systemctl status --no-pager pi-agent-runner.service || true
