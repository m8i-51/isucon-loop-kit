from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.paths import is_ready
from isuctl.sync_down import DEFAULT_EXCLUDES, run_sync_down


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


def test_run_sync_down_marks_ready_and_rsyncs_with_excludes(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    rsync_calls: list[tuple] = []

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        rsync_calls.append((host.host, remote_path, local_path, excludes))
        local_path.mkdir(parents=True, exist_ok=True)
        (local_path / "main.go").write_text("package main\n", encoding="utf-8")

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo"),
    ):
        local_dir = run_sync_down(cfg_path)

    assert local_dir == (tmp_path / "work").resolve()
    assert is_ready(local_dir)
    assert len(rsync_calls) == 1
    host, remote_path, path, excludes = rsync_calls[0]
    assert host == "10.0.0.1"
    assert remote_path == "/home/isucon/webapp"
    assert path == local_dir
    assert excludes == DEFAULT_EXCLUDES


def test_run_sync_down_picks_first_app_host(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[
            Host(name="db1", host="10.0.0.2", role=["db"]),
            Host(name="app1", host="10.0.0.1", role=["app"]),
        ],
    )
    seen_hosts: list[str] = []

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        seen_hosts.append(host.host)
        local_path.mkdir(parents=True, exist_ok=True)

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo"),
    ):
        run_sync_down(cfg_path)

    assert seen_hosts == ["10.0.0.1"]


def test_run_sync_down_falls_back_to_first_host(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="db1", host="10.0.0.2", role=["db"])],
    )
    seen_hosts: list[str] = []

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        seen_hosts.append(host.host)
        local_path.mkdir(parents=True, exist_ok=True)

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo"),
    ):
        run_sync_down(cfg_path)

    assert seen_hosts == ["10.0.0.2"]


def test_run_sync_down_requires_hosts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(tmp_path, hosts=[])
    with pytest.raises(ValueError, match="at least one host"):
        run_sync_down(cfg_path)


def test_run_sync_down_syncs_optional_paths(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    optional_calls: list[tuple[str, Path]] = []

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        local_path.mkdir(parents=True, exist_ok=True)

    def fake_optional(ssh, host, remote_path, local_file):
        optional_calls.append((remote_path, local_file))

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        if "env.sh" in cmd:
            R.returncode = 0
        elif "/sql" in cmd:
            R.returncode = 1
        elif "schema.sql" in cmd:
            R.returncode = 0
        else:
            R.returncode = 1
        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down._rsync_optional_file", side_effect=fake_optional),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo"),
    ):
        run_sync_down(cfg_path)

    assert ("/home/isucon/env.sh", tmp_path / "env.sh") in optional_calls
    assert (
        "/home/isucon/webapp/schema.sql",
        tmp_path / "work" / "schema.sql",
    ) in optional_calls


def test_ensure_git_repo_initializes_when_missing(tmp_path: Path):
    from isuctl.sync_down import _ensure_git_repo

    work = tmp_path / "work"
    work.mkdir()
    (work / "main.go").write_text("package main\n", encoding="utf-8")
    _ensure_git_repo(work)
    assert (work / ".git").is_dir()


def test_ensure_git_repo_skips_existing_git(tmp_path: Path):
    from isuctl.sync_down import _ensure_git_repo

    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").mkdir()
    with patch("isuctl.sync_down.subprocess.run") as run:
        _ensure_git_repo(work)
        run.assert_not_called()


def test_run_sync_down_marks_ready_after_git_init(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    call_order: list[str] = []

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        local_path.mkdir(parents=True, exist_ok=True)
        (local_path / "main.go").write_text("package main\n", encoding="utf-8")

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo", side_effect=lambda d: call_order.append("git")),
        patch("isuctl.sync_down.mark_ready", side_effect=lambda d: call_order.append("ready")),
    ):
        run_sync_down(cfg_path)

    assert call_order == ["git", "ready"]


def test_run_sync_down_does_not_mark_ready_when_git_fails(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    def fake_rsync(ssh, host, remote_path, local_path, *, excludes=None):
        local_path.mkdir(parents=True, exist_ok=True)

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 1
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.sync_down.rsync_from_remote", side_effect=fake_rsync),
        patch("isuctl.sync_down.run_ssh", side_effect=fake_ssh),
        patch("isuctl.sync_down._ensure_git_repo", side_effect=RuntimeError("git init failed")),
        patch("isuctl.sync_down.mark_ready") as mark_ready_mock,
    ):
        with pytest.raises(RuntimeError, match="git init failed"):
            run_sync_down(cfg_path)

    mark_ready_mock.assert_not_called()
