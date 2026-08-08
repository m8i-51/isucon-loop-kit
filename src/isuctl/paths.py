from __future__ import annotations

from pathlib import Path


def out_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "out"


def ready_marker_path(local_dir: Path) -> Path:
    return local_dir / ".isucon-ready"


def is_ready(local_dir: Path) -> bool:
    return ready_marker_path(local_dir).exists()


def mark_ready(local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    ready_marker_path(local_dir).write_text("ok\n", encoding="utf-8")
