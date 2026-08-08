from __future__ import annotations

import json
import re
from pathlib import Path

from isuctl.config import load_config
from isuctl.paths import out_dir

TOP_N = 10
SCHEMA_EXCERPT_LINES = 80
SQL_DISPLAY_MAX_CHARS = 240
SQL_EXTRACT_MAX_CHARS = 4000
CODE_SEARCH_EXTENSIONS = {
    ".go",
    ".py",
    ".rb",
    ".php",
    ".js",
    ".ts",
    ".java",
    ".rs",
    ".cs",
}
SQL_LINE_RE = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE)\b",
    re.IGNORECASE,
)
TABLE_NAME_RE = re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)
NUMERIC_SEGMENT_RE = re.compile(r"^\d+$")
SQL_STRING_LITERAL_RE = re.compile(r"'[^']*'")
SQL_NUMBER_LITERAL_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def normalize_alp_entry(entry: dict) -> dict[str, float | int | str]:
    uri = str(entry.get("uri", entry.get("path", "")))
    count = int(entry.get("count", 0))
    sum_time = float(entry.get("sum_time", entry.get("sum", 0.0)))
    if "avg_time" in entry:
        avg_time = float(entry["avg_time"])
    elif "avg" in entry:
        avg_time = float(entry["avg"])
    else:
        avg_time = sum_time / count if count else 0.0
    return {
        "uri": uri,
        "count": count,
        "sum_time": sum_time,
        "avg_time": avg_time,
    }


def _latest_analyze_dir() -> Path | None:
    analyze_root = out_dir() / "analyze"
    if not analyze_root.exists():
        return None
    dirs = sorted(
        (path for path in analyze_root.iterdir() if path.is_dir()),
        reverse=True,
    )
    return dirs[0] if dirs else None


def _normalize_alp_data(raw: list) -> list[dict[str, float | int | str]]:
    normalized = [normalize_alp_entry(item) for item in raw if isinstance(item, dict)]
    normalized.sort(key=lambda item: float(item["sum_time"]), reverse=True)
    return normalized


def _fingerprint_sql(sql: str) -> str:
    fingerprinted = SQL_STRING_LITERAL_RE.sub("?", sql)
    fingerprinted = SQL_NUMBER_LITERAL_RE.sub("?", fingerprinted)
    return " ".join(fingerprinted.split())


def _extract_sql_lines(slow_txt: str) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for line in slow_txt.splitlines():
        stripped = line.strip().rstrip(";")
        if not stripped or stripped.startswith("#"):
            continue
        if not SQL_LINE_RE.match(stripped):
            continue
        # Skip bulk seed dumps; they drown out useful app queries in packs.
        upper = stripped.upper()
        if upper.startswith("INSERT") and "VALUES" in upper and stripped.count("(") > 3:
            continue
        if len(stripped) > SQL_EXTRACT_MAX_CHARS:
            stripped = stripped[: SQL_EXTRACT_MAX_CHARS - 3] + "..."
        fingerprint = _fingerprint_sql(stripped)
        if fingerprint not in seen:
            seen.add(fingerprint)
            queries.append(stripped)
    return queries


def _truncate_sql_for_display(sql: str) -> str:
    if len(sql) <= SQL_DISPLAY_MAX_CHARS:
        return sql
    return sql[: SQL_DISPLAY_MAX_CHARS - 3] + "..."


def _extract_table_names(sql_lines: list[str]) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for sql in sql_lines:
        for match in TABLE_NAME_RE.finditer(sql):
            name = match.group(1).lower()
            if name not in seen:
                seen.add(name)
                tables.append(name)
    return tables


def _uri_search_terms(uris: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for uri in uris:
        for segment in uri.split("/"):
            if not segment or NUMERIC_SEGMENT_RE.match(segment):
                continue
            if segment not in seen:
                seen.add(segment)
                terms.append(segment)
    return terms


def _is_ignored_candidate(path: Path, local_dir: Path) -> bool:
    try:
        parts = path.relative_to(local_dir).parts
    except ValueError:
        parts = path.parts
    ignored = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__"}
    if any(part in ignored for part in parts):
        return True
    if path.name in {".gitignore", ".gitattributes", ".DS_Store"}:
        return True
    # Skip extensionless binaries / build artifacts commonly checked into AMI trees.
    if path.suffix == "" and path.is_file():
        try:
            with path.open("rb") as fh:
                head = fh.read(4)
            if head.startswith(b"\x7fELF") or head.startswith(b"#!"):
                return True
        except OSError:
            return True
    return False


def _find_candidate_files(local_dir: Path, terms: list[str]) -> list[str]:
    if not local_dir.exists() or not terms:
        return []

    matches: list[str] = []
    seen_paths: set[str] = set()
    for path in local_dir.rglob("*"):
        if not path.is_file():
            continue
        if _is_ignored_candidate(path, local_dir):
            continue
        if path.suffix and path.suffix not in CODE_SEARCH_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower_text = text.lower()
        if any(term.lower() in lower_text for term in terms):
            rel = path.relative_to(local_dir).as_posix()
            if rel not in seen_paths:
                seen_paths.add(rel)
                matches.append(rel)
    return sorted(matches)


def _find_schema_file(local_dir: Path) -> Path | None:
    candidates = [
        local_dir / "sql" / "schema.sql",
        local_dir / "sql" / "1-schema.sql",
        local_dir / "db" / "schema.sql",
        local_dir / "schema.sql",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    patterns = ("*schema*.sql", "schema.sql")
    matches: list[Path] = []
    for pattern in patterns:
        for path in local_dir.rglob(pattern):
            if path.is_file():
                matches.append(path)
    if not matches:
        return None
    # Prefer names that look like schema definitions over data dumps.
    matches.sort(
        key=lambda p: (
            0 if "schema" in p.name.lower() and "data" not in p.name.lower() else 1,
            len(str(p)),
            str(p),
        )
    )
    return matches[0]


def _schema_excerpt(schema_path: Path | None, table_names: list[str]) -> str:
    if schema_path is None:
        return "_ローカルプロジェクトに schema.sql が見つかりません。_\n"

    lines = schema_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not table_names:
        excerpt = lines[:SCHEMA_EXCERPT_LINES]
        return "\n".join(excerpt) + ("\n" if excerpt else "")

    table_patterns = [
        re.compile(
            rf"CREATE\s+TABLE\s+`?{re.escape(name)}`?",
            re.IGNORECASE,
        )
        for name in table_names
    ]
    excerpt_lines: list[str] = []
    capturing = False
    for line in lines:
        if any(pattern.search(line) for pattern in table_patterns):
            capturing = True
        if capturing:
            excerpt_lines.append(line)
            if line.strip().endswith(";") and len(excerpt_lines) > 1:
                capturing = False
        if len(excerpt_lines) >= SCHEMA_EXCERPT_LINES:
            break

    if not excerpt_lines:
        excerpt_lines = lines[:SCHEMA_EXCERPT_LINES]
    return "\n".join(excerpt_lines) + ("\n" if excerpt_lines else "")


def _format_top_endpoints(alp_data: list[dict[str, float | int | str]]) -> str:
    lines = ["| 順位 | URI | 回数 | 合計時間 | 平均時間 |", "| --- | --- | ---: | ---: | ---: |"]
    for rank, entry in enumerate(alp_data[:TOP_N], start=1):
        uri = str(entry["uri"])
        count = int(entry["count"])
        sum_time = float(entry["sum_time"])
        avg_time = float(entry["avg_time"])
        lines.append(
            f"| {rank} | `{uri}` | {count} | {sum_time:.3f} | {avg_time:.3f} |"
        )
    if len(alp_data) > TOP_N:
        lines.append("")
        lines.append(f"_上位 {TOP_N} / 全 {len(alp_data)} エンドポイントを表示_")
    if not alp_data:
        lines.append("| - | _アクセスログなし_ | 0 | 0 | 0 |")
    return "\n".join(lines) + "\n"


def _format_top_sqls(sql_lines: list[str]) -> str:
    if not sql_lines:
        return "_slow log から SQL を抽出できませんでした。_\n"
    lines: list[str] = []
    for rank, sql in enumerate(sql_lines[:TOP_N], start=1):
        lines.append(f"{rank}. `{_truncate_sql_for_display(sql)}`")
    if len(sql_lines) > TOP_N:
        lines.append("")
        lines.append(f"_上位 {TOP_N} / 全 {len(sql_lines)} クエリを表示_")
    return "\n".join(lines) + "\n"


def _format_candidate_locations(paths: list[str]) -> str:
    if not paths:
        return "_エンドポイント / テーブル名ヒューリスティックに一致する候補ファイルなし。_\n"
    return "\n".join(f"- `{path}`" for path in paths[:TOP_N]) + "\n"


def _format_hypotheses(
    alp_data: list[dict[str, float | int | str]],
    table_names: list[str],
) -> str:
    lines = ["- [ ] 最も遅いエンドポイントをプロファイルして改善する"]
    if table_names:
        tables = ", ".join(table_names[:3])
        lines.append(f"- [ ] `{tables}` に触るクエリの index / 書き換えを検討する")
    if alp_data:
        top_uri = str(alp_data[0]["uri"])
        lines.append(f"- [ ] `{top_uri}` のハンドラと DB 呼び出しを追う")
    lines.append("- [ ] 変更後に再ベンチし scores.jsonl と比較する")
    return "\n".join(lines) + "\n"


def _build_pack_md(
    alp_data: list[dict[str, float | int | str]],
    slow_txt: str,
    local_dir: Path,
) -> str:
    sql_lines = _extract_sql_lines(slow_txt)
    table_names = _extract_table_names(sql_lines)
    uri_terms = _uri_search_terms([str(entry["uri"]) for entry in alp_data[:TOP_N]])
    search_terms = uri_terms + table_names
    candidate_paths = _find_candidate_files(local_dir, search_terms)
    schema_path = _find_schema_file(local_dir)

    sections = [
        "# ISUCON 分析パック",
        "",
        "## 遅いエンドポイント",
        "",
        _format_top_endpoints(alp_data),
        "## 遅い SQL",
        "",
        _format_top_sqls(sql_lines),
        "## 候補コード位置",
        "",
        _format_candidate_locations(candidate_paths),
        "## スキーマ抜粋",
        "",
        _schema_excerpt(schema_path, table_names),
        "## 次の仮説",
        "",
        _format_hypotheses(alp_data, table_names),
    ]
    return "\n".join(sections)


def run_pack(config_path: Path, analyze_dir: Path | None = None) -> Path:
    config = load_config(config_path)
    if analyze_dir is not None:
        if not analyze_dir.exists():
            raise ValueError(f"analyze ディレクトリがありません: {analyze_dir}")
        if not analyze_dir.is_dir():
            raise ValueError(f"analyze パスがディレクトリではありません: {analyze_dir}")
        source_dir = analyze_dir
    else:
        source_dir = _latest_analyze_dir()
        if source_dir is None:
            raise ValueError(
                "analyze ディレクトリがありません。先に analyze するか --analyze-dir を指定してください"
            )

    alp_path = source_dir / "alp.json"
    slow_path = source_dir / "slow.txt"
    alp_data: list[dict[str, float | int | str]] = []
    if alp_path.exists():
        raw = json.loads(alp_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            alp_data = _normalize_alp_data(raw)

    slow_txt = ""
    if slow_path.exists():
        slow_txt = slow_path.read_text(encoding="utf-8")

    local_dir = Path(config.project.local_dir).expanduser()
    if not local_dir.is_absolute():
        local_dir = (Path.cwd() / local_dir).resolve()

    pack_content = _build_pack_md(alp_data, slow_txt, local_dir)
    pack_path = out_dir() / "pack.md"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(pack_content, encoding="utf-8")
    return pack_path
