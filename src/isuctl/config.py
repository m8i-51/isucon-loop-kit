from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProjectConfig(BaseModel):
    name: str
    local_dir: str = "./work"


class SshConfig(BaseModel):
    user: str = "isucon"
    key: str = "~/.ssh/id_ed25519"
    bootstrap_user: str = "ubuntu"


class Host(BaseModel):
    name: str
    host: str
    role: list[str] = Field(default_factory=lambda: ["app"])
    remote_app_dir: str = "/home/isucon/webapp"
    # Empty transport follows the file: compose when [compose] is set, else ssh.
    transport: Literal["", "ssh", "compose"] = ""
    service: str = ""
    exec_user: str = ""
    access_log: str = ""
    access_time_unit: Literal["s", "ms", "us"] = "s"
    slow_log: str = ""
    slow_log_via: Literal["file", "stderr"] = "file"
    db_kind: Literal["", "mysql", "postgres"] = ""


_SLOW_THRESHOLD_RE = re.compile(r"^(0|[1-9][0-9]*)(us|ms|s|min|h|d)?$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ComposeConfig(BaseModel):
    """Local docker compose project that stands in for contest hosts.

    ``project_dir`` is relative to the config file unless it is absolute.
    ``source_dest`` is the build-context subdirectory that ``deploy`` replaces
    with ``git archive`` of ``--branch`` (the Dockerfile stays put).
    """

    project_dir: str
    file: str = ""
    project_name: str = ""
    build: list[str] = Field(default_factory=list)
    up: list[str] = Field(default_factory=list)
    source_dest: str = ""
    bench_service: str = ""
    bench_profile: str = ""
    bench_command: list[str] = Field(default_factory=list)
    slow_threshold: str = "200ms"
    db_name: str = "postgres"
    db_user: str = "postgres"
    http_url: str = "http://127.0.0.1/"

    @field_validator("bench_command", mode="before")
    @classmethod
    def _split_bench_command(cls, value: object) -> object:
        if isinstance(value, str):
            return shlex.split(value)
        return value

    @field_validator("slow_threshold")
    @classmethod
    def _check_threshold(cls, value: str) -> str:
        if not _SLOW_THRESHOLD_RE.fullmatch(value):
            raise ValueError("slow_threshold は 200ms のような値です")
        return value

    @field_validator("db_name", "db_user")
    @classmethod
    def _check_ident(cls, value: str) -> str:
        if not _IDENT_RE.fullmatch(value):
            raise ValueError("db_name / db_user は識別子にしてください")
        return value


class IsuconConfig(BaseModel):
    project: ProjectConfig
    ssh: SshConfig = Field(default_factory=SshConfig)
    hosts: list[Host] = Field(default_factory=list)
    compose: ComposeConfig | None = None


def default_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "isucon.toml"


def load_config(path: Path) -> IsuconConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return IsuconConfig.model_validate(data)


def uses_compose(config: IsuconConfig) -> bool:
    """True when this file drives the docker compose transport."""
    if config.compose is not None:
        return True
    return any(host.transport == "compose" for host in config.hosts)


def config_uses_compose(path: Path) -> bool:
    if not path.is_file():
        return False
    return uses_compose(load_config(path))


def save_config(path: Path, config: IsuconConfig) -> None:
    lines: list[str] = []
    lines.append("[project]")
    lines.append(f"name = {_toml_str(config.project.name)}")
    lines.append(f"local_dir = {_toml_str(config.project.local_dir)}")
    lines.append("")
    lines.append("[ssh]")
    lines.append(f"user = {_toml_str(config.ssh.user)}")
    lines.append(f"key = {_toml_str(config.ssh.key)}")
    lines.append(f"bootstrap_user = {_toml_str(config.ssh.bootstrap_user)}")
    lines.append("")
    if config.compose is not None:
        lines.extend(_compose_lines(config.compose))
        lines.append("")
    for host in config.hosts:
        lines.extend(_host_lines(host))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(item) for item in values) + "]"


def _compose_lines(compose: ComposeConfig) -> list[str]:
    lines = ["[compose]", f"project_dir = {_toml_str(compose.project_dir)}"]
    optional_strings = (
        ("file", compose.file, ""),
        ("project_name", compose.project_name, ""),
        ("source_dest", compose.source_dest, ""),
        ("bench_service", compose.bench_service, ""),
        ("bench_profile", compose.bench_profile, ""),
        ("slow_threshold", compose.slow_threshold, "200ms"),
        ("db_name", compose.db_name, "postgres"),
        ("db_user", compose.db_user, "postgres"),
        ("http_url", compose.http_url, "http://127.0.0.1/"),
    )
    for key, value, default in optional_strings:
        if value != default:
            lines.append(f"{key} = {_toml_str(value)}")
    if compose.build:
        lines.append(f"build = {_toml_list(compose.build)}")
    if compose.up:
        lines.append(f"up = {_toml_list(compose.up)}")
    if compose.bench_command:
        lines.append(f"bench_command = {_toml_list(compose.bench_command)}")
    return lines


def _host_lines(host: Host) -> list[str]:
    role = _toml_list(host.role)
    lines = [
        "[[hosts]]",
        f"name = {_toml_str(host.name)}",
        f"host = {_toml_str(host.host)}",
        f"role = {role}",
        f"remote_app_dir = {_toml_str(host.remote_app_dir)}",
    ]
    if host.transport:
        lines.append(f"transport = {_toml_str(host.transport)}")
    if host.service:
        lines.append(f"service = {_toml_str(host.service)}")
    if host.exec_user:
        lines.append(f"exec_user = {_toml_str(host.exec_user)}")
    if host.access_log:
        lines.append(f"access_log = {_toml_str(host.access_log)}")
    if host.access_time_unit != "s":
        lines.append(f"access_time_unit = {_toml_str(host.access_time_unit)}")
    if host.slow_log:
        lines.append(f"slow_log = {_toml_str(host.slow_log)}")
    if host.slow_log_via != "file":
        lines.append(f"slow_log_via = {_toml_str(host.slow_log_via)}")
    if host.db_kind:
        lines.append(f"db_kind = {_toml_str(host.db_kind)}")
    return lines
