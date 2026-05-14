#!/usr/bin/env bash
set -euo pipefail
cd "/home/dorbian/.pacp/app"
. .venv/bin/activate
export PACP_HOME="${PACP_HOME:-/home/dorbian/.pacp}"
PORT="${PAC_PORT:-443}"
if [ "$PORT" -lt 1024 ] 2>/dev/null; then
  if ! python - "$PORT" <<'PYBIND' >/dev/null 2>&1
import socket, sys
s = socket.socket()
try:
    s.bind(('0.0.0.0', int(sys.argv[1])))
finally:
    s.close()
PYBIND
  then
    echo "PAC cannot bind privileged port $PORT as this user; falling back to 8443. Run sudo ./install.sh or install the systemd service with CAP_NET_BIND_SERVICE for port 443." >&2
    PORT=8443
  fi
fi
export PAC_PORT="$PORT"
CERT="$PACP_HOME/config/tls/pac-server.crt"
KEY="$PACP_HOME/config/tls/private/pac-server.key"
if [ "${PAC_HTTPS:-1}" = "1" ] && [ ! -f "$CERT" ] && command -v openssl >/dev/null 2>&1; then
  "/home/dorbian/.pacp/app/scripts/ensure-pac-ca.sh" "$PACP_HOME" "$PORT" >/dev/null 2>&1 || true
fi
if [ "${PAC_HTTPS:-1}" = "1" ] && [ -f "$CERT" ] && [ -f "$KEY" ]; then
  exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --ssl-certfile "$CERT" --ssl-keyfile "$KEY" --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn pi_agent_platform.api.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
