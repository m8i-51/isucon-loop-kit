import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from isuctl.bench_note import run_bench_note
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


def test_cli_bench_note_command(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("isuctl.cli.run_bench_note") as run_bench_note_mock:
        run_bench_note_mock.return_value = tmp_path / "out" / "scores.jsonl"
        result = CliRunner().invoke(app, ["bench-note", "5000", "--note", "ok"])

    assert result.exit_code == 0
    run_bench_note_mock.assert_called_once_with(5000, note="ok")
    assert "記録先" in result.stdout
