# ISUCON Loop Kit 実装プラン

> **エージェント向け:** タスク単位実装には superpowers:subagent-driven-development（推奨）または superpowers:executing-plans を使う。進捗は `- [ ]` で追跡。

**ゴール:** ソロ運用向け CLI（`isuctl`）を作り、EC2 からコードを引き、高速デプロイし、alp / slow-query の分析パックで計測→改善ループを回す。

**構成:** Python Typer CLI が `isucon.toml` を読み書きし、SSH + rsync でホストと通信し、正規化した成果物を `out/` に書く。可視化は pprotein（ドキュメント + 補助）で、フルダッシュボードは自作しない。`sync-down` 済みになるまで `deploy` は拒否する。

**技術:** Python 3.12+、Typer、pydantic v2、pytest、ruff。システムツール: ssh、rsync、alp、pt-query-digest（subprocess）。

## 全体制約

- Python >= 3.12
- 当日アプリの主言語想定: Python webapp
- デプロイ経路に GitHub Actions を使わない
- `deploy` は成功した `sync-down` 前は拒否（`--force` はテスト/緊急のみ）
- ファイルは小さく単一目的。インライン import 禁止
- CLI のユーザー向け文言は日本語。識別子は英語のまま
- ドックフーディング対象: ISUCON14 AMI（`ami-0e334c50145a3ee41` または matsuu 代替）

---

## File Structure

```text
pyproject.toml
README.md
.gitignore
src/isuctl/
  __init__.py
  __main__.py
  cli.py                 # Typer app, command wiring only
  config.py              # isucon.toml models + load/save
  paths.py               # local_dir / out_dir / marker helpers
  remote.py              # SSH + rsync wrappers
  discover.py
  sync_down.py
  snapshot.py
  deploy.py
  rollback.py
  bootstrap.py
  pull.py
  analyze.py
  bench_note.py
  pack.py
  templates/
    nginx_ltsv.conf
    mysql_slow.cnf
assets/pprotein/
  README.md              # install + tunnel notes (no VPC co-location)
scripts/
  dogfood-checklist.md
tests/
  conftest.py
  test_config.py
  test_paths.py
  test_remote.py
  test_discover.py
  test_sync_down.py
  test_deploy.py
  test_rollback.py
  test_bootstrap.py
  test_pull.py
  test_analyze.py
  test_bench_note.py
  test_pack.py
  fixtures/
    sample_access.ltsv
    sample_slow.log
    fake_remote_tree/
work/                    # gitignored runtime workdir
out/                     # gitignored artifacts
```

---

### Task 1: Project scaffold + CLI stub

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/isuctl/__init__.py`
- Create: `src/isuctl/__main__.py`
- Create: `src/isuctl/cli.py`
- Create: `tests/test_cli_version.py`
- Create: `README.md`

**Interfaces:**
- Consumes: nothing
- Produces: console entry point `isuctl`; `cli.app` Typer instance; package version `0.1.0`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_version.py
from typer.testing import CliRunner
from isuctl.cli import app

runner = CliRunner()

def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moriko/Projects/isucon-loop-kit && python -m pytest tests/test_cli_version.py -v`
Expected: FAIL (module/package missing or app missing)

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "isuctl"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "typer>=0.12",
  "pydantic>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]

[project.scripts]
isuctl = "isuctl.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/isuctl"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```gitignore
# .gitignore
__pycache__/
.pytest_cache/
.ruff_cache/
*.egg-info/
.venv/
dist/
work/
out/
.isucon-ready
*.pem
```

```python
# src/isuctl/__init__.py
__version__ = "0.1.0"
```

```python
# src/isuctl/__main__.py
from isuctl.cli import app

if __name__ == "__main__":
    app()
```

```python
# src/isuctl/cli.py
import typer
from isuctl import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True)

def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    """ISUCON measure→fix loop toolkit."""

# placeholder so imports stay stable; real commands added in later tasks
@app.command("ping")
def ping() -> None:
    typer.echo("pong")
```

```markdown
# README.md
# isucon-loop-kit

Solo ISUCON loop kit (`isuctl`). See `docs/superpowers/specs/2026-08-09-isucon-loop-kit-design.md`.
```

- [ ] **Step 4: Install and run tests**

Run:
```bash
cd /Users/moriko/Projects/isucon-loop-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/test_cli_version.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src/isuctl tests/test_cli_version.py
git commit -m "$(cat <<'EOF'
feat: scaffold isuctl package and CLI stub

EOF
)"
```

---

### Task 2: Config model (`isucon.toml`)

**Files:**
- Create: `src/isuctl/config.py`
- Create: `src/isuctl/paths.py`
- Create: `tests/test_config.py`
- Create: `tests/test_paths.py`
- Modify: `src/isuctl/cli.py` (add `init-config` command)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class SshConfig(BaseModel): user: str; key: str`
  - `class Host(BaseModel): name: str; host: str; role: list[str]; remote_app_dir: str = "/home/isucon/webapp"`
  - `class ProjectConfig(BaseModel): name: str; local_dir: str = "./work"`
  - `class IsuconConfig(BaseModel): project: ProjectConfig; ssh: SshConfig; hosts: list[Host]`
  - `load_config(path: Path) -> IsuconConfig`
  - `save_config(path: Path, config: IsuconConfig) -> None`
  - `default_config_path(cwd: Path | None = None) -> Path` → `cwd / "isucon.toml"`
  - `ready_marker_path(local_dir: Path) -> Path` → `local_dir / ".isucon-ready"`
  - `out_dir(cwd: Path | None = None) -> Path` → `cwd / "out"`
  - `is_ready(local_dir: Path) -> bool`
  - `mark_ready(local_dir: Path) -> None`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
from pathlib import Path
from isuctl.config import IsuconConfig, Host, ProjectConfig, SshConfig, load_config, save_config

def test_roundtrip(tmp_path: Path):
    cfg = IsuconConfig(
        project=ProjectConfig(name="demo", local_dir=str(tmp_path / "work")),
        ssh=SshConfig(user="isucon", key="~/.ssh/id_ed25519"),
        hosts=[Host(name="app1", host="1.2.3.4", role=["app", "web"])],
    )
    path = tmp_path / "isucon.toml"
    save_config(path, cfg)
    loaded = load_config(path)
    assert loaded.project.name == "demo"
    assert loaded.hosts[0].host == "1.2.3.4"
    assert "app" in loaded.hosts[0].role
```

```python
# tests/test_paths.py
from pathlib import Path
from isuctl.paths import is_ready, mark_ready, ready_marker_path

def test_ready_marker(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    assert not is_ready(work)
    mark_ready(work)
    assert is_ready(work)
    assert ready_marker_path(work).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py tests/test_paths.py -v`
Expected: FAIL (import errors)

- [ ] **Step 3: Implement**

```python
# src/isuctl/config.py
from __future__ import annotations

from pathlib import Path

import tomllib
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    name: str
    local_dir: str = "./work"


class SshConfig(BaseModel):
    user: str = "isucon"
    key: str = "~/.ssh/id_ed25519"


class Host(BaseModel):
    name: str
    host: str
    role: list[str] = Field(default_factory=lambda: ["app"])
    remote_app_dir: str = "/home/isucon/webapp"


class IsuconConfig(BaseModel):
    project: ProjectConfig
    ssh: SshConfig = Field(default_factory=SshConfig)
    hosts: list[Host] = Field(default_factory=list)


def default_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "isucon.toml"


def load_config(path: Path) -> IsuconConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return IsuconConfig.model_validate(data)


def save_config(path: Path, config: IsuconConfig) -> None:
    # Minimal TOML writer for our schema (avoid extra deps).
    lines: list[str] = []
    lines.append("[project]")
    lines.append(f'name = "{config.project.name}"')
    lines.append(f'local_dir = "{config.project.local_dir}"')
    lines.append("")
    lines.append("[ssh]")
    lines.append(f'user = "{config.ssh.user}"')
    lines.append(f'key = "{config.ssh.key}"')
    lines.append("")
    for h in config.hosts:
        lines.append("[[hosts]]")
        lines.append(f'name = "{h.name}"')
        lines.append(f'host = "{h.host}"')
        role = ", ".join(f'"{r}"' for r in h.role)
        lines.append(f"role = [{role}]")
        lines.append(f'remote_app_dir = "{h.remote_app_dir}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
```

```python
# src/isuctl/paths.py
from __future__ import annotations

from pathlib import Path


def out_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "out"


def ready_marker_path(local_dir: Path) -> Path:
    return local_dir / ".isucon-ready"


def is_ready(local_dir: Path) -> bool:
    return ready_marker_path(local_dir).exists()


def mark_ready(local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    ready_marker_path(local_dir).write_text("ok\n", encoding="utf-8")
```

Add to `cli.py`:

```python
from pathlib import Path
from isuctl.config import IsuconConfig, ProjectConfig, SshConfig, Host, save_config, default_config_path

@app.command("init-config")
def init_config(
    name: str = typer.Option("isucon", help="Project name"),
    host: str = typer.Option(..., help="Primary host IP/DNS"),
    user: str = typer.Option("isucon"),
    key: str = typer.Option("~/.ssh/id_ed25519"),
) -> None:
    path = default_config_path()
    if path.exists():
        typer.secho(f"already exists: {path}", fg=typer.colors.RED)
        raise typer.Exit(1)
    cfg = IsuconConfig(
        project=ProjectConfig(name=name, local_dir="./work"),
        ssh=SshConfig(user=user, key=key),
        hosts=[Host(name="app1", host=host, role=["app", "web", "db"])],
    )
    save_config(path, cfg)
    typer.echo(f"wrote {path}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py tests/test_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/isuctl/config.py src/isuctl/paths.py src/isuctl/cli.py tests/test_config.py tests/test_paths.py
git commit -m "$(cat <<'EOF'
feat: add isucon.toml config model and ready marker

EOF
)"
```

---

### Task 3: Remote SSH/rsync layer

**Files:**
- Create: `src/isuctl/remote.py`
- Create: `tests/test_remote.py`

**Interfaces:**
- Consumes: `SshConfig`, `Host`
- Produces:
  - `class RemoteError(RuntimeError)`
  - `ssh_base_args(ssh: SshConfig) -> list[str]`
  - `run_ssh(ssh: SshConfig, host: Host, remote_command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]`
  - `rsync_from_remote(ssh, host, remote_path: str, local_path: Path, *, excludes: list[str] | None = None) -> None`
  - `rsync_to_remote(ssh, host, local_path: Path, remote_path: str, *, excludes: list[str] | None = None) -> None`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_remote.py
from isuctl.config import SshConfig
from isuctl.remote import ssh_base_args

def test_ssh_base_args_expands_identity():
    args = ssh_base_args(SshConfig(user="isucon", key="~/.ssh/id_ed25519"))
    assert "-i" in args
    # key path should be expanded (no leading ~)
    i = args.index("-i")
    assert not args[i + 1].startswith("~")
```

Also add a unit test that mocks `subprocess.run` for `run_ssh` success/failure.

```python
from unittest.mock import patch
from isuctl.config import Host, SshConfig
from isuctl.remote import run_ssh, RemoteError
import pytest

def test_run_ssh_raises_on_failure():
    host = Host(name="a", host="10.0.0.1", role=["app"])
    ssh = SshConfig(user="isucon", key="/tmp/key")
    with patch("isuctl.remote.subprocess.run") as run:
        run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        with pytest.raises(RemoteError):
            run_ssh(ssh, host, "true")
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_remote.py -v`

- [ ] **Step 3: Implement**

```python
# src/isuctl/remote.py
from __future__ import annotations

import subprocess
from pathlib import Path

from isuctl.config import Host, SshConfig


class RemoteError(RuntimeError):
    pass


def ssh_base_args(ssh: SshConfig) -> list[str]:
    key = str(Path(ssh.key).expanduser())
    return [
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
    ]


def run_ssh(
    ssh: SshConfig,
    host: Host,
    remote_command: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ssh",
        *ssh_base_args(ssh),
        f"{ssh.user}@{host.host}",
        remote_command,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"ssh failed: {cmd}")
    return result


def _rsync(ssh: SshConfig, source: str, dest: str, excludes: list[str] | None) -> None:
    key = str(Path(ssh.key).expanduser())
    cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -i {key} -o StrictHostKeyChecking=accept-new -o BatchMode=yes",
    ]
    for ex in excludes or []:
        cmd.extend(["--exclude", ex])
    cmd.extend([source, dest])
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        raise RemoteError(result.stderr.strip() or f"rsync failed: {cmd}")


def rsync_from_remote(
    ssh: SshConfig,
    host: Host,
    remote_path: str,
    local_path: Path,
    *,
    excludes: list[str] | None = None,
) -> None:
    local_path.mkdir(parents=True, exist_ok=True)
    source = f"{ssh.user}@{host.host}:{remote_path.rstrip('/')}/"
    _rsync(ssh, source, str(local_path) + "/", excludes)


def rsync_to_remote(
    ssh: SshConfig,
    host: Host,
    local_path: Path,
    remote_path: str,
    *,
    excludes: list[str] | None = None,
) -> None:
    source = str(local_path).rstrip("/") + "/"
    dest = f"{ssh.user}@{host.host}:{remote_path.rstrip('/')}/"
    _rsync(ssh, source, dest, excludes)
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/isuctl/remote.py tests/test_remote.py
git commit -m "$(cat <<'EOF'
feat: add SSH and rsync remote helpers

EOF
)"
```

---

### Task 4: `discover`

**Files:**
- Create: `src/isuctl/discover.py`
- Create: `tests/test_discover.py`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- Consumes: `run_ssh`, `IsuconConfig`, `save_config`
- Produces: `discover_host(ssh, host) -> dict[str, object]` updating host roles / `remote_app_dir`; `run_discover(config_path: Path) -> IsuconConfig`

Discovery probes (remote shell one-liner / small script):

1. Prefer existing dirs in order: `/home/isucon/webapp`, `/home/isucon/isunum`, `/home/isucon`
2. Detect python tree if `**/python` or `requirements.txt` / `pyproject.toml` under webapp
3. Detect mysql via `systemctl is-active mysql || systemctl is-active mysqld || true`
4. Detect nginx via `systemctl is-active nginx || true`
5. Write roles: always keep host name; add `web` if nginx active; add `db` if mysql active; add `app` if webapp dir exists

- [ ] **Step 1: Write failing test with mocked `run_ssh`**

```python
# tests/test_discover.py
from pathlib import Path
from unittest.mock import patch
from isuctl.config import IsuconConfig, ProjectConfig, SshConfig, Host, save_config
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
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `discover.py` and wire `isuctl discover`**

Remote probe command (exact string in code):

```bash
set -e
for d in /home/isucon/webapp /home/isucon/isunum /home/isucon; do
  if [ -d "$d" ]; then echo "$d"; break; fi
done
(systemctl is-active nginx 2>/dev/null || echo inactive)
(systemctl is-active mysql 2>/dev/null || systemctl is-active mysqld 2>/dev/null || echo inactive)
```

Parse three lines → update config → `save_config`.

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: add discover command to probe remote layout

EOF
)"
```

---

### Task 5: `sync-down` + ready marker

**Files:**
- Create: `src/isuctl/sync_down.py`
- Create: `tests/test_sync_down.py`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- Consumes: `rsync_from_remote`, `mark_ready`, `load_config`
- Produces: `run_sync_down(config_path: Path) -> Path` (local work dir)

Default excludes: `.git`, `__pycache__`, `node_modules`, `vendor`, `*.log`, `.venv`, `venv`, `tmp`

Behavior:

1. Load config; require ≥1 host
2. Choose primary host: first with role `app`, else `hosts[0]`
3. Resolve `local_dir` relative to cwd; mkdir
4. rsync remote_app_dir → local_dir
5. Also attempt rsync of `/home/isucon/env.sh` and `/home/isucon/webapp/sql` or `.../schema.sql` if present (best-effort; ignore missing via separate ssh test or rsync toleration — implement as optional second/third rsync only if remote path exists via `run_ssh test -e`)
6. `mark_ready(local_dir)`
7. If local_dir is not a git repo, run `git init` + initial commit of synced files (subprocess)

- [ ] **Step 1: Failing test** — mock `rsync_from_remote` and `run_ssh`; assert marker created and rsync called with excludes

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement + `isuctl sync-down`**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: add sync-down from EC2 and ready marker

EOF
)"
```

---

### Task 6: `snapshot`

**Files:**
- Create: `src/isuctl/snapshot.py`
- Create: `tests/test_snapshot.py`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- Produces: `run_snapshot(config_path: Path, label: str | None = None) -> str` remote tarball path

Remote command creates `/home/isucon/snapshots/snap-YYYYMMDD-HHMMSS.tar.gz` of `remote_app_dir` (+ `/etc/nginx` if readable). Return remote path string.

- [ ] **Step 1: Test with mocked `run_ssh` asserting command contains `tar` and snapshots dir**

- [ ] **Step 2–5:** Implement, wire `isuctl snapshot`, commit

```bash
git commit -m "$(cat <<'EOF'
feat: add remote snapshot command

EOF
)"
```

---

### Task 7: `deploy` + guard + `rollback`

**Files:**
- Create: `src/isuctl/deploy.py`
- Create: `src/isuctl/rollback.py`
- Create: `tests/test_deploy.py`
- Create: `tests/test_rollback.py`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- Produces:
  - `DeployBlockedError`
  - `run_deploy(config_path: Path, *, force: bool = False, restart_unit: str = "isucon-python.service") -> None`
  - `run_rollback(config_path: Path, git_ref: str = "HEAD~1", *, force: bool = False) -> None`

Deploy steps:

1. Load config; resolve local_dir
2. If not `is_ready(local_dir)` and not `force`: raise `DeployBlockedError`
3. Optional: create local git tag `pre-deploy-TIMESTAMP` if repo
4. `rsync_to_remote` with same excludes as sync-down **plus** `.isucon-ready`
5. `run_ssh` restart: `sudo systemctl restart {restart_unit} || sudo systemctl restart isucon-webapp || true` — actually prefer configurable unit in toml later; for v1 try common names then `echo restarted`
6. Health: `run_ssh 'curl -fsS http://127.0.0.1/ || curl -fsS http://127.0.0.1:8080/ || true'`

Rollback:

1. Require ready (same guard)
2. `git -C local_dir checkout/ref` via `git reset --hard {git_ref}` only if clean policy: use `git switch --detach` + warn — **v1: `git -C local reset --hard REF` then `run_deploy(..., force=True)`**

- [ ] **Step 1: Tests**

```python
def test_deploy_blocked_without_ready(tmp_path):
    # config pointing at empty work dir without marker
    # expect DeployBlockedError
    ...

def test_deploy_runs_when_ready(tmp_path):
    # mark_ready, mock rsync_to_remote + run_ssh
    ...
```

- [ ] **Step 2–5:** Implement, wire `deploy` / `rollback`, commit

```bash
git commit -m "$(cat <<'EOF'
feat: add guarded deploy and rollback

EOF
)"
```

---

### Task 8: `bootstrap`

**Files:**
- Create: `src/isuctl/bootstrap.py`
- Create: `src/isuctl/templates/nginx_ltsv.conf`
- Create: `src/isuctl/templates/mysql_slow.cnf`
- Create: `tests/test_bootstrap.py`
- Modify: `src/isuctl/cli.py`
- Modify: `pyproject.toml` to include package data templates

**Interfaces:**
- Produces: `run_bootstrap(config_path: Path) -> None`

Actions (idempotent-ish):

1. Ensure remote dirs for logs exist
2. Upload nginx LTSV snippet to `/home/isucon/isuctl/nginx_ltsv.conf` and print instruction to include it (do not silently overwrite whole nginx.conf)
3. Upload mysql slow snippet similarly
4. `sudo` copy into `/etc/nginx/conf.d/isuctl_ltsv.conf` and `/etc/mysql/conf.d/isuctl_slow.cnf` when permitted; reload nginx; note mysql may need restart
5. Install alp binary if missing (detect arch via `uname -m`, download release) — best-effort with clear message on failure

Template nginx:

```nginx
log_format ltsv "time:$time_iso8601\t"
                "remote_addr:$remote_addr\t"
                "request_method:$request_method\t"
                "uri:$request_uri\t"
                "status:$status\t"
                "request_time:$request_time\t"
                "upstream_response_time:$upstream_response_time";
access_log /var/log/nginx/access.log ltsv;
```

Template mysql:

```ini
[mysqld]
slow_query_log = 1
slow_query_log_file = /var/log/mysql/mysql-slow.log
long_query_time = 0
log_queries_not_using_indexes = 1
```

- [ ] **Step 1: Test that bootstrap calls upload paths / ssh with mocked remote**

- [ ] **Step 2–5:** Implement, commit

```bash
git commit -m "$(cat <<'EOF'
feat: add bootstrap for nginx LTSV and MySQL slow log

EOF
)"
```

---

### Task 9: `pull` + `analyze` + `bench-note`

**Files:**
- Create: `src/isuctl/pull.py`
- Create: `src/isuctl/analyze.py`
- Create: `src/isuctl/bench_note.py`
- Create: `tests/test_pull.py`
- Create: `tests/test_analyze.py`
- Create: `tests/test_bench_note.py`
- Create: `tests/fixtures/sample_access.ltsv`
- Create: `tests/fixtures/sample_slow.log`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- `run_pull(config_path) -> Path` → creates `out/raw/<timestamp>/` with copied logs
- `run_analyze(raw_dir: Path | None = None) -> Path` → writes `out/analyze/<timestamp>/{alp.json,slow.txt,summary.md}`
- `run_bench_note(score: int, note: str = "") -> Path` → appends `out/scores.jsonl`

Pull remote paths (try in order via `test -e`):

- `/var/log/nginx/access.log`
- `/var/log/mysql/mysql-slow.log`
- `/tmp/mysql-slow.log`

Analyze:

- Prefer calling `alp ltsv` if binary exists; else parse LTSV in Python grouping by `uri` summing `request_time`
- Prefer `pt-query-digest` if exists; else write first 200 slow lines + note

Fixture-driven unit tests must not require alp installed: force Python fallback path.

- [ ] **Step 1: Write fixture + tests for Python alp fallback aggregation**

Sample LTSV two URIs; assert summary ranks by sum time.

- [ ] **Step 2–5:** Implement all three commands, commit

```bash
git commit -m "$(cat <<'EOF'
feat: add pull, analyze, and bench-note commands

EOF
)"
```

---

### Task 10: `pack`

**Files:**
- Create: `src/isuctl/pack.py`
- Create: `tests/test_pack.py`
- Modify: `src/isuctl/cli.py`

**Interfaces:**
- `run_pack(config_path: Path, analyze_dir: Path | None = None) -> Path` → `out/pack.md`

`pack.md` sections (exact headings):

```markdown
# ISUCON Analysis Pack

## Top Endpoints
...

## Top SQLs
...

## Candidate Code Locations
...

## Schema Excerpt
...

## Next Hypotheses
- [ ]
```

Candidate code: ripgrep/`Path.rglob` over `local_dir` for endpoint path segments and SQL table names from summary (simple heuristics).

- [ ] **Step 1: Test pack writes all required headings given fake analyze summary**

- [ ] **Step 2–5:** Implement, commit

```bash
git commit -m "$(cat <<'EOF'
feat: add pack command for Cursor analysis bundles

EOF
)"
```

---

### Task 11: pprotein helper docs (no VPC co-location)

**Files:**
- Create: `assets/pprotein/README.md`
- Create: `scripts/dogfood-checklist.md`
- Modify: `README.md` (link to both)

**Content requirements for `assets/pprotein/README.md`:**

- Install pprotein on **laptop** or separate non-contest network
- SSH local forward example: `ssh -L 19000:127.0.0.1:19000 isucon@HOST`
- Explicit warning: do **not** place monitoring EC2 in the contest VPC
- Point to `isuctl bootstrap` for log format prerequisites
- Link upstream: `https://github.com/kaz/pprotein`

**Dogfood checklist** must include:

1. Launch ISUCON14 AMI in `ap-northeast-1`
2. `isuctl init-config --host ...`
3. `discover` → `sync-down` → `snapshot` → `bootstrap`
4. Dummy edit → `deploy`
5. `pull` → `analyze` → `pack`
6. Stop/terminate instance

- [ ] **Step 1: Write the two markdown files (no code test; review headings exist)**

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: add pprotein setup notes and dogfood checklist

EOF
)"
```

---

### Task 12: End-to-end dry run against local fake remote (optional CI smoke)

**Files:**
- Create: `tests/test_e2e_fake_remote.py`
- Create: `tests/fixtures/fake_remote_tree/webapp/app.py`
- Create: `tests/fixtures/fake_remote_tree/webapp/sql/schema.sql`

**Approach:** Use a temp “remote” directory and monkeypatch `run_ssh` / rsync functions to copy locally, exercising `sync_down → mark_ready → deploy guard → analyze fixtures → pack` without AWS.

- [ ] **Step 1: Write e2e test**

- [ ] **Step 2: Run `pytest -v` full suite — all PASS**

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
test: add fake-remote end-to-end smoke for core loop

EOF
)"
```

---

## Self-Review (plan vs spec)

| Spec item | Task |
|---|---|
| `isucon.toml` + paths | Task 2 |
| SSH/rsync | Task 3 |
| discover / sync-down / snapshot | Tasks 4–6 |
| deploy guard + rollback | Task 7 |
| bootstrap nginx/mysql | Task 8 |
| pull / analyze / bench-note | Task 9 |
| pack for Cursor | Task 10 |
| pprotein (not custom dashboard) | Task 11 |
| ISUCON14 dogfood | Task 11 checklist (+ manual) |
| No GHA deploy / no heavy o11y | Global constraints + Task 11 warning |
| EC2 as source of truth | Task 5 sync-down first |

No intentional TBD placeholders remain in task steps.
