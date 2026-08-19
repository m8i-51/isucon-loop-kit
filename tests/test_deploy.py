from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.deploy import DEPLOY_EXCLUDES, DeployBlockedError, run_deploy
from isuctl.paths import mark_ready
from isuctl.sync_down import DEFAULT_EXCLUDES


def _write_config(tmp_path: Path, *, hosts: list[Host], local_dir: str = "./work") -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir=local_dir),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            hosts=hosts,
        ),
    )
    return cfg_path


def test_deploy_blocked_without_ready(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    with pytest.raises(DeployBlockedError):
        run_deploy(cfg_path)


def test_deploy_runs_when_ready(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    local_dir = (tmp_path / "work").resolve()
    mark_ready(local_dir)
    rsync_calls: list[tuple] = []
    ssh_calls: list[str] = []

    def fake_rsync(ssh, host, local_path, remote_path, *, excludes=None, delete=False):
        rsync_calls.append((host.host, local_path, remote_path, excludes, delete))

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.deploy.rsync_to_remote", side_effect=fake_rsync),
        patch("isuctl.deploy.run_ssh", side_effect=fake_ssh),
        patch("isuctl.deploy._create_pre_deploy_tag"),
    ):
        run_deploy(cfg_path)

    assert len(rsync_calls) == 1
    host, path, remote_path, excludes, delete = rsync_calls[0]
    assert host == "10.0.0.1"
    assert path == local_dir
    assert remote_path == "/home/isucon/webapp"
    assert excludes == DEPLOY_EXCLUDES
    assert delete is True
    assert ".isucon-ready" in excludes
    assert DEFAULT_EXCLUDES == excludes[:-1]
    assert "systemctl restart" in ssh_calls[0]
    assert "isucon-python.service" in ssh_calls[0]
    assert "isuride-python.service" in ssh_calls[0]
    assert "curl -fsS http://127.0.0.1/" in ssh_calls[1]


def test_deploy_force_bypasses_ready_guard(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    with (
        patch("isuctl.deploy.rsync_to_remote"),
        patch("isuctl.deploy.run_ssh"),
        patch("isuctl.deploy._create_pre_deploy_tag"),
    ):
        run_deploy(cfg_path, force=True)


def test_deploy_picks_first_app_host(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[
            Host(name="db1", host="10.0.0.2", role=["db"]),
            Host(name="app1", host="10.0.0.1", role=["app"]),
        ],
    )
    mark_ready(tmp_path / "work")
    seen_hosts: list[str] = []

    def fake_rsync(ssh, host, local_path, remote_path, *, excludes=None, delete=False):
        seen_hosts.append(host.host)

    with (
        patch("isuctl.deploy.rsync_to_remote", side_effect=fake_rsync),
        patch("isuctl.deploy.run_ssh"),
        patch("isuctl.deploy._create_pre_deploy_tag"),
    ):
        run_deploy(cfg_path)

    assert seen_hosts == ["10.0.0.1"]


def test_deploy_creates_pre_deploy_tag(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    local_dir = tmp_path / "work"
    local_dir.mkdir()
    mark_ready(local_dir)
    (local_dir / ".git").mkdir()
    tag_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        tag_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("isuctl.deploy.rsync_to_remote"),
        patch("isuctl.deploy.run_ssh"),
        patch("isuctl.deploy.subprocess.run", side_effect=fake_run),
        patch("isuctl.deploy.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-120000"
        run_deploy(cfg_path)

    assert tag_calls
    assert tag_calls[0][:3] == ["git", "-C", str(local_dir.resolve())]
    assert tag_calls[0][3] == "tag"
    assert tag_calls[0][4] == "pre-deploy-20260809-120000"


def test_deploy_requires_hosts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path, hosts=[])
    mark_ready(tmp_path / "work")
    with pytest.raises(ValueError, match="ホストが1つ以上"):
        run_deploy(cfg_path)


def test_deploy_custom_restart_unit(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    mark_ready(tmp_path / "work")
    ssh_calls: list[str] = []

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.deploy.rsync_to_remote"),
        patch("isuctl.deploy.run_ssh", side_effect=fake_ssh),
        patch("isuctl.deploy._create_pre_deploy_tag"),
    ):
        run_deploy(cfg_path, restart_unit="myapp.service")

    assert "myapp.service" in ssh_calls[0]
    assert "systemctl restart" in ssh_calls[0]


def test_cli_deploy_command(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_deploy") as run_deploy_mock:
        result = CliRunner().invoke(app, ["deploy", "--config", str(cfg_path)])

    assert result.exit_code == 0
    run_deploy_mock.assert_called_once_with(cfg_path, force=False)


def test_cli_deploy_force_flag(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_deploy") as run_deploy_mock:
        result = CliRunner().invoke(app, ["deploy", "--config", str(cfg_path), "--force"])

    assert result.exit_code == 0
    run_deploy_mock.assert_called_once_with(cfg_path, force=True)
