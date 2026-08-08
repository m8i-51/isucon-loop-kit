from __future__ import annotations

import shlex
from datetime import datetime
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.paths import out_dir
from isuctl.remote import rsync_file_from_remote, run_ssh

REMOTE_LOG_PATHS: list[tuple[str, str]] = [
    ("/var/log/nginx/access.log", "access.log"),
    ("/var/log/mysql/mysql-slow.log", "mysql-slow.log"),
    ("/tmp/mysql-slow.log", "mysql-slow.log"),
]


def _primary_host(hosts: list[Host]) -> Host:
    for host in hosts:
        if "app" in host.role:
            return host
    return hosts[0]


def _remote_exists(ssh, host: Host, remote_path: str) -> bool:
    result = run_ssh(ssh, host, f"test -e {shlex.quote(remote_path)}", check=False)
    return result.returncode == 0


def run_pull(config_path: Path) -> Path:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config must have at least one host")

    host = _primary_host(config.hosts)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_dir = out_dir() / "raw" / timestamp
    raw_dir.mkdir(parents=True, exist_ok=True)

    pulled_slow = False
    for remote_path, local_name in REMOTE_LOG_PATHS:
        if local_name == "mysql-slow.log" and pulled_slow:
            continue
        if not _remote_exists(config.ssh, host, remote_path):
            continue
        local_file = raw_dir / local_name
        rsync_file_from_remote(config.ssh, host, remote_path, local_file)
        if local_name == "mysql-slow.log":
            pulled_slow = True

    return raw_dir
