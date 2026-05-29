#!/usr/bin/env bash
set -euo pipefail

REPO="${PAC_GITHUB_REPO:-pac-labs/controller}"
COMPONENT="${1:-}"
TARGET="${PAC_TARGET:-}"
DEST_DIR="${PAC_BIN_DIR:-$HOME/.local/bin}"
TOKEN="${GITHUB_TOKEN:-${PAC_GITHUB_TOKEN:-}}"

fail() { printf '[pac-binary] %s\n' "$*" >&2; exit 1; }
log() { printf '[pac-binary] %s\n' "$*"; }

[ -n "$COMPONENT" ] || fail "Usage: $0 pac-endpoint|pacctl [target]"
case "$COMPONENT" in
  pac-endpoint|pacctl) ;;
  *) fail "Unsupported component: $COMPONENT. Expected pac-endpoint or pacctl." ;;
esac
if [ $# -ge 2 ]; then TARGET="$2"; fi

os_name() {
  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    linux*) printf linux ;;
    darwin*) printf darwin ;;
    msys*|mingw*|cygwin*) printf windows ;;
    *) fail "Unsupported OS: $(uname -s)" ;;
  esac
}
arch_name() {
  case "$(uname -m)" in
    x86_64|amd64) printf amd64 ;;
    aarch64|arm64) printf arm64 ;;
    *) fail "Unsupported architecture: $(uname -m)" ;;
  esac
}

if [ -z "$TARGET" ]; then
  TARGET="$(os_name)/$(arch_name)"
fi
GOOS="${TARGET%/*}"
GOARCH="${TARGET#*/}"
EXT=""
[ "$GOOS" = "windows" ] && EXT=".exe"
ASSET="${COMPONENT}-${GOOS}-${GOARCH}${EXT}"
DEST_NAME="$COMPONENT$EXT"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

AUTH=()
[ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
API="https://api.github.com/repos/${REPO}/releases/latest"
log "Resolving latest release for ${REPO}"
RELEASE_JSON="$TMP_DIR/release.json"
curl -fsSL "${AUTH[@]}" "$API" -o "$RELEASE_JSON"
URL="$(python3 - "$RELEASE_JSON" "$ASSET" <<'PY'
import json, sys
release=json.load(open(sys.argv[1]))
asset=sys.argv[2]
for item in release.get('assets', []):
    if item.get('name') == asset:
        print(item.get('browser_download_url', ''))
        break
PY
)"
[ -n "$URL" ] || fail "Release asset not found: $ASSET"
mkdir -p "$DEST_DIR"
log "Downloading $ASSET"
curl -fL "${AUTH[@]}" "$URL" -o "$DEST_DIR/$DEST_NAME"
chmod +x "$DEST_DIR/$DEST_NAME" || true
log "Installed $DEST_DIR/$DEST_NAME"
