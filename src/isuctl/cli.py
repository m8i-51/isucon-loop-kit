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
