from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isuctl.paths import out_dir


def scores_path() -> Path:
    return out_dir() / "scores.jsonl"


def read_scores(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or scores_path()
    if not target.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def previous_and_best(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not entries:
        return None, None
    previous = entries[-1]
    best = max(entries, key=lambda e: int(e["score"]))
    return previous, best


@dataclass(frozen=True)
class ScoreComparison:
    score: int
    previous: dict[str, Any] | None
    best: dict[str, Any] | None

    @property
    def delta_vs_previous(self) -> int | None:
        if self.previous is None:
            return None
        return self.score - int(self.previous["score"])

    @property
    def delta_vs_best(self) -> int | None:
        if self.best is None:
            return None
        return self.score - int(self.best["score"])

    @property
    def is_regression_vs_previous(self) -> bool:
        delta = self.delta_vs_previous
        return delta is not None and delta < 0

    @property
    def is_regression_vs_best(self) -> bool:
        delta = self.delta_vs_best
        return delta is not None and delta < 0


def compare_score(
    score: int, entries: list[dict[str, Any]] | None = None
) -> ScoreComparison:
    history = entries if entries is not None else read_scores()
    previous, best = previous_and_best(history)
    return ScoreComparison(score=score, previous=previous, best=best)


def format_history_lines(entries: list[dict[str, Any]]) -> list[str]:
    previous, best = previous_and_best(entries)
    lines: list[str] = []
    if previous is None:
        lines.append("履歴: なし（初回記録）")
        return lines
    prev_note = f" ({previous['note']})" if previous.get("note") else ""
    lines.append(f"前回: {previous['score']}{prev_note}")
    if best is not None:
        best_note = f" ({best['note']})" if best.get("note") else ""
        same = best is previous or int(best["score"]) == int(previous["score"])
        if same:
            lines.append(f"最高: {best['score']}（前回と同じ）")
        else:
            lines.append(f"最高: {best['score']}{best_note}")
    return lines


def format_comparison_lines(comparison: ScoreComparison) -> list[str]:
    lines: list[str] = [f"今回: {comparison.score}"]
    if comparison.delta_vs_previous is not None:
        delta = comparison.delta_vs_previous
        sign = "+" if delta > 0 else ""
        lines.append(f"前回比: {sign}{delta}")
    if comparison.delta_vs_best is not None:
        delta = comparison.delta_vs_best
        sign = "+" if delta > 0 else ""
        lines.append(f"最高比: {sign}{delta}")
    if comparison.is_regression_vs_previous:
        lines.append(
            "注意: 前回よりスコアが下がっています。残すなら記録、戻すなら "
            "`isuctl rollback` を検討してください。"
        )
    elif comparison.is_regression_vs_best:
        lines.append(
            "注意: 自己ベストより低いです。必要なら `isuctl rollback` を検討してください。"
        )
    return lines


def run_bench_note(score: int, note: str = "") -> Path:
    path = scores_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "note": note,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return path
