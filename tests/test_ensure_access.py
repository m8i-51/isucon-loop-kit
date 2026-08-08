from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.ensure_access import run_ensure_access


def _write_config(tmp_path: Path, *, bootstrap_user: str = "ubuntu") -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            ssh=SshConfig(
                user="isucon",
                key="/tmp/k",
                bootstrap_user=bootstrap_user,
            ),
            hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
        ),
    )
    return cfg_path


def test_ensure_access_copies_authorized_keys(tmp_path: Path, capsys):
    cfg_path = _write_config(tmp_path)
    ssh_calls: list[tuple[str, str]] = []

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_calls.append((ssh.user, cmd))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch("isuctl.ensure_access.run_ssh", side_effect=fake_ssh):
        run_ensure_access(cfg_path)

    assert ssh_calls[0][0] == "ubuntu"
    assert "authorized_keys" in ssh_calls[0][1]
    assert ssh_calls[1][0] == "isucon"
    assert "接続できます" in capsys.readouterr().out


def test_ensure_access_noop_when_bootstrap_user_same(tmp_path: Path, capsys):
    cfg_path = _write_config(tmp_path, bootstrap_user="isucon")
    with patch("isuctl.ensure_access.run_ssh") as ssh_mock:
        run_ensure_access(cfg_path)
    ssh_mock.assert_not_called()
    assert "何もしません" in capsys.readouterr().out


def test_ensure_access_raises_if_contest_user_still_unreachable(tmp_path: Path):
    cfg_path = _write_config(tmp_path)

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 0 if ssh.user == "ubuntu" else 1
            stdout = ""
            stderr = "Permission denied"

        return R()

    with patch("isuctl.ensure_access.run_ssh", side_effect=fake_ssh):
        with pytest.raises(RuntimeError, match="SSH が失敗"):
            run_ensure_access(cfg_path)
