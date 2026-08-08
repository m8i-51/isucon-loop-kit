import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.analyze import (
    _fallback_slow_summary,
    _normalize_alp_data,
    aggregate_ltsv_by_uri,
    run_analyze,
)
from isuctl.cli import app

FIXTURES = Path(__file__).parent / "fixtures"


def test_aggregate_ltsv_by_uri_ranks_by_sum_time():
    lines = (FIXTURES / "sample_access.ltsv").read_text(encoding="utf-8").splitlines()
    results = aggregate_ltsv_by_uri(lines)
    assert len(results) == 2
    assert results[0]["uri"] == "/api/foo"
    assert results[0]["sum_time"] == pytest.approx(1.2)
    assert results[0]["count"] == 2
    assert results[1]["uri"] == "/api/bar"
    assert results[1]["sum_time"] == pytest.approx(0.4)


def test_aggregate_ltsv_strips_query_string():
    lines = [
        "uri:/api/app/nearby-chairs?latitude=1&longitude=2\trequest_time:1.0",
        "uri:/api/app/nearby-chairs?latitude=9&longitude=8\trequest_time:2.0",
    ]
    results = aggregate_ltsv_by_uri(lines)
    assert len(results) == 1
    assert results[0]["uri"] == "/api/app/nearby-chairs"
    assert results[0]["count"] == 2
    assert results[0]["sum_time"] == pytest.approx(3.0)


def test_fallback_slow_summary_ranks_by_query_time(tmp_path: Path):
    slow = tmp_path / "mysql-slow.log"
    slow.write_text(
        "\n".join(
            [
                "# Query_time: 0.10  Lock_time: 0.00 Rows_sent: 1  Rows_examined: 1",
                "SELECT * FROM rides WHERE id = 1;",
                "# Query_time: 1.50  Lock_time: 0.00 Rows_sent: 0  Rows_examined: 0",
                "INSERT INTO `chair_locations` VALUES ('a',1),('b',2),('c',3),('d',4);",
                "# Query_time: 0.80  Lock_time: 0.00 Rows_sent: 1  Rows_examined: 10",
                "SELECT id,",
                "       name",
                "FROM chairs",
                "WHERE is_active = TRUE;",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = _fallback_slow_summary(slow)
    assert "FROM chairs WHERE is_active = TRUE" in summary
    assert "SELECT * FROM rides WHERE id = 1" in summary
    assert "chair_locations" not in summary
    assert summary.index("0.8000") < summary.index("0.1000")


def test_run_analyze_python_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "out" / "raw" / "20260809-120000"
    raw_dir.mkdir(parents=True)
    (raw_dir / "access.log").write_text(
        (FIXTURES / "sample_access.ltsv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (raw_dir / "mysql-slow.log").write_text(
        (FIXTURES / "sample_slow.log").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with (
        patch("isuctl.analyze.shutil.which", return_value=None),
        patch("isuctl.analyze.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-130000"
        out_dir = run_analyze(raw_dir)

    assert out_dir == tmp_path / "out" / "analyze" / "20260809-130000"
    alp = json.loads((out_dir / "alp.json").read_text(encoding="utf-8"))
    assert alp[0]["uri"] == "/api/foo"
    assert alp[0]["sum_time"] == pytest.approx(1.2)

    slow_txt = (out_dir / "slow.txt").read_text(encoding="utf-8")
    assert "pt-query-digest なし" in slow_txt
    assert "SELECT * FROM users" in slow_txt

    summary = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "/api/foo" in summary
    assert "1.200" in summary or "1.2" in summary


def test_run_analyze_uses_latest_raw_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    older = tmp_path / "out" / "raw" / "20260809-100000"
    newer = tmp_path / "out" / "raw" / "20260809-120000"
    for d in (older, newer):
        d.mkdir(parents=True)
        (d / "access.log").write_text(
            (FIXTURES / "sample_access.ltsv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    with (
        patch("isuctl.analyze.shutil.which", return_value=None),
        patch("isuctl.analyze.datetime") as dt,
    ):
        dt.now.return_value.strftime.return_value = "20260809-130000"
        out_dir = run_analyze(None)

    alp = json.loads((out_dir / "alp.json").read_text(encoding="utf-8"))
    assert alp[0]["uri"] == "/api/foo"


def test_run_analyze_requires_raw_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="生ログディレクトリがありません"):
        run_analyze(None)


def test_cli_analyze_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    with patch("isuctl.cli.run_analyze") as run_analyze_mock:
        run_analyze_mock.return_value = tmp_path / "out" / "analyze" / "20260809-130000"
        result = CliRunner().invoke(app, ["analyze", "--raw-dir", str(raw_dir)])

    assert result.exit_code == 0
    run_analyze_mock.assert_called_once_with(raw_dir)


def test_normalize_alp_data_accepts_alp_native_keys():
    raw = [{"uri": "/api/foo", "count": 10, "sum": 1.5, "avg": 0.15}]
    normalized = _normalize_alp_data(raw)
    assert normalized[0]["sum_time"] == pytest.approx(1.5)
    assert normalized[0]["avg_time"] == pytest.approx(0.15)


def test_run_analyze_rejects_empty_logs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "out" / "raw" / "20260809-120000"
    raw_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="access.log / slow log"):
        run_analyze(raw_dir)


def test_run_analyze_allow_empty(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "out" / "raw" / "20260809-120000"
    raw_dir.mkdir(parents=True)

    with patch("isuctl.analyze.datetime") as dt:
        dt.now.return_value.strftime.return_value = "20260809-130000"
        out_dir = run_analyze(raw_dir, allow_empty=True)

    assert out_dir == tmp_path / "out" / "analyze" / "20260809-130000"
    alp = json.loads((out_dir / "alp.json").read_text(encoding="utf-8"))
    assert alp == []
