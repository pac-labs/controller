#!/bin/sh
set -eu
mkdir -p /out
if ! touch /out/.pac-write-test 2>/dev/null; then
  echo "Output directory /out is not writable by the build container." >&2
  exit 13
fi
rm -f /out/.pac-write-test
VERSION="${PAC_VERSION:-dev}"
COMPILED_SERVER_URL="${PAC_COMPILED_SERVER_URL:-${PAC_BUILD_SERVER_URL:-}}"
BINARY_NAME="${PAC_BINARY_NAME:-$(basename "$PWD")}"
BINARY_NAME="$(printf '%s' "$BINARY_NAME" | tr -d '[:space:]')"
TARGETS="${PAC_TARGETS:-linux/amd64,linux/arm64,windows/amd64,darwin/amd64,darwin/arm64}"
BUILD_OUT="/tmp/pac-binary-out"
rm -rf "$BUILD_OUT"
mkdir -p "$BUILD_OUT"
OLD_IFS="$IFS"
IFS=','
for target in $TARGETS; do
  IFS="$OLD_IFS"
  case "$target" in
    */*) ;;
    *) echo "Invalid target: $target" >&2; exit 2 ;;
  esac
  GOOS="${target%/*}"
  GOARCH="${target#*/}"
  EXT=""
  if [ "$GOOS" = "windows" ]; then EXT=".exe"; fi
  NAME="${BINARY_NAME}-${VERSION}-${GOOS}-${GOARCH}${EXT}"
  TMP_OUT="${BUILD_OUT}/${NAME}"
  FINAL_OUT="/out/${NAME}"
  echo "building ${target} -> ${FINAL_OUT}"
  GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=${VERSION} -X main.defaultServerURL=${COMPILED_SERVER_URL}" -o "$TMP_OUT" .
  install -m 0755 "$TMP_OUT" "$FINAL_OUT"
  IFS=','
done
IFS="$OLD_IFS"
