#!/usr/bin/env bash
# Minimal dogfood loop against the Docker contest SSH target.
# Assumes scripts/dogfood-docker-up.sh already succeeded.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="/usr/local/go/bin:${PATH:-}"

if ! command -v isuctl >/dev/null 2>&1; then
  python3 -m pip install -e . >/dev/null
fi

log() { printf '[dogfood-loop] %s\n' "$*"; }

log "discover"
isuctl discover || true

log "sync-down"
isuctl sync-down

log "bootstrap (best-effort on compose layout)"
isuctl bootstrap || true

# Generate a little LTSV traffic if access log is empty
ssh isucon-dogfood 'sudo test -s /var/log/nginx/access.ltsv.log' 2>/dev/null || true
for i in $(seq 1 20); do
  curl -fsS -o /dev/null "http://127.0.0.1:8080/" || true
  curl -fsS -o /dev/null "http://127.0.0.1:8080/api/owner/sales" || true
done

# Optional short bench if go is available
if command -v go >/dev/null 2>&1 && [[ -d /opt/isucon14/bench ]]; then
  log "short bench (30s, may fail payment — still produces traffic)"
  (cd /opt/isucon14/bench && go run . run --target http://127.0.0.1:8080 -t 30 --skip-static-sanity-check) \
    || true
fi

# Sync mysql slow log into contest share if present in db container
DB_CID="$(docker ps -qf name=development-db-1 || true)"
if [[ -n "$DB_CID" ]]; then
  SLOW="$(docker exec "$DB_CID" sh -c 'ls /var/lib/mysql/*-slow.log 2>/dev/null | head -1' || true)"
  if [[ -n "$SLOW" ]]; then
    docker cp "$DB_CID:$SLOW" /tmp/mysql-slow.log 2>/dev/null || true
    if [[ -f /tmp/mysql-slow.log ]]; then
      docker cp /tmp/mysql-slow.log "$(docker ps -qf name=contest-ssh):/var/log/mysql/mysql-slow.log" 2>/dev/null || true
    fi
  fi
fi

log "pull → analyze → pack"
isuctl pull
isuctl analyze
isuctl pack
isuctl bench-note 0 --note "docker dogfood" || true

log "done — see out/pack.md and out/analyze/"
ls -la out/pack.md out/analyze 2>/dev/null || true
