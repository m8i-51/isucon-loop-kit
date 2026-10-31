#!/usr/bin/env bash
# Contest morning: copy examples → real inventory, then edit IPs once.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cp -n "$ROOT/inventory/hosts.example.yml" "$ROOT/inventory/hosts.yml" || true
for h in s1 s2 s3; do
  src="$ROOT/inventory/host_vars/${h}.example.yml"
  dst="$ROOT/inventory/host_vars/${h}.yml"
  if [[ -f "$src" && ! -f "$dst" ]]; then
    cp "$src" "$dst"
  fi
done
echo "Edit inventory/hosts.yml and inventory/host_vars/*.yml with contest IPs, then:"
echo "  ansible all -m ping"
