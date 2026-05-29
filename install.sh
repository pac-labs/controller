#!/usr/bin/env bash
set -euo pipefail

if [ -z "${PACP_HOME:-}" ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER:-root}" != "root" ]; then
  PAC_USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
  PACP_HOME="${PAC_USER_HOME:-$HOME}/.pacp"
else
  PACP_HOME="${PACP_HOME:-$HOME/.pacp}"
fi
APP_DIR="${PACP_APP_DIR:-$PACP_HOME/app}"
PORT="${PAC_PORT:-443}"
PAC_HTTPS="${PAC_HTTPS:-1}"
SERVICE="${PAC_SERVICE:-pacp}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\033[1;35m[pac]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[pac]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[pac]\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; elif have sudo; then sudo "$@"; else fail "Need root privileges for: $*"; fi
}

port_is_privileged() { [ "${PORT:-0}" -gt 0 ] 2>/dev/null && [ "$PORT" -lt 1024 ]; }
service_user() { if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER:-root}" != "root" ]; then printf '%s' "$SUDO_USER"; else id -un; fi; }
service_group() { id -gn "$(service_user)" 2>/dev/null || id -gn; }

[ -f "$SRC_DIR/pyproject.toml" ] || fail "pyproject.toml missing. cd into the extracted package directory first."
[ -d "$SRC_DIR/pi_agent_platform" ] || fail "pi_agent_platform/ missing. Package is incomplete."

install_os_python_bits() {
  if have dnf; then
    log "Installing Python packaging support with dnf if needed"
    sudo_cmd dnf install -y python3 python3-pip python3-virtualenv || true
  elif have apt-get; then
    log "Installing Python packaging support with apt if needed"
    sudo_cmd apt-get update
    sudo_cmd apt-get install -y python3 python3-pip python3-venv
  fi
}

pick_python() {
  for p in "${PYTHON_BIN:-}" python3.12 python3.11 python3.10 python3.9 python3; do
    [ -n "$p" ] || continue
    if have "$p"; then
      if "$p" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
      then
        command -v "$p"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python || true)"
if [ -z "$PY" ]; then
  install_os_python_bits
  PY="$(pick_python || true)"
fi
[ -n "$PY" ] || fail "Python 3.9+ not found. Install python3 and rerun."

if ! "$PY" -m venv --help >/dev/null 2>&1; then
  install_os_python_bits
fi
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  install_os_python_bits
fi
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  warn "pip is still missing. Trying ensurepip."
  "$PY" -m ensurepip --upgrade || true
fi
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  fail "pip is unavailable for $PY. On RHEL try: sudo dnf install -y python3-pip python3-virtualenv"
fi

mkdir -p "$APP_DIR" "$PACP_HOME/config" "$PACP_HOME/workspaces" "$PACP_HOME/sessions" "$PACP_HOME/artifacts" "$PACP_HOME/logs" "$PACP_HOME/cache" "$PACP_HOME/run"
log "Installing from $SRC_DIR to $APP_DIR"
log "PAC home: $PACP_HOME"

# Copy only project-owned entries. Never copy the caller's working directory or entire home.
# When switching an already-installed app from user mode to host/system mode, SRC_DIR and
# APP_DIR can be the same directory. In that case a remove+copy cycle would delete the
# source before copying it, which made VERSION disappear and broke host-mode installs.
entries=(
  README.md VERSION VERSION_1.md VERSION_CURRENT.md requirements.txt pyproject.toml .gitignore
  pi_agent_platform config scripts deploy containers docs tests vscode-extension mcp
  docs-zed-mcp-example.json MANIFEST.json
)
SRC_REAL="$(realpath -m "$SRC_DIR")"
APP_REAL="$(realpath -m "$APP_DIR")"
if [ "$SRC_REAL" = "$APP_REAL" ]; then
  log "Source and target app directory are the same; refreshing install in place"
else
  for entry in "${entries[@]}"; do
    if [ -e "$SRC_DIR/$entry" ]; then
      rm -rf "$APP_DIR/$entry"
      cp -a "$SRC_DIR/$entry" "$APP_DIR/"
    fi
  done
fi
if [ ! -f "$APP_DIR/VERSION" ]; then
  if [ -f "$APP_DIR/VERSION_CURRENT.md" ]; then
    head -n 1 "$APP_DIR/VERSION_CURRENT.md" > "$APP_DIR/VERSION"
  else
    printf '%s
' '1.0.57' > "$APP_DIR/VERSION"
  fi
fi

cd "$APP_DIR"
log "Using Python: $($PY --version 2>&1)"

if [ ! -d .venv ]; then
  log "Creating virtualenv"
  "$PY" -m venv .venv
fi
. .venv/bin/activate

log "Installing dependencies"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -e .

mkdir -p "$PACP_HOME/config" "$PACP_HOME/workspaces" "$PACP_HOME/artifacts" "$PACP_HOME/logs" "$PACP_HOME/run"
if [ ! -f "$PACP_HOME/config/config.yaml" ]; then
  if [ -f "$APP_DIR/config/config.yaml" ]; then
    cp "$APP_DIR/config/config.yaml" "$PACP_HOME/config/config.yaml"
  else
    cp "$APP_DIR/config/example.config.yaml" "$PACP_HOME/config/config.yaml"
  fi
fi

generate_pac_ca_and_server_cert() {
  local tls_dir="$PACP_HOME/config/tls"
  local private_dir="$tls_dir/private"
  local ca_cert="$tls_dir/pac-root-ca.crt"
  local ca_key="$private_dir/pac-root-ca.key"
  local server_cert="$tls_dir/pac-server.crt"
  local server_key="$private_dir/pac-server.key"
  local csr="$private_dir/pac-server.csr"
  local ext="$private_dir/pac-server.ext"
  local details="$tls_dir/ca-details.yaml"
  mkdir -p "$private_dir"
  chmod 700 "$private_dir" || true
  if ! have openssl; then
    warn "openssl not found; PAC will fall back to HTTP on port $PORT"
    return 1
  fi
  if [ ! -f "$ca_cert" ] || [ ! -f "$ca_key" ]; then
    log "Generating PAC local root CA, valid for 30 years"
    openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days 10950 \
      -keyout "$ca_key" -out "$ca_cert" \
      -subj "/CN=PAC Local Root CA/O=PAC/C=NL" >/dev/null 2>&1 || return 1
    chmod 600 "$ca_key" || true
  fi
  if [ -f "$server_cert" ] && ! openssl x509 -noout -text -in "$server_cert" 2>/dev/null | grep -q 'DNS:admin.pac.local'; then
    rm -f "$server_cert" "$server_key" "$csr"
  fi
  if [ ! -f "$server_cert" ] || [ ! -f "$server_key" ]; then
    log "Generating PAC HTTPS certificate signed by the PAC CA"
    cat > "$ext" <<'EOFEXT'
subjectAltName=DNS:localhost,DNS:admin.pac.local,DNS:pac.local,IP:127.0.0.1,IP:::1
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
basicConstraints=CA:FALSE
EOFEXT
    openssl req -newkey rsa:2048 -nodes -keyout "$server_key" -out "$csr" \
      -subj "/CN=localhost/O=PAC/C=NL" >/dev/null 2>&1 || return 1
    openssl x509 -req -in "$csr" -CA "$ca_cert" -CAkey "$ca_key" -CAcreateserial \
      -out "$server_cert" -days 825 -sha256 -extfile "$ext" >/dev/null 2>&1 || return 1
    chmod 600 "$server_key" || true
  fi
  cat > "$details" <<EOFDETAILS
created_or_checked_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
ca_valid_days: 10950
server_valid_days: 825
ca_cert_file: $ca_cert
ca_key_file: $ca_key
server_cert_file: $server_cert
server_key_file: $server_key
public_url: https://admin.pac.local${PORT:+:$PORT}
trust_hint: import pac-root-ca.crt into clients that do not trust the local PAC CA yet
EOFDETAILS
  chmod 600 "$details" || true
  install_pac_ca_into_system "$ca_cert" || true
}

install_pac_ca_into_system() {
  local ca_cert="$1"
  [ -f "$ca_cert" ] || return 0
  if have update-ca-certificates && [ -d /usr/local/share/ca-certificates ]; then
    log "Installing PAC CA into system trust store"
    sudo_cmd cp "$ca_cert" /usr/local/share/ca-certificates/pac-root-ca.crt || return 0
    sudo_cmd update-ca-certificates || true
  elif have trust; then
    log "Installing PAC CA with p11-kit trust"
    sudo_cmd trust anchor "$ca_cert" || true
  elif have update-ca-trust && [ -d /etc/pki/ca-trust/source/anchors ]; then
    log "Installing PAC CA into RHEL trust store"
    sudo_cmd cp "$ca_cert" /etc/pki/ca-trust/source/anchors/pac-root-ca.crt || return 0
    sudo_cmd update-ca-trust extract || true
  else
    warn "No known system trust tool found. CA saved at $ca_cert"
  fi
}

if [ "$PAC_HTTPS" = "1" ]; then
  generate_pac_ca_and_server_cert || warn "Could not generate PAC CA/server cert; PAC will fall back to HTTP on port $PORT"
fi

cat > "$APP_DIR/run.sh" <<EOF2
#!/usr/bin/env bash
set -euo pipefail
cd "$APP_DIR"
. .venv/bin/activate
export PACP_HOME="$PACP_HOME"
CERT="$PACP_HOME/config/tls/pac-server.crt"
KEY="$PACP_HOME/config/tls/private/pac-server.key"
CA="$PACP_HOME/config/tls/pac-root-ca.crt"
if [ "\${PAC_HTTPS:-$PAC_HTTPS}" = "1" ] && [ ! -f "\$CERT" ] && command -v openssl >/dev/null 2>&1; then
  "$APP_DIR/scripts/ensure-pac-ca.sh" "$PACP_HOME" "$PORT" >/dev/null 2>&1 || true
fi
if [ "\${PAC_HTTPS:-$PAC_HTTPS}" = "1" ] && [ -f "\$CERT" ] && [ -f "\$KEY" ]; then
  exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --ssl-certfile "\$CERT" --ssl-keyfile "\$KEY" --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
EOF2
chmod +x "$APP_DIR/run.sh"

# If sudo was used only to set up the privileged service/CA trust, keep the PAC home owned by the login user.
if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER:-root}" != "root" ]; then
  sudo_cmd chown -R "$(service_user):$(service_group)" "$PACP_HOME" || true
fi

if have systemctl && [ -d /etc/systemd/system ]; then
  if [ "$(id -u)" -eq 0 ] || port_is_privileged; then
    UNIT="/etc/systemd/system/${SERVICE}.service"
    RUN_USER="$(service_user)"
    RUN_GROUP="$(service_group)"
    log "Installing system service: $SERVICE on port $PORT"
    if port_is_privileged && [ "$(id -u)" -ne 0 ]; then
      warn "Port $PORT requires elevated setup; sudo may ask for your password. The service will run as $RUN_USER with CAP_NET_BIND_SERVICE."
    fi
    cat > /tmp/pacp-service.$$ <<EOF2
[Unit]
Description=PAC - Pi Agent Control
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/run.sh
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PACP_HOME=${PACP_HOME}
Environment=PAC_PORT=${PORT}
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF2
    # Install the unit atomically and verify it before asking systemd to enable it.
    # Some systems are picky about enabling a bare service name immediately after
    # a generated unit is moved into place, so use the absolute unit path first.
    sudo_cmd install -m 0644 /tmp/pacp-service.$$ "$UNIT"
    rm -f /tmp/pacp-service.$$ || true
    if [ ! -f "$UNIT" ]; then
      fail "System service unit was not written: $UNIT"
    fi
    sudo_cmd systemctl daemon-reload
    if ! sudo_cmd systemctl enable --now "$UNIT"; then
      warn "systemctl enable with absolute unit path failed; retrying with ${SERVICE}.service"
      sudo_cmd systemctl enable --now "${SERVICE}.service" || fail "Failed to enable ${SERVICE}.service even though $UNIT exists"
    fi
    log "Installed system service: $SERVICE"
  else
    UNIT="$HOME/.config/systemd/user/${SERVICE}.service"
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<EOF2
[Unit]
Description=PAC - Pi Agent Control
After=network-online.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/run.sh
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PACP_HOME=${PACP_HOME}
Environment=PAC_PORT=${PORT}

[Install]
WantedBy=default.target
EOF2
    systemctl --user daemon-reload || true
    systemctl --user enable --now "$SERVICE" || warn "User service written but not started. Manual start: $APP_DIR/run.sh"
    log "Installed user service: $SERVICE"
  fi
else
  warn "systemd not found; start manually: $APP_DIR/run.sh"
fi


# PAC source/update zips do not bundle compiled endpoint/client binaries.
# pac-endpoint and pacctl are downloaded from GitHub Release assets on demand,
# with local source builds reserved for explicit fallback flows. Avoid starting
# legacy Zed/MCP binary builds during controller installation; that behavior is
# moving into pacctl.
mkdir -p "$PACP_HOME/bin"
cat > "$PACP_HOME/bin/README.md" <<'EOFBIN'
PAC runtime/client binaries are resolved from GitHub Release assets:

- pac-endpoint: endpoint/workspace wrapper
- pacctl: client/API/editor/provider utility

The controller source package intentionally does not bundle compiled binaries.

Install helpers copied with PAC:
  $APP_DIR/scripts/install-pac-binary.sh pacctl
  $APP_DIR/scripts/install-pac-binary.sh pac-endpoint
EOFBIN

cat <<EOF2

PACP installed.
Application: $APP_DIR
PAC home:   $PACP_HOME
Config:      $PACP_HOME/config/config.yaml
State DB:    $PACP_HOME/state.db
URL:         https://admin.pac.local:$PORT
Manual:      $APP_DIR/run.sh
EOF2
