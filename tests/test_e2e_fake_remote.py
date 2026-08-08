from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.analyze import run_analyze
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.deploy import DeployBlockedError, run_deploy
from isuctl.pack import run_pack
from isuctl.paths import is_ready, mark_ready
from isuctl.sync_down import run_sync_down

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_REMOTE_SRC = FIXTURES / "fake_remote_tree"
REMOTE_PREFIX = "/home/isucon/"

PACK_HEADINGS = [
    "# ISUCON 分析パック",
    "## 遅いエンドポイント",
    "## 遅い SQL",
    "## 候補コード位置",
    "## スキーマ抜粋",
    "## 次の仮説",
]


def _map_remote(remote_home: Path, remote_path: str) -> Path:
    if not remote_path.startswith(REMOTE_PREFIX):
        raise ValueError(f"unexpected remote path: {remote_path}")
    return remote_home / remote_path[len(REMOTE_PREFIX) :]


def _copy_tree(src: Path, dst: Path, *, excludes: list[str] | None = None) -> None:
    ignore = shutil.ignore_patterns(*(excludes or []))
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def _make_local_remote(remote_home: Path):
    def local_rsync_from_remote(ssh, host, remote_path, local_path, *, excludes=None):
        src = _map_remote(remote_home, remote_path.rstrip("/"))
        _copy_tree(src, local_path, excludes=excludes)

    def local_rsync_file_from_remote(ssh, host, remote_file, local_file):
        src = _map_remote(remote_home, remote_file)
        local_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_file)

    def local_rsync_to_remote(ssh, host, local_path, remote_path, *, excludes=None, delete=False):
        dst = _map_remote(remote_home, remote_path.rstrip("/"))
        _copy_tree(local_path, dst, excludes=excludes)

    def local_run_ssh(ssh, host, remote_command, check=True):
        if remote_command.startswith("test -e "):
            quoted = remote_command[len("test -e ") :]
            remote_file = shlex.split(quoted)[0]
            path = _map_remote(remote_home, remote_file)
            code = 0 if path.exists() else 1
            return subprocess.CompletedProcess(args=[], returncode=code, stdout="", stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    return local_run_ssh, local_rsync_from_remote, local_rsync_file_from_remote, local_rsync_to_remote


def _write_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="e2e", local_dir="./work"),
            ssh=SshConfig(user="isucon", key="/tmp/fake-key"),
            hosts=[
                Host(
                    name="app1",
                    host="fake-remote",
                    role=["app"],
                    remote_app_dir=f"{REMOTE_PREFIX}webapp",
                ),
            ],
        ),
    )
    return cfg_path


def _seed_raw_logs(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "out" / "raw" / "20260809-120000"
    raw_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "sample_access.ltsv", raw_dir / "access.log")
    shutil.copy(FIXTURES / "sample_slow.log", raw_dir / "mysql-slow.log")
    return raw_dir


@pytest.fixture
def e2e_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    remote_home = tmp_path / "remote_home"
    shutil.copytree(FAKE_REMOTE_SRC, remote_home)
    cfg_path = _write_config(tmp_path)
    ssh, rsync_from, rsync_file_from, rsync_to = _make_local_remote(remote_home)
    patches = [
        patch("isuctl.sync_down.run_ssh", side_effect=ssh),
        patch("isuctl.sync_down.rsync_from_remote", side_effect=rsync_from),
        patch("isuctl.sync_down.rsync_file_from_remote", side_effect=rsync_file_from),
        patch("isuctl.deploy.run_ssh", side_effect=ssh),
        patch("isuctl.deploy.rsync_to_remote", side_effect=rsync_to),
    ]
    for p in patches:
        p.start()
    yield tmp_path, cfg_path, remote_home
    for p in patches:
        p.stop()


def test_e2e_fake_remote_core_loop(e2e_workspace):
    tmp_path, cfg_path, remote_home = e2e_workspace
    local_dir = run_sync_down(cfg_path)

    assert local_dir == (tmp_path / "work").resolve()
    assert is_ready(local_dir)
    assert (local_dir / "app.py").is_file()
    assert (local_dir / "sql" / "schema.sql").is_file()
    assert "/api/foo" in (local_dir / "app.py").read_text(encoding="utf-8")

    with pytest.raises(DeployBlockedError):
        (local_dir / ".isucon-ready").unlink()
        run_deploy(cfg_path)

    mark_ready(local_dir)
    run_deploy(cfg_path)

    deployed_remote = remote_home / "webapp"
    assert (deployed_remote / "app.py").is_file()
    assert not (deployed_remote / ".isucon-ready").exists()

    raw_dir = _seed_raw_logs(tmp_path)
    with patch("isuctl.analyze.shutil.which", return_value=None):
        analyze_dir = run_analyze(raw_dir)

    assert (analyze_dir / "alp.json").is_file()
    assert (analyze_dir / "slow.txt").is_file()
    assert (analyze_dir / "summary.md").is_file()

    pack_path = run_pack(cfg_path, analyze_dir)
    content = pack_path.read_text(encoding="utf-8")
    for heading in PACK_HEADINGS:
        assert heading in content
    assert "/api/foo" in content
    assert "users" in content
    assert "app.py" in content
    assert "CREATE TABLE users" in content
