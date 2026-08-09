import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from isuctl.bench_note import (
    compare_score,
    format_comparison_lines,
    format_history_lines,
    read_scores,
    run_bench_note,
)
from isuctl.cli import app


def test_run_bench_note_appends_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("isuctl.bench_note.datetime") as dt:
        dt.now.return_value.isoformat.return_value = "2026-08-09T12:00:00+00:00"
        path = run_bench_note(12345, note="first bench")

    assert path == tmp_path / "out" / "scores.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["score"] == 12345
    assert entry["note"] == "first bench"
    assert entry["timestamp"] == "2026-08-09T12:00:00+00:00"


def test_run_bench_note_appends_multiple(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("isuctl.bench_note.datetime") as dt:
        dt.now.return_value.isoformat.side_effect = [
            "2026-08-09T12:00:00+00:00",
            "2026-08-09T13:00:00+00:00",
        ]
        run_bench_note(1000)
        path = run_bench_note(2000, note="improved")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["score"] == 2000
    assert json.loads(lines[1])["note"] == "improved"


def test_read_scores_and_compare_regression(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_bench_note(3000, note="baseline")
    run_bench_note(5000, note="best")
    history = read_scores()
    comparison = compare_score(4000, history)

    assert comparison.previous["score"] == 5000
    assert comparison.best["score"] == 5000
    assert comparison.delta_vs_previous == -1000
    assert comparison.is_regression_vs_previous
    assert comparison.is_regression_vs_best

    lines = format_comparison_lines(comparison)
    assert any("前回比: -1000" in line for line in lines)
    assert any("注意:" in line for line in lines)


def test_format_history_lines_empty():
    assert format_history_lines([]) == ["履歴: なし（初回記録）"]


def test_cli_bench_note_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("isuctl.cli.run_bench_note") as run_bench_note_mock:
        run_bench_note_mock.return_value = tmp_path / "out" / "scores.jsonl"
        result = CliRunner().invoke(app, ["bench-note", "5000", "--note", "ok"])

    assert result.exit_code == 0
    run_bench_note_mock.assert_called_once_with(5000, note="ok")
    assert "記録先" in result.stdout
    assert "今回: 5000" in result.stdout


def test_cli_bench_note_prompts_for_score(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("isuctl.cli.run_bench_note") as run_bench_note_mock:
        run_bench_note_mock.return_value = tmp_path / "out" / "scores.jsonl"
        result = CliRunner().invoke(app, ["bench-note", "--note", "after bench"], input="7777\n")

    assert result.exit_code == 0
    run_bench_note_mock.assert_called_once_with(7777, note="after bench")
    assert "ベンチ後のスコアを入力してください" in result.stdout


def test_cli_bench_note_confirms_regression(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_bench_note(9000, note="good")

    result = CliRunner().invoke(
        app, ["bench-note", "1000", "--note", "worse"], input="n\n"
    )

    assert result.exit_code == 1
    assert "前回より低いスコアを記録しますか?" in result.stdout
    assert "記録をキャンセルしました" in result.stdout
    assert len(read_scores()) == 1


def test_cli_bench_note_yes_skips_confirm(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_bench_note(9000, note="good")

    result = CliRunner().invoke(app, ["bench-note", "1000", "--yes", "--note", "worse"])

    assert result.exit_code == 0
    assert len(read_scores()) == 2
    assert read_scores()[-1]["score"] == 1000
