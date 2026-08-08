from pathlib import Path

from isuctl.paths import is_ready, mark_ready, ready_marker_path


def test_ready_marker(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    assert not is_ready(work)
    mark_ready(work)
    assert is_ready(work)
    assert ready_marker_path(work).exists()
