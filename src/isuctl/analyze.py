from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from isuctl.pack import normalize_alp_entry
from isuctl.paths import out_dir

SLOW_FALLBACK_LINES = 200
SLOW_DIGEST_MAX_CHARS = 80_000
SLOW_FALLBACK_TOP_N = 30
SLOW_SQL_DISPLAY_CHARS = 240
QUERY_TIME_RE = re.compile(r"Query_time:\s*([0-9.]+)")
SQL_START_RE = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE)\b",
    re.IGNORECASE,
)
SLOW_LOG_NAMES = ("mysql-slow.log", "slow.log")
PG_DURATION_RE = re.compile(
    r"duration:\s*([0-9.]+)\s*ms\s+"
    r"(?:statement|execute|parse|bind)(?:\s+<[^>]*>)?:\s*(.*)$",
    re.IGNORECASE,
)
POSTGRES_SLOW_MARKER = "# PostgreSQL slow log"
_SLOW_SNIFF_LINES = 20_000
_MYSQL_FALLBACK_NOTE = (
    "- pt-query-digest が使えないため、`slow.txt` の抜粋を参照してください。"
)
_MYSQL_DIGEST_NOTE = "- pt-query-digest 出力は `slow.txt` を参照してください。"
_POSTGRES_NOTE = (
    "- PostgreSQL の slow ログを duration 順に集計しました。`slow.txt` を参照してください。"
)


def normalize_uri(uri: str) -> str:
    """Strip query string and fragment for aggregation."""
    if not uri:
        return uri
    parts = urlsplit(uri)
    path = parts.path or uri.split("?", 1)[0]
    return path or uri


def aggregate_ltsv_by_uri(lines: Iterable[str]) -> list[dict[str, float | int | str]]:
    totals: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "sum_time": 0.0}
    )
    for line in lines:
        if not line.strip():
            continue
        fields = _parse_ltsv_line(line)
        uri = normalize_uri(fields.get("uri", ""))
        if not uri:
            continue
        try:
            request_time = float(fields.get("request_time", "0"))
        except ValueError:
            request_time = 0.0
        totals[uri]["count"] = int(totals[uri]["count"]) + 1
        totals[uri]["sum_time"] = float(totals[uri]["sum_time"]) + request_time

    results: list[dict[str, float | int | str]] = []
    for uri, data in totals.items():
        count = int(data["count"])
        sum_time = float(data["sum_time"])
        results.append(
            {
                "uri": uri,
                "count": count,
                "sum_time": sum_time,
                "avg_time": sum_time / count if count else 0.0,
            }
        )
    results.sort(key=lambda item: float(item["sum_time"]), reverse=True)
    return results


def _parse_ltsv_line(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in line.strip().split("\t"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        fields[key] = value
    return fields


def _latest_raw_dir() -> Path | None:
    raw_root = out_dir() / "raw"
    if not raw_root.exists():
        return None
    dirs = sorted(
        (path for path in raw_root.iterdir() if path.is_dir()),
        reverse=True,
    )
    return dirs[0] if dirs else None


def parse_alp_stdout(text: str) -> list[dict[str, float | int | str]] | None:
    """Parse alp --format json (dict rows or header matrix) or TSV."""
    stripped = text.strip()
    if not stripped:
        return None
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return [item for item in data if isinstance(item, dict)]
        if (
            isinstance(data, list)
            and len(data) >= 2
            and isinstance(data[0], list)
        ):
            headers = [str(h) for h in data[0]]
            rows: list[dict[str, float | int | str]] = []
            for row in data[1:]:
                if not isinstance(row, list):
                    continue
                rows.append(dict(zip(headers, row, strict=False)))
            return rows or None
        return None
    return _parse_alp_tsv(stripped)


def _parse_alp_tsv(text: str) -> list[dict[str, float | int | str]] | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    header = [col.strip() for col in lines[0].split("\t")]
    start = 0
    colnames: list[str]
    if header and header[0] in {"count", "method", "uri"}:
        colnames = header
        start = 1
    else:
        colnames = ["count", "uri", "sum", "avg"]
    rows: list[dict[str, float | int | str]] = []
    for line in lines[start:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rows.append(dict(zip(colnames, parts, strict=False)))
    return rows or None


def _alp_command(access_log: Path) -> list[str]:
    # alp -f is --filters, not the log file. --output is the column list, not JSON.
    return [
        "alp",
        "ltsv",
        "--file",
        str(access_log),
        "--format",
        "tsv",
        "--output",
        "count,uri,sum,avg",
        "--uri-label",
        "uri",
        "--method-label",
        "request_method",
        "--reqtime-label",
        "request_time",
        "--apptime-label",
        "upstream_response_time",
        "--sort",
        "sum",
        "--reverse",
    ]


def _run_alp(access_log: Path) -> list[dict[str, float | int | str]] | None:
    if shutil.which("alp") is None:
        return None
    result = subprocess.run(
        _alp_command(access_log), text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    return parse_alp_stdout(result.stdout)


def _merge_by_normalized_uri(
    alp_data: list[dict[str, float | int | str]],
) -> list[dict[str, float | int | str]]:
    totals: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "sum_time": 0.0}
    )
    for entry in alp_data:
        normalized = normalize_alp_entry(entry)
        uri = normalize_uri(str(normalized["uri"]))
        count = int(normalized["count"])
        sum_time = float(normalized["sum_time"])
        totals[uri]["count"] = int(totals[uri]["count"]) + count
        totals[uri]["sum_time"] = float(totals[uri]["sum_time"]) + sum_time

    results: list[dict[str, float | int | str]] = []
    for uri, data in totals.items():
        count = int(data["count"])
        sum_time = float(data["sum_time"])
        results.append(
            {
                "uri": uri,
                "count": count,
                "sum_time": sum_time,
                "avg_time": sum_time / count if count else 0.0,
            }
        )
    results.sort(key=lambda item: float(item["sum_time"]), reverse=True)
    return results


def _normalize_alp_data(
    alp_data: list[dict[str, float | int | str]],
) -> list[dict[str, float | int | str]]:
    return _merge_by_normalized_uri(alp_data)


def _alp_has_usable_times(
    alp_data: list[dict[str, float | int | str]],
) -> bool:
    normalized = _normalize_alp_data(alp_data)
    return any(float(item["sum_time"]) > 0 for item in normalized)


def _analyze_access(access_log: Path) -> list[dict[str, float | int | str]]:
    alp_data = _run_alp(access_log)
    if alp_data is not None and _alp_has_usable_times(alp_data):
        return _normalize_alp_data(alp_data)
    lines = access_log.read_text(encoding="utf-8").splitlines()
    return aggregate_ltsv_by_uri(lines)


def _run_pt_query_digest(slow_log: Path) -> str | None:
    if shutil.which("pt-query-digest") is None:
        return None
    cmd = ["pt-query-digest", str(slow_log)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def _truncate_slow_output(text: str) -> str:
    if len(text) <= SLOW_DIGEST_MAX_CHARS:
        return text
    return (
        text[:SLOW_DIGEST_MAX_CHARS]
        + "\n\n# isuctl analyze により切り詰め "
        f"（上限 {SLOW_DIGEST_MAX_CHARS} 文字）\n"
    )


def _is_bulk_insert(sql: str) -> bool:
    upper = sql.upper()
    return upper.startswith("INSERT") and "VALUES" in upper and sql.count("(") > 3


def _fallback_slow_summary(slow_log: Path) -> str:
    """Rank MySQL slow-log entries by Query_time when pt-query-digest is missing."""
    entries: list[tuple[float, str]] = []
    current_time: float | None = None
    collecting = False
    sql_parts: list[str] = []

    def flush() -> None:
        nonlocal current_time, collecting, sql_parts
        if current_time is None or not sql_parts:
            current_time = None
            collecting = False
            sql_parts = []
            return
        sql = " ".join(part.strip() for part in sql_parts if part.strip())
        sql = " ".join(sql.split())
        if sql and not _is_bulk_insert(sql):
            if len(sql) > SLOW_SQL_DISPLAY_CHARS:
                sql = sql[: SLOW_SQL_DISPLAY_CHARS - 3] + "..."
            entries.append((current_time, sql))
        current_time = None
        collecting = False
        sql_parts = []

    for raw in slow_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("#"):
            if collecting:
                flush()
            match = QUERY_TIME_RE.search(stripped)
            if match:
                current_time = float(match.group(1))
            continue
        if not stripped:
            if collecting:
                flush()
            continue
        if stripped.upper().startswith("SET TIMESTAMP"):
            continue
        if SQL_START_RE.match(stripped) and current_time is not None:
            if collecting:
                flush()
            collecting = True
            sql_parts = [stripped]
            if stripped.rstrip().endswith(";"):
                flush()
            continue
        if collecting:
            sql_parts.append(stripped)
            if stripped.rstrip().endswith(";"):
                flush()

    if collecting:
        flush()

    if not entries:
        lines = slow_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        excerpt = "\n".join(lines[:SLOW_FALLBACK_LINES])
        return (
            "# pt-query-digest なし。アプリ向けクエリを抽出できませんでした。"
            f"先頭 {SLOW_FALLBACK_LINES} 行を表示します\n\n{excerpt}\n"
        )

    entries.sort(key=lambda item: item[0], reverse=True)
    lines = [
        "# pt-query-digest なし。Query_time 順（巨大 INSERT は除外）",
        "",
    ]
    for rank, (query_time, sql) in enumerate(entries[:SLOW_FALLBACK_TOP_N], start=1):
        lines.append(f"{rank}. Query_time={query_time:.4f}")
        lines.append(sql.rstrip(";") + ";")
        lines.append("")
    if len(entries) > SLOW_FALLBACK_TOP_N:
        lines.append(f"_上位 {SLOW_FALLBACK_TOP_N} / 全 {len(entries)} クエリを表示_")
        lines.append("")
    return "\n".join(lines)


def _is_postgres_slow(slow_log: Path) -> bool:
    """True when the file looks like PostgreSQL rather than a MySQL slow log."""
    with slow_log.open("r", encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle):
            if "Query_time:" in line:
                return False
            if index == 0 and "mysqld" in line and "Version" in line:
                return False
            if PG_DURATION_RE.search(line):
                return True
            if index >= _SLOW_SNIFF_LINES:
                break
    return False


def _fallback_postgres_summary(slow_log: Path) -> str:
    """Rank log_min_duration_statement lines when no local PostgreSQL tool exists."""
    totals: dict[str, list[float]] = defaultdict(list)
    for raw in slow_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = PG_DURATION_RE.search(raw.strip())
        if match is None:
            continue
        try:
            duration_ms = float(match.group(1))
        except ValueError:
            continue
        sql = " ".join(match.group(2).split()).strip().rstrip(";")
        if not sql or _is_bulk_insert(sql):
            continue
        if len(sql) > SLOW_SQL_DISPLAY_CHARS:
            sql = sql[: SLOW_SQL_DISPLAY_CHARS - 3] + "..."
        totals[sql].append(duration_ms)

    if not totals:
        lines = slow_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        excerpt = "\n".join(lines[:SLOW_FALLBACK_LINES])
        return (
            f"{POSTGRES_SLOW_MARKER}。duration 行を抽出できませんでした。"
            f"先頭 {SLOW_FALLBACK_LINES} 行を表示します\n\n{excerpt}\n"
        )

    ranked = sorted(
        totals.items(),
        key=lambda item: (-sum(item[1]), -len(item[1]), item[0]),
    )
    lines = [
        f"{POSTGRES_SLOW_MARKER}。duration 合計順（log_min_duration_statement）",
        "# 手元ツールなし。行単位で集計しました",
        "",
    ]
    shown = ranked[:SLOW_FALLBACK_TOP_N]
    for rank, (sql, samples) in enumerate(shown, start=1):
        total_ms = sum(samples)
        mean_ms = total_ms / len(samples)
        lines.append(
            f"{rank}. calls={len(samples)} total_ms={total_ms:.3f} mean_ms={mean_ms:.3f}"
        )
        lines.append(sql.rstrip(";") + ";")
        lines.append("")
    if len(ranked) > SLOW_FALLBACK_TOP_N:
        lines.append(f"_上位 {SLOW_FALLBACK_TOP_N} / 全 {len(ranked)} クエリを表示_")
        lines.append("")
    return "\n".join(lines)


def _run_pgbadger(slow_log: Path) -> str | None:
    if shutil.which("pgbadger") is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["pgbadger", "--quiet", "--outfile", "-", str(slow_log)],
            text=True,
            capture_output=True,
            check=False,
            cwd=tmp,
        )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout


def _analyze_postgres(slow_log: Path) -> str:
    report = _run_pgbadger(slow_log)
    if report is not None:
        body = f"{POSTGRES_SLOW_MARKER}（pgbadger）\n\n{report.strip()}\n"
        return _truncate_slow_output(body)
    return _truncate_slow_output(_fallback_postgres_summary(slow_log))


def _analyze_slow(slow_log: Path) -> tuple[str, str]:
    if _is_postgres_slow(slow_log):
        return _analyze_postgres(slow_log), "postgres"
    digest = _run_pt_query_digest(slow_log)
    if digest is not None:
        return _truncate_slow_output(digest), "mysql-digest"
    return _truncate_slow_output(_fallback_slow_summary(slow_log)), "mysql-fallback"


def _slow_query_notes(slow_kinds: list[str]) -> list[str]:
    if not slow_kinds:
        return [_MYSQL_DIGEST_NOTE]
    notes: list[str] = []
    if "mysql-fallback" in slow_kinds:
        notes.append(_MYSQL_FALLBACK_NOTE)
    if "mysql-digest" in slow_kinds:
        notes.append(_MYSQL_DIGEST_NOTE)
    if "postgres" in slow_kinds:
        notes.append(_POSTGRES_NOTE)
    return notes


def _write_summary(
    alp_data: list[dict[str, float | int | str]],
    *,
    access_log: Path | None,
    slow_logs: list[Path],
    slow_kinds: list[str],
) -> str:
    lines = ["# 解析サマリ", ""]
    if access_log is not None:
        lines.append(f"- アクセスログ: `{access_log.name}`")
    if slow_logs:
        names = ", ".join(f"`{path.name}`" for path in slow_logs)
        lines.append(f"- slow ログ: {names}")
    lines.append("")
    lines.append("## 遅いエンドポイント（request_time 合計）")
    lines.append("")
    lines.append("| 順位 | URI | 回数 | 合計時間 | 平均時間 |")
    lines.append("| --- | --- | ---: | ---: | ---: |")
    for rank, entry in enumerate(alp_data, start=1):
        uri = str(entry.get("uri", ""))
        count = int(entry.get("count", 0))
        sum_time = float(entry.get("sum_time", 0.0))
        avg_time = float(entry.get("avg_time", sum_time / count if count else 0.0))
        lines.append(
            f"| {rank} | `{uri}` | {count} | {sum_time:.3f} | {avg_time:.3f} |"
        )
    lines.append("")
    lines.append("## Slow Query メモ")
    lines.append("")
    lines.extend(_slow_query_notes(slow_kinds))
    lines.append("")
    return "\n".join(lines)


def _present_slow_logs(source_dir: Path) -> list[Path]:
    found: list[Path] = []
    for name in SLOW_LOG_NAMES:
        path = source_dir / name
        if _has_log_content(path):
            found.append(path)
    return found


def _has_log_content(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def run_analyze(raw_dir: Path | None = None, *, allow_empty: bool = False) -> Path:
    source_dir = raw_dir or _latest_raw_dir()
    if source_dir is None:
        raise ValueError("生ログディレクトリがありません。先に pull するか --raw-dir を指定してください")

    access_log = source_dir / "access.log"
    slow_logs = _present_slow_logs(source_dir)

    has_access = _has_log_content(access_log)
    has_slow = bool(slow_logs)
    if not allow_empty and not has_access and not has_slow:
        raise ValueError(
            "access.log / slow log の中身がありません。先に pull するか allow_empty を使ってください"
        )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    analyze_dir = out_dir() / "analyze" / timestamp
    analyze_dir.mkdir(parents=True, exist_ok=True)

    alp_data: list[dict[str, float | int | str]] = []
    if has_access:
        alp_data = _analyze_access(access_log)
    (analyze_dir / "alp.json").write_text(
        json.dumps(alp_data, indent=2) + "\n",
        encoding="utf-8",
    )

    slow_parts: list[str] = []
    slow_kinds: list[str] = []
    if has_slow:
        multiple = len(slow_logs) > 1
        for slow_log in slow_logs:
            text, kind = _analyze_slow(slow_log)
            slow_kinds.append(kind)
            if multiple:
                slow_parts.append(f"# file: {slow_log.name}\n\n{text.rstrip()}\n")
            else:
                slow_parts.append(text)
        slow_txt = "\n".join(slow_parts)
    else:
        slow_txt = "# slow query ログなし\n"
    (analyze_dir / "slow.txt").write_text(slow_txt, encoding="utf-8")

    summary = _write_summary(
        alp_data,
        access_log=access_log if has_access else None,
        slow_logs=slow_logs if has_slow else [],
        slow_kinds=slow_kinds,
    )
    (analyze_dir / "summary.md").write_text(summary, encoding="utf-8")

    return analyze_dir
