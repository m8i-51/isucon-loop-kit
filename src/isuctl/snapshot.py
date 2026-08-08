from __future__ import annotations

import shlex
from datetime import datetime
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.remote import run_ssh


def _primary_host(hosts: list[Host]) -> Host:
    for host in hosts:
        if "app" in host.role:
            return host
    return hosts[0]


def _snapshot_name(timestamp: str, label: str | None) -> str:
    if label:
        return f"snap-{timestamp}-{label}.tar.gz"
    return f"snap-{timestamp}.tar.gz"


def run_snapshot(config_path: Path, label: str | None = None) -> str:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config must have at least one host")

    host = _primary_host(config.hosts)
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
