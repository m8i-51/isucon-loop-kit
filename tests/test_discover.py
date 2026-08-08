from pathlib import Path
from unittest.mock import patch

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.discover import run_discover


def test_discover_sets_remote_app_dir(tmp_path: Path):
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir=str(tmp_path / "work")),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            hosts=[Host(name="app1", host="10.0.0.1", role=[])],
        ),
    )

    def fake_ssh(ssh, host, cmd, check=True):
        class R:
            returncode = 0
            stdout = "/home/isucon/webapp\nactive\nactive\n"
            stderr = ""

        return R()

    with patch("isuctl.discover.run_ssh", side_effect=fake_ssh):
        cfg = run_discover(cfg_path)
    assert cfg.hosts[0].remote_app_dir == "/home/isucon/webapp"
    assert "app" in cfg.hosts[0].role
