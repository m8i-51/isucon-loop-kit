#!/usr/bin/env bash
# Idempotent Cloud Agent install for isucon-loop-kit + ISUCON14 docker dogfood.
set -euo pipefail

cd /workspace

export PATH="$HOME/.local/bin:/usr/local/go/bin:$PATH"

# Prefer uv (PEP 668 blocks bare pip on many Cloud Agent images).
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --extra dev
export PATH="/workspace/.venv/bin:$PATH"

# Host tools needed by isuctl / dogfood scripts
if ! command -v rsync >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is missing from the base snapshot; rebuild the environment image" >&2
  exit 1
fi

# Ensure docker socket usable by ubuntu
if [[ -S /var/run/docker.sock ]]; then
  sudo chmod 666 /var/run/docker.sock || true
fi

chmod +x scripts/dogfood-docker-up.sh scripts/dogfood-docker-loop.sh \
  assets/isucon14-docker/ssh/entrypoint.sh 2>/dev/null || true

# Warm ISUCON14 tree (clone if absent; frontend build if needed)
export ISUCON14_DIR="${ISUCON14_DIR:-/opt/isucon14}"
if [[ ! -d "$ISUCON14_DIR/.git" ]]; then
  sudo mkdir -p "$(dirname "$ISUCON14_DIR")"
  sudo chown "$(id -u):$(id -g)" "$(dirname "$ISUCON14_DIR")" 2>/dev/null || true
  git clone --depth 1 https://github.com/isucon/isucon14.git "$ISUCON14_DIR"
fi
cp assets/isucon14-docker/Dockerfile.python \
  "$ISUCON14_DIR/development/dockerfiles/Dockerfile.python.dogfood"
if [[ ! -d "$ISUCON14_DIR/frontend/build/client" ]]; then
  (cd "$ISUCON14_DIR/frontend" && pnpm install && pnpm run build)
fi

# Go 1.23 for bench (best-effort)
if ! /usr/local/go/bin/go version 2>/dev/null | grep -q 'go1.23'; then
  if [[ ! -x /usr/local/go/bin/go ]]; then
    curl -fsSL https://go.dev/dl/go1.23.6.linux-amd64.tar.gz -o /tmp/go123.tar.gz
    sudo rm -rf /usr/local/go
    sudo tar -C /usr/local -xzf /tmp/go123.tar.gz
  fi
fi

echo "install ok: $(isuctl --version 2>/dev/null || isuctl --help | head -1)"
