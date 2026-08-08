from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.snapshot import run_snapshot


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


def test_run_snapshot_creates_remote_tarball(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    ssh_calls: list[str] = []

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.snapshot.run_ssh", side_effect=fake_ssh),
        patch("isuctl.snapshot.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        remote_path = run_snapshot(cfg_path)

    assert remote_path == "/home/isucon/snapshots/snap-20260809-120000.tar.gz"
    assert len(ssh_calls) == 1
    cmd = ssh_calls[0]
    assert "tar" in cmd
    assert "/home/isucon/snapshots" in cmd
    assert "home/isucon/webapp" in cmd
    assert "/etc/nginx" in cmd


def test_run_snapshot_with_label(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with (
        patch("isuctl.snapshot.run_ssh"),
        patch("isuctl.snapshot.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        remote_path = run_snapshot(cfg_path, label="pre-deploy")

    assert remote_path == "/home/isucon/snapshots/snap-20260809-120000-pre-deploy.tar.gz"


def test_run_snapshot_picks_first_app_host(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        hosts=[
            Host(name="db1", host="10.0.0.2", role=["db"]),
            Host(name="app1", host="10.0.0.1", role=["app"]),
        ],
    )
    seen_hosts: list[str] = []

    def fake_ssh(ssh, host, cmd, check=True):
        seen_hosts.append(host.host)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.snapshot.run_ssh", side_effect=fake_ssh),
        patch("isuctl.snapshot.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        run_snapshot(cfg_path)

    assert seen_hosts == ["10.0.0.1"]


def test_run_snapshot_requires_hosts(tmp_path: Path):
    cfg_path = _write_config(tmp_path, hosts=[])
    with pytest.raises(ValueError, match="ホストが1つ以上"):
        run_snapshot(cfg_path)


def test_cli_snapshot_command(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with (
        patch("isuctl.cli.run_snapshot") as run_snapshot_mock,
    ):
        run_snapshot_mock.return_value = "/home/isucon/snapshots/snap-20260809-120000.tar.gz"
        result = CliRunner().invoke(app, ["snapshot", "--config", str(cfg_path)])

    assert result.exit_code == 0
    run_snapshot_mock.assert_called_once_with(cfg_path, label=None)
    assert "/home/isucon/snapshots/snap-20260809-120000.tar.gz" in result.stdout
