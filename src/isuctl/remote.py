from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from isuctl.config import Host, SshConfig


class RemoteError(RuntimeError):
    pass


def ssh_base_args(ssh: SshConfig) -> list[str]:
    key = str(Path(ssh.key).expanduser())
    return [
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]


def run_ssh(
    ssh: SshConfig,
    host: Host,
    remote_command: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ssh",
        *ssh_base_args(ssh),
        f"{ssh.user}@{host.host}",
        remote_command,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"ssh failed: {cmd}")
    return result


def _rsync(
    ssh: SshConfig,
    source: str,
    dest: str,
    excludes: list[str] | None,
    *,
    delete: bool = False,
) -> None:
    ssh_cmd = "ssh " + " ".join(shlex.quote(part) for part in ssh_base_args(ssh))
    cmd = [
        "rsync",
        "-az",
        "-e",
        ssh_cmd,
    ]
    if delete:
        cmd.append("--delete")
    for ex in excludes or []:
        cmd.extend(["--exclude", ex])
    cmd.extend([source, dest])
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"rsync failed: {cmd}")


def rsync_file_from_remote(
    ssh: SshConfig,
    host: Host,
    remote_file: str,
    local_file: Path,
) -> None:
    local_file.parent.mkdir(parents=True, exist_ok=True)
    source = f"{ssh.user}@{host.host}:{remote_file}"
    _rsync(ssh, source, str(local_file), None)


def rsync_file_to_remote(
    ssh: SshConfig,
    host: Host,
    local_file: Path,
    remote_file: str,
) -> None:
    dest = f"{ssh.user}@{host.host}:{remote_file}"
    _rsync(ssh, str(local_file), dest, None)


def rsync_from_remote(
    ssh: SshConfig,
    host: Host,
    remote_path: str,
    local_path: Path,
    *,
    excludes: list[str] | None = None,
) -> None:
    local_path.mkdir(parents=True, exist_ok=True)
    source = f"{ssh.user}@{host.host}:{remote_path.rstrip('/')}/"
    _rsync(ssh, source, str(local_path) + "/", excludes)


def rsync_to_remote(
    ssh: SshConfig,
    host: Host,
    local_path: Path,
    remote_path: str,
    *,
    excludes: list[str] | None = None,
    delete: bool = False,
) -> None:
    source = str(local_path).rstrip("/") + "/"
    dest = f"{ssh.user}@{host.host}:{remote_path.rstrip('/')}/"
    _rsync(ssh, source, dest, excludes, delete=delete)
