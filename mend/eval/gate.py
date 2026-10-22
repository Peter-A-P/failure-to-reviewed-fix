"""What project 03's release gate is handed for each ablation: a spec and one file per side.

The plan runs the ablations through the 03 gate (PLAN.md section 1) rather than computing
a paired test here, so that the statistics, the power screen and Holm's adjustment across
suites are the portfolio's one implementation. The gate grades nothing. This module turns
graded outcomes into its adapter's format (03's gate/adapter.py and docs/gate-adapter.md):
a spec whose suites have source kind outcomes_file, and per side, per suite, one boolean
per item. Item ids are SWE-bench instance ids, so the gate pairs the two sides task by task.

Two suites per ablation, each a property where higher is better, because the gate asks
whether the candidate is worse than the baseline by more than the margin:

- resolved: the hidden tests passed (the no-test-first ablation), or verdict-right: the
  reviewer accepted a patch the hidden tests passed or rejected one they failed (the
  review ablation, where the patches are identical and only the verdict differs);
- not-confidently-wrong: the task was not auto-proposed with a patch the hidden tests
  failed. This is the confidently-wrong rate turned the right way up, one item per task.

A task whose arm produced no verdict (a reply that could not be read twice) is absent from
that side's outcomes and counted as ungradeable, the gate's own rule.

The margin is ten points, set before either arm ran. At 40 tasks a paired interval on
these measures is roughly twelve points either side, so a three-point margin could only
ever warn; the gate's power screen says what each suite can and cannot decide, and its
interval is reported whatever the verdict.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from mend.graph.route import Tier

DELTA_POINTS = 10.0

Grade = Callable[[Mapping[str, Any], bool], bool | None]


def _tier(run: Mapping[str, Any]) -> str | None:
    return (run.get("state") or {}).get("tier")


def resolved(run: Mapping[str, Any], passed: bool) -> bool | None:
    del run
    return passed


def not_confidently_wrong(run: Mapping[str, Any], passed: bool) -> bool | None:
    state = run.get("state") or {}
    if (
        state.get("stage") == "stopped"
        and state.get("review") is None
        and state.get("patch") is not None
    ):
        # Drafted, then no verdict: ungradeable, not right or wrong.
        return None
    return not (_tier(run) == Tier.AUTO_PROPOSE.value and not passed)


def verdict_right(run: Mapping[str, Any], passed: bool) -> bool | None:
    review = (run.get("state") or {}).get("review")
    if review is None:
        return None
    return bool(review["agrees"]) == passed


SUITES: dict[str, dict[str, Grade]] = {
    "no-test-first": {"resolved": resolved, "not-confidently-wrong": not_confidently_wrong},
    "self-review": {"verdict-right": verdict_right, "not-confidently-wrong": not_confidently_wrong},
}


def spec(ablation: str) -> dict[str, Any]:
    return {
        "version": 1,
        "name": f"mend-{ablation}",
        "delta_points": DELTA_POINTS,
        "alpha": 0.05,
        "resamples": 2000,
        "seed": 0,
        "suites": [
            {"key": key, "source": {"kind": "outcomes_file", "block": key}}
            for key in SUITES[ablation]
        ],
    }


def side(
    ablation: str,
    label: str,
    runs: Sequence[Mapping[str, Any]],
    passed: Mapping[str, bool],
    *,
    source: Mapping[str, str],
) -> dict[str, Any]:
    """One side: per suite, a verdict per task, and the cost and latency of its calls."""
    hops = [h for run in runs for h in run.get("hops") or ()]
    costed = [float(h["cost_usd"]) for h in hops if h.get("cost_usd") is not None]
    latency = statistics.median(float(h["latency_ms"]) for h in hops) if hops else 0.0
    suites: dict[str, Any] = {}
    for key, grade in SUITES[ablation].items():
        outcomes: dict[str, bool] = {}
        ungradeable = 0
        for run in runs:
            issue_id = str(run["issue"]["issue_id"])
            value = grade(run, bool(passed.get(issue_id)))
            if value is None:
                ungradeable += 1
            else:
                outcomes[issue_id] = value
        suites[key] = {
            "suite": key,
            "outcomes": dict(sorted(outcomes.items())),
            "ungradeable_items": ungradeable,
            "calls": len(hops),
            "latency_p50_ms": round(latency, 1),
            "cost_usd": round(sum(costed), 6),
            "uncosted_calls": len(hops) - len(costed),
        }
    return {"label": label, "source": dict(source), "suites": suites}


def write_spec(ablation: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "spec.yaml"
    path.write_text(
        yaml.safe_dump(spec(ablation), sort_keys=False), encoding="utf-8", newline="\n"
    )
    return path
