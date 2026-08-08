from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from isuctl.paths import out_dir


def run_bench_note(score: int, note: str = "") -> Path:
    scores_path = out_dir() / "scores.jsonl"
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "score": score,
        "note": note,
    }
    with scores_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return scores_path
