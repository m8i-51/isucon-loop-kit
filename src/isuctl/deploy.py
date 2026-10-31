from __future__ import annotations

from pathlib import Path

from isuctl.ansible_run import AnsibleError, run_playbook


class DeployBlockedError(RuntimeError):
    """Kept for rollback / callers that still catch this name."""


def run_deploy(
    config_path: Path | None = None,
    *,
    branch: str,
    limit: str | None = None,
    force: bool = False,
    restart_unit: str | None = None,
) -> None:
    """Deploy via ansible/playbooks/deploy.yml.

    ``config_path``, ``force``, and ``restart_unit`` are accepted for CLI
    compatibility but ignored — Ansible inventory/group_vars own that state.
    The playbook checks out ``branch`` from ``repo_url``; it does not rsync
    the local worktree.
    """
    del config_path, force, restart_unit  # unused by design
    branch = branch.strip()
    if not branch:
        raise DeployBlockedError("branch が空です。--branch を指定してください。")
    try:
        run_playbook("deploy.yml", extra_vars={"branch": branch}, limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc


def run_check(*, limit: str | None = None) -> None:
    try:
        run_playbook("check.yml", limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc


def run_provision(*, limit: str | None = None) -> None:
    """First-hour init playbook."""
    try:
        run_playbook("init.yml", limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc
