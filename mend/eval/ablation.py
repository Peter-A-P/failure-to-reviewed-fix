"""The ablation tables: what each arm did, task by task, from the committed run logs.

The release gate decides whether an ablated arm is worse than the main design by more than
the margin (mend.eval.gate, gate-runs/). These tables say what the arms did, so the gate's
verdict can be read against the counts it was made on. Every share carries a Wilson
interval and its n.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mend.eval.stats import wilson
from mend.graph.route import Tier

Run = Mapping[str, Any]


def _state(run: Run) -> Mapping[str, Any]:
    return run.get("state") or {}


def _agrees(run: Run) -> bool | None:
    review = _state(run).get("review")
    return None if review is None else bool(review["agrees"])


def _auto(run: Run) -> bool:
    return _state(run).get("tier") == Tier.AUTO_PROPOSE.value


def review_row(name: str, runs: Sequence[Run], passed: Mapping[str, bool]) -> str:
    """One reviewer, over the patches it reviewed."""
    judged = [r for r in runs if _agrees(r) is not None]
    ok = [r for r in judged if passed.get(str(r["issue"]["issue_id"]))]
    bad = [r for r in judged if not passed.get(str(r["issue"]["issue_id"]))]
    objected = [r for r in judged if _agrees(r) is False]
    right = [r for r in judged if _agrees(r) == bool(passed.get(str(r["issue"]["issue_id"])))]
    auto = [r for r in judged if _auto(r)]
    wrong_auto = [r for r in auto if not passed.get(str(r["issue"]["issue_id"]))]
    return (
        f"| {name} | {wilson(len(objected), len(judged)).as_percent()} "
        f"| {wilson(sum(1 for r in bad if _agrees(r) is False), len(bad)).as_percent()} "
        f"| {wilson(sum(1 for r in ok if _agrees(r) is False), len(ok)).as_percent()} "
        f"| {wilson(len(right), len(judged)).as_percent()} "
        f"| {wilson(len(wrong_auto), len(auto)).as_percent()} |"
    )


def review_table(arms: Sequence[tuple[str, Sequence[Run]]], passed: Mapping[str, bool]) -> str:
    lines = [
        "| Reviewer | Objected | Caught: objected to a patch the hidden tests failed "
        "| False alarm: objected to a patch they passed | Verdict matched the hidden tests "
        "| Confidently wrong among auto-proposals |",
        "|---|---|---|---|---|---|",
    ]
    lines += [review_row(name, runs, passed) for name, runs in arms]
    return "\n".join(lines)


def agreement(a: Sequence[Run], b: Sequence[Run]) -> str:
    """How often two reviews of the same patches gave the same verdict."""
    first = {str(r["issue"]["issue_id"]): _agrees(r) for r in a}
    pairs = [(first[k], _agrees(r)) for r in b if (k := str(r["issue"]["issue_id"])) in first]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    return wilson(sum(1 for x, y in pairs if x == y), len(pairs)).as_percent()


def first_test_row(name: str, runs: Sequence[Run], passed: Mapping[str, bool]) -> str:
    resolved = sum(1 for r in runs if passed.get(str(r["issue"]["issue_id"])))
    drafted = sum(1 for r in runs if (_state(r).get("patch") or {}).get("diff"))
    auto = [r for r in runs if _auto(r)]
    wrong = sum(1 for r in auto if not passed.get(str(r["issue"]["issue_id"])))
    costs = [float(r["cost_usd"]) for r in runs if r.get("cost_usd") is not None]
    return (
        f"| {name} | {wilson(resolved, len(runs)).as_percent()} | {drafted} "
        f"| {len(auto)} | {wilson(wrong, len(auto)).as_percent()} "
        f"| US${sum(costs) / len(costs):.3f} |"
    )


def first_test_table(
    main: Sequence[Run],
    main_passed: Mapping[str, bool],
    ablated: Sequence[Run],
    ablated_passed: Mapping[str, bool],
) -> str:
    lines = [
        "| Arm | Resolved on hidden tests | Patches drafted | Auto-proposed "
        "| Confidently wrong among auto-proposals | Model cost per task |",
        "|---|---|---|---|---|---|",
        first_test_row("Failing test first (main run, same tasks)", main, main_passed),
        first_test_row("No failing test first", ablated, ablated_passed),
    ]
    both = only_main = only_ablated = 0
    by_id = {str(r["issue"]["issue_id"]) for r in ablated}
    for issue_id in sorted(by_id):
        a, b = bool(main_passed.get(issue_id)), bool(ablated_passed.get(issue_id))
        both += a and b
        only_main += a and not b
        only_ablated += b and not a
    lines.append("")
    lines.append(
        f"Task by task: {both} resolved by both, {only_main} only with the test first, "
        f"{only_ablated} only without it."
    )
    return "\n".join(lines)


def gate_table(ledger: Path, names: Sequence[tuple[str, str]]) -> str:
    """The latest gate decision for each ablation, suite by suite, from this repository's
    gate ledger. names maps a spec name to the row label."""
    records: dict[str, Mapping[str, Any]] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[str(record.get("spec_name") or record.get("spec", {}).get("name"))] = record
    lines = [
        "| Ablation | Suite | Paired tasks | Main design | Ablated | Ablated minus main (95% CI) "
        "| Gate verdict at a 10-point margin |",
        "|---|---|---|---|---|---|---|",
    ]
    for spec_name, label in names:
        record = records.get(spec_name)
        if record is None:
            continue
        for suite in record["suites"]:

            def pct(x: float | None) -> str:
                return "" if x is None else f"{x * 100:.1f}%"

            diff = (
                f"{suite['difference'] * 100:+.1f} ({suite['lo'] * 100:+.1f} to "
                f"{suite['hi'] * 100:+.1f}) points"
                if suite["difference"] is not None
                else ""
            )
            lines.append(
                f"| {label} | {suite['suite']} | {suite['paired_items']} "
                f"| {pct(suite['baseline_accuracy'])} | {pct(suite['candidate_accuracy'])} "
                f"| {diff} | {suite['verdict']} |"
            )
    return "\n".join(lines)
