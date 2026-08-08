from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, SshConfig
from isuctl.remote import RemoteError, rsync_from_remote, rsync_to_remote, run_ssh, ssh_base_args


def test_ssh_base_args_expands_identity():
    args = ssh_base_args(SshConfig(user="isucon", key="~/.ssh/id_ed25519"))
    assert "-i" in args
    i = args.index("-i")
    assert not args[i + 1].startswith("~")


def test_run_ssh_success():
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        result = run_ssh(ssh, host, "true")
        assert result.returncode == 0
        assert result.stdout == "ok"
        run.assert_called_once()
        cmd = run.call_args[0][0]
        assert cmd[0] == "ssh"
        assert "isucon@10.0.0.1" in cmd
        assert cmd[-1] == "true"


def test_run_ssh_raises_on_failure():
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        with pytest.raises(RemoteError, match="boom"):
            run_ssh(ssh, host, "true")


def test_run_ssh_no_check_on_failure():
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        result = run_ssh(ssh, host, "true", check=False)
        assert result.returncode == 1


def test_rsync_from_remote(tmp_path: Path):
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    local = tmp_path / "work"
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        rsync_from_remote(ssh, host, "/home/isucon/webapp", local)
        cmd = run.call_args[0][0]
        assert cmd[0] == "rsync"
        assert "isucon@10.0.0.1:/home/isucon/webapp/" in cmd
        assert str(local) + "/" in cmd


def test_rsync_to_remote(tmp_path: Path):
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    local = tmp_path / "work"
    local.mkdir()
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        rsync_to_remote(ssh, host, local, "/home/isucon/webapp")
        cmd = run.call_args[0][0]
        assert cmd[0] == "rsync"
        assert str(local) + "/" in cmd
        assert "isucon@10.0.0.1:/home/isucon/webapp/" in cmd


def test_rsync_excludes(tmp_path: Path):
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    local = tmp_path / "work"
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        rsync_to_remote(ssh, host, local, "/remote", excludes=["node_modules", ".git"])
        cmd = run.call_args[0][0]
        assert "--exclude" in cmd
        assert "node_modules" in cmd
        assert ".git" in cmd


def test_rsync_raises_on_failure(tmp_path: Path):
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    local = tmp_path / "work"
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "rsync fail"})()
        with pytest.raises(RemoteError, match="rsync fail"):
            rsync_from_remote(ssh, host, "/remote", local)
