from __future__ import annotations

from pathlib import Path

from isuctl.config import Host, IsuconConfig, SshConfig, load_config, save_config
from isuctl.remote import run_ssh

PROBE_COMMAND = """set -e
APP_DIR=""
for d in /home/isucon/webapp /home/isucon/isunum /home/isucon; do
  if [ -d "$d" ]; then APP_DIR="$d"; break; fi
done
printf '%s\\n' "$APP_DIR"
nginx_status=$(systemctl is-active nginx 2>/dev/null || true)
printf '%s\\n' "${nginx_status:-inactive}"
mysql_status=$(systemctl is-active mysql 2>/dev/null || systemctl is-active mysqld 2>/dev/null || true)
printf '%s\\n' "${mysql_status:-inactive}"
"""


def discover_host(ssh: SshConfig, host: Host) -> dict[str, object]:
    result = run_ssh(ssh, host, PROBE_COMMAND)
    lines = result.stdout.rstrip().splitlines()
    app_dir = lines[0].strip() if len(lines) > 0 else ""
    nginx_status = lines[1].strip() if len(lines) > 1 else "inactive"
    mysql_status = lines[2].strip() if len(lines) > 2 else "inactive"

    roles: list[str] = []
    if app_dir.startswith("/"):
        roles.append("app")
    if nginx_status == "active":
        roles.append("web")
    if mysql_status == "active":
        roles.append("db")

    updates: dict[str, object] = {"role": roles}
    if app_dir.startswith("/"):
        updates["remote_app_dir"] = app_dir
    return updates


def run_discover(config_path: Path) -> IsuconConfig:
    config = load_config(config_path)
    for host in config.hosts:
        updates = discover_host(config.ssh, host)
        if "remote_app_dir" in updates:
            host.remote_app_dir = str(updates["remote_app_dir"])
        host.role = list(updates["role"])
    save_config(config_path, config)
    return config
