#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" 2>/dev/null && pwd -P || printf '%s' "$ROOT")"
INSTALL_ROOT="$ROOT"
if [ "$(basename "$ROOT")" = "app" ] && [ -d "$(dirname "$ROOT")/logs" ]; then
  INSTALL_ROOT="$(dirname "$ROOT")"
fi
SINCE_LINES="${PAC_DEBUG_LINES:-600}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/tmp/pac-host-debug-${STAMP}"
mkdir -p "$OUT/logs"

sanitize_bundle() {
  grep -RIl . "$OUT" | xargs -r sed -i -E \
    -e 's/(api[_-]?key|token|secret|password|authorization|bearer)[=: ]+[A-Za-z0-9._~+\/=-]+/\1=<redacted>/Ig' \
    -e 's/(sk-[A-Za-z0-9_-]{20,})/<redacted-openai-key>/g' \
    -e 's#(ssl-keyfile +)[^ ]+#\1<redacted-keyfile>#Ig' \
    -e 's#(tls/private/)[^ ]+#\1<redacted>#Ig'
}

copy_tail() {
  local file_path="$1"
  local label_root="$2"
  [ -f "$file_path" ] || return 0
  local rel safe
  rel="${file_path#$label_root/}"
  safe="$(printf '%s' "$rel" | sed 's#^\./##; s#[/ ]#_#g')"
  tail -n "$SINCE_LINES" "$file_path" > "$OUT/logs/$safe.tail" 2>/dev/null || true
}

{
  echo "== PAC HOST DEBUG =="
  date -u
  hostname || true
  printf 'root=%s\n' "$ROOT"
  printf 'install_root=%s\n' "$INSTALL_ROOT"
  printf 'user=%s\n' "${USER:-unknown}"
} > "$OUT/00-summary.txt"

{
  cd "$ROOT" 2>/dev/null || true
  echo "## version"
  cat VERSION 2>/dev/null || true
  cat VERSION_CURRENT.md 2>/dev/null || true
  echo
  echo "## python"
  python3 --version 2>&1 || true
  command -v python3 || true
  [ -x .venv/bin/python ] && .venv/bin/python --version 2>&1 || true
  echo
  echo "## process"
  ps auxww | grep -Ei 'pac|pi_agent|uvicorn|fastapi|python' | grep -v grep || true
  echo
  echo "## ports"
  ss -ltnp 2>/dev/null | grep -Ei 'python|uvicorn|pac|:8443|:8444|:8000|:8080|:3000|:5173|:9123' || true
} > "$OUT/01-runtime.txt" 2>&1

{
  echo "## app logs"
  (cd "$ROOT" 2>/dev/null && find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './venv' -prune -o \
    -path './node_modules' -prune -o \
    -path './dist' -prune -o \
    -type f \( -name '*.log' -o -name 'events.jsonl' -o -name 'events.json' -o -name '*session*.jsonl' -o -name '*session*.json' \) \
    -printf '%TY-%Tm-%Td %TH:%TM app/%p\n' 2>/dev/null | sort -r | head -80) || true
  echo
  echo "## install logs"
  (cd "$INSTALL_ROOT" 2>/dev/null && find logs pi-agent-artifacts app/pi-agent-artifacts updates -maxdepth 4 \
    -type f \( -name '*.log' -o -name '*.txt' -o -name 'events.jsonl' -o -name 'events.json' -o -name '*session*.jsonl' -o -name '*session*.json' \) \
    -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | sort -r | head -120) || true
} > "$OUT/02-log-index.txt" 2>&1

while IFS= read -r file_path; do
  copy_tail "$ROOT/${file_path#./}" "$ROOT"
done < <(cd "$ROOT" 2>/dev/null && find . \
  -path './.git' -prune -o \
  -path './.venv' -prune -o \
  -path './venv' -prune -o \
  -path './node_modules' -prune -o \
  -path './dist' -prune -o \
  -type f \( -name '*.log' -o -name 'events.jsonl' -o -name 'events.json' -o -name '*session*.jsonl' -o -name '*session*.json' \) \
  -print 2>/dev/null | head -60)

while IFS= read -r file_path; do
  copy_tail "$INSTALL_ROOT/${file_path#./}" "$INSTALL_ROOT"
done < <(cd "$INSTALL_ROOT" 2>/dev/null && find logs pi-agent-artifacts app/pi-agent-artifacts updates -maxdepth 4 \
  -type f \( -name '*.log' -o -name '*.txt' -o -name 'events.jsonl' -o -name 'events.json' -o -name '*session*.jsonl' -o -name '*session*.json' \) \
  -print 2>/dev/null | head -100)

{
  cd "$ROOT" 2>/dev/null || true
  find pi_agent_platform .github scripts -maxdepth 4 -type f 2>/dev/null | sort | head -700
} > "$OUT/03-tree.txt" 2>&1

{
  echo "## environment names only"
  env | sed -E 's/=.*/=<redacted>/' | sort | grep -Ei 'PAC|PI_|OPENAI|ANTHROPIC|GOOGLE|NVIDIA|MODEL|PROVIDER|TOKEN|KEY|SECRET|DATABASE|REDIS|HOST|PORT' || true
} > "$OUT/04-env-redacted.txt" 2>&1

{
  echo "## systemd units"
  systemctl --user --no-pager --type=service 2>/dev/null | grep -Ei 'pac|pi|agent' || true
  systemctl --no-pager --type=service 2>/dev/null | grep -Ei 'pac|pi|agent' || true
  echo
  echo "## pacp user status"
  systemctl --user --no-pager status pacp.service 2>/dev/null || true
  echo
  echo "## pacp system status"
  systemctl --no-pager status pacp.service 2>/dev/null || true
  echo
  echo "## recent pacp user journal"
  journalctl --user -u pacp.service --no-pager -n 500 2>/dev/null || true
  echo
  echo "## recent pacp system journal"
  journalctl -u pacp.service --no-pager -n 500 2>/dev/null || true
} > "$OUT/05-systemd-journal.txt" 2>&1

{
  echo "## containers"
  podman ps -a 2>/dev/null || docker ps -a 2>/dev/null || true
  echo
  echo "## pac container logs"
  if command -v podman >/dev/null 2>&1; then
    for name in $(podman ps -a --format '{{.Names}}' 2>/dev/null | grep -Ei 'pac|pi' || true); do
      echo "### $name"
      podman logs --tail "$SINCE_LINES" "$name" 2>&1 || true
    done
  elif command -v docker >/dev/null 2>&1; then
    for name in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Ei 'pac|pi' || true); do
      echo "### $name"
      docker logs --tail "$SINCE_LINES" "$name" 2>&1 || true
    done
  fi
} > "$OUT/06-containers.txt" 2>&1

{
  echo "## session/artifact directories"
  find "$INSTALL_ROOT" -maxdepth 4 -type d \( -name '*session*' -o -name 'pi-agent-artifacts' -o -name 'artifacts' \) -print 2>/dev/null | head -100 || true
  echo
  echo "## recent sqlite/db files"
  find "$INSTALL_ROOT" -maxdepth 4 -type f \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' 2>/dev/null | sort -r | head -50 || true
} > "$OUT/07-state-index.txt" 2>&1

sanitize_bundle

tar -C /tmp -czf "$OUT.tar.gz" "$(basename "$OUT")"
echo "$OUT.tar.gz"
