from __future__ import annotations

import subprocess
from pathlib import Path

from isuctl.config import load_config
from isuctl.deploy import DeployBlockedError, run_deploy
from isuctl.hostsutil import primary_host
from isuctl.paths import is_ready


def _worktree_is_dirty(local_dir: Path) -> bool:
    if not (local_dir / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(local_dir), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def run_rollback(
    config_path: Path,
    git_ref: str = "HEAD~1",
    *,
    force: bool = False,
) -> None:
    config = load_config(config_path)
    local_dir = (Path.cwd() / config.project.local_dir).resolve()
    if not is_ready(local_dir) and not force:
        raise DeployBlockedError(
            f"local dir が未準備です: 先に sync-down するか --force を使ってください ({local_dir})"
        )

    primary_host(config.hosts)
    if _worktree_is_dirty(local_dir) and not force:
        raise DeployBlockedError(
            f"未コミットの変更があります。"
            f"コミットするか --force を使ってください ({local_dir})"
        )

    subprocess.run(
        ["git", "-C", str(local_dir), "reset", "--hard", git_ref],
        check=True,
        capture_output=True,
        text=True,
    )
    run_deploy(config_path, force=True)
