from __future__ import annotations

from pathlib import Path

from isuctl.ansible_run import AnsibleError, run_playbook
from isuctl.compose_transport import check_compose, deploy_compose, provision_compose
from isuctl.config import config_uses_compose
from isuctl.remote import RemoteError


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
    """Deploy via ansible/playbooks/deploy.yml, or docker compose.

    Without a ``[compose]`` config, ``config_path`` is ignored and the
    playbook checks out ``branch`` from ``repo_url``. ``force`` and
    ``restart_unit`` stay unused on that path.

    With ``[compose]``, the git ref is archived into the build context, then
    ``docker compose build`` and ``up -d --wait`` run. Ansible is not called.
    """
    del force, restart_unit  # unused by the ansible path
    branch = branch.strip()
    if not branch:
        raise DeployBlockedError("branch が空です。--branch を指定してください。")
    if config_path is not None and config_uses_compose(config_path):
        try:
            deploy_compose(config_path, branch=branch, limit=limit)
        except (RemoteError, ValueError) as exc:
            raise DeployBlockedError(str(exc)) from exc
        return
    try:
        run_playbook("deploy.yml", extra_vars={"branch": branch}, limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc


def run_check(
    *, limit: str | None = None, config_path: Path | None = None
) -> None:
    if config_path is not None and config_uses_compose(config_path):
        try:
            check_compose(config_path, limit=limit)
        except (RemoteError, ValueError) as exc:
            raise DeployBlockedError(str(exc)) from exc
        return
    try:
        run_playbook("check.yml", limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc


def run_provision(
    *, limit: str | None = None, config_path: Path | None = None
) -> None:
    """First-hour init. Ansible init.yml, or compose up when [compose] is set."""
    if config_path is not None and config_uses_compose(config_path):
        try:
            provision_compose(config_path, limit=limit)
        except (RemoteError, ValueError) as exc:
            raise DeployBlockedError(str(exc)) from exc
        return
    try:
        run_playbook("init.yml", limit=limit)
    except AnsibleError as exc:
        raise DeployBlockedError(str(exc)) from exc
