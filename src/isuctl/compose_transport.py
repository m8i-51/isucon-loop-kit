"""Docker Compose transport for the laptop loop.

SSH+Ansible stays the contest path. This module runs only when isucon.toml
has a ``[compose]`` table. Containers are reached with ``docker compose exec``
and ``docker compose cp`` (logs on stderr use ``docker compose logs``).
"""

from __future__ import annotations

import fnmatch
import importlib.resources
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from isuctl.config import (
    ComposeConfig,
    Host,
    IsuconConfig,
    load_config,
    save_config,
)
from isuctl.hostsutil import primary_host
from isuctl.log_sources import REMOTE_LOG_PATHS, _is_glob, _newest_match_script
from isuctl.paths import mark_ready, out_dir
from isuctl.probe import interpret_probe_stdout
from isuctl.remote import RemoteError
from isuctl.snapshot_tar import snapshot_name, snapshot_remote_command

# Same names sync-down drops on the SSH path.
SYNC_EXCLUDES = (
    ".git",
    "__pycache__",
    "node_modules",
    "vendor",
    "*.log",
    ".venv",
    "venv",
    "tmp",
)

COMPOSE_PROBE = """APP_DIR=""
for d in /home/isucon/webapp /home/isucon/isunum /home/isucon /src /app; do
  if [ -d "$d" ]; then APP_DIR="$d"; break; fi
done
printf '%s\\n' "$APP_DIR"
if command -v nginx >/dev/null 2>&1; then printf 'active\\n'; else printf 'inactive\\n'; fi
if command -v mysqld >/dev/null 2>&1 || command -v mariadbd >/dev/null 2>&1; then printf 'active\\n'; else printf 'inactive\\n'; fi
if command -v apache2 >/dev/null 2>&1 || command -v httpd >/dev/null 2>&1; then printf 'active\\n'; else printf 'inactive\\n'; fi
if command -v postgres >/dev/null 2>&1; then printf 'active\\n'; else printf 'inactive\\n'; fi
"""

_DETECT_WEB = (
    "if command -v nginx >/dev/null 2>&1; then echo nginx; "
    "elif command -v apache2 >/dev/null 2>&1 || command -v httpd >/dev/null 2>&1; "
    "then echo apache; else echo none; fi"
)
_DETECT_DB = (
    "if command -v mysqld >/dev/null 2>&1 || command -v mariadbd >/dev/null 2>&1; "
    "then echo mysql; "
    "elif command -v postgres >/dev/null 2>&1; then echo postgres; "
    "else echo none; fi"
)
_HTTP_PROBE = """url=$1
if command -v curl >/dev/null 2>&1; then
  curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$url" || echo fail
elif command -v wget >/dev/null 2>&1; then
  wget -q -O /dev/null --timeout=3 "$url" && echo 200 || echo fail
else
  echo skip
fi
"""
_URL_RE = re.compile(r"^https?://[A-Za-z0-9_.:/-]+$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_TIME_DIVISOR = {"ms": 1000.0, "us": 1_000_000.0}


def resolve_project_dir(compose: ComposeConfig, config_path: Path) -> Path:
    """``project_dir`` is relative to the config file unless absolute."""
    raw = Path(compose.project_dir).expanduser()
    if raw.is_absolute():
        return raw
    return (config_path.parent / raw).resolve()


def ensure_compose_config(config: IsuconConfig) -> ComposeConfig:
    if config.compose is None:
        raise ValueError("compose transport には [compose] が必要です")
    if not config.hosts:
        raise ValueError("config にホストが1つ以上必要です")
    explicit_ssh = [host.name for host in config.hosts if host.transport == "ssh"]
    if explicit_ssh:
        raise ValueError(
            "compose 設定と transport=ssh が混在しています: " + ", ".join(explicit_ssh)
        )
    missing = [host.name for host in config.hosts if not host.service]
    if missing:
        raise ValueError(
            "compose の host には service が必要です: " + ", ".join(missing)
        )
    return config.compose


def convert_ltsv_request_time(text: str, unit: str) -> str:
    """Rewrite ``request_time`` into seconds for alp."""
    if unit == "s":
        return text
    divisor = _TIME_DIVISOR.get(unit)
    if divisor is None:
        raise ValueError(f"access_time_unit が不正です: {unit}")
    ends_nl = text.endswith("\n")
    rewritten_lines: list[str] = []
    for line in text.splitlines():
        fields: list[str] = []
        for field in line.split("\t"):
            prefix = "request_time:"
            if field.startswith(prefix):
                raw = field[len(prefix) :]
                try:
                    seconds = float(raw) / divisor
                except ValueError:
                    fields.append(field)
                else:
                    fields.append(f"{prefix}{seconds:.6f}")
            else:
                fields.append(field)
        rewritten_lines.append("\t".join(fields))
    body = "\n".join(rewritten_lines)
    if ends_nl and body:
        body += "\n"
    return body


def parse_running_services(stdout: str) -> set[str]:
    """Service names whose ``docker compose ps --format json`` row is running."""
    text = stdout.strip()
    if not text:
        return set()
    try:
        if text.startswith("["):
            rows = json.loads(text)
        else:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise RemoteError(f"docker compose ps の JSON を読めません: {exc}") from exc
    if not isinstance(rows, list):
        raise RemoteError("docker compose ps の JSON が配列ではありません")
    running: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and _row_running(row):
            service = str(row.get("Service") or "")
            if service:
                running.add(service)
    return running


def _row_running(row: dict[str, object]) -> bool:
    state = str(row.get("State") or "").lower()
    status = str(row.get("Status") or "").lower()
    return state.startswith("running") or status.startswith("up")


def _docker_run(
    args: list[str],
    *,
    input_text: str | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        if capture:
            return subprocess.run(
                args,
                text=True,
                capture_output=True,
                check=False,
                input=input_text,
            )
        return subprocess.run(args, text=True, check=False, input=input_text)
    except FileNotFoundError as exc:
        raise RemoteError(
            "docker が PATH にありません。Docker Compose v2 (`docker compose`) が必要です。"
        ) from exc


def _local_run(
    args: list[str],
    **kwargs: object,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, **kwargs)  # type: ignore[arg-type]


class ComposeClient:
    def __init__(self, compose: ComposeConfig, project_dir: Path) -> None:
        self.compose = compose
        self.project_dir = project_dir
        self.base = _compose_base(compose, project_dir)

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        proc = _docker_run(
            [*self.base, *args], input_text=input_text, capture=capture
        )
        if check and proc.returncode != 0:
            raise RemoteError(_failure_detail(proc, [*self.base, *args]))
        return proc

    def exec_service(
        self,
        host: Host,
        command: str | list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if isinstance(command, str):
            remote = ["sh", "-c", command]
        else:
            remote = list(command)
        args = ["exec", "-T"]
        if host.exec_user:
            args.extend(["-u", host.exec_user])
        args.append(host.service)
        args.extend(remote)
        return self.run(args, check=check, input_text=input_text)

    def cp_from(self, service: str, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run(["cp", f"{service}:{remote}", str(local)])

    def cp_to(self, local: Path, service: str, remote: str) -> None:
        self.run(["cp", str(local), f"{service}:{remote}"])


def _compose_base(compose: ComposeConfig, project_dir: Path) -> list[str]:
    cmd = ["docker", "compose", "--project-directory", str(project_dir)]
    if compose.file:
        file_path = Path(compose.file)
        if not file_path.is_absolute():
            file_path = project_dir / file_path
        cmd.extend(["-f", str(file_path)])
    if compose.project_name:
        cmd.extend(["-p", compose.project_name])
    return cmd


def _failure_detail(proc: subprocess.CompletedProcess[str], cmd: list[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    if detail:
        return detail
    return f"docker compose が失敗しました (exit {proc.returncode}): {' '.join(cmd)}"


def _client_for(config: IsuconConfig, config_path: Path) -> ComposeClient:
    compose = ensure_compose_config(config)
    return ComposeClient(compose, resolve_project_dir(compose, config_path))


def _filter_hosts(hosts: list[Host], limit: str | None) -> list[Host]:
    if limit is None or not limit.strip():
        return list(hosts)
    wanted = {part.strip() for part in limit.split(",") if part.strip()}
    known = {host.name for host in hosts} | {host.service for host in hosts}
    unknown = wanted - known
    if unknown:
        raise ValueError(
            "--limit に一致するホストがありません: " + ", ".join(sorted(unknown))
        )
    return [
        host for host in hosts if host.name in wanted or host.service in wanted
    ]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _pick(configured: list[str], selected: list[Host], *, limited: bool) -> list[str]:
    if not limited:
        return _dedupe(configured)
    allowed = {host.service for host in selected}
    return _dedupe([name for name in configured if name in allowed])


def _template_path(name: str) -> Path:
    root = importlib.resources.files("isuctl")
    return Path(str(root / "templates" / name))


def _last_line(stdout: str | None) -> str:
    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _remote_exists(client: ComposeClient, host: Host, remote_path: str) -> bool:
    result = client.exec_service(
        host, f"test -e {shlex.quote(remote_path)}", check=False
    )
    return result.returncode == 0


def _resolve_remote(client: ComposeClient, host: Host, pattern: str) -> str | None:
    if _is_glob(pattern):
        result = client.exec_service(
            host, ["bash", "-c", _newest_match_script(pattern)], check=False
        )
        if result.returncode != 0:
            return None
        return _last_line(result.stdout) or None
    if _remote_exists(client, host, pattern):
        return pattern
    return None


def _log_hosts(config: IsuconConfig) -> tuple[list[Host], list[Host]]:
    web = [host for host in config.hosts if "web" in host.role or host.access_log]
    db = [
        host
        for host in config.hosts
        if "db" in host.role or host.slow_log or host.slow_log_via == "stderr"
    ]
    if not web and not db:
        primary = primary_host(config.hosts)
        return [primary], [primary]
    return web, db


def _access_candidates(host: Host) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if host.access_log:
        items.append((host.access_log, "access.log"))
    items.extend(
        (pattern, name) for pattern, name in REMOTE_LOG_PATHS if name == "access.log"
    )
    return items


def _slow_name(host: Host, pattern: str) -> str:
    if host.db_kind == "mysql" or "mysql" in pattern:
        return "mysql-slow.log"
    if host.db_kind == "postgres" or "postgres" in pattern or "pgsql" in pattern:
        return "slow.log"
    return "slow.log"


def _slow_candidates(host: Host) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if host.slow_log:
        items.append((host.slow_log, _slow_name(host, host.slow_log)))
    items.extend(
        (pattern, name) for pattern, name in REMOTE_LOG_PATHS if name != "access.log"
    )
    return items


def _has_slow(pulled: set[str]) -> bool:
    return "mysql-slow.log" in pulled or "slow.log" in pulled


def _looks_like_slow(text: str) -> bool:
    return "duration:" in text or "Query_time:" in text


def _stderr_local_name(host: Host, text: str) -> str:
    if host.db_kind == "mysql":
        return "mysql-slow.log"
    if host.db_kind == "postgres":
        return "slow.log"
    if "Query_time:" in text and "duration:" not in text:
        return "mysql-slow.log"
    return "slow.log"


def _pull_stderr(
    client: ComposeClient,
    host: Host,
    raw_dir: Path,
    pulled: set[str],
    *,
    require_marker: bool,
) -> None:
    result = client.run(
        ["logs", "--no-color", "--no-log-prefix", host.service], check=False
    )
    text = result.stdout or ""
    if not text.strip():
        return
    if require_marker and not _looks_like_slow(text):
        return
    local_name = _stderr_local_name(host, text)
    if local_name in pulled:
        return
    (raw_dir / local_name).write_text(text, encoding="utf-8")
    pulled.add(local_name)


def pull_compose(config_path: Path) -> Path:
    config = load_config(config_path)
    ensure_compose_config(config)
    client = _client_for(config, config_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_dir = out_dir() / "raw" / timestamp
    raw_dir.mkdir(parents=True, exist_ok=True)

    pulled: set[str] = set()
    web_hosts, db_hosts = _log_hosts(config)
    for host in web_hosts:
        for pattern, local_name in _access_candidates(host):
            if local_name in pulled:
                break
            remote = _resolve_remote(client, host, pattern)
            if remote is None:
                continue
            dest = raw_dir / local_name
            client.cp_from(host.service, remote, dest)
            if host.access_time_unit != "s":
                original = dest.read_text(encoding="utf-8", errors="replace")
                dest.write_text(
                    convert_ltsv_request_time(original, host.access_time_unit),
                    encoding="utf-8",
                )
            pulled.add(local_name)
            break

    for host in db_hosts:
        if host.slow_log_via == "stderr":
            _pull_stderr(client, host, raw_dir, pulled, require_marker=False)
            continue
        for pattern, local_name in _slow_candidates(host):
            if local_name in pulled:
                continue
            remote = _resolve_remote(client, host, pattern)
            if remote is None:
                continue
            client.cp_from(host.service, remote, raw_dir / local_name)
            pulled.add(local_name)
        if not _has_slow(pulled):
            _pull_stderr(client, host, raw_dir, pulled, require_marker=True)

    if not pulled:
        print(
            "警告: コンテナにログが見つかりません。取得ファイル数は 0 です",
            file=sys.stderr,
        )
        raise ValueError(
            "ログを1つも取得できませんでした。コンテナのパスと slow_log_via を確認してください"
        )
    return raw_dir


def discover_compose(config_path: Path) -> IsuconConfig:
    config = load_config(config_path)
    ensure_compose_config(config)
    client = _client_for(config, config_path)
    for host in config.hosts:
        if not host.transport:
            host.transport = "compose"
        result = client.exec_service(host, COMPOSE_PROBE)
        updates = interpret_probe_stdout(result.stdout)
        roles = updates["role"]
        if not isinstance(roles, list):
            raise RemoteError(f"{host.name} の probe 結果が不正です")
        host.role = [str(role) for role in roles]
        if "remote_app_dir" in updates:
            host.remote_app_dir = str(updates["remote_app_dir"])
    save_config(config_path, config)
    return config


def _prune(root: Path) -> None:
    if not root.exists():
        return
    names = {item for item in SYNC_EXCLUDES if "*" not in item}
    patterns = [item for item in SYNC_EXCLUDES if "*" in item]
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        if not path.exists() or path == root:
            continue
        matched = path.name in names or any(
            fnmatch.fnmatch(path.name, pattern) for pattern in patterns
        )
        if not matched:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def _ensure_git_repo(local_dir: Path) -> None:
    if (local_dir / ".git").exists():
        return
    subprocess.run(
        ["git", "init"], cwd=local_dir, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=local_dir, check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=isucon@localhost",
            "-c",
            "user.name=isucon",
            "commit",
            "-m",
            "リモートからの初回同期",
        ],
        cwd=local_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def _sync_optional(client: ComposeClient, host: Host, local_dir: Path) -> None:
    if _remote_exists(client, host, "/home/isucon/env.sh"):
        client.cp_from(
            host.service, "/home/isucon/env.sh", local_dir.parent / "env.sh"
        )
    sql_remote = f"{host.remote_app_dir.rstrip('/')}/sql"
    if _remote_exists(client, host, sql_remote):
        dest = local_dir / "sql"
        dest.mkdir(parents=True, exist_ok=True)
        client.cp_from(host.service, sql_remote.rstrip("/") + "/.", dest)
        _prune(dest)
        return
    schema_remote = f"{host.remote_app_dir.rstrip('/')}/schema.sql"
    if _remote_exists(client, host, schema_remote):
        client.cp_from(host.service, schema_remote, local_dir / "schema.sql")


def sync_down_compose(config_path: Path) -> Path:
    config = load_config(config_path)
    ensure_compose_config(config)
    client = _client_for(config, config_path)
    host = primary_host(config.hosts)
    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    remote = host.remote_app_dir.rstrip("/") + "/."
    client.cp_from(host.service, remote, local_dir)
    _prune(local_dir)
    _sync_optional(client, host, local_dir)
    _ensure_git_repo(local_dir)
    mark_ready(local_dir)
    return local_dir


def snapshot_compose(config_path: Path, label: str | None = None) -> str:
    config = load_config(config_path)
    ensure_compose_config(config)
    client = _client_for(config, config_path)
    host = primary_host(config.hosts)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = snapshot_name(timestamp, label)
    remote_path = f"/home/isucon/snapshots/{name}"
    app_rel = host.remote_app_dir.lstrip("/")
    client.exec_service(host, snapshot_remote_command(remote_path, app_rel))
    local = out_dir() / "snapshots" / name
    client.cp_from(host.service, remote_path, local)
    return str(local)


def _detect(client: ComposeClient, host: Host, script: str) -> str:
    result = client.exec_service(host, script, check=False)
    if result.returncode != 0:
        return "none"
    return _last_line(result.stdout) or "none"


# Alpine nginx includes /etc/nginx/http.d from the http context.
# /etc/nginx/conf.d is included from the root context there (and the
# directory may be missing). Debian/Ubuntu include conf.d from http.
_NGINX_LTSV_PATHS = (
    "/etc/nginx/http.d/isuctl_ltsv.conf",
    "/etc/nginx/conf.d/isuctl_ltsv.conf",
)


def _bootstrap_nginx(client: ComposeClient, host: Host) -> None:
    local = _template_path("nginx_ltsv.conf")
    candidates = [
        path
        for path in _NGINX_LTSV_PATHS
        if _remote_exists(client, host, str(Path(path).parent))
    ]
    if not candidates:
        # Directory not created yet: keep the Debian/Ubuntu default path.
        candidates = ["/etc/nginx/conf.d/isuctl_ltsv.conf"]
    errors: list[str] = []
    for remote in candidates:
        client.cp_to(local, host.service, remote)
        result = client.exec_service(
            host,
            "touch /var/log/nginx/access.ltsv.log && nginx -t && nginx -s reload",
            check=False,
        )
        if result.returncode == 0:
            print(f"{host.name}: nginx LTSV → /var/log/nginx/access.ltsv.log ({remote})")
            return
        client.exec_service(host, f"rm -f {shlex.quote(remote)}", check=False)
        detail = (result.stderr or result.stdout or "").strip()
        errors.append(f"{remote}: {detail or f'exit {result.returncode}'}")
    raise RemoteError("nginx LTSV を入れられませんでした: " + "; ".join(errors))


def _bootstrap_apache(
    client: ComposeClient, host: Host, config: IsuconConfig, config_path: Path
) -> None:
    kind = _detect(
        client,
        host,
        "if command -v httpd >/dev/null 2>&1 && ! command -v apache2 >/dev/null 2>&1; "
        "then echo httpd; else echo apache2; fi",
    )
    if kind == "httpd":
        remote_conf = "/etc/httpd/conf.d/isuctl-ltsv.conf"
        access_log = "/var/log/httpd/access_log"
    else:
        remote_conf = "/etc/apache2/conf-enabled/isuctl-ltsv.conf"
        access_log = "/var/log/apache2/access.log"
    text = (
        _template_path("apache_ltsv.conf")
        .read_text(encoding="utf-8")
        .replace("__ACCESS_LOG__", access_log)
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".conf", delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    try:
        client.cp_to(tmp_path, host.service, remote_conf)
    finally:
        tmp_path.unlink(missing_ok=True)
    client.exec_service(
        host,
        "touch "
        + shlex.quote(access_log)
        + " && (apache2ctl graceful || apachectl graceful || httpd -k graceful)",
    )
    if host.access_time_unit == "s":
        host.access_time_unit = "us"
        save_config(config_path, config)
    print(
        f"{host.name}: Apache LTSV → {access_log} "
        "(request_time はマイクロ秒。pull が秒に直します)"
    )


def _bootstrap_mysql(client: ComposeClient, host: Host) -> None:
    client.cp_to(
        _template_path("mysql_slow.cnf"),
        host.service,
        "/etc/mysql/conf.d/isuctl_slow.cnf",
    )
    client.run(["restart", host.service])
    client.exec_service(
        host, "touch /var/log/mysql/mysql-slow.log || true", check=False
    )
    print(f"{host.name}: MySQL slow log → /var/log/mysql/mysql-slow.log (long_query_time=0.2)")


def _psql(
    client: ComposeClient,
    host: Host,
    user: str,
    database: str,
    sql: str,
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    return client.exec_service(
        host,
        ["psql", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database, "-f", "-"],
        check=check,
        input_text=sql,
    )


def _bootstrap_postgres(client: ComposeClient, host: Host, compose: ComposeConfig) -> None:
    statements = [
        f"ALTER SYSTEM SET log_min_duration_statement = '{compose.slow_threshold}';",
        "ALTER SYSTEM SET log_line_prefix = '%m [%p] %q%u@%d ';",
    ]
    needs_restart = False
    directory = ""
    if host.slow_log_via == "stderr" or not host.slow_log or _is_glob(host.slow_log):
        statements.append("ALTER SYSTEM SET log_destination = 'stderr';")
        statements.append("SELECT pg_reload_conf();")
    else:
        if not _SAFE_PATH_RE.fullmatch(host.slow_log):
            raise ValueError(f"slow_log のパスが不正です: {host.slow_log}")
        directory = str(Path(host.slow_log).parent)
        filename = Path(host.slow_log).name
        statements.extend(
            [
                "ALTER SYSTEM SET log_destination = 'stderr';",
                "ALTER SYSTEM SET logging_collector = on;",
                f"ALTER SYSTEM SET log_directory = '{directory}';",
                f"ALTER SYSTEM SET log_filename = '{filename}';",
            ]
        )
        needs_restart = True
    _psql(
        client,
        host,
        compose.db_user,
        compose.db_name,
        "\n".join(statements) + "\n",
        check=True,
    )
    if needs_restart:
        client.exec_service(host, f"mkdir -p {shlex.quote(directory)}", check=False)
        client.run(["restart", host.service])
    _try_pg_stat_statements(client, host, compose)
    where = "stderr" if not needs_restart else host.slow_log
    print(
        f"{host.name}: PostgreSQL log_min_duration_statement={compose.slow_threshold} ({where})"
    )


def _try_pg_stat_statements(
    client: ComposeClient, host: Host, compose: ComposeConfig
) -> None:
    available = _psql(
        client,
        host,
        compose.db_user,
        compose.db_name,
        "SELECT name FROM pg_available_extensions WHERE name = 'pg_stat_statements';\n",
        check=False,
    )
    if available.returncode != 0 or "pg_stat_statements" not in (available.stdout or ""):
        print(f"{host.name}: pg_stat_statements は入っていないのでスキップしました")
        return
    preload = _psql(
        client,
        host,
        compose.db_user,
        compose.db_name,
        "SHOW shared_preload_libraries;\n",
        check=False,
    )
    if preload.returncode != 0 or "pg_stat_statements" not in (preload.stdout or ""):
        print(
            f"{host.name}: pg_stat_statements はパッケージにありますが "
            "shared_preload_libraries に無いので有効化していません"
        )
        return
    created = _psql(
        client,
        host,
        compose.db_user,
        compose.db_name,
        "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;\n",
        check=False,
    )
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "").strip()
        print(f"{host.name}: CREATE EXTENSION pg_stat_statements に失敗したので続行します: {detail}")
        return
    print(f"{host.name}: pg_stat_statements を有効にしました")


def _web_kind(client: ComposeClient, host: Host) -> str:
    detected = _detect(client, host, _DETECT_WEB)
    if detected in {"nginx", "apache"}:
        return detected
    if "apache" in host.access_log or "httpd" in host.access_log:
        return "apache"
    if "nginx" in host.access_log:
        return "nginx"
    return "none"


def _db_kind(client: ComposeClient, host: Host) -> str:
    if host.db_kind in {"mysql", "postgres"}:
        return host.db_kind
    detected = _detect(client, host, _DETECT_DB)
    if detected in {"mysql", "postgres"}:
        return detected
    return "none"


def bootstrap_compose(config_path: Path) -> None:
    config = load_config(config_path)
    compose = ensure_compose_config(config)
    client = _client_for(config, config_path)
    web_hosts = [host for host in config.hosts if "web" in host.role]
    db_hosts = [host for host in config.hosts if "db" in host.role]
    if not web_hosts and not db_hosts:
        web_hosts = list(config.hosts)
        db_hosts = list(config.hosts)
    print("コンテナへログ設定を入れます。web / db を作り直したら bootstrap を再実行してください。")
    for host in web_hosts:
        kind = _web_kind(client, host)
        if kind == "nginx":
            _bootstrap_nginx(client, host)
        elif kind == "apache":
            _bootstrap_apache(client, host, config, config_path)
        else:
            print(f"{host.name}: web サーバが見つからないので LTSV はスキップしました")
    for host in db_hosts:
        kind = _db_kind(client, host)
        if kind == "mysql":
            _bootstrap_mysql(client, host)
        elif kind == "postgres":
            _bootstrap_postgres(client, host, compose)
        else:
            print(f"{host.name}: DB サーバが見つからないので slow log はスキップしました")


def _source_dest(project: Path, source_dest: str) -> Path:
    raw = source_dest.strip()
    if not raw:
        raise RemoteError(
            "compose.source_dest を設定してください。"
            "deploy は Dockerfile を残したまま、そのサブディレクトリへソースを置きます。"
        )
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise RemoteError("compose.source_dest は project_dir 内の相対パスにしてください")
    dest = (project / rel).resolve()
    project_resolved = project.resolve()
    if dest == project_resolved or project_resolved not in dest.parents:
        raise RemoteError("compose.source_dest は project_dir のサブディレクトリにしてください")
    return dest


def _warn_dirty(local_dir: Path) -> None:
    if not (local_dir / ".git").exists():
        return
    result = _local_run(
        ["git", "-C", str(local_dir), "status", "--porcelain"],
        text=True,
        capture_output=True,
    )
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    if stdout.strip():
        print(
            "警告: 未コミットの変更はイメージに入りません。"
            "コミットしてから、その ref を --branch に渡してください。",
            file=sys.stderr,
        )


def _process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace").strip()
    return value.strip()


def _export_ref(local_dir: Path, ref: str, dest: Path) -> None:
    if not (local_dir / ".git").exists():
        raise RemoteError(
            f"git リポジトリではありません: {local_dir}。"
            "先に sync-down するか、アプリの checkout を local_dir に置いてください。"
        )
    archive = _local_run(
        ["git", "-C", str(local_dir), "archive", "--format=tar", ref],
        capture_output=True,
    )
    if archive.returncode != 0:
        raise RemoteError(f"git archive {ref} に失敗しました: {_process_text(archive.stderr)}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    payload = archive.stdout if isinstance(archive.stdout, bytes) else b""
    extracted = _local_run(
        ["tar", "-x", "-C", str(dest)],
        input=payload,
        capture_output=True,
    )
    if extracted.returncode != 0:
        raise RemoteError(
            "build context への展開に失敗しました: " + _process_text(extracted.stderr)
        )


def _project_or_raise(compose: ComposeConfig, config_path: Path) -> Path:
    project = resolve_project_dir(compose, config_path)
    if not project.is_dir():
        raise RemoteError(f"compose.project_dir がありません: {project}")
    return project


def deploy_compose(config_path: Path, *, branch: str, limit: str | None = None) -> None:
    branch = branch.strip()
    if not branch:
        raise RemoteError("branch が空です。--branch を指定してください。")
    config = load_config(config_path)
    compose = ensure_compose_config(config)
    project = _project_or_raise(compose, config_path)
    limited = bool(limit and limit.strip())
    selected = _filter_hosts(config.hosts, limit)
    build_services = _pick(compose.build, selected, limited=limited)
    up_pool = compose.up or [host.service for host in config.hosts]
    up_services = _pick(up_pool, selected, limited=limited)
    client = ComposeClient(compose, project)
    if build_services:
        dest = _source_dest(project, compose.source_dest)
        local_dir = (Path.cwd() / config.project.local_dir).resolve()
        _warn_dirty(local_dir)
        _export_ref(local_dir, branch, dest)
        client.run(["build", *build_services])
    if not up_services:
        raise RemoteError("up する service がありません")
    client.run(["up", "-d", "--wait", *up_services])
    print(
        "compose deploy "
        f"branch={branch} build={','.join(build_services) or '-'} "
        f"up={','.join(up_services)}"
    )


def provision_compose(config_path: Path, *, limit: str | None = None) -> None:
    config = load_config(config_path)
    compose = ensure_compose_config(config)
    project = _project_or_raise(compose, config_path)
    limited = bool(limit and limit.strip())
    selected = _filter_hosts(config.hosts, limit)
    up_pool = compose.up or [host.service for host in config.hosts]
    services = _pick(up_pool, selected, limited=limited)
    if not services:
        raise RemoteError("up する service がありません")
    ComposeClient(compose, project).run(["up", "-d", "--build", "--wait", *services])
    print(f"compose provision up={','.join(services)}")


def _http_probe(client: ComposeClient, host: Host, url: str) -> str:
    if not _URL_RE.fullmatch(url):
        return "skip"
    result = client.exec_service(host, ["sh", "-c", _HTTP_PROBE, "probe", url], check=False)
    return _last_line(result.stdout) or "fail"


def check_compose(config_path: Path, *, limit: str | None = None) -> None:
    config = load_config(config_path)
    compose = ensure_compose_config(config)
    client = _client_for(config, config_path)
    selected = _filter_hosts(config.hosts, limit)
    ps = client.run(["ps", "--all", "--format", "json"])
    running = parse_running_services(ps.stdout or "")
    probe_host = next((host for host in selected if "web" in host.role), None)
    if probe_host is None:
        probe_host = next((host for host in selected if "app" in host.role), None)
    down: list[str] = []
    for host in selected:
        up = host.service in running
        bits = [
            f"host={host.name}",
            f"service={host.service}",
            f"running={'yes' if up else 'no'}",
        ]
        if not up:
            down.append(host.service)
        elif "web" in host.role:
            web = client.exec_service(
                host,
                "if command -v nginx >/dev/null 2>&1; then nginx -t >/dev/null; "
                "elif command -v apache2ctl >/dev/null 2>&1; then apache2ctl -t >/dev/null; "
                "elif command -v apachectl >/dev/null 2>&1; then apachectl -t >/dev/null; "
                "else echo skip; fi",
                check=False,
            )
            bits.append(f"web_config_rc={web.returncode}")
        if up and probe_host is host:
            bits.append(f"http={_http_probe(client, host, compose.http_url)}")
        print(" ".join(bits))
    if down:
        raise RemoteError("起動していない service があります: " + ", ".join(down))


def run_bench(config_path: Path) -> None:
    if not config_path.is_file():
        raise ValueError(
            "isuctl bench は [compose] のときだけ実行します。"
            "競技サーバではベンチを起動しません。"
        )
    config = load_config(config_path)
    if config.compose is None and not any(host.transport == "compose" for host in config.hosts):
        raise ValueError(
            "isuctl bench は [compose] のときだけ実行します。"
            "競技サーバではベンチを起動しません。"
        )
    compose = ensure_compose_config(config)
    if not compose.bench_service or not compose.bench_command:
        raise ValueError("compose.bench_service と compose.bench_command を設定してください")
    project = _project_or_raise(compose, config_path)
    client = ComposeClient(compose, project)
    base = client.base
    if compose.bench_profile:
        base = ["docker", "compose", "--profile", compose.bench_profile, *base[2:]]
    cmd = [
        *base,
        "run",
        "--rm",
        "--no-deps",
        compose.bench_service,
        *compose.bench_command,
    ]
    proc = _docker_run(cmd, capture=False)
    if proc.returncode != 0:
        raise RemoteError(f"bench が失敗しました (exit {proc.returncode})")
