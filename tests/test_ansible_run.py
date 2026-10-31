import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from isuctl.ansible_run import AnsibleError, repo_root, run_playbook


def _kit(tmp_path: Path) -> Path:
    playbooks = tmp_path / "ansible" / "playbooks"
    playbooks.mkdir(parents=True)
    (playbooks / "deploy.yml").write_text("---\n", encoding="utf-8")
    (playbooks / "check.yml").write_text("---\n", encoding="utf-8")
    return tmp_path


def test_repo_root_walks_parents(tmp_path: Path):
    root = _kit(tmp_path)
    nested = root / "work" / "webapp"
    nested.mkdir(parents=True)
    assert repo_root(nested) == root


def test_repo_root_missing(tmp_path: Path):
    with pytest.raises(AnsibleError, match="ansible/playbooks"):
        repo_root(tmp_path)


def test_run_playbook_builds_command(tmp_path: Path):
    root = _kit(tmp_path)
    completed = subprocess.CompletedProcess(args=[], returncode=0)
    with (
        patch(
            "isuctl.ansible_run.shutil.which", return_value="/usr/bin/ansible-playbook"
        ),
        patch("isuctl.ansible_run.subprocess.run", return_value=completed) as run,
    ):
        run_playbook(
            "deploy.yml",
            extra_vars={"branch": "feat/x"},
            limit=" s1,s2 ",
            cwd=root / "work",
        )
    cmd = run.call_args.args[0]
    assert cmd == [
        "/usr/bin/ansible-playbook",
        "playbooks/deploy.yml",
        "--limit",
        "s1,s2",
        "-e",
        "branch=feat/x",
    ]
    assert run.call_args.kwargs["cwd"] == root / "ansible"


def test_run_playbook_missing_file(tmp_path: Path):
    root = _kit(tmp_path)
    with pytest.raises(AnsibleError, match="playbook がありません"):
        run_playbook("missing.yml", cwd=root)


def test_run_playbook_missing_binary(tmp_path: Path):
    root = _kit(tmp_path)
    with (
        patch("isuctl.ansible_run.shutil.which", return_value=None),
        pytest.raises(AnsibleError, match="PATH"),
    ):
        run_playbook("check.yml", cwd=root)


def test_run_playbook_nonzero_exit(tmp_path: Path):
    root = _kit(tmp_path)
    completed = subprocess.CompletedProcess(args=[], returncode=2)
    with (
        patch(
            "isuctl.ansible_run.shutil.which", return_value="/usr/bin/ansible-playbook"
        ),
        patch("isuctl.ansible_run.subprocess.run", return_value=completed),
        pytest.raises(AnsibleError, match="exit 2"),
    ):
        run_playbook("deploy.yml", cwd=root)
