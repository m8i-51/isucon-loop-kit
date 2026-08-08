from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.cli import app
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.pull import run_pull


def _write_config(tmp_path: Path, *, hosts: list[Host]) -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            hosts=hosts,
        ),
    )
    return cfg_path


def test_run_pull_copies_existing_logs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app", "web", "db"])],
    )
    exists_checks: list[str] = []
    rsync_calls: list[tuple[str, Path]] = []

    def fake_ssh(ssh, host, cmd, check=True):
        exists_checks.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        if "test -e" in cmd and "/tmp/mysql-slow.log" in cmd:
            R.returncode = 1
        return R()

    def fake_rsync(ssh, host, remote_file, local_file):
        rsync_calls.append((remote_file, local_file))
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text(f"content from {remote_file}", encoding="utf-8")

    with (
        patch("isuctl.pull.run_ssh", side_effect=fake_ssh),
        patch("isuctl.pull.rsync_file_from_remote", side_effect=fake_rsync),
        patch("isuctl.pull.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        raw_dir = run_pull(cfg_path)

    assert raw_dir == tmp_path / "out" / "raw" / "20260809-120000"
    assert (raw_dir / "access.log").exists()
    assert (raw_dir / "mysql-slow.log").exists()
    remote_paths = [r for r, _ in rsync_calls]
    assert "/var/log/nginx/access.ltsv.log" in remote_paths
    assert "/var/log/nginx/access.log" not in remote_paths
    assert "/var/log/mysql/mysql-slow.log" in remote_paths
    assert "/tmp/mysql-slow.log" not in remote_paths


def test_run_pull_requires_hosts(tmp_path: Path):
    cfg_path = _write_config(tmp_path, hosts=[])
    with pytest.raises(ValueError, match="at least one host"):
        run_pull(cfg_path)


def test_run_pull_raises_when_no_logs_found(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.pull.run_ssh", side_effect=fake_ssh),
        patch("isuctl.pull.rsync_file_from_remote") as rsync_mock,
        patch("isuctl.pull.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        with pytest.raises(ValueError, match="no log files transferred"):
            run_pull(cfg_path)

    rsync_mock.assert_not_called()
    captured = capsys.readouterr()
    assert "warning: no log files found" in captured.err


def test_cli_pull_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_pull") as run_pull_mock:
        run_pull_mock.return_value = tmp_path / "out" / "raw" / "20260809-120000"
        result = CliRunner().invoke(app, ["pull", "--config", str(cfg_path)])

    assert result.exit_code == 0
    run_pull_mock.assert_called_once_with(cfg_path)
    assert "pulled to" in result.stdout


def test_run_pull_falls_back_to_sudo_copy_on_permission_denied(
    tmp_path: Path, monkeypatch
):
    from isuctl.remote import RemoteError

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    rsync_calls: list[str] = []
    ssh_cmds: list[str] = []

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_cmds.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        # Prefer ltsv exists; skip slow logs for this test.
        if "test -e" in cmd and "mysql-slow" in cmd:
            R.returncode = 1
        if "test -e" in cmd and "access.log" in cmd and "ltsv" not in cmd:
            R.returncode = 1
        return R()

    def fake_rsync(ssh, host, remote_file, local_file):
        rsync_calls.append(remote_file)
        if remote_file.startswith("/var/log/"):
            raise RemoteError("Permission denied (13)")
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text("ok", encoding="utf-8")

    with (
        patch("isuctl.pull.run_ssh", side_effect=fake_ssh),
        patch("isuctl.pull.rsync_file_from_remote", side_effect=fake_rsync),
        patch("isuctl.pull.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-130000"
        raw_dir = run_pull(cfg_path)

    assert (raw_dir / "access.log").read_text(encoding="utf-8") == "ok"
    assert any("sudo cp" in cmd for cmd in ssh_cmds)
    assert any(p.startswith("/tmp/isuctl-pull-") for p in rsync_calls)
