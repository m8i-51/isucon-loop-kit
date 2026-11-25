"""Parse the five-line service probe used by discover."""

from __future__ import annotations


def _status_at(lines: list[str], index: int) -> str:
    if len(lines) <= index:
        return "inactive"
    return lines[index].strip() or "inactive"


def interpret_probe_stdout(stdout: str) -> dict[str, object]:
    """Map probe stdout to role / remote_app_dir updates.

    Line 0 is the app directory. Lines 1–4 are nginx, mysql, apache, postgres,
    each exactly one of ``active`` or ``inactive``.
    """
    lines = stdout.rstrip().splitlines()
    app_dir = lines[0].strip() if len(lines) > 0 else ""
    nginx_status = _status_at(lines, 1)
    mysql_status = _status_at(lines, 2)
    apache_status = _status_at(lines, 3)
    postgres_status = _status_at(lines, 4)

    roles: list[str] = []
    if app_dir.startswith("/"):
        roles.append("app")
    if nginx_status == "active" or apache_status == "active":
        roles.append("web")
    if mysql_status == "active" or postgres_status == "active":
        roles.append("db")

    updates: dict[str, object] = {"role": roles}
    if app_dir.startswith("/"):
        updates["remote_app_dir"] = app_dir
    return updates
