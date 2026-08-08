from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from isuctl.pack import normalize_alp_entry
from isuctl.paths import out_dir

SLOW_FALLBACK_LINES = 200


def _parse_ltsv_line(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in line.strip().split("\t"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        fields[key] = value
    return fields


def aggregate_ltsv_by_uri(lines: Iterable[str]) -> list[dict[str, float | int | str]]:
    totals: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "sum_time": 0.0}
    )
    for line in lines:
        if not line.strip():
            continue
        fields = _parse_ltsv_line(line)
        uri = fields.get("uri", "")
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


def _latest_raw_dir() -> Path | None:
    raw_root = out_dir() / "raw"
    if not raw_root.exists():
        return None
    dirs = sorted(
        (path for path in raw_root.iterdir() if path.is_dir()),
        reverse=True,
    )
    return dirs[0] if dirs else None


def _run_alp(access_log: Path) -> list[dict[str, float | int | str]] | None:
    if shutil.which("alp") is None:
        return None
    cmd = ["alp", "ltsv", "-f", str(access_log), "--output", "json"]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    return None


def _normalize_alp_data(
    alp_data: list[dict[str, float | int | str]],
) -> list[dict[str, float | int | str]]:
    normalized = [normalize_alp_entry(entry) for entry in alp_data]
    normalized.sort(key=lambda item: float(item["sum_time"]), reverse=True)
    return normalized


def _analyze_access(access_log: Path) -> list[dict[str, float | int | str]]:
    alp_data = _run_alp(access_log)
    if alp_data is not None:
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


def _analyze_slow(slow_log: Path) -> str:
    digest = _run_pt_query_digest(slow_log)
    if digest is not None:
        return digest
    lines = slow_log.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[:SLOW_FALLBACK_LINES])
    return (
        "# pt-query-digest not available; showing first "
        f"{SLOW_FALLBACK_LINES} lines\n\n{excerpt}\n"
    )


def _write_summary(
    alp_data: list[dict[str, float | int | str]],
    slow_txt: str,
    *,
    access_log: Path | None,
    slow_log: Path | None,
) -> str:
    lines = ["# Analysis Summary", ""]
    if access_log is not None:
        lines.append(f"- Access log: `{access_log.name}`")
    if slow_log is not None:
        lines.append(f"- Slow log: `{slow_log.name}`")
    lines.append("")
    lines.append("## Top Endpoints (by total request_time)")
    lines.append("")
    lines.append("| Rank | URI | Count | Sum Time | Avg Time |")
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
    lines.append("## Slow Query Notes")
    lines.append("")
    if "pt-query-digest not available" in slow_txt:
        lines.append("- pt-query-digest was not available; see `slow.txt` excerpt.")
    else:
        lines.append("- See `slow.txt` for pt-query-digest output.")
    lines.append("")
    return "\n".join(lines)


def _has_log_content(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def run_analyze(raw_dir: Path | None = None, *, allow_empty: bool = False) -> Path:
    source_dir = raw_dir or _latest_raw_dir()
    if source_dir is None:
        raise ValueError("no raw log directory found; run pull first or pass --raw-dir")

    access_log = source_dir / "access.log"
    slow_log = source_dir / "mysql-slow.log"

    has_access = _has_log_content(access_log)
    has_slow = _has_log_content(slow_log)
    if not allow_empty and not has_access and not has_slow:
        raise ValueError(
            "no access.log or slow log content found; run pull first or pass --allow-empty"
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

    slow_txt = ""
    if has_slow:
        slow_txt = _analyze_slow(slow_log)
    else:
        slow_txt = "# No slow query log found\n"
    (analyze_dir / "slow.txt").write_text(slow_txt, encoding="utf-8")

    summary = _write_summary(
        alp_data,
        slow_txt,
        access_log=access_log if has_access else None,
        slow_log=slow_log if has_slow else None,
    )
    (analyze_dir / "summary.md").write_text(summary, encoding="utf-8")

    return analyze_dir
