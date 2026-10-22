"""The README's tables, written from the committed results and from nothing else.

The repository rule is that the report command fills the tables and nobody edits them by
hand. Each table sits between two markers in README.md, <!-- report:name --> and
<!-- /report:name -->, and replace_section rewrites only what is between them. The inputs
are files under results/, committed beside the code, so anyone can rerun the command and
get the same tables, and anyone who reruns the pipeline can compare.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mend.cluster.crossval import Fold, paired, summarise
from mend.eval.results import (
    IssueOutcome,
    confidently_wrong_rate,
    cost_per_attempted,
    cost_per_resolved,
    hit_rate,
    quiet_precision,
    reviewer_value,
    test_first_rate,
    tier_table,
)
from mend.graph.route import Tier

_TIER_NAMES = {
    Tier.AUTO_PROPOSE: "Auto-propose (draft PR)",
    Tier.SUGGEST: "Suggest",
    Tier.QUIET: "Stay quiet",
}


def load_outcomes(path: Path) -> list[IssueOutcome]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [IssueOutcome(**{**r, "tier": Tier(r["tier"])}) for r in rows]


def load_folds(path: Path) -> list[Fold]:
    return [
        Fold(held_out=tuple(f["held_out"]), ari={k: float(v) for k, v in f["ari"].items()})
        for f in json.loads(path.read_text(encoding="utf-8"))
    ]


def _money(interval_text: str) -> str:
    return "US$" + interval_text


def resolution_table(outcomes: Sequence[IssueOutcome]) -> str:
    lines = [
        "| Tier | Issues | Hit rate on hidden tests (95% CI) | Confidently wrong (95% CI) "
        "| Cost per attempted (95% CI) | Cost per resolved (95% CI) |",
        "|---|---|---|---|---|---|",
    ]
    for row in tier_table(outcomes):
        wrong = row.confidently_wrong.as_percent() if row.confidently_wrong is not None else ""
        lines.append(
            f"| {_TIER_NAMES[row.tier]} | {row.n} | {row.hit_rate.as_percent()} | {wrong} "
            f"| {_money(row.cost_per_attempted.as_value(3))} "
            f"| {_money(row.cost_per_resolved.as_value(3))} |"
        )
    lines.append(
        f"| **All** | {len(outcomes)} | {hit_rate(outcomes).as_percent()} "
        f"| {confidently_wrong_rate(outcomes).as_percent()} of auto-proposals "
        f"| {_money(cost_per_attempted(outcomes).as_value(3))} "
        f"| {_money(cost_per_resolved(outcomes).as_value(3))} |"
    )
    return "\n".join(lines)


def review_table(outcomes: Sequence[IssueOutcome]) -> str:
    value = reviewer_value(outcomes)
    return "\n".join(
        [
            "| Test-first rate (95% CI) | Reviewer objected (95% CI) "
            "| Patch wrong when the reviewer objected | Patch wrong when it agreed "
            "| Stay-quiet precision (95% CI) |",
            "|---|---|---|---|---|",
            f"| {test_first_rate(outcomes).as_percent()} "
            f"| {value.disagreement_rate.as_percent()} "
            f"| {value.fixer_wrong_when_disagreed.as_percent()} "
            f"| {value.fixer_wrong_when_agreed.as_percent()} "
            f"| {quiet_precision(outcomes).as_percent()} |",
        ]
    )


def clustering_table(folds: Sequence[Fold], *, label: str) -> str:
    lines = [
        "| Labelled set | Method | Held-out ARI, mean | Spread across folds (not a CI) |",
        "|---|---|---|---|",
    ]
    names = {
        "record-level": "Record-level (fingerprint, text, locality)",
        "fingerprint": "Fingerprint only",
        "two-stage": "Two-stage (incidents, then signatures)",
    }
    for key, name in names.items():
        spread = summarise(folds, key)
        lines.append(
            f"| {label} | {name} | {spread.mean:.3f} | {spread.low:.3f} to {spread.high:.3f} |"
        )
    difference, wins = paired(folds, "two-stage", "record-level")
    lines.append(
        f"| {label} | Two-stage minus record-level, paired | {difference.mean:.3f} "
        f"| {difference.low:.3f} to {difference.high:.3f}; higher on {wins} of {len(folds)} folds |"
    )
    return "\n".join(lines)


def load_kfold(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _ci(values: Sequence[float], *, percent: bool = False, places: int = 3) -> str:
    est, low, high = values
    if percent:
        return f"{est * 100:.1f}% ({low * 100:.1f}% to {high * 100:.1f}%)"
    return f"{est:.{places}f} ({low:.{places}f} to {high:.{places}f})"


def kfold_table(sets: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
    """The labelled sets measured by k-fold over causes: one row per method, then the
    paired difference. Intervals are a delete-one-cause jackknife (mend.cluster.metrics)."""
    lines = [
        "| Labelled set | Method | ARI (95% CI) | Purity (95% CI) | Completeness (95% CI) "
        "| Symptoms per ticket (95% CI) |",
        "|---|---|---|---|---|---|",
    ]
    names = {
        "record-level": "Record-level (fingerprint, text, locality)",
        "fingerprint": "Fingerprint only",
    }
    shown: set[str] = set()
    for label, payload in sets:
        pooled = payload["pooled"]
        # The fingerprint has no text channel, so a second embedder on the same set gives
        # it the same row; it is shown once per set.
        base = label.split(",")[0].split(" (")[0]
        for key, name in names.items():
            if key == "fingerprint" and base in shown:
                continue
            m = pooled[key]
            lines.append(
                f"| {label} | {name} | {_ci(m['ari'])} | {_ci(m['purity'], percent=True)} "
                f"| {_ci(m['completeness'], percent=True)} "
                f"| {_ci(m['symptoms_per_ticket'], places=2)} |"
            )
        shown.add(base)
        folds = payload["folds"]
        wins = sum(1 for f in folds if f["ari"]["record-level"] > f["ari"]["fingerprint"])
        lines.append(
            f"| {label} | Record-level minus fingerprint, paired "
            f"| {_ci(payload['record_level_minus_fingerprint_ari'])} "
            f"| higher on {wins} of {len(folds)} folds | | |"
        )
    return "\n".join(lines)


def replace_section(text: str, name: str, body: str) -> str:
    pattern = re.compile(
        rf"(<!-- report:{re.escape(name)} -->\n).*?(<!-- /report:{re.escape(name)} -->)", re.S
    )
    if not pattern.search(text):
        raise ValueError(f"README has no report:{name} markers")
    return pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text, count=1)
