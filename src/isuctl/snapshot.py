from __future__ import annotations

from datetime import datetime
from pathlib import Path

from isuctl.compose_transport import snapshot_compose
from isuctl.config import load_config, uses_compose
from isuctl.hostsutil import primary_host
from isuctl.remote import run_ssh
from isuctl.snapshot_tar import snapshot_name, snapshot_remote_command


def run_snapshot(config_path: Path, label: str | None = None) -> str:
    config = load_config(config_path)
    if uses_compose(config):
        return snapshot_compose(config_path, label=label)
    host = primary_host(config.hosts)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    remote_path = f"/home/isucon/snapshots/{snapshot_name(timestamp, label)}"

    app_rel = host.remote_app_dir.lstrip("/")
    remote_cmd = snapshot_remote_command(remote_path, app_rel)
    run_ssh(config.ssh, host, remote_cmd)
    return remote_path
