from __future__ import annotations

import subprocess
from pathlib import Path

from isuctl.config import load_config
from isuctl.deploy import DeployBlockedError, run_deploy
from isuctl.paths import is_ready


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
            f"local dir is not ready: run sync-down first or use --force ({local_dir})"
        )

    if not config.hosts:
        raise ValueError("config must have at least one host")

    subprocess.run(
        ["git", "-C", str(local_dir), "reset", "--hard", git_ref],
        check=True,
        capture_output=True,
        text=True,
    )
    run_deploy(config_path, force=True)
