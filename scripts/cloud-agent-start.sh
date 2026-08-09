#!/usr/bin/env bash
# Per-boot: Docker daemon + ISUCON14 dogfood compose.
set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/go/bin:$PATH"
export ISUCON_LOOP_KIT_ROOT="${ISUCON_LOOP_KIT_ROOT:-/workspace}"

if ! docker info >/dev/null 2>&1; then
  sudo service docker start || true
  sleep 2
fi
if [[ -S /var/run/docker.sock ]]; then
  sudo chmod 666 /var/run/docker.sock || true
fi

# Start (or refresh) the dogfood stack. Idempotent enough for reboots.
"$ISUCON_LOOP_KIT_ROOT/scripts/dogfood-docker-up.sh"

echo "start ok: curl $(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/)"
