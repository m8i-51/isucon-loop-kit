from __future__ import annotations

from pathlib import Path

import tomllib
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    name: str
    local_dir: str = "./work"


class SshConfig(BaseModel):
    user: str = "isucon"
    key: str = "~/.ssh/id_ed25519"


class Host(BaseModel):
    name: str
    host: str
    role: list[str] = Field(default_factory=lambda: ["app"])
    remote_app_dir: str = "/home/isucon/webapp"


class IsuconConfig(BaseModel):
    project: ProjectConfig
    ssh: SshConfig = Field(default_factory=SshConfig)
    hosts: list[Host] = Field(default_factory=list)


def default_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "isucon.toml"


def load_config(path: Path) -> IsuconConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return IsuconConfig.model_validate(data)


def save_config(path: Path, config: IsuconConfig) -> None:
    lines: list[str] = []
    lines.append("[project]")
    lines.append(f'name = "{config.project.name}"')
    lines.append(f'local_dir = "{config.project.local_dir}"')
    lines.append("")
    lines.append("[ssh]")
    lines.append(f'user = "{config.ssh.user}"')
    lines.append(f'key = "{config.ssh.key}"')
    lines.append("")
    for h in config.hosts:
        lines.append("[[hosts]]")
        lines.append(f'name = "{h.name}"')
        lines.append(f'host = "{h.host}"')
        role = ", ".join(f'"{r}"' for r in h.role)
        lines.append(f"role = [{role}]")
        lines.append(f'remote_app_dir = "{h.remote_app_dir}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
