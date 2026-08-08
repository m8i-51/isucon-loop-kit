from __future__ import annotations

import shlex
from pathlib import Path

from isuctl.config import Host, SshConfig, load_config, save_config
from isuctl.hostsutil import primary_host
from isuctl.remote import run_ssh


def run_ensure_access(config_path: Path) -> None:
    """Copy SSH authorized_keys from bootstrap_user to contest user (isucon).

    Typical AMI flow: login works as ubuntu, but isucon has no key yet.
    """
    config = load_config(config_path)
    if not config.hosts:
        raise ValueError("config must have at least one host")

    host = primary_host(config.hosts)
    contest_user = config.ssh.user
    bootstrap_user = config.ssh.bootstrap_user
    if not bootstrap_user or bootstrap_user == contest_user:
        print(
            "ensure-access: bootstrap_user unset or same as user; "
            "nothing to do (set [ssh].bootstrap_user = \"ubuntu\")"
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

    # Verify contest user SSH works with the same key.
    probe = run_ssh(config.ssh, host, "true", check=False)
    if probe.returncode != 0:
        raise RuntimeError(
            f"ensure-access copied keys but {contest_user}@{host.host} still fails SSH"
        )
    print(f"ensure-access: {contest_user}@{host.host} is reachable")
