from __future__ import annotations

from pathlib import Path

from isuctl.config import Host, IsuconConfig, SshConfig, load_config, save_config
from isuctl.remote import run_ssh


def _status_at(lines: list[str], index: int) -> str:
    if len(lines) <= index:
        return "inactive"
    return lines[index].strip() or "inactive"


PROBE_COMMAND = """set -e
APP_DIR=""
for d in /home/isucon/webapp /home/isucon/isunum /home/isucon; do
  if [ -d "$d" ]; then APP_DIR="$d"; break; fi
done
printf '%s\\n' "$APP_DIR"
nginx_status=$(systemctl is-active nginx 2>/dev/null || true)
printf '%s\\n' "${nginx_status:-inactive}"
mysql_status=$(systemctl is-active mysql 2>/dev/null || true)
if [ "$mysql_status" != "active" ]; then
  mysqld_status=$(systemctl is-active mysqld 2>/dev/null || true)
  if [ "$mysqld_status" = "active" ]; then mysql_status=active; fi
fi
printf '%s\\n' "${mysql_status:-inactive}"
apache_status=$(systemctl is-active apache2 2>/dev/null || true)
if [ "$apache_status" != "active" ]; then
  httpd_status=$(systemctl is-active httpd 2>/dev/null || true)
  if [ "$httpd_status" = "active" ]; then apache_status=active; fi
fi
printf '%s\\n' "${apache_status:-inactive}"
postgres_status=$(systemctl is-active postgresql 2>/dev/null || true)
if [ "$postgres_status" != "active" ]; then
  if systemctl list-units --no-pager --type=service --state=active --no-legend 'postgresql@*' 2>/dev/null | grep -q .; then
    postgres_status=active
  fi
fi
printf '%s\\n' "${postgres_status:-inactive}"
"""


def discover_host(ssh: SshConfig, host: Host) -> dict[str, object]:
    result = run_ssh(ssh, host, PROBE_COMMAND)
    lines = result.stdout.rstrip().splitlines()
    app_dir = lines[0].strip() if len(lines) > 0 else ""
    nginx_status = _status_at(lines, 1)
    mysql_status = _status_at(lines, 2)
    apache_status = _status_at(lines, 3)
    postgres_status = _status_at(lines, 4)

    roles: list[str] = []
    if app_dir.startswith("/"):
        roles.append("app")
    if nginx_status == "active" or apache_status == "active":
        roles.append("web")
    if mysql_status == "active" or postgres_status == "active":
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
