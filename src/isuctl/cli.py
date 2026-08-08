from pathlib import Path

import typer

from isuctl import __version__
from isuctl.analyze import run_analyze
from isuctl.bench_note import run_bench_note
from isuctl.bootstrap import run_bootstrap
from isuctl.config import (
    Host,
    IsuconConfig,
    ProjectConfig,
    SshConfig,
    default_config_path,
    save_config,
)
from isuctl.deploy import DeployBlockedError, run_deploy
from isuctl.discover import run_discover
from isuctl.pull import run_pull
from isuctl.rollback import run_rollback
from isuctl.snapshot import run_snapshot
from isuctl.sync_down import run_sync_down

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


@app.command("discover")
def discover(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
) -> None:
    cfg = run_discover(config)
    for h in cfg.hosts:
        roles = ", ".join(h.role) or "(none)"
        typer.echo(f"{h.name} ({h.host}): roles=[{roles}] remote_app_dir={h.remote_app_dir}")
    typer.echo(f"updated {config}")


@app.command("sync-down")
def sync_down(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
) -> None:
    local_dir = run_sync_down(config)
    typer.echo(f"synced to {local_dir}")


@app.command("deploy")
def deploy(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
    force: bool = typer.Option(False, "--force", help="Deploy without ready marker"),
) -> None:
    try:
        run_deploy(config, force=force)
    except DeployBlockedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo("deployed")


@app.command("rollback")
def rollback(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
    git_ref: str = typer.Option("HEAD~1", "--ref", help="Git ref to reset to"),
    force: bool = typer.Option(False, "--force", help="Rollback without ready marker"),
) -> None:
    try:
        run_rollback(config, git_ref=git_ref, force=force)
    except DeployBlockedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo(f"rolled back to {git_ref} and deployed")


@app.command("bootstrap")
def bootstrap(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
) -> None:
    run_bootstrap(config)
    typer.echo("bootstrapped")


@app.command("snapshot")
def snapshot(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
    label: str | None = typer.Option(None, "--label", "-l", help="Optional snapshot label"),
) -> None:
    remote_path = run_snapshot(config, label=label)
    typer.echo(f"snapshot: {remote_path}")


@app.command("pull")
def pull(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="Path to isucon.toml"
    ),
) -> None:
    raw_dir = run_pull(config)
    typer.echo(f"pulled to {raw_dir}")


@app.command("analyze")
def analyze(
    raw_dir: Path | None = typer.Option(
        None, "--raw-dir", help="Raw log directory (default: latest out/raw/*)"
    ),
) -> None:
    out = run_analyze(raw_dir)
    typer.echo(f"analyzed to {out}")


@app.command("bench-note")
def bench_note(
    score: int = typer.Argument(..., help="Benchmark score"),
    note: str = typer.Option("", "--note", "-n", help="Optional note"),
) -> None:
    path = run_bench_note(score, note=note)
    typer.echo(f"recorded to {path}")
