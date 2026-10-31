import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.cli import app
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.deploy import DeployBlockedError
from isuctl.paths import mark_ready
from isuctl.rollback import run_rollback


def _write_config(tmp_path: Path, *, hosts=None, local_dir: str = "./work") -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir=local_dir),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            hosts=hosts or [Host(name="app1", host="10.0.0.1", role=["app"])],
        ),
    )
    return cfg_path


def _git_ready(tmp_path: Path) -> Path:
    local_dir = tmp_path / "work"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / ".git").mkdir()
    mark_ready(local_dir)
    return local_dir


def test_rollback_blocked_without_ready(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    with pytest.raises(DeployBlockedError):
        run_rollback(cfg_path)


def test_rollback_resets_and_deploys(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    _git_ready(tmp_path)
    calls: list[list[str]] = []
    deploy_calls: list[tuple] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stdout = "abcdead\n" if "rev-parse" in cmd else ""
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    def fake_deploy(config_path, *, branch, limit=None, force=False, restart_unit=None):
        deploy_calls.append((config_path, branch, limit, force))

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy", side_effect=fake_deploy),
    ):
        run_rollback(cfg_path, git_ref="HEAD~1")

    work = str((tmp_path / "work").resolve())
    assert any(cmd[:4] == ["git", "-C", work, "reset"] for cmd in calls)
    assert deploy_calls == [(cfg_path, "abcdead", None, True)]


def test_rollback_force_bypasses_ready_guard(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    local_dir = tmp_path / "work"
    local_dir.mkdir()
    (local_dir / ".git").mkdir()

    def fake_run(cmd, **kwargs):
        stdout = "deadbeef\n" if "rev-parse" in cmd else ""
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy") as deploy_mock,
    ):
        run_rollback(cfg_path, force=True)
    deploy_mock.assert_called_once()


def test_rollback_force_skips_dirty_probe(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    _git_ready(tmp_path)
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        stdout = "abc1234\n" if "rev-parse" in cmd else ""
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy"),
    ):
        run_rollback(cfg_path, force=True)
    assert not any("status" in cmd for cmd in seen)


def test_rollback_custom_git_ref(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    _git_ready(tmp_path)
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        stdout = "abc1234\n" if "rev-parse" in cmd else ""
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy"),
    ):
        run_rollback(cfg_path, git_ref="abc1234")
    assert any("abc1234" in cmd for cmd in seen if cmd[3] == "reset")


def test_rollback_blocked_when_worktree_dirty(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    _git_ready(tmp_path)

    def fake_run(cmd, **kwargs):
        if "status" in cmd:
            return type(
                "R", (), {"returncode": 0, "stdout": " M app.py\n", "stderr": ""}
            )()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy") as deploy_mock,
        pytest.raises(DeployBlockedError, match="未コミット"),
    ):
        run_rollback(cfg_path)
    deploy_mock.assert_not_called()


def test_rollback_missing_git_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    local_dir = tmp_path / "work"
    local_dir.mkdir()
    mark_ready(local_dir)
    with pytest.raises(DeployBlockedError, match="git リポジトリではありません"):
        run_rollback(cfg_path, force=True)


def test_rollback_wraps_git_failure(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    _git_ready(tmp_path)

    def fake_run(cmd, **kwargs):
        if "reset" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="unknown revision")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with (
        patch("isuctl.rollback.subprocess.run", side_effect=fake_run),
        patch("isuctl.rollback.run_deploy") as deploy_mock,
        pytest.raises(DeployBlockedError, match="unknown revision"),
    ):
        run_rollback(cfg_path)
    deploy_mock.assert_not_called()


def test_cli_rollback_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    with patch("isuctl.cli.run_rollback") as run_rollback_mock:
        result = CliRunner().invoke(
            app, ["rollback", "--config", str(cfg_path), "--ref", "HEAD~2"]
        )
    assert result.exit_code == 0
    run_rollback_mock.assert_called_once_with(
        cfg_path, git_ref="HEAD~2", force=False, limit=None
    )


def test_cli_rollback_force_flag(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path)
    with patch("isuctl.cli.run_rollback") as run_rollback_mock:
        result = CliRunner().invoke(
            app, ["rollback", "--config", str(cfg_path), "--force"]
        )
    assert result.exit_code == 0
    run_rollback_mock.assert_called_once_with(
        cfg_path, git_ref="HEAD~1", force=True, limit=None
    )
