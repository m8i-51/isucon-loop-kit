from __future__ import annotations

import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from isuctl.config import load_config
from isuctl.hostsutil import primary_host
from isuctl.paths import is_ready
from isuctl.remote import rsync_to_remote, run_ssh
from isuctl.sync_down import DEFAULT_EXCLUDES

DEPLOY_EXCLUDES = [*DEFAULT_EXCLUDES, ".isucon-ready"]
KNOWN_APP_UNITS = (
    "isuride-python.service",
    "isuride-go.service",
    "isuride-ruby.service",
    "isuride-node.service",
    "isuride-perl.service",
    "isuride-php.service",
    "isuride-rust.service",
    "isucon-python.service",
    "isucon-webapp.service",
)


class DeployBlockedError(RuntimeError):
    pass


def _restart_command(restart_unit: str) -> str:
    units: list[str] = []
    for name in (restart_unit, *KNOWN_APP_UNITS):
        if name and name not in units:
            units.append(name)
    known = " ".join(shlex.quote(unit) for unit in units)
    return (
        "restarted=0; "
        f"for u in {known}; do "
        'if systemctl cat "$u" >/dev/null 2>&1; then '
        'sudo systemctl restart "$u" && echo "restarted $u" && restarted=1 && break; '
        "fi; "
        "done; "
        'if [ "$restarted" -eq 0 ]; then '
        "u=$(systemctl list-units --type=service --state=running --no-legend | "
        "awk '{print $1}' | grep -E '^(isucon|isuride|isuports|isucholar)' | "
        "grep -vE 'matcher|nginx|mysql' | head -1); "
        'if [ -n "$u" ]; then '
        'sudo systemctl restart "$u" && echo "restarted $u" && restarted=1; '
        "fi; "
        "fi; "
        'if [ "$restarted" -eq 0 ]; then '
        'echo "warning: no app systemd unit restarted" >&2; '
        "fi"
    )


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
    host = primary_host(config.hosts)

    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    if not is_ready(local_dir) and not force:
        raise DeployBlockedError(
            f"local dir が未準備です: 先に sync-down するか --force を使ってください ({local_dir})"
        )

    _create_pre_deploy_tag(local_dir)
    rsync_to_remote(
        config.ssh,
        host,
        local_dir,
        host.remote_app_dir,
        excludes=DEPLOY_EXCLUDES,
        delete=True,
    )
    run_ssh(config.ssh, host, _restart_command(restart_unit), check=False)
    health_cmd = (
        "curl -fsS http://127.0.0.1/ || curl -fsS http://127.0.0.1:8080/ || true"
    )
    run_ssh(config.ssh, host, health_cmd, check=False)
