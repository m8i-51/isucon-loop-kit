from __future__ import annotations

import subprocess
from pathlib import Path

from isuctl.config import load_config
from isuctl.deploy import DeployBlockedError, run_deploy
from isuctl.paths import is_ready


def _git(local_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(local_dir), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else f" (exit {exc.returncode})"
        raise DeployBlockedError(
            f"git {' '.join(args)} に失敗しました{suffix}"
        ) from exc


def _worktree_is_dirty(local_dir: Path) -> bool:
    if not (local_dir / ".git").exists():
        return False
    result = _git(local_dir, "status", "--porcelain")
    return bool(result.stdout.strip())


def run_rollback(
    config_path: Path,
    git_ref: str = "HEAD~1",
    *,
    force: bool = False,
    limit: str | None = None,
) -> None:
    """Reset local worktree to git_ref, then ansible-deploy that SHA.

    The playbook checks out the SHA from ``repo_url``, so the commit must
    already be on that remote. Local-only commits are not uploaded.
    """
    config = load_config(config_path)
    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    if not is_ready(local_dir) and not force:
        raise DeployBlockedError(
            f"local dir が未準備です: 先に sync-down するか --force を使ってください ({local_dir})"
        )
    if not (local_dir / ".git").exists():
        raise DeployBlockedError(f"git リポジトリではありません: {local_dir}")
    if not force and _worktree_is_dirty(local_dir):
        raise DeployBlockedError(
            f"未コミットの変更があります。"
            f"コミットするか --force を使ってください ({local_dir})"
        )

    _git(local_dir, "reset", "--hard", git_ref)
    # Deploy the resolved SHA so remotes match the reset worktree intent.
    sha = _git(local_dir, "rev-parse", "HEAD").stdout.strip()
    if not sha:
        raise DeployBlockedError("HEAD の SHA が取れませんでした")
    run_deploy(config_path, branch=sha, limit=limit, force=True)
