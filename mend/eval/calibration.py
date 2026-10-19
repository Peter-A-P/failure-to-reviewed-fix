"""Turning a validation run into routing thresholds, and keeping them where they can be read.

PLAN.md section 2.5: the thresholds are chosen on the validation split against a stated
false-positive target, the whole trade-off curve is published, and the main run uses the
thresholds without seeing its own outcomes first. This module is the hand-off between the
two runs. calibrate() is mend.graph.route.calibrate; what is here reads a run's records into
calibration rows, writes the chosen thresholds to a committed file with where they came
from, and reads them back.

The file refuses to be overwritten, for the reason the subset file does: thresholds chosen
again after the main run had been seen would be tuned on the main run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from mend.eval.stats import wilson
from mend.graph.route import CurvePoint, Outcome, Thresholds


def calibration_rows(
    runs: Iterable[Mapping[str, Any]], judged: Mapping[str, bool | None]
) -> list[Outcome]:
    """One row per task. A task with no drafted patch is a row the router could never
    propose, so coverage on the curve is a share of every task, not of the drafted ones."""
    rows = []
    for run in runs:
        issue_id = str(run["issue"]["issue_id"])
        state = run.get("state") or {}
        patch = state.get("patch") or {}
        review = state.get("review") or {}
        rows.append(
            Outcome(
                issue_id=issue_id,
                score=float(state.get("score") or 0.0),
                reviewer_agrees=bool(review.get("agrees")),
                resolved=bool(judged.get(issue_id)),
                eligible=bool(patch.get("test_passes") and patch.get("suite_green")),
            )
        )
    return rows


def write_thresholds(thresholds: Thresholds, path: Path, provenance: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(
            f"{path} already holds calibrated thresholds. Recalibrating after the main run "
            "would tune them on it; delete the file in a commit that says why."
        )
    payload = {
        "auto_propose": thresholds.auto_propose,
        "suggest": thresholds.suggest,
        "target_confidently_wrong": thresholds.target_confidently_wrong,
        "calibrated_on": thresholds.calibrated_on,
        "provenance": dict(provenance),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_thresholds(path: Path) -> Thresholds:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Thresholds(
        auto_propose=float(data["auto_propose"]),
        suggest=float(data["suggest"]),
        target_confidently_wrong=float(data["target_confidently_wrong"]),
        calibrated_on=str(data["calibrated_on"]),
    )


def curve_table(points: Sequence[CurvePoint]) -> str:
    """The curve as a Markdown table, one row wherever the number auto-proposed changes:
    between those thresholds nothing differs, and a hundred identical rows hide the shape."""
    lines = [
        "| Threshold from | Auto-proposed | Resolved | Confidently wrong (95% CI) | Coverage |",
        "|---|---|---|---|---|",
    ]
    previous = None
    for point in points:
        if point.n_auto == previous:
            continue
        previous = point.n_auto
        wrong = wilson(point.n_auto - point.n_resolved, point.n_auto)
        wrong_text = wrong.as_percent() if point.n_auto else "none proposed"
        lines.append(
            f"| {point.threshold:.2f} | {point.n_auto} | {point.n_resolved} | {wrong_text} "
            f"| {point.coverage:.0%} |"
        )
    return "\n".join(lines)
