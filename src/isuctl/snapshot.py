from __future__ import annotations

import re
import shlex
from datetime import datetime
from pathlib import Path

from isuctl.config import load_config
from isuctl.hostsutil import primary_host
from isuctl.remote import run_ssh

_LABEL_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _snapshot_name(timestamp: str, label: str | None) -> str:
    if not label:
        return f"snap-{timestamp}.tar.gz"
    safe = _LABEL_SAFE_RE.sub("-", label).strip("-.")
    safe = re.sub(r"-{2,}", "-", safe)
    if not safe:
        raise ValueError("snapshot の --label に使える文字がありません")
    return f"snap-{timestamp}-{safe}.tar.gz"


def run_snapshot(config_path: Path, label: str | None = None) -> str:
    config = load_config(config_path)
    host = primary_host(config.hosts)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    remote_path = f"/home/isucon/snapshots/{_snapshot_name(timestamp, label)}"

    app_rel = host.remote_app_dir.lstrip("/")
    remote_cmd = (
        f"mkdir -p /home/isucon/snapshots && "
        f"if [ -r /etc/nginx ]; then "
        f"tar czf {shlex.quote(remote_path)} -C / {shlex.quote(app_rel)} etc/nginx; "
        f"else "
        f"tar czf {shlex.quote(remote_path)} -C / {shlex.quote(app_rel)}; "
        f"fi"
    )
    run_ssh(config.ssh, host, remote_cmd)
    return remote_path
