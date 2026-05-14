#!/usr/bin/env bash
# ensure-pac-ca.sh - Generate PAC TLS certificates with proper SANs
set -euo pipefail
PACP_HOME="${1:-${PACP_HOME:-$HOME/.pacp}}"
PORT="${2:-${PAC_PORT:-443}}"
TLS_DIR="$PACP_HOME/config/tls"
PRIVATE_DIR="$TLS_DIR/private"
CA_CERT="$TLS_DIR/pac-root-ca.crt"
CA_KEY="$PRIVATE_DIR/pac-root-ca.key"
SERVER_CERT="$TLS_DIR/pac-server.crt"
SERVER_KEY="$PRIVATE_DIR/pac-server.key"
CSR="$PRIVATE_DIR/pac-server.csr"
EXT="$PRIVATE_DIR/pac-server.ext"
DETAILS="$TLS_DIR/ca-details.yaml"

mkdir -p "$PRIVATE_DIR"
chmod 700 "$PRIVATE_DIR" || true
command -v openssl >/dev/null 2>&1 || exit 0

# Create root CA if missing
if [ ! -f "$CA_CERT" ] || [ ! -f "$CA_KEY" ]; then
  openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days 10950 \
    -keyout "$CA_KEY" -out "$CA_CERT" \
    -subj "/CN=PAC Local Root CA/O=PAC/C=NL" >/dev/null 2>&1
  chmod 600 "$CA_KEY" || true
fi

# Regenerate server cert if it doesn't include our required SANs
if [ -f "$SERVER_CERT" ] && ! openssl x509 -noout -text -in "$SERVER_CERT" 2>/dev/null | grep -q 'DNS:admin.pac.local'; then
  rm -f "$SERVER_CERT" "$SERVER_KEY" "$CSR"
fi

if [ ! -f "$SERVER_CERT" ] || [ ! -f "$SERVER_KEY" ]; then
  # Collect all LAN IPs for SAN
  LAN_IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^192\.168\.|^10\.|^172\.(1[6-9]|2[0-9]|3[0-1])\.' | sort -u | paste -sd, -)

  # Build SAN line (DNS + IPs)
  SAN="DNS:localhost,DNS:admin.pac.local,DNS:pac.local,DNS:developer.dorbian.com,IP:127.0.0.1,IP:::1"
  if [ -n "$LAN_IPS" ]; then
    SAN="$SAN,$LAN_IPS"
  fi

  printf 'subjectAltName=%s\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n' "$SAN" > "$EXT"

  openssl req -newkey rsa:2048 -nodes -keyout "$SERVER_KEY" -out "$CSR" \
    -subj "/CN=localhost/O=PAC/C=NL" >/dev/null 2>&1
  openssl x509 -req -in "$CSR" -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$SERVER_CERT" -days 825 -sha256 -extfile "$EXT" >/dev/null 2>&1
  chmod 600 "$SERVER_KEY" || true
fi

cat > "$DETAILS" <<EOFDETAILS
created_or_checked_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
ca_valid_days: 10950
server_valid_days: 825
ca_cert_file: $CA_CERT
ca_key_file: $CA_KEY
server_cert_file: $SERVER_CERT
server_key_file: $SERVER_KEY
public_url: https://admin.pac.local${PORT:+:$PORT}
EOFDETAILS
chmod 600 "$DETAILS" || true