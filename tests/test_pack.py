import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.cli import app
from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, save_config
from isuctl.pack import normalize_alp_entry, run_pack

REQUIRED_HEADINGS = [
    "# ISUCON Analysis Pack",
    "## Top Endpoints",
    "## Top SQLs",
    "## Candidate Code Locations",
    "## Schema Excerpt",
    "## Next Hypotheses",
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
    (analyze_dir / "summary.md").write_text("# Analysis Summary\n", encoding="utf-8")

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
        (d / "summary.md").write_text("# Analysis Summary\n", encoding="utf-8")

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
    with pytest.raises(ValueError, match="no analyze directory"):
        run_pack(cfg_path, None)


def test_run_pack_rejects_missing_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    cfg_path = _write_config(tmp_path, work)
    missing = tmp_path / "out" / "analyze" / "missing"
    with pytest.raises(ValueError, match="does not exist"):
        run_pack(cfg_path, missing)


def test_run_pack_rejects_non_directory_analyze_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    cfg_path = _write_config(tmp_path, work)
    not_dir = tmp_path / "out" / "analyze.txt"
    not_dir.parent.mkdir(parents=True)
    not_dir.write_text("not a dir", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
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
    (analyze_dir / "summary.md").write_text("# Analysis Summary\n", encoding="utf-8")

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
    assert "packed to" in result.stdout
