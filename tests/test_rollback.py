from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.deploy import DeployBlockedError
from isuctl.paths import mark_ready
from isuctl.rollback import run_rollback


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


def test_rollback_blocked_without_ready(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    with pytest.raises(DeployBlockedError):
        run_rollback(cfg_path)


def test_rollback_resets_and_deploys(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    local_dir = (tmp_path / "work").resolve()
    mark_ready(local_dir)
    git_calls: list[list[str]] = []
    deploy_calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        git_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_deploy(config_path, *, force=False, restart_unit="isucon-python.service"):
        deploy_calls.append((config_path, force, restart_unit))

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy", side_effect=fake_deploy),
    ):
        run_rollback(cfg_path, git_ref="HEAD~1")

    assert git_calls
    assert git_calls[0][:3] == ["git", "-C", str(local_dir)]
    assert git_calls[0][3:] == ["reset", "--hard", "HEAD~1"]
    assert deploy_calls == [(cfg_path, True, "isucon-python.service")]


def test_rollback_requires_hosts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path, hosts=[])
    mark_ready(tmp_path / "work")
    git_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        git_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy"),
    ):
        with pytest.raises(ValueError, match="ホストが1つ以上"):
            run_rollback(cfg_path)

    assert git_calls == []


def test_rollback_force_bypasses_ready_guard(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    with (
        patch("isuctl.rollback.subprocess.run"),
        patch("isuctl.rollback.run_deploy"),
    ):
        run_rollback(cfg_path, force=True)


def test_rollback_custom_git_ref(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    mark_ready(tmp_path / "work")
    git_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        git_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy"),
    ):
        run_rollback(cfg_path, git_ref="abc1234")

    assert git_calls[0][-1] == "abc1234"


def test_cli_rollback_command(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_rollback") as run_rollback_mock:
        result = CliRunner().invoke(
            app, ["rollback", "--config", str(cfg_path), "--ref", "HEAD~2"]
        )

    assert result.exit_code == 0
    run_rollback_mock.assert_called_once_with(cfg_path, git_ref="HEAD~2", force=False)


def test_cli_rollback_force_flag(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_rollback") as run_rollback_mock:
        result = CliRunner().invoke(app, ["rollback", "--config", str(cfg_path), "--force"])

    assert result.exit_code == 0
    run_rollback_mock.assert_called_once_with(cfg_path, git_ref="HEAD~1", force=True)
