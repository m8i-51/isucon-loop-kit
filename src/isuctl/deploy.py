from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.paths import is_ready
from isuctl.remote import rsync_to_remote, run_ssh
from isuctl.sync_down import DEFAULT_EXCLUDES

DEPLOY_EXCLUDES = [*DEFAULT_EXCLUDES, ".isucon-ready"]


class DeployBlockedError(RuntimeError):
    pass


def _primary_host(hosts: list[Host]) -> Host:
    for host in hosts:
        if "app" in host.role:
            return host
    return hosts[0]


def _create_pre_deploy_tag(local_dir: Path) -> None:
    if not (local_dir / ".git").exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    subprocess.run(
        ["git", "-C", str(local_dir), "tag", f"pre-deploy-{timestamp}"],
        check=True,
        capture_output=True,
        text=True,
    )


def run_deploy(
    config_path: Path,
    *,
    force: bool = False,
    restart_unit: str = "isucon-python.service",
) -> None:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config にホストが1つ以上必要です")

    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    if not is_ready(local_dir) and not force:
        raise DeployBlockedError(
            f"local dir が未準備です: 先に sync-down するか --force を使ってください ({local_dir})"
        )

    host = _primary_host(config.hosts)
    _create_pre_deploy_tag(local_dir)
    rsync_to_remote(
        config.ssh,
        host,
        local_dir,
        host.remote_app_dir,
        excludes=DEPLOY_EXCLUDES,
        delete=True,
    )
    restart_cmd = (
        f"sudo systemctl restart {restart_unit} || "
        "sudo systemctl restart isucon-webapp || true"
    )
    run_ssh(config.ssh, host, restart_cmd)
    health_cmd = (
        "curl -fsS http://127.0.0.1/ || curl -fsS http://127.0.0.1:8080/ || true"
    )
    run_ssh(config.ssh, host, health_cmd, check=False)
