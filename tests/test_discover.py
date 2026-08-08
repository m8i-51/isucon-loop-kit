from pathlib import Path
from unittest.mock import patch

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.discover import PROBE_COMMAND, discover_host, run_discover


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


def test_discover_empty_app_dir_does_not_set_app_role(tmp_path: Path):
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
            stdout = "\nactive\nactive\n"
            stderr = ""

        return R()

    with patch("isuctl.discover.run_ssh", side_effect=fake_ssh):
        cfg = run_discover(cfg_path)
    assert "app" not in cfg.hosts[0].role
    assert cfg.hosts[0].remote_app_dir == "/home/isucon/webapp"
    assert "web" in cfg.hosts[0].role
    assert "db" in cfg.hosts[0].role


def test_discover_parses_exactly_one_status_line_per_service():
    host = Host(name="app1", host="10.0.0.1", role=[])
    ssh = SshConfig(user="isucon", key="/tmp/k")

    def fake_ssh(ssh_cfg, h, cmd, check=True):
        class R:
            returncode = 0
            # nginx inactive (one line), mysql active — old probe would shift mysql to line 3
            stdout = "/home/isucon/webapp\ninactive\nactive\n"
            stderr = ""

        return R()

    with patch("isuctl.discover.run_ssh", side_effect=fake_ssh):
        updates = discover_host(ssh, host)

    assert updates["role"] == ["app", "db"]
    assert "web" not in updates["role"]


def test_discover_probe_avoids_inactive_duplication():
    assert "|| echo inactive" not in PROBE_COMMAND
    assert "nginx_status=$(systemctl is-active nginx" in PROBE_COMMAND
