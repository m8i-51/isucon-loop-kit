from __future__ import annotations

import shlex
from pathlib import Path

from isuctl.config import SshConfig, load_config
from isuctl.hostsutil import primary_host
from isuctl.remote import run_ssh


def run_ensure_access(config_path: Path) -> None:
    """bootstrap_user の authorized_keys を競技ユーザーへコピーする。

    典型的な AMI では ubuntu で入れるが、isucon には鍵がまだない。
    """
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config にホストが1つ以上必要です")

    host = primary_host(config.hosts)
    contest_user = config.ssh.user
    bootstrap_user = config.ssh.bootstrap_user
    if not bootstrap_user or bootstrap_user == contest_user:
        print(
            "ensure-access: bootstrap_user 未設定、または user と同じです。"
            ' 何もしません（[ssh].bootstrap_user = "ubuntu" を設定）'
        )
        return

    bootstrap_ssh = SshConfig(user=bootstrap_user, key=config.ssh.key)
    contest_home = f"/home/{contest_user}"
    bootstrap_home = f"/home/{bootstrap_user}"
    cmd = (
        f"sudo mkdir -p {shlex.quote(contest_home + '/.ssh')} && "
        f"sudo cp {shlex.quote(bootstrap_home + '/.ssh/authorized_keys')} "
        f"{shlex.quote(contest_home + '/.ssh/authorized_keys')} && "
        f"sudo chown -R {shlex.quote(contest_user + ':' + contest_user)} "
        f"{shlex.quote(contest_home + '/.ssh')} && "
        f"sudo chmod 700 {shlex.quote(contest_home + '/.ssh')} && "
        f"sudo chmod 600 {shlex.quote(contest_home + '/.ssh/authorized_keys')}"
    )
    run_ssh(bootstrap_ssh, host, cmd, check=True)

    probe = run_ssh(config.ssh, host, "true", check=False)
    if probe.returncode != 0:
        raise RuntimeError(
            f"ensure-access: 鍵はコピーしたが {contest_user}@{host.host} への SSH が失敗"
        )
    print(f"ensure-access: {contest_user}@{host.host} に接続できます")
