"""Calibration rows from a run, and the thresholds file that refuses to be rewritten."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mend.eval.calibration import calibration_rows, curve_table, load_thresholds, write_thresholds
from mend.graph.route import Thresholds, routing_curve


def run(issue_id: str, score: float, agrees: bool, *, green: bool = True) -> dict[str, Any]:
    return {
        "issue": {"issue_id": issue_id},
        "state": {
            "score": score,
            "review": {"agrees": agrees},
            "patch": {"test_passes": True, "suite_green": green},
        },
    }


def test_rows_carry_eligibility_and_the_harness_verdict() -> None:
    rows = calibration_rows(
        [run("a", 0.8, True), run("b", 0.9, True, green=False), {"issue": {"issue_id": "c"}}],
        {"a": True, "b": True},
    )
    by_id = {r.issue_id: r for r in rows}
    assert by_id["a"].eligible and by_id["a"].resolved
    assert not by_id["b"].eligible
    assert not by_id["c"].eligible and not by_id["c"].resolved and by_id["c"].score == 0.0


def test_thresholds_round_trip_and_refuse_to_be_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    chosen = Thresholds(
        auto_propose=0.57, suggest=0.35, target_confidently_wrong=0.03, calibrated_on="validation"
    )
    write_thresholds(chosen, path, {"tasks": 30})
    assert load_thresholds(path) == chosen
    with pytest.raises(FileExistsError):
        write_thresholds(chosen, path, {"tasks": 30})


def test_the_curve_table_has_a_row_where_the_count_changes() -> None:
    rows = calibration_rows(
        [run("a", 0.8, True), run("b", 0.5, True), run("c", 0.3, False)], {"a": True}
    )
    table = curve_table(routing_curve(rows))
    lines = table.splitlines()[2:]
    assert [line.split("|")[2].strip() for line in lines] == ["2", "1", "0"]
