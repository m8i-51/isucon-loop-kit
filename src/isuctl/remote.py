from __future__ import annotations

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
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"ssh failed: {cmd}")
    return result


def _rsync(ssh: SshConfig, source: str, dest: str, excludes: list[str] | None) -> None:
    key = str(Path(ssh.key).expanduser())
    cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -i {key} -o StrictHostKeyChecking=accept-new -o BatchMode=yes",
    ]
    for ex in excludes or []:
        cmd.extend(["--exclude", ex])
    cmd.extend([source, dest])
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"rsync failed: {cmd}")


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
) -> None:
    source = str(local_path).rstrip("/") + "/"
    dest = f"{ssh.user}@{host.host}:{remote_path.rstrip('/')}/"
    _rsync(ssh, source, dest, excludes)
