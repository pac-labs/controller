#!/usr/bin/env sh
set -eu
OUT=${OUT:-/out}
mkdir -p "$OUT"
VERSION=$(cat /src/VERSION 2>/dev/null || echo "0.1.0")
cat > /src/build-info.txt <<EOM
version=$VERSION
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
go_version=$(go version)
EOM
build_one() {
  GOOS="$1" GOARCH="$2" EXT=""
  [ "$GOOS" = "windows" ] && EXT=".exe"
  latest="$OUT/pac-mcp-${GOOS}-${GOARCH}${EXT}"
  versioned="$OUT/pac-mcp-${VERSION}-${GOOS}-${GOARCH}${EXT}"
  echo "building pac-mcp ${GOOS}/${GOARCH} -> $latest and $versioned"
  GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=$VERSION" -o "$latest" .
  cp "$latest" "$versioned"
}
build_one linux amd64
build_one linux arm64
build_one darwin amd64
build_one darwin arm64
build_one windows amd64
build_one windows arm64
sha256sum "$OUT"/pac-mcp-* > "$OUT/SHA256SUMS"
cp /src/build-info.txt "$OUT/build-info.txt"
ls -lah "$OUT"
