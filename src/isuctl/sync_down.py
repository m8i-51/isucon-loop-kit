from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.paths import mark_ready
from isuctl.remote import rsync_file_from_remote, rsync_from_remote, run_ssh

DEFAULT_EXCLUDES = [
    ".git",
    "__pycache__",
    "node_modules",
    "vendor",
    "*.log",
    ".venv",
    "venv",
    "tmp",
]


def _primary_host(hosts: list[Host]) -> Host:
    for host in hosts:
        if "app" in host.role:
            return host
    return hosts[0]


def _remote_exists(ssh, host: Host, remote_path: str) -> bool:
    result = run_ssh(ssh, host, f"test -e {shlex.quote(remote_path)}", check=False)
    return result.returncode == 0


def _rsync_optional_file(ssh, host: Host, remote_path: str, local_file: Path) -> None:
    rsync_file_from_remote(ssh, host, remote_path, local_file)


def _rsync_optional_dir(
    ssh,
    host: Host,
    remote_path: str,
    local_dir: Path,
) -> None:
    rsync_from_remote(ssh, host, remote_path, local_dir, excludes=DEFAULT_EXCLUDES)


def _ensure_git_repo(local_dir: Path) -> None:
    if (local_dir / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=local_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "-A"], cwd=local_dir, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=isucon@localhost",
            "-c",
            "user.name=isucon",
            "commit",
            "-m",
            "Initial sync from remote",
        ],
        cwd=local_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def _sync_optional_paths(ssh, host: Host, local_dir: Path) -> None:
    if _remote_exists(ssh, host, "/home/isucon/env.sh"):
        _rsync_optional_file(ssh, host, "/home/isucon/env.sh", local_dir.parent / "env.sh")

    sql_remote = f"{host.remote_app_dir.rstrip('/')}/sql"
    if _remote_exists(ssh, host, sql_remote):
        _rsync_optional_dir(ssh, host, sql_remote, local_dir / "sql")
        return

    schema_remote = f"{host.remote_app_dir.rstrip('/')}/schema.sql"
    if _remote_exists(ssh, host, schema_remote):
        _rsync_optional_file(ssh, host, schema_remote, local_dir / "schema.sql")


def run_sync_down(config_path: Path) -> Path:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config must have at least one host")

    host = _primary_host(config.hosts)
    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    rsync_from_remote(
        config.ssh,
        host,
        host.remote_app_dir,
        local_dir,
        excludes=DEFAULT_EXCLUDES,
    )
    _sync_optional_paths(config.ssh, host, local_dir)
    mark_ready(local_dir)
    _ensure_git_repo(local_dir)
    return local_dir
