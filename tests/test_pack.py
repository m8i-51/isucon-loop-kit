import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.cli import app
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.pack import (
    SQL_DISPLAY_MAX_CHARS,
    _extract_sql_lines,
    _find_candidate_files,
    _find_schema_file,
    _format_top_sqls,
    normalize_alp_entry,
    run_pack,
)

REQUIRED_HEADINGS = [
    "# ISUCON 分析パック",
    "## 遅いエンドポイント",
    "## 遅い SQL",
    "## 候補コード位置",
    "## スキーマ抜粋",
    "## 次の仮説",
]


def _write_config(tmp_path: Path, local_dir: Path) -> Path:
    cfg_path = tmp_path / "isucon.toml"
    save_config(
        cfg_path,
        IsuconConfig(
            project=ProjectConfig(name="t", local_dir=str(local_dir)),
            ssh=SshConfig(user="isucon", key="/tmp/k"),
            hosts=[Host(name="app1", host="10.0.0.1", role=["app"])],
        ),
    )
    return cfg_path


def test_normalize_alp_entry_python_fallback_shape():
    entry = {"uri": "/api/foo", "count": 2, "sum_time": 1.2, "avg_time": 0.6}
    normalized = normalize_alp_entry(entry)
    assert normalized["uri"] == "/api/foo"
    assert normalized["count"] == 2
    assert normalized["sum_time"] == pytest.approx(1.2)
    assert normalized["avg_time"] == pytest.approx(0.6)


def test_normalize_alp_entry_alp_native_shape():
    entry = {"uri": "/api/bar", "count": 5, "sum": 2.5, "avg": 0.5}
    normalized = normalize_alp_entry(entry)
    assert normalized["uri"] == "/api/bar"
    assert normalized["count"] == 5
    assert normalized["sum_time"] == pytest.approx(2.5)
    assert normalized["avg_time"] == pytest.approx(0.5)


def test_run_pack_writes_required_headings(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "main.go").write_text(
        "package main\nfunc fooHandler() {}\nfunc usersQuery() {}",
        encoding="utf-8",
    )
    schema_dir = work / "sql"
    schema_dir.mkdir(parents=True)
    (schema_dir / "schema.sql").write_text(
        "CREATE TABLE users (id INT PRIMARY KEY);\nCREATE TABLE items (id INT);",
        encoding="utf-8",
    )

    analyze_dir = tmp_path / "out" / "analyze" / "20260809-130000"
    analyze_dir.mkdir(parents=True)
    alp_data = [
        {"uri": "/api/foo", "count": 2, "sum_time": 1.2, "avg_time": 0.6},
        {"uri": "/api/bar", "count": 1, "sum_time": 0.4, "avg_time": 0.4},
    ]
    (analyze_dir / "alp.json").write_text(json.dumps(alp_data), encoding="utf-8")
    (analyze_dir / "slow.txt").write_text(
        "SELECT * FROM users WHERE id = 1;\nSELECT * FROM items WHERE user_id = 1;",
        encoding="utf-8",
    )
    (analyze_dir / "summary.md").write_text("# 解析サマリ\n", encoding="utf-8")

    cfg_path = _write_config(tmp_path, work)
    pack_path = run_pack(cfg_path, analyze_dir)

    assert pack_path == tmp_path / "out" / "pack.md"
    content = pack_path.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        assert heading in content
    assert "/api/foo" in content
    assert "users" in content
    assert "main.go" in content
    assert "CREATE TABLE users" in content
    assert "- [ ]" in content


def test_run_pack_uses_latest_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()

    older = tmp_path / "out" / "analyze" / "20260809-100000"
    newer = tmp_path / "out" / "analyze" / "20260809-120000"
    for d in (older, newer):
        d.mkdir(parents=True)
        (d / "alp.json").write_text("[]", encoding="utf-8")
        (d / "slow.txt").write_text("", encoding="utf-8")
        (d / "summary.md").write_text("# 解析サマリ\n", encoding="utf-8")

    alp_data = [{"uri": "/only-new", "count": 1, "sum_time": 9.9, "avg_time": 9.9}]
    (newer / "alp.json").write_text(json.dumps(alp_data), encoding="utf-8")

    cfg_path = _write_config(tmp_path, work)
    pack_path = run_pack(cfg_path, None)
    content = pack_path.read_text(encoding="utf-8")
    assert "/only-new" in content


def test_run_pack_requires_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    cfg_path = _write_config(tmp_path, work)
    with pytest.raises(ValueError, match="analyze ディレクトリがありません"):
        run_pack(cfg_path, None)


def test_run_pack_rejects_missing_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    cfg_path = _write_config(tmp_path, work)
    missing = tmp_path / "out" / "analyze" / "missing"
    with pytest.raises(ValueError, match="analyze ディレクトリがありません"):
        run_pack(cfg_path, missing)


def test_run_pack_rejects_non_directory_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    cfg_path = _write_config(tmp_path, work)
    not_dir = tmp_path / "out" / "analyze.txt"
    not_dir.parent.mkdir(parents=True)
    not_dir.write_text("not a dir", encoding="utf-8")
    with pytest.raises(ValueError, match="ディレクトリではありません"):
        run_pack(cfg_path, not_dir)


def test_run_pack_resolves_relative_local_dir_from_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    schema_dir = work / "sql"
    schema_dir.mkdir(parents=True)
    (schema_dir / "schema.sql").write_text(
        "CREATE TABLE users (id INT PRIMARY KEY);",
        encoding="utf-8",
    )

    analyze_dir = tmp_path / "out" / "analyze" / "20260809-130000"
    analyze_dir.mkdir(parents=True)
    (analyze_dir / "alp.json").write_text("[]", encoding="utf-8")
    (analyze_dir / "slow.txt").write_text("", encoding="utf-8")
    (analyze_dir / "summary.md").write_text("# 解析サマリ\n", encoding="utf-8")

    cfg_path = _write_config(tmp_path, Path("./work"))
    pack_path = run_pack(cfg_path, analyze_dir)
    content = pack_path.read_text(encoding="utf-8")
    assert "CREATE TABLE users" in content


def test_cli_pack_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "isucon.toml"
    analyze_dir = tmp_path / "out" / "analyze" / "20260809-130000"

    with patch("isuctl.cli.run_pack") as run_pack_mock:
        run_pack_mock.return_value = tmp_path / "out" / "pack.md"
        result = CliRunner().invoke(
            app,
            ["pack", "--config", str(cfg_path), "--analyze-dir", str(analyze_dir)],
        )

    assert result.exit_code == 0
    run_pack_mock.assert_called_once_with(cfg_path, analyze_dir)
    assert "パック出力" in result.stdout


def test_find_schema_file_accepts_numbered_schema(tmp_path: Path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    schema = sql_dir / "1-schema.sql"
    schema.write_text("CREATE TABLE users (id INT);\n", encoding="utf-8")
    (sql_dir / "2-master-data.sql").write_text("INSERT INTO users VALUES (1);\n", encoding="utf-8")
    found = _find_schema_file(tmp_path)
    assert found == schema


def test_find_candidate_files_ignores_dot_git(tmp_path: Path):
    (tmp_path / "app.go").write_text("func nearbyChairs() {}\n", encoding="utf-8")
    git_obj = tmp_path / ".git" / "objects" / "ab"
    git_obj.mkdir(parents=True)
    (git_obj / "cdef").write_text("nearbyChairs binary garbage\n", encoding="utf-8")
    node = tmp_path / "node_modules" / "pkg"
    node.mkdir(parents=True)
    (node / "index.js").write_text("nearbyChairs()\n", encoding="utf-8")

    matches = _find_candidate_files(tmp_path, ["nearbyChairs"])
    assert matches == ["app.go"]


def test_extract_sql_lines_truncates_giant_inserts():
    giant = "INSERT INTO `chair_locations` VALUES " + ("('x')," * 5000)
    sqls = _extract_sql_lines(giant + "\nSELECT * FROM rides WHERE id = 1;\n")
    assert sqls == ["SELECT * FROM rides WHERE id = 1"]
    formatted = _format_top_sqls(sqls)
    assert "SELECT * FROM rides WHERE id = 1" in formatted
    assert len(formatted) < 2000


def test_extract_sql_lines_fingerprints_literals():
    text = "\n".join(
        [
            "SELECT * FROM chair_locations WHERE chair_id = 'aaa' ORDER BY created_at DESC LIMIT 1;",
            "SELECT * FROM chair_locations WHERE chair_id = 'bbb' ORDER BY created_at DESC LIMIT 1;",
            "SELECT * FROM rides WHERE id = 1;",
        ]
    )
    sqls = _extract_sql_lines(text)
    assert len(sqls) == 2
    assert "chair_locations" in sqls[0]
    assert "rides" in sqls[1]
