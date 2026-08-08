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
from isuctl.ensure_access import run_ensure_access
from isuctl.pack import run_pack
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
    """ISUCON 計測→改善ループ用キット。"""


@app.command("init-config")
def init_config(
    name: str = typer.Option("isucon", help="プロジェクト名"),
    host: str = typer.Option(..., help="プライマリホストの IP / DNS"),
    user: str = typer.Option("isucon", help="SSH ユーザー"),
    key: str = typer.Option("~/.ssh/id_ed25519", help="SSH 秘密鍵パス"),
) -> None:
    """isucon.toml を新規作成する。"""
    path = default_config_path()
    if path.exists():
        typer.secho(f"すでに存在します: {path}", fg=typer.colors.RED)
        raise typer.Exit(1)
    cfg = IsuconConfig(
        project=ProjectConfig(name=name, local_dir="./work"),
        ssh=SshConfig(user=user, key=key),
        hosts=[Host(name="app1", host=host, role=["app", "web", "db"])],
    )
    save_config(path, cfg)
    typer.echo(f"作成しました: {path}")


@app.command("ensure-access")
def ensure_access(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """bootstrap_user (ubuntu) の SSH 鍵を競技ユーザー (isucon) へコピーする。"""
    run_ensure_access(config)


@app.command("discover")
def discover(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """リモートを探索して roles / remote_app_dir を埋める。"""
    cfg = run_discover(config)
    for h in cfg.hosts:
        roles = ", ".join(h.role) or "(なし)"
        typer.echo(f"{h.name} ({h.host}): roles=[{roles}] remote_app_dir={h.remote_app_dir}")
    typer.echo(f"更新しました: {config}")


@app.command("sync-down")
def sync_down(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """EC2 から手元へコードを取得する。"""
    local_dir = run_sync_down(config)
    typer.echo(f"同期先: {local_dir}")


@app.command("deploy")
def deploy(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
    force: bool = typer.Option(
        False, "--force", help="ready マーカーなしでもデプロイする"
    ),
) -> None:
    """手元の変更をリモートへ rsync デプロイする。"""
    try:
        run_deploy(config, force=force)
    except DeployBlockedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo("デプロイ完了")


@app.command("rollback")
def rollback(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
    git_ref: str = typer.Option("HEAD~1", "--ref", help="戻す git ref"),
    force: bool = typer.Option(
        False, "--force", help="ready マーカーなしでもロールバックする"
    ),
) -> None:
    """指定 ref に戻して再デプロイする。"""
    try:
        run_rollback(config, git_ref=git_ref, force=force)
    except DeployBlockedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo(f"{git_ref} へロールバックしてデプロイしました")


@app.command("bootstrap")
def bootstrap(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """nginx LTSV / MySQL slow / alp / pt-query-digest などを初期配備する。"""
    run_bootstrap(config)
    typer.echo("bootstrap 完了")


@app.command("snapshot")
def snapshot(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
    label: str | None = typer.Option(None, "--label", "-l", help="任意のスナップショット名"),
) -> None:
    """リモートに復元ポイントを作る。"""
    remote_path = run_snapshot(config, label=label)
    typer.echo(f"snapshot: {remote_path}")


@app.command("pull")
def pull(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """リモートからログを取得する。"""
    raw_dir = run_pull(config)
    typer.echo(f"取得先: {raw_dir}")


@app.command("analyze")
def analyze(
    raw_dir: Path | None = typer.Option(
        None, "--raw-dir", help="生ログディレクトリ（省略時は最新の out/raw/*）"
    ),
) -> None:
    """alp / slow 解析を実行する。"""
    out = run_analyze(raw_dir)
    typer.echo(f"解析結果: {out}")


@app.command("pack")
def pack(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
    analyze_dir: Path | None = typer.Option(
        None, "--analyze-dir", help="解析結果ディレクトリ（省略時は最新の out/analyze/*）"
    ),
) -> None:
    """Cursor 用の分析パックを作る。"""
    path = run_pack(config, analyze_dir)
    typer.echo(f"パック出力: {path}")


@app.command("bench-note")
def bench_note(
    score: int = typer.Argument(..., help="ベンチマークスコア"),
    note: str = typer.Option("", "--note", "-n", help="任意メモ"),
) -> None:
    """スコアとメモを履歴に残す。"""
    path = run_bench_note(score, note=note)
    typer.echo(f"記録先: {path}")
