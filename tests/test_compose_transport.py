"""Compose transport tests. Docker is mocked; git archive uses a real repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from isuctl.cli import app
from isuctl.compose_transport import (
    COMPOSE_PROBE,
    SYNC_EXCLUDES,
    _docker_run,
    _source_dest,
    check_compose,
    convert_ltsv_request_time,
    parse_running_services,
    pull_compose,
    run_bench,
)
from isuctl.config import (
    ComposeConfig,
    Host,
    IsuconConfig,
    ProjectConfig,
    SshConfig,
    load_config,
    save_config,
)
from isuctl.deploy import DeployBlockedError, run_check, run_deploy, run_provision
from isuctl.discover import run_discover
from isuctl.paths import mark_ready
from isuctl.pull import run_pull
from isuctl.remote import RemoteError
from isuctl.rollback import run_rollback
from isuctl.snapshot import run_snapshot
from isuctl.sync_down import DEFAULT_EXCLUDES, run_sync_down

REPO = Path(__file__).resolve().parents[1]
BANNED = ("isureal", "app-asia", "app-europe", "nip.io", "172.28.10.2", "23552")
RUNNING_PS = (
    '{"Service":"web","State":"running"}\n'
    '{"Service":"app","State":"running"}\n'
    '{"Service":"db","State":"running"}'
)


class DockerFake:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None, bool]] = []
        self.files: dict[str, str] = {}
        self.exists: set[str] = set()
        self.globs: dict[str, str] = {}
        self.logs = ""
        self.ps = ""
        self.by_service: dict[str, str] = {}
        self.sql: dict[str, str] = {}
        self.uploaded: list[tuple[str, str]] = []

    def __call__(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(args), input_text, capture))
        sub = _subcommand(args)
        text = " ".join(args)
        rc = 0
        stdout = ""
        if sub == "exec" and input_text:
            for key, value in self.sql.items():
                if key in input_text:
                    stdout = value
                    break
        elif sub == "exec" and "test -e " in text:
            rc = 0 if any(path in text for path in self.exists) else 1
        elif sub == "exec" and "for f in " in text:
            for pattern, path in self.globs.items():
                if pattern in text:
                    stdout = path + "\n"
                    break
            else:
                rc = 0
                stdout = "\n"
        elif sub == "exec":
            service = _exec_service(args)
            stdout = self.by_service.get(service, "")
        elif sub == "logs":
            stdout = self.logs
        elif sub == "ps":
            stdout = self.ps
        elif sub == "cp":
            src, dest = args[-2], args[-1]
            if ":" in src and ":" not in dest:
                remote = src.split(":", 1)[1]
                target = Path(dest)
                target.parent.mkdir(parents=True, exist_ok=True)
                content = self.files.get(remote, "copied\n")
                if target.exists() and target.is_dir():
                    (target / "app.py").write_text(content, encoding="utf-8")
                    (target / "noise.log").write_text("noise\n", encoding="utf-8")
                    vendor = target / "vendor"
                    vendor.mkdir(exist_ok=True)
                    (vendor / "lib.txt").write_text("x\n", encoding="utf-8")
                else:
                    target.write_text(content, encoding="utf-8")
            elif ":" in dest:
                local = Path(src)
                if local.is_file():
                    self.uploaded.append((dest, local.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr="")


def _subcommand(args: list[str]) -> str:
    index = 0
    if args and args[0] == "docker":
        index = 1
    if index < len(args) and args[index] == "compose":
        index += 1
    valued = {
        "--project-directory",
        "-f",
        "--file",
        "-p",
        "--project-name",
        "--profile",
    }
    while index < len(args):
        token = args[index]
        if token in valued:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _exec_service(args: list[str]) -> str:
    if "exec" not in args:
        return ""
    rest = args[args.index("exec") + 1 :]
    if rest[:1] == ["-T"]:
        rest = rest[1:]
    if rest[:1] == ["-u"]:
        rest = rest[2:]
    return rest[0] if rest else ""


def _hosts() -> list[Host]:
    return [
        Host(
            name="app1",
            host="app",
            role=["app"],
            transport="compose",
            service="app",
            remote_app_dir="/home/isucon/webapp",
        ),
        Host(
            name="web1",
            host="web",
            role=["web"],
            transport="compose",
            service="web",
            access_log="/var/log/nginx/access.ltsv.log",
        ),
        Host(
            name="db1",
            host="db",
            role=["db"],
            transport="compose",
            service="db",
            db_kind="postgres",
            slow_log_via="stderr",
        ),
    ]


def _write_compose(tmp_path: Path, *, hosts: list[Host] | None = None) -> Path:
    project = tmp_path / "stack"
    (project / "app" / "src").mkdir(parents=True)
    (project / "app" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    path = tmp_path / "isucon.toml"
    save_config(
        path,
        IsuconConfig(
            project=ProjectConfig(name="practice", local_dir="./work"),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            compose=ComposeConfig(
                project_dir=str(project),
                file="compose.yaml",
                project_name="practice",
                build=["app"],
                up=["web", "app", "db"],
                source_dest="app/src",
                bench_service="bench",
                bench_profile="bench",
                bench_command=["./bench", "-target", "http://web"],
                db_name="practice",
            ),
            hosts=hosts if hosts is not None else _hosts(),
        ),
    )
    return path


def _git_commit(repo: Path, name: str, content: str, message: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _patch_docker(monkeypatch: pytest.MonkeyPatch, fake: DockerFake) -> None:
    monkeypatch.setattr("isuctl.compose_transport._docker_run", fake)


def test_sync_excludes_match_ssh_list() -> None:
    assert tuple(DEFAULT_EXCLUDES) == SYNC_EXCLUDES


def test_convert_ltsv_request_time_scales_units() -> None:
    raw = "uri:/a\trequest_time:1500000\tstatus:200\n"
    assert convert_ltsv_request_time(raw, "s") == raw
    assert "request_time:1.500000" in convert_ltsv_request_time(raw, "us")
    assert "request_time:1.500000" in convert_ltsv_request_time(
        "request_time:1500\n", "ms"
    )
    assert convert_ltsv_request_time("request_time:nope\n", "us") == "request_time:nope\n"


def test_parse_running_services_accepts_array_and_lines() -> None:
    assert parse_running_services("") == set()
    assert parse_running_services('{"Service":"web","State":"running"}') == {"web"}
    text = '[{"Service":"app","Status":"Up 2 seconds"},{"Service":"db","State":"exited"}]'
    assert parse_running_services(text) == {"app"}
    with pytest.raises(RemoteError, match="JSON"):
        parse_running_services("{")


def test_compose_probe_prints_five_status_lines() -> None:
    result = subprocess.run(
        ["sh", "-c", COMPOSE_PROBE],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 5
    assert all(line in {"active", "inactive"} for line in lines[1:])


def test_example_config_loads_and_project_exists() -> None:
    path = REPO / "examples" / "compose" / "isucon.example.toml"
    cfg = load_config(path)
    assert cfg.compose is not None
    assert cfg.compose.bench_service == "bench"
    assert {host.service for host in cfg.hosts} == {"app", "web", "db"}
    project = (path.parent / cfg.compose.project_dir).resolve()
    assert (project / "compose.yaml").is_file()
    blob = "\n".join(
        item.read_text(encoding="utf-8")
        for item in [
            path,
            REPO / "src" / "isuctl" / "compose_transport.py",
            REPO / "examples" / "compose" / "README.md",
            REPO / "README.md",
            REPO / "AGENTS.md",
        ]
        if item.is_file()
    )
    for banned in BANNED:
        assert banned not in blob


def test_ssh_save_omits_compose_fields(tmp_path: Path) -> None:
    path = tmp_path / "isucon.toml"
    save_config(
        path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
        ),
    )
    text = path.read_text(encoding="utf-8")
    assert "[compose]" not in text
    assert "transport" not in text


def test_compose_roundtrip_and_bench_command_string(tmp_path: Path) -> None:
    path = _write_compose(tmp_path)
    loaded = load_config(path)
    assert loaded.compose is not None
    assert loaded.compose.build == ["app"]
    assert loaded.compose.bench_command == ["./bench", "-target", "http://web"]
    assert loaded.hosts[2].slow_log_via == "stderr"
    raw = tmp_path / "string.toml"
    raw.write_text(
        path.read_text(encoding="utf-8").replace(
            'bench_command = ["./bench", "-target", "http://web"]',
            'bench_command = "./bench -target http://web"',
        ),
        encoding="utf-8",
    )
    assert load_config(raw).compose is not None
    assert load_config(raw).compose.bench_command == ["./bench", "-target", "http://web"]


def test_invalid_slow_threshold_rejected(tmp_path: Path) -> None:
    path = _write_compose(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        'project_name = "practice"\n',
        'project_name = "practice"\nslow_threshold = "200ms; drop"\n',
    )
    broken = tmp_path / "bad.toml"
    broken.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(broken)


def test_source_dest_must_stay_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "stack"
    project.mkdir()
    with pytest.raises(RemoteError, match="サブディレクトリ"):
        _source_dest(project, ".")
    with pytest.raises(RemoteError, match="相対パス"):
        _source_dest(project, "../outside")


def test_missing_docker_is_remote_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    monkeypatch.setattr("isuctl.compose_transport.subprocess.run", boom)
    with pytest.raises(RemoteError, match="docker が PATH"):
        _docker_run(["docker", "compose", "version"])


def test_pull_copies_access_log_and_stderr_slow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    fake = DockerFake()
    fake.exists.add("/var/log/nginx/access.ltsv.log")
    fake.files["/var/log/nginx/access.ltsv.log"] = "uri:/a\trequest_time:0.2\n"
    fake.logs = "duration: 12.0 ms statement: SELECT 1\n"
    _patch_docker(monkeypatch, fake)

    def fail_ssh(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ssh")

    monkeypatch.setattr("isuctl.pull.run_ssh", fail_ssh)
    raw = run_pull(path)
    assert "request_time:0.2" in (raw / "access.log").read_text(encoding="utf-8")
    assert "duration:" in (raw / "slow.log").read_text(encoding="utf-8")
    assert any(_subcommand(call[0]) == "logs" for call in fake.calls)
    logs = next(call[0] for call in fake.calls if _subcommand(call[0]) == "logs")
    assert "--no-color" in logs and "--no-log-prefix" in logs and "db" in logs
    base = fake.calls[0][0]
    assert base[base.index("--project-directory") + 1] == str(tmp_path / "stack")
    assert base[base.index("-p") + 1] == "practice"


def test_pull_resolves_postgres_glob_then_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    hosts = _hosts()
    hosts[2].slow_log_via = "file"
    hosts[2].slow_log = ""
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.globs["/var/log/postgresql/*.log"] = "/var/log/postgresql/postgresql.log"
    fake.files["/var/log/postgresql/postgresql.log"] = (
        "duration: 3.0 ms statement: SELECT 1\n"
    )
    _patch_docker(monkeypatch, fake)
    raw = pull_compose(path)
    assert "duration: 3.0 ms" in (raw / "slow.log").read_text(encoding="utf-8")
    copied = [
        call[0][-2]
        for call in fake.calls
        if _subcommand(call[0]) == "cp" and call[0][-2].startswith("db:")
    ]
    assert "db:/var/log/postgresql/postgresql.log" in copied


def test_pull_converts_apache_microseconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    hosts = _hosts()
    hosts[1].access_log = "/var/log/apache2/access.log"
    hosts[1].access_time_unit = "us"
    hosts[2].slow_log_via = "file"
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.exists.add("/var/log/apache2/access.log")
    fake.files["/var/log/apache2/access.log"] = "request_time:1500000\turi:/a\n"
    _patch_docker(monkeypatch, fake)
    raw = run_pull(path)
    assert "request_time:1.500000" in (raw / "access.log").read_text(encoding="utf-8")


def test_pull_stderr_fallback_requires_slow_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    hosts = _hosts()
    hosts[2].slow_log_via = "file"
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.logs = "ready to accept connections\n"
    _patch_docker(monkeypatch, fake)
    with pytest.raises(ValueError, match="ログを1つも取得できませんでした"):
        run_pull(path)


def test_discover_updates_roles_and_keeps_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_compose(tmp_path)
    fake = DockerFake()
    fake.by_service = {
        "app": "/home/isucon/webapp\ninactive\ninactive\ninactive\ninactive\n",
        "web": "\ninactive\ninactive\nactive\ninactive\n",
        "db": "\ninactive\ninactive\ninactive\nactive\n",
    }
    _patch_docker(monkeypatch, fake)
    cfg = run_discover(path)
    assert cfg.hosts[0].role == ["app"]
    assert cfg.hosts[0].remote_app_dir == "/home/isucon/webapp"
    assert cfg.hosts[1].role == ["web"]
    assert cfg.hosts[2].role == ["db"]
    loaded = load_config(path)
    assert loaded.compose is not None
    assert loaded.compose.bench_service == "bench"
    assert loaded.hosts[0].service == "app"
    assert loaded.hosts[1].transport == "compose"


def test_discover_passes_exec_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = _hosts()
    hosts[0].exec_user = "isucon"
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.by_service = {
        "app": "/home/isucon/webapp\ninactive\ninactive\ninactive\ninactive\n",
        "web": "\ninactive\ninactive\ninactive\ninactive\n",
        "db": "\ninactive\ninactive\ninactive\nactive\n",
    }
    _patch_docker(monkeypatch, fake)
    run_discover(path)
    app_exec = next(
        call[0] for call in fake.calls if _exec_service(call[0]) == "app"
    )
    assert "-T" in app_exec
    assert app_exec[app_exec.index("-u") + 1] == "isucon"


def test_sync_down_copies_and_prunes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    fake = DockerFake()
    fake.files["/home/isucon/webapp/."] = "print('ok')\n"
    _patch_docker(monkeypatch, fake)
    local = run_sync_down(path)
    assert (local / "app.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (local / "noise.log").exists()
    assert not (local / "vendor").exists()
    assert (local / ".git").is_dir()
    assert (local / ".isucon-ready").is_file()
    copied = next(call[0] for call in fake.calls if _subcommand(call[0]) == "cp")
    assert copied[-2] == "app:/home/isucon/webapp/."


def test_snapshot_tars_web_configs_and_copies_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    with pytest.MonkeyPatch.context() as ctx:
        ctx.setattr("isuctl.compose_transport.datetime", _FixedNow())
        remote = run_snapshot(path, label="pre deploy")
    assert remote.endswith("snap-20260809-120000-pre-deploy.tar.gz")
    assert Path(remote).is_file()
    script = next(
        call[0][-1] for call in fake.calls if _subcommand(call[0]) == "exec"
    )
    assert "etc/nginx" in script
    assert "etc/apache2" in script
    assert "etc/httpd" in script
    assert "home/isucon/webapp" in script


class _FixedNow:
    def now(self) -> _FixedNow:
        return self

    def strftime(self, _fmt: str) -> str:
        return "20260809-120000"


def test_bootstrap_nginx_and_postgres_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_compose(tmp_path)
    fake = DockerFake()
    fake.by_service["web"] = "nginx\n"
    fake.sql = {
        "pg_available_extensions": "pg_stat_statements\n",
        "shared_preload_libraries": "\n",
    }
    _patch_docker(monkeypatch, fake)
    from isuctl.bootstrap import run_bootstrap

    run_bootstrap(path)
    uploaded = " ".join(dest for dest, _text in fake.uploaded)
    assert "isuctl_ltsv.conf" in uploaded
    assert any(
        "nginx -s reload" in " ".join(call[0]) for call in fake.calls
    )
    sql = "\n".join(call[1] or "" for call in fake.calls)
    assert "ALTER SYSTEM SET log_min_duration_statement = '200ms'" in sql
    assert "pg_reload_conf" in sql
    assert "CREATE EXTENSION" not in sql
    assert not any(_subcommand(call[0]) == "restart" for call in fake.calls)
    assert "shared_preload_libraries" in capsys.readouterr().out


def test_bootstrap_postgres_creates_extension_when_preloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = [host for host in _hosts() if host.service == "db"]
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.sql = {
        "pg_available_extensions": "pg_stat_statements\n",
        "shared_preload_libraries": "pg_stat_statements\n",
    }
    _patch_docker(monkeypatch, fake)
    from isuctl.bootstrap import run_bootstrap

    run_bootstrap(path)
    sql = "\n".join(call[1] or "" for call in fake.calls)
    assert "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" in sql


def test_bootstrap_apache_httpd_sets_microsecond_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = [
        Host(
            name="web1",
            host="web",
            role=["web"],
            transport="compose",
            service="web",
            access_log="/var/log/httpd/access_log",
        )
    ]
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.by_service["web"] = "httpd\n"
    _patch_docker(monkeypatch, fake)
    from isuctl.bootstrap import run_bootstrap

    run_bootstrap(path)
    assert load_config(path).hosts[0].access_time_unit == "us"
    bodies = [text for dest, text in fake.uploaded if "isuctl-ltsv.conf" in dest]
    assert bodies
    assert "/var/log/httpd/access_log" in bodies[0]
    assert "__ACCESS_LOG__" not in bodies[0]
    assert "httpd/conf.d" in fake.uploaded[0][0]


def test_bootstrap_postgres_file_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = [
        Host(
            name="db1",
            host="db",
            role=["db"],
            transport="compose",
            service="db",
            db_kind="postgres",
            slow_log="/var/log/postgresql/postgresql.log",
            slow_log_via="file",
        )
    ]
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    fake.sql = {"pg_available_extensions": ""}
    _patch_docker(monkeypatch, fake)
    from isuctl.bootstrap import run_bootstrap

    run_bootstrap(path)
    sql = "\n".join(call[1] or "" for call in fake.calls)
    assert "logging_collector = on" in sql
    assert "/var/log/postgresql" in sql
    assert any(_subcommand(call[0]) == "restart" for call in fake.calls)


def test_bootstrap_mysql_restarts_after_cnf_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = [
        Host(
            name="db1",
            host="db",
            role=["db"],
            transport="compose",
            service="db",
            db_kind="mysql",
            slow_log="/var/log/mysql/mysql-slow.log",
        )
    ]
    path = _write_compose(tmp_path, hosts=hosts)
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    from isuctl.bootstrap import run_bootstrap

    run_bootstrap(path)
    assert any(
        dest.endswith("isuctl_slow.cnf") for dest, _text in fake.uploaded
    )
    restart = next(call[0] for call in fake.calls if _subcommand(call[0]) == "restart")
    assert restart[-1] == "db"


def test_deploy_archives_ref_then_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    _git_commit(tmp_path / "work", "main.go", "package main\n", "init")
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)

    def fail_playbook(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ansible")

    monkeypatch.setattr("isuctl.deploy.run_playbook", fail_playbook)
    run_deploy(path, branch="HEAD")
    baked = (tmp_path / "stack" / "app" / "src" / "main.go").read_text(encoding="utf-8")
    assert baked == "package main\n"
    assert (tmp_path / "stack" / "app" / "Dockerfile").is_file()
    build = next(call[0] for call in fake.calls if _subcommand(call[0]) == "build")
    up = next(call[0] for call in fake.calls if _subcommand(call[0]) == "up")
    assert build[-1] == "app"
    assert "-d" in up and "--wait" in up
    assert up[-3:] == ["web", "app", "db"]


def test_deploy_warns_and_skips_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    work = tmp_path / "work"
    _git_commit(work, "main.go", "package main\n", "init")
    (work / "extra.go").write_text("package extra\n", encoding="utf-8")
    _patch_docker(monkeypatch, DockerFake())
    run_deploy(path, branch="HEAD")
    assert "未コミット" in capsys.readouterr().err
    assert not (tmp_path / "stack" / "app" / "src" / "extra.go").exists()


def test_deploy_limit_skips_unselected_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    _git_commit(tmp_path / "work", "main.go", "package main\n", "init")
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    run_deploy(path, branch="HEAD", limit="web1")
    assert not any(_subcommand(call[0]) == "build" for call in fake.calls)
    up = next(call[0] for call in fake.calls if _subcommand(call[0]) == "up")
    assert up[-1] == "web"


def test_ssh_config_deploy_still_calls_ansible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "isucon.toml"
    save_config(
        path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            hosts=[Host(name="app1", host="10.0.0.1")],
        ),
    )
    called: list[tuple[object, ...]] = []

    def playbook(*args: object, **kwargs: object) -> None:
        called.append(args)

    monkeypatch.setattr("isuctl.deploy.run_playbook", playbook)
    run_deploy(path, branch="main", limit="s1")
    assert called and called[0][0] == "deploy.yml"


def test_rollback_rebuilds_previous_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    work = tmp_path / "work"
    _git_commit(work, "main.go", "one\n", "first")
    mark_ready(work)
    _git_commit(work, "main.go", "two\n", "second")
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    monkeypatch.setattr(
        "isuctl.deploy.run_playbook",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("ansible")),
    )
    run_rollback(path, git_ref="HEAD~1")
    assert (tmp_path / "stack" / "app" / "src" / "main.go").read_text(
        encoding="utf-8"
    ) == "one\n"
    assert (work / "main.go").read_text(encoding="utf-8") == "one\n"
    assert any(_subcommand(call[0]) == "build" for call in fake.calls)


def test_check_reports_http_and_fails_when_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_compose(tmp_path)
    fake = DockerFake()
    fake.ps = RUNNING_PS
    fake.by_service = {"web": "200\n", "app": "200\n"}
    _patch_docker(monkeypatch, fake)
    check_compose(path)
    out = capsys.readouterr().out
    assert "service=web running=yes" in out
    assert "http=200" in out
    assert "web_config_rc=0" in out

    fake.ps = '{"Service":"app","State":"running"}'
    fake.calls.clear()
    with pytest.raises(RemoteError, match="起動していない"):
        check_compose(path)


def test_provision_builds_and_ssh_provision_stays_ansible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_compose(tmp_path)
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    run_provision(config_path=path)
    up = next(call[0] for call in fake.calls if _subcommand(call[0]) == "up")
    assert "--build" in up and "--wait" in up

    ssh = tmp_path / "ssh.toml"
    save_config(
        ssh,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            hosts=[Host(name="s1", host="10.0.0.1")],
        ),
    )
    called: list[str] = []

    def playbook(name: str, **_kwargs: object) -> None:
        called.append(name)

    monkeypatch.setattr("isuctl.deploy.run_playbook", playbook)
    run_provision(config_path=ssh)
    run_check(config_path=ssh, limit="s1")
    assert called == ["init.yml", "check.yml"]


def test_bench_runs_inside_compose_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_compose(tmp_path)
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)
    run_bench(path)
    cmd, _stdin, capture = fake.calls[0]
    assert capture is False
    assert cmd[cmd.index("--profile") + 1] == "bench"
    assert cmd[cmd.index("run") :] == [
        "run",
        "--rm",
        "--no-deps",
        "bench",
        "./bench",
        "-target",
        "http://web",
    ]


def test_bench_refuses_ssh_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "isucon.toml"
    save_config(
        path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir="./work"),
            hosts=[Host(name="app1", host="10.0.0.1")],
        ),
    )
    fake = DockerFake()
    _patch_docker(monkeypatch, fake)

    def fail_ssh(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ssh")

    monkeypatch.setattr("isuctl.remote.run_ssh", fail_ssh)
    with pytest.raises(ValueError, match="競技サーバ"):
        run_bench(path)
    assert fake.calls == []


def test_cli_deploy_check_bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_compose(tmp_path)
    _git_commit(tmp_path / "work", "main.go", "package main\n", "init")
    fake = DockerFake()
    fake.ps = RUNNING_PS
    fake.by_service["web"] = "200\n"
    _patch_docker(monkeypatch, fake)
    monkeypatch.setattr(
        "isuctl.deploy.run_playbook",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("ansible")),
    )
    deployed = CliRunner().invoke(
        app, ["deploy", "--config", str(path), "--branch", "HEAD"]
    )
    assert deployed.exit_code == 0, deployed.stdout
    assert "デプロイ完了" in deployed.stdout
    checked = CliRunner().invoke(app, ["check", "--config", str(path)])
    assert checked.exit_code == 0, checked.stdout
    benched = CliRunner().invoke(app, ["bench", "--config", str(path)])
    assert benched.exit_code == 0, benched.stdout
    assert "bench 完了" in benched.stdout


def test_cli_ensure_access_is_noop_for_compose(tmp_path: Path) -> None:
    path = _write_compose(tmp_path)
    result = CliRunner().invoke(app, ["ensure-access", "--config", str(path)])
    assert result.exit_code == 0
    assert "鍵配布は不要" in result.stdout


def test_mixed_transport_is_rejected(tmp_path: Path) -> None:
    hosts = _hosts()
    hosts[0].transport = "ssh"
    path = _write_compose(tmp_path, hosts=hosts)
    with pytest.raises(ValueError, match="transport=ssh"):
        run_discover(path)


def test_deploy_still_requires_branch(tmp_path: Path) -> None:
    path = _write_compose(tmp_path)
    with pytest.raises(DeployBlockedError, match="branch"):
        run_deploy(path, branch="  ")
