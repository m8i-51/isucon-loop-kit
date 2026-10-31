from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AnsibleError(RuntimeError):
    pass


def repo_root(cwd: Path | None = None) -> Path:
    """Find the loop-kit root (directory that contains ansible/playbooks)."""
    start = (cwd or Path.cwd()).resolve()
    for path in [start, *start.parents]:
        if (path / "ansible" / "playbooks").is_dir():
            return path
    raise AnsibleError(
        "ansible/playbooks が見つかりません。"
        "isucon-loop-kit のルートで実行してください。"
    )


def ansible_dir(cwd: Path | None = None) -> Path:
    return repo_root(cwd) / "ansible"


def run_playbook(
    playbook: str,
    *,
    extra_vars: dict[str, str] | None = None,
    limit: str | None = None,
    cwd: Path | None = None,
) -> None:
    """Run ansible-playbook <playbook> inside ansible/. playbook is a name like deploy.yml."""
    adir = ansible_dir(cwd)
    playbook_path = adir / "playbooks" / playbook
    if not playbook_path.is_file():
        raise AnsibleError(f"playbook がありません: {playbook_path}")

    ansible_bin = shutil.which("ansible-playbook")
    if not ansible_bin:
        raise AnsibleError(
            "ansible-playbook が PATH にありません。`brew install ansible` など。"
        )

    cmd = [ansible_bin, str(playbook_path.relative_to(adir))]
    limit = (limit or "").strip()
    if limit:
        cmd.extend(["--limit", limit])
    for key, value in (extra_vars or {}).items():
        cmd.extend(["-e", f"{key}={value}"])

    proc = subprocess.run(cmd, cwd=adir, check=False)
    if proc.returncode != 0:
        raise AnsibleError(
            f"ansible-playbook が失敗しました (exit {proc.returncode}): {' '.join(cmd)}"
        )
