from __future__ import annotations

import shlex
import sys
from datetime import datetime
from pathlib import Path

from isuctl.config import Host, load_config
from isuctl.hostsutil import primary_host
from isuctl.paths import out_dir
from isuctl.remote import RemoteError, rsync_file_from_remote, run_ssh

REMOTE_LOG_PATHS: list[tuple[str, str]] = [
    ("/var/log/nginx/access.ltsv.log", "access.log"),
    ("/var/log/nginx/access.log", "access.log"),
    ("/var/log/mysql/mysql-slow.log", "mysql-slow.log"),
    ("/tmp/mysql-slow.log", "mysql-slow.log"),
]


def _remote_exists(ssh, host: Host, remote_path: str) -> bool:
    quoted = shlex.quote(remote_path)
    result = run_ssh(ssh, host, f"test -e {quoted}", check=False)
    if result.returncode == 0:
        return True
    # Logs are often root-owned; probe with sudo as a fallback.
    sudo_result = run_ssh(ssh, host, f"sudo test -e {quoted}", check=False)
    return sudo_result.returncode == 0


def _pull_one(ssh, host: Host, remote_path: str, local_file: Path) -> None:
    try:
        rsync_file_from_remote(ssh, host, remote_path, local_file)
        return
    except RemoteError as exc:
        if "Permission denied" not in str(exc):
            raise
    # Fallback: copy via sudo to a readable temp path, then rsync.
    quoted = shlex.quote(remote_path)
    tmp_remote = f"/tmp/isuctl-pull-{local_file.name}"
    tmp_quoted = shlex.quote(tmp_remote)
    result = run_ssh(
        ssh,
        host,
        f"sudo cp {quoted} {tmp_quoted} && sudo chmod 644 {tmp_quoted} && sudo chown {shlex.quote(ssh.user)} {tmp_quoted}",
        check=False,
    )
    if result.returncode != 0:
        raise RemoteError(
            f"failed to copy {remote_path} via sudo: {result.stderr.strip()}"
        )
    try:
        rsync_file_from_remote(ssh, host, tmp_remote, local_file)
    finally:
        run_ssh(ssh, host, f"rm -f {tmp_quoted}", check=False)


def run_pull(config_path: Path) -> Path:
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config にホストが1つ以上必要です")

    host = primary_host(config.hosts)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_dir = out_dir() / "raw" / timestamp
    raw_dir.mkdir(parents=True, exist_ok=True)

    pulled_access = False
    pulled_slow = False
    transferred = 0
    for remote_path, local_name in REMOTE_LOG_PATHS:
        if local_name == "access.log" and pulled_access:
            continue
        if local_name == "mysql-slow.log" and pulled_slow:
            continue
        if not _remote_exists(config.ssh, host, remote_path):
            continue
        local_file = raw_dir / local_name
        _pull_one(config.ssh, host, remote_path, local_file)
        transferred += 1
        if local_name == "access.log":
            pulled_access = True
        if local_name == "mysql-slow.log":
            pulled_slow = True

    if transferred == 0:
        print(
            "警告: リモートにログが見つかりません。取得ファイル数は 0 です",
            file=sys.stderr,
        )
        raise ValueError(
            "ログを1つも取得できませんでした。リモートのパスと権限を確認してください"
        )

    return raw_dir
