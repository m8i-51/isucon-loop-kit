"""Remote log paths shared by the SSH pull and the compose transport."""

from __future__ import annotations

import re

# First existing path for each local name wins. nginx / MySQL stay ahead of
# Apache / PostgreSQL so the old loop still prefers those logs.
REMOTE_LOG_PATHS: list[tuple[str, str]] = [
    ("/var/log/nginx/access.ltsv.log", "access.log"),
    ("/var/log/nginx/access.log", "access.log"),
    ("/var/log/apache2/access.log", "access.log"),
    ("/var/log/httpd/access_log", "access.log"),
    ("/var/log/httpd/access.log", "access.log"),
    ("/var/log/mysql/mysql-slow.log", "mysql-slow.log"),
    ("/tmp/mysql-slow.log", "mysql-slow.log"),
    # log_min_duration_statement is written to the server log, not a separate file.
    ("/var/log/postgresql/*.log", "slow.log"),
    ("/var/lib/postgresql/*/main/log/*.log", "slow.log"),
    ("/var/lib/pgsql/data/log/*.log", "slow.log"),
    ("/var/lib/pgsql/*/data/log/*.log", "slow.log"),
]

_GLOB_META_RE = re.compile(r"[*?]")
_GLOB_SAFE_RE = re.compile(r"^[A-Za-z0-9_./*?-]+$")


def _is_glob(pattern: str) -> bool:
    return _GLOB_META_RE.search(pattern) is not None


def _newest_match_script(pattern: str) -> str:
    """Bash script that prints the newest file matching pattern, or nothing."""
    if not _GLOB_SAFE_RE.fullmatch(pattern):
        raise ValueError(f"unsafe log glob: {pattern}")
    return (
        "shopt -s nullglob; "
        "newest=; newest_mtime=-1; "
        f"for f in {pattern}; do "
        '[ -f "$f" ] || continue; '
        'm=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo -1); '
        'if [ "$m" -gt "$newest_mtime" ]; then newest=$f; newest_mtime=$m; fi; '
        "done; "
        'printf "%s\\n" "$newest"'
    )
