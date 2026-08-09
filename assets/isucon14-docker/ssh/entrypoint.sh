#!/usr/bin/env bash
set -euo pipefail

AUTH_KEYS_SRC="${AUTHORIZED_KEYS_FILE:-/ssh-keys/authorized_keys}"
AUTH_KEYS_DST=/home/isucon/.ssh/authorized_keys

mkdir -p /home/isucon/.ssh /home/isucon/webapp /var/log/nginx /var/log/mysql /home/isucon/local/bin
if [[ -f "$AUTH_KEYS_SRC" ]]; then
  cp "$AUTH_KEYS_SRC" "$AUTH_KEYS_DST"
fi
chown -R isucon:isucon /home/isucon/.ssh
chmod 700 /home/isucon/.ssh
chmod 600 "$AUTH_KEYS_DST" 2>/dev/null || true

# Soft placeholders so discover/bootstrap have something to poke.
touch /var/log/nginx/access.ltsv.log /var/log/nginx/access.log /var/log/mysql/mysql-slow.log
chmod 644 /var/log/nginx/* /var/log/mysql/* || true

exec /usr/sbin/sshd -D -e
