from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.bootstrap import (
    MYSQL_REMOTE_SNIPPET,
    MYSQL_SYSTEM_PATH,
    NGINX_REMOTE_SNIPPET,
    NGINX_SYSTEM_PATH,
    REMOTE_ISUCTL_DIR,
    run_bootstrap,
    template_path,
)
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config


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


def test_template_files_exist_and_match_brief():
    nginx = template_path("nginx_ltsv.conf").read_text(encoding="utf-8")
    mysql = template_path("mysql_slow.cnf").read_text(encoding="utf-8")
    assert "log_format ltsv" in nginx
    assert "access_log /var/log/nginx/access.log ltsv" in nginx
    assert "slow_query_log = 1" in mysql
    assert "slow_query_log_file = /var/log/mysql/mysql-slow.log" in mysql
    assert "long_query_time = 0" in mysql
    assert "log_queries_not_using_indexes = 1" in mysql


def test_run_bootstrap_uploads_snippets_and_runs_ssh(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app", "web", "db"])],
    )
    rsync_calls: list[tuple[Path, str]] = []
    ssh_calls: list[tuple[str, bool]] = []

    def fake_rsync_file(ssh, host, local_file, remote_file):
        rsync_calls.append((local_file, remote_file))

    def fake_ssh(ssh, host, cmd, check=True):
        ssh_calls.append((cmd, check))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.bootstrap.rsync_file_to_remote", side_effect=fake_rsync_file),
        patch("isuctl.bootstrap.run_ssh", side_effect=fake_ssh),
    ):
        run_bootstrap(cfg_path)

    assert len(rsync_calls) == 2
    nginx_local, nginx_remote = rsync_calls[0]
    mysql_local, mysql_remote = rsync_calls[1]
    assert nginx_local.name == "nginx_ltsv.conf"
    assert nginx_remote == NGINX_REMOTE_SNIPPET
    assert mysql_local.name == "mysql_slow.cnf"
    assert mysql_remote == MYSQL_REMOTE_SNIPPET

    mkdir_cmds = [cmd for cmd, _ in ssh_calls if "mkdir" in cmd]
    assert mkdir_cmds
    assert REMOTE_ISUCTL_DIR in mkdir_cmds[0]
    assert "/var/log/nginx" in mkdir_cmds[0]
    assert "/var/log/mysql" in mkdir_cmds[0]

    assert any(NGINX_SYSTEM_PATH in cmd for cmd, _ in ssh_calls)
    assert any(MYSQL_SYSTEM_PATH in cmd for cmd, _ in ssh_calls)
    assert any("nginx" in cmd and "reload" in cmd for cmd, _ in ssh_calls)
    assert any("alp" in cmd for cmd, _ in ssh_calls)


def test_run_bootstrap_picks_first_app_host(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        hosts=[
            Host(name="db1", host="10.0.0.2", role=["db"]),
            Host(name="app1", host="10.0.0.1", role=["app"]),
        ],
    )
    seen_hosts: list[str] = []

    def fake_rsync_file(ssh, host, local_file, remote_file):
        seen_hosts.append(host.host)

    def fake_ssh(ssh, host, cmd, check=True):
        seen_hosts.append(host.host)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with (
        patch("isuctl.bootstrap.rsync_file_to_remote", side_effect=fake_rsync_file),
        patch("isuctl.bootstrap.run_ssh", side_effect=fake_ssh),
    ):
        run_bootstrap(cfg_path)

    assert seen_hosts
    assert all(h == "10.0.0.1" for h in seen_hosts)


def test_run_bootstrap_requires_hosts(tmp_path: Path):
    cfg_path = _write_config(tmp_path, hosts=[])
    with pytest.raises(ValueError, match="at least one host"):
        run_bootstrap(cfg_path)


def test_run_bootstrap_prints_nginx_include_instruction(tmp_path: Path, capsys):
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )
    with (
        patch("isuctl.bootstrap.rsync_file_to_remote"),
        patch("isuctl.bootstrap.run_ssh"),
    ):
        run_bootstrap(cfg_path)

    out = capsys.readouterr().out
    assert NGINX_REMOTE_SNIPPET in out
    assert "include" in out.lower()
    assert "mysql" in out.lower()


def test_cli_bootstrap_command(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from isuctl.cli import app

    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        tmp_path,
        hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
    )

    with patch("isuctl.cli.run_bootstrap") as run_bootstrap_mock:
        result = CliRunner().invoke(app, ["bootstrap", "--config", str(cfg_path)])

    assert result.exit_code == 0
    run_bootstrap_mock.assert_called_once_with(cfg_path)
    assert "bootstrapped" in result.stdout.lower()
