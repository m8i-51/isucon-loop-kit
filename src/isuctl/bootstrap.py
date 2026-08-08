from __future__ import annotations

import importlib.resources
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.hostsutil import primary_host
from isuctl.remote import rsync_file_to_remote, run_ssh

REMOTE_ISUCTL_DIR = "/home/isucon/isuctl"
NGINX_REMOTE_SNIPPET = f"{REMOTE_ISUCTL_DIR}/nginx_ltsv.conf"
MYSQL_REMOTE_SNIPPET = f"{REMOTE_ISUCTL_DIR}/mysql_slow.cnf"
NGINX_SYSTEM_PATH = "/etc/nginx/conf.d/isuctl_ltsv.conf"
MYSQL_SYSTEM_PATH = "/etc/mysql/conf.d/isuctl_slow.cnf"
ALP_VERSION = "1.0.21"
ALP_INSTALL_DIR = "/home/isucon/local/bin"
ACCESS_LTSV_LOG = "/var/log/nginx/access.ltsv.log"
ACCESS_LOG = "/var/log/nginx/access.log"
SLOW_LOG = "/var/log/mysql/mysql-slow.log"


def template_path(name: str) -> Path:
    root = importlib.resources.files("isuctl")
    return Path(str(root / "templates" / name))


def _ensure_remote_dirs(ssh, host: Host) -> None:
    cmd = (
        f"mkdir -p {REMOTE_ISUCTL_DIR} && "
        "(sudo mkdir -p /var/log/nginx /var/log/mysql || mkdir -p /var/log/nginx /var/log/mysql || true)"
    )
    run_ssh(ssh, host, cmd, check=False)


def _upload_snippets(ssh, host: Host) -> None:
    rsync_file_to_remote(
        ssh, host, template_path("nginx_ltsv.conf"), NGINX_REMOTE_SNIPPET
    )
    rsync_file_to_remote(
        ssh, host, template_path("mysql_slow.cnf"), MYSQL_REMOTE_SNIPPET
    )


def _print_include_instructions() -> None:
    print(
        f"MySQL slow query snippet uploaded to {MYSQL_REMOTE_SNIPPET}.\n"
        f"Nginx LTSV access log target: {ACCESS_LTSV_LOG}"
    )


def _deploy_system_configs(ssh, host: Host) -> None:
    nginx_cmd = (
        f"sudo cp {NGINX_REMOTE_SNIPPET} {NGINX_SYSTEM_PATH} && "
        f"sudo touch {ACCESS_LTSV_LOG} && "
        "(sudo nginx -t && sudo systemctl reload nginx || true)"
    )
    mysql_cmd = (
        f"sudo cp {MYSQL_REMOTE_SNIPPET} {MYSQL_SYSTEM_PATH} && "
        "(sudo systemctl restart mysql || sudo systemctl restart mysqld || true) && "
        f"(sudo touch {SLOW_LOG} || true)"
    )
    run_ssh(ssh, host, nginx_cmd, check=False)
    run_ssh(ssh, host, mysql_cmd, check=False)


def _fix_log_permissions(ssh, host: Host) -> None:
    cmd = (
        f"sudo chmod 755 /var/log/nginx /var/log/mysql 2>/dev/null || true; "
        f"sudo touch {ACCESS_LTSV_LOG} {ACCESS_LOG} {SLOW_LOG} 2>/dev/null || true; "
        f"sudo chmod 644 {ACCESS_LTSV_LOG} {ACCESS_LOG} {SLOW_LOG} 2>/dev/null || true"
    )
    run_ssh(ssh, host, cmd, check=False)


def _install_alp(ssh, host: Host) -> None:
    cmd = (
        f"if command -v alp >/dev/null 2>&1 || [ -x {ALP_INSTALL_DIR}/alp ]; then exit 0; fi; "
        "ARCH=$(uname -m); "
        "case \"$ARCH\" in "
        "x86_64) ALP_ARCH=amd64 ;; "
        "aarch64|arm64) ALP_ARCH=arm64 ;; "
        "*) echo \"bootstrap: unsupported arch for alp: $ARCH\"; exit 0 ;; "
        "esac; "
        f"URL=\"https://github.com/tkuchiki/alp/releases/download/v{ALP_VERSION}/alp_linux_${{ALP_ARCH}}.tar.gz\"; "
        "TMP=$(mktemp -d); "
        "if curl -fsSL \"$URL\" -o \"$TMP/alp.tar.gz\"; then "
        f"mkdir -p {ALP_INSTALL_DIR} && "
        "tar xzf \"$TMP/alp.tar.gz\" -C \"$TMP\" && "
        f"install \"$TMP/alp\" {ALP_INSTALL_DIR}/alp; "
        "else "
        f"echo \"bootstrap: failed to download alp from $URL\"; "
        "fi; "
        "rm -rf \"$TMP\""
    )
    run_ssh(ssh, host, cmd, check=False)


def run_bootstrap(config_path: Path) -> None:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config must have at least one host")

    host = primary_host(config.hosts)
    _ensure_remote_dirs(config.ssh, host)
    _upload_snippets(config.ssh, host)
    _print_include_instructions()
    _deploy_system_configs(config.ssh, host)
    _fix_log_permissions(config.ssh, host)
    _install_alp(config.ssh, host)
