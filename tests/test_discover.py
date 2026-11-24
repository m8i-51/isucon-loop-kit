import os
import shlex
import subprocess
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
    assert "systemctl is-active apache2" in PROBE_COMMAND
    assert "systemctl is-active httpd" in PROBE_COMMAND
    assert "systemctl is-active postgresql" in PROBE_COMMAND
    assert "postgresql@*" in PROBE_COMMAND
    assert PROBE_COMMAND.count("printf") == 5


def test_discover_apache_and_postgres_set_web_and_db_roles():
    host = Host(name="app1", host="10.0.0.1", role=[])
    ssh = SshConfig(user="isucon", key="/tmp/k")

    def fake_ssh(ssh_cfg, h, cmd, check=True):
        class R:
            returncode = 0
            stdout = "/home/isucon/webapp\ninactive\ninactive\nactive\nactive\n"
            stderr = ""

        return R()

    with patch("isuctl.discover.run_ssh", side_effect=fake_ssh):
        updates = discover_host(ssh, host)

    assert updates["role"] == ["app", "web", "db"]


def test_discover_nginx_and_apache_are_one_web_role():
    host = Host(name="app1", host="10.0.0.1", role=[])
    ssh = SshConfig(user="isucon", key="/tmp/k")

    def fake_ssh(ssh_cfg, h, cmd, check=True):
        class R:
            returncode = 0
            stdout = "/home/isucon/webapp\nactive\ninactive\nactive\ninactive\n"
            stderr = ""

        return R()

    with patch("isuctl.discover.run_ssh", side_effect=fake_ssh):
        updates = discover_host(ssh, host)

    assert updates["role"] == ["app", "web"]


def _fake_systemctl(bindir: Path, body: str) -> None:
    bindir.mkdir()
    path = bindir / "systemctl"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_probe(bindir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", PROBE_COMMAND],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_probe_reports_httpd_and_postgres_cluster(tmp_path: Path):
    _fake_systemctl(
        tmp_path / "bin",
        """#!/bin/sh
if [ "$1" = is-active ]; then
  case "$2" in
    httpd) echo active; exit 0 ;;
    *) echo inactive; exit 3 ;;
  esac
fi
if [ "$1" = list-units ]; then
  echo 'postgresql@16-main.service loaded active running'
  exit 0
fi
echo inactive
exit 3
""",
    )
    result = _run_probe(tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1:] == [
        "inactive",
        "inactive",
        "active",
        "active",
    ]


def test_probe_skips_httpd_when_apache2_is_active(tmp_path: Path):
    calls = tmp_path / "calls"
    quoted_calls = shlex.quote(str(calls))
    _fake_systemctl(
        tmp_path / "bin",
        f"""#!/bin/sh
echo "$1 $2" >> {quoted_calls}
if [ "$1" = is-active ]; then
  case "$2" in
    apache2) echo active; exit 0 ;;
    postgresql) echo active; exit 0 ;;
    *) echo inactive; exit 3 ;;
  esac
fi
echo inactive
exit 3
""",
    )
    result = _run_probe(tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1:] == [
        "inactive",
        "inactive",
        "active",
        "active",
    ]
    recorded = calls.read_text(encoding="utf-8")
    assert "is-active httpd" not in recorded
    assert "list-units" not in recorded


def test_probe_all_inactive_stays_one_line_per_service(tmp_path: Path):
    _fake_systemctl(
        tmp_path / "bin",
        """#!/bin/sh
if [ "$1" = is-active ]; then
  echo inactive
  exit 3
fi
exit 0
""",
    )
    result = _run_probe(tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1:] == [
        "inactive",
        "inactive",
        "inactive",
        "inactive",
    ]
