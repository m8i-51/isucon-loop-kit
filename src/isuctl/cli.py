from collections.abc import Callable
from pathlib import Path

import typer

from isuctl import __version__
from isuctl.analyze import run_analyze
from isuctl.bench_note import (
    compare_score,
    format_comparison_lines,
    format_history_lines,
    read_scores,
    run_bench_note,
)
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
from isuctl.remote import RemoteError
from isuctl.rollback import run_rollback
from isuctl.snapshot import run_snapshot
from isuctl.sync_down import run_sync_down

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _cli_call[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    try:
        return fn(*args, **kwargs)
    except (DeployBlockedError, RemoteError, ValueError, RuntimeError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc


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
    bootstrap_user: str = typer.Option(
        "ubuntu", help="AMI 初期ユーザー（ensure-access で鍵をコピーする元）"
    ),
) -> None:
    """isucon.toml を新規作成する。"""
    path = default_config_path()
    if path.exists():
        typer.secho(f"すでに存在します: {path}", fg=typer.colors.RED)
        raise typer.Exit(1)
    cfg = IsuconConfig(
        project=ProjectConfig(name=name, local_dir="./work"),
        ssh=SshConfig(user=user, key=key, bootstrap_user=bootstrap_user),
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
    _cli_call(run_ensure_access, config)


@app.command("discover")
def discover(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """リモートを探索して roles / remote_app_dir を埋める。"""
    cfg = _cli_call(run_discover, config)
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
    local_dir = _cli_call(run_sync_down, config)
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
    _cli_call(run_deploy, config, force=force)
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
    """指定 ref に戻して再デプロイする（git reset --hard）。"""
    _cli_call(run_rollback, config, git_ref=git_ref, force=force)
    typer.echo(f"{git_ref} へロールバックしてデプロイしました")


@app.command("bootstrap")
def bootstrap(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """nginx LTSV / MySQL slow / alp / pt-query-digest などを初期配備する。"""
    _cli_call(run_bootstrap, config)
    typer.echo("bootstrap 完了")


@app.command("snapshot")
def snapshot(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
    label: str | None = typer.Option(None, "--label", "-l", help="任意のスナップショット名"),
) -> None:
    """リモートに復元ポイントを作る。"""
    remote_path = _cli_call(run_snapshot, config, label=label)
    typer.echo(f"snapshot: {remote_path}")


@app.command("pull")
def pull(
    config: Path = typer.Option(
        default_config_path(), "--config", "-c", help="isucon.toml のパス"
    ),
) -> None:
    """リモートからログを取得する。"""
    raw_dir = _cli_call(run_pull, config)
    typer.echo(f"取得先: {raw_dir}")


@app.command("analyze")
def analyze(
    raw_dir: Path | None = typer.Option(
        None, "--raw-dir", help="生ログディレクトリ（省略時は最新の out/raw/*）"
    ),
) -> None:
    """alp / slow 解析を実行する。"""
    out = _cli_call(run_analyze, raw_dir)
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
    path = _cli_call(run_pack, config, analyze_dir)
    typer.echo(f"パック出力: {path}")


@app.command("bench-note")
def bench_note(
    score: int | None = typer.Argument(
        None, help="ベンチマークスコア（省略時は対話入力）"
    ),
    note: str = typer.Option("", "--note", "-n", help="任意メモ"),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="低下時の確認プロンプトをスキップする"
    ),
) -> None:
    """ベンチ後のスコアをユーザー報告として履歴に残す。"""
    history = read_scores()
    for line in format_history_lines(history):
        typer.echo(line)

    if score is None:
        score = typer.prompt("ベンチ後のスコアを入力してください", type=int)

    comparison = compare_score(score, history)
    for line in format_comparison_lines(comparison):
        if line.startswith("注意:"):
            typer.secho(line, fg=typer.colors.YELLOW)
        else:
            typer.echo(line)

    if (
        comparison.is_regression_vs_previous
        and not yes
        and not typer.confirm("前回より低いスコアを記録しますか?", default=True)
    ):
        typer.echo("記録をキャンセルしました")
        raise typer.Exit(1)

    path = run_bench_note(score, note=note)
    typer.echo(f"記録先: {path}")
