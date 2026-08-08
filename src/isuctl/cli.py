from pathlib import Path

import typer

from isuctl import __version__
from isuctl.config import (
    Host,
    IsuconConfig,
    ProjectConfig,
    SshConfig,
    default_config_path,
    save_config,
)
from isuctl.discover import run_discover
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


# placeholder so imports stay stable; real commands added in later tasks
@app.command("ping")
def ping() -> None:
    typer.echo("pong")
