from __future__ import annotations

import re
import shlex
from datetime import datetime
from pathlib import Path

from isuctl.config import load_config
from isuctl.hostsutil import primary_host
from isuctl.remote import run_ssh

_LABEL_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _snapshot_remote_command(remote_path: str, app_rel: str) -> str:
    """Tar the app dir plus nginx/apache configs that are readable."""
    quoted_remote = shlex.quote(remote_path)
    quoted_app = shlex.quote(app_rel)
    parts = [
        "mkdir -p /home/isucon/snapshots",
        f"set -- {quoted_app}",
        'if [ -r /etc/nginx ]; then set -- "$@" etc/nginx; fi',
        'if [ -r /etc/apache2 ]; then set -- "$@" etc/apache2; fi',
        'if [ -r /etc/httpd ]; then set -- "$@" etc/httpd; fi',
        f'tar czf {quoted_remote} -C / "$@"',
    ]
    return " && ".join(parts)


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
    remote_cmd = _snapshot_remote_command(remote_path, app_rel)
    run_ssh(config.ssh, host, remote_cmd)
    return remote_path
