from __future__ import annotations

from pathlib import Path

from isuctl.compose_transport import discover_compose
from isuctl.config import (
    Host,
    IsuconConfig,
    SshConfig,
    load_config,
    save_config,
    uses_compose,
)
from isuctl.probe import interpret_probe_stdout
from isuctl.remote import run_ssh

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
    return interpret_probe_stdout(result.stdout)


def run_discover(config_path: Path) -> IsuconConfig:
    config = load_config(config_path)
    if uses_compose(config):
        return discover_compose(config_path)
    for host in config.hosts:
        updates = discover_host(config.ssh, host)
        if "remote_app_dir" in updates:
            host.remote_app_dir = str(updates["remote_app_dir"])
        host.role = list(updates["role"])
    save_config(config_path, config)
    return config
