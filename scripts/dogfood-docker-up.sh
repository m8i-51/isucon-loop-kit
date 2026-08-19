#!/usr/bin/env bash
# Bring up ISUCON14 Python compose + SSH contest target for isuctl dogfood.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ISUCON_LOOP_KIT_ROOT="$ROOT"
ASSETS="$ROOT/assets/isucon14-docker"
ISUCON14_DIR="${ISUCON14_DIR:-/opt/isucon14}"
COMPOSE_DOGFOOD="$ASSETS/compose.dogfood.yml"
SSH_DIR="${SSH_DIR:-$HOME/.ssh/isucon-dogfood}"
KEY_PATH="$SSH_DIR/id_ed25519"

log() { printf '[dogfood-up] %s\n' "$*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

need_cmd docker
need_cmd git
need_cmd ssh-keygen
need_cmd curl

if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    sudo service docker start || true
    sleep 1
  fi
fi
if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is not running" >&2
  exit 1
fi

if [[ ! -d "$ISUCON14_DIR/.git" ]]; then
  log "cloning isucon/isucon14 → $ISUCON14_DIR"
  sudo mkdir -p "$(dirname "$ISUCON14_DIR")"
  sudo chown "$(id -u):$(id -g)" "$(dirname "$ISUCON14_DIR")" 2>/dev/null || true
  git clone --depth 1 https://github.com/isucon/isucon14.git "$ISUCON14_DIR"
fi

# Use kit Dockerfile (unpinned mysql client) for webapp builds.
cp "$ASSETS/Dockerfile.python" \
  "$ISUCON14_DIR/development/dockerfiles/Dockerfile.python.dogfood"

# SSL-safe init.sh (mariadb client vs mysql:8)
if ! grep -q -- '--ssl-mode=DISABLED' "$ISUCON14_DIR/webapp/sql/init.sh"; then
  sed -i 's/mysql -u"$ISUCON_DB_USER"/mysql --ssl-mode=DISABLED -u"$ISUCON_DB_USER"/g' \
    "$ISUCON14_DIR/webapp/sql/init.sh"
fi

if [[ ! -d "$ISUCON14_DIR/frontend/build/client" ]]; then
  need_cmd pnpm
  log "building frontend"
  (cd "$ISUCON14_DIR/frontend" && pnpm install && pnpm run build)
fi

mkdir -p "$SSH_DIR"
if [[ ! -f "$KEY_PATH" ]]; then
  ssh-keygen -t ed25519 -N '' -f "$KEY_PATH" >/dev/null
fi
AUTH_KEYS="$SSH_DIR/authorized_keys"
cp "$KEY_PATH.pub" "$AUTH_KEYS"

# Seed named volume before compose (external: true in overlay)
docker volume create dogfood_ssh_keys >/dev/null
docker volume create dogfood_nginx_logs >/dev/null
docker volume create dogfood_mysql_slow_share >/dev/null
docker volume create dogfood_mysql_data >/dev/null
docker run --rm \
  -v dogfood_ssh_keys:/keys \
  -v "$AUTH_KEYS:/authorized_keys:ro" \
  public.ecr.aws/docker/library/alpine:3.20 \
  sh -c 'cp /authorized_keys /keys/authorized_keys && chmod 644 /keys/authorized_keys'

log "starting compose"
cd "$ISUCON14_DIR/development"
docker compose -f compose-python.yml -f "$COMPOSE_DOGFOOD" up -d --build

log "waiting for http://127.0.0.1:8080"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://127.0.0.1:8080/; then
    break
  fi
  sleep 2
done
curl -fsS -o /dev/null http://127.0.0.1:8080/

# Point payment gateway at host (bench payment mock)
docker compose -f compose-python.yml -f "$COMPOSE_DOGFOOD" exec -T db \
  mysql -uisucon -pisucon isuride -e \
  "UPDATE settings SET value='http://host.docker.internal:12345' WHERE name='payment_gateway_url';" \
  >/dev/null 2>&1 || true

# SSH config alias for non-22 port
SSH_CONFIG="$HOME/.ssh/config"
mkdir -p "$HOME/.ssh"
touch "$SSH_CONFIG"
if ! grep -q 'Host isucon-dogfood' "$SSH_CONFIG" 2>/dev/null; then
  cat >> "$SSH_CONFIG" <<EOF

Host isucon-dogfood
  HostName 127.0.0.1
  Port 2222
  User isucon
  IdentityFile $KEY_PATH
  StrictHostKeyChecking accept-new
  UserKnownHostsFile $SSH_DIR/known_hosts
EOF
fi
chmod 600 "$SSH_CONFIG" || true

# Wait for ssh
for _ in $(seq 1 30); do
  if ssh -o BatchMode=yes -o ConnectTimeout=2 isucon-dogfood true 2>/dev/null; then
    break
  fi
  sleep 1
done
ssh -o BatchMode=yes isucon-dogfood true

# Write isucon.toml in workspace if missing
cd "$ROOT"
if [[ ! -f isucon.toml ]]; then
  if command -v isuctl >/dev/null 2>&1; then
    isuctl init-config --name isucon14-docker --host isucon-dogfood --user isucon --key "$KEY_PATH" --bootstrap-user isucon
  else
    cat > isucon.toml <<EOF
[project]
name = "isucon14-docker"
local_dir = "./work"

[ssh]
user = "isucon"
key = "$KEY_PATH"
bootstrap_user = "isucon"

[[hosts]]
name = "app1"
host = "isucon-dogfood"
role = ["app", "web", "db"]
remote_app_dir = "/home/isucon/webapp"
EOF
  fi
fi

log "ready"
log "  app:  http://127.0.0.1:8080"
log "  ssh:  ssh isucon-dogfood"
log "  next: scripts/dogfood-docker-loop.sh"
