"""Tar invocation shared by SSH and compose snapshots."""

from __future__ import annotations

import re
import shlex

_LABEL_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def snapshot_remote_command(remote_path: str, app_rel: str) -> str:
    """Tar the app dir plus nginx/apache configs that are readable."""
    quoted_remote = shlex.quote(remote_path)
    quoted_app = shlex.quote(app_rel)
    parts = [
        "mkdir -p /home/isucon/snapshots",
        f"set -- {quoted_app}",
        'if [ -r /etc/nginx ]; then set -- "$@" etc/nginx; fi',
        'if [ -r /etc/apache2 ]; then set -- "$@" etc/apache2; fi',
        'if [ -r /etc/httpd ]; then set -- "$@" etc/httpd; fi',
        f'tar czf {quoted_remote} -C / "$@"',
    ]
    return " && ".join(parts)


def snapshot_name(timestamp: str, label: str | None) -> str:
    if not label:
        return f"snap-{timestamp}.tar.gz"
    safe = _LABEL_SAFE_RE.sub("-", label).strip("-.")
    safe = re.sub(r"-{2,}", "-", safe)
    if not safe:
        raise ValueError("snapshot の --label に使える文字がありません")
    return f"snap-{timestamp}-{safe}.tar.gz"
