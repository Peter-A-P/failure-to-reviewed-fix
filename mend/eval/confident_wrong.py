"""Why a confident patch was wrong: the false-positive taxonomy.

A confidently-wrong rate is a number. What makes it useful to anybody building one of
these is knowing which way it goes wrong, so every auto-proposal the hidden tests rejected
is classified into one of the causes below, and the counts are published
(docs/false-positives.md).

The categories were chosen before the first run, from the failure modes the design
predicts, so that classification is a judgement about which bucket a case falls in rather
than an invitation to invent a bucket that makes the distribution look tidy. A case that
fits none of them is UNCLASSIFIED, and the count of those is reported too: a taxonomy that
never fails to classify anything is a taxonomy that has stopped being informative.

Classification is manual. The automatic hints in `hint` narrow it down from the evidence
already on the record, but nothing here decides, because the whole value of the taxonomy
is that a person looked at the diff.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from mend.eval.stats import wilson
from mend.graph.route import Tier


class Cause(StrEnum):
    """Why an auto-proposed patch failed the hidden tests."""

    # The generated test failed on the broken commit and passed after the patch, but it
    # tested something other than the reported bug. The patch satisfies it and fixes
    # nothing. The predicted commonest cause, and the one test-first is meant to reduce.
    TEST_PROVED_NOTHING = "test_proved_nothing"

    # The patch treats the symptom at the point it surfaced rather than the cause: a None
    # check where the None should never have been produced. The visible test passes; the
    # hidden tests exercise the other paths into the same fault.
    SYMPTOM_NOT_CAUSE = "symptom_not_cause"

    # The patch fixes the reported case and breaks a case the visible suite does not
    # cover. Distinguished from the above because the fix was right and the blast radius
    # was wrong.
    REGRESSION_ELSEWHERE = "regression_elsewhere"

    # Localisation pointed at the wrong place, and everything downstream was a coherent
    # answer to the wrong question.
    WRONG_LOCATION = "wrong_location"

    # The patch is a plausible fix for the issue as written, and the issue as written is
    # not what the maintainers meant. A real category, and the one no amount of model
    # capability removes.
    ISSUE_UNDERSPECIFIED = "issue_underspecified"

    # The patch changes behaviour the hidden tests pin, in a way that is defensible but
    # not what the project decided. Sorting order, error message wording, a default.
    DEFENSIBLE_DISAGREEMENT = "defensible_disagreement"

    # Nothing above fits. Reported rather than forced into a neighbour.
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class Classification:
    """One wrong auto-proposal, classified, with the evidence that justified it.

    note is required and not allowed to be empty: a taxonomy row with no sentence
    explaining it is a row nobody can check, and the point of publishing this is that a
    reader can disagree with a specific call.
    """

    issue_id: str
    cause: Cause
    note: str

    def __post_init__(self) -> None:
        if not self.note.strip():
            raise ValueError(f"{self.issue_id}: a classification must say why")


def hint(
    *,
    files_touched: int,
    lines_changed: int,
    touches_traceback_frames: bool,
    suite_green: bool,
    reviewer_objected: bool,
    issue_has_traceback: bool = True,
) -> tuple[Cause, ...]:
    """Causes worth looking at first, from the evidence already on the record.

    A shortlist for the person classifying, in no particular order of likelihood, and
    explicitly not a decision. Returns every cause when the evidence says nothing, which
    is the honest answer rather than a confident guess. A patch can only miss the
    traceback's frames when the issue had a traceback, so an issue without one says
    nothing about location.
    """
    candidates: list[Cause] = []
    if issue_has_traceback and not touches_traceback_frames:
        candidates.append(Cause.WRONG_LOCATION)
    if files_touched == 1 and lines_changed <= 3:
        # A one-line change at the point of failure is what a symptom patch looks like.
        candidates.append(Cause.SYMPTOM_NOT_CAUSE)
    if files_touched > 3 or lines_changed > 100:
        candidates.append(Cause.REGRESSION_ELSEWHERE)
    if not suite_green:
        candidates.append(Cause.REGRESSION_ELSEWHERE)
    if reviewer_objected:
        candidates.append(Cause.TEST_PROVED_NOTHING)
    return tuple(dict.fromkeys(candidates)) or tuple(Cause)


def tabulate(classifications: Sequence[Classification]) -> dict[Cause, int]:
    """Counts by cause, every cause present, zeroes included.

    Zeroes included because "no patch in this run failed for this reason" is a finding,
    and a table that omits the empty rows hides it.
    """
    counts = dict.fromkeys(Cause, 0)
    for item in classifications:
        counts[item.cause] += 1
    return counts


# What each cause means in one line, for the template a person fills in and the README.
MEANING: dict[Cause, str] = {
    Cause.TEST_PROVED_NOTHING: "the generated test passed after the patch but tested "
    "something other than the reported bug",
    Cause.SYMPTOM_NOT_CAUSE: "guarded the point of failure instead of fixing where the bad "
    "value came from",
    Cause.REGRESSION_ELSEWHERE: "fixed the reported case and broke one the visible suite "
    "does not cover",
    Cause.WRONG_LOCATION: "changed the wrong place",
    Cause.ISSUE_UNDERSPECIFIED: "a fair reading of the issue as written, not what the "
    "maintainers meant",
    Cause.DEFENSIBLE_DISAGREEMENT: "reasonable behaviour the project decided differently: "
    "wording, an order, a default",
    Cause.UNCLASSIFIED: "none of the above",
}


def wrong_auto_proposals(
    runs: Iterable[Mapping[str, Any]], passed: Mapping[str, bool]
) -> list[Mapping[str, Any]]:
    """The run records this taxonomy is about: auto-proposed, and failed the hidden tests."""
    return sorted(
        (
            r
            for r in runs
            if (r.get("state") or {}).get("tier") == Tier.AUTO_PROPOSE.value
            and not passed.get(str(r["issue"]["issue_id"]))
        ),
        key=lambda r: str(r["issue"]["issue_id"]),
    )


def template(issue_ids: Sequence[str]) -> str:
    """The file a person fills in: one entry per case, cause and note left empty."""
    lines = [
        "# Why each auto-proposed patch failed the hidden tests (docs/false-positives.md).",
        "# Filled in by hand, by a person who read the hidden tests; no model reads them.",
        "# cause is one of:",
        *(f"#   {c.value}: {MEANING[c]}" for c in Cause),
        "# note is one sentence a reader could check against the diff. Both are required.",
        "",
    ]
    for issue_id in issue_ids:
        lines += [f"- issue_id: {issue_id}", '  cause: ""', '  note: ""', ""]
    return "\n".join(lines)


def read(path: Path, issue_ids: Sequence[str]) -> list[Classification] | None:
    """The classifications in path, or None while any case is still blank.

    The file has to cover exactly the cases the run produced: a case dropped or added by
    hand would change the denominator, which is the one thing this table must not do."""
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    found = [str(r["issue_id"]) for r in rows]
    if sorted(found) != sorted(issue_ids):
        raise ValueError(
            f"{path} must classify exactly {sorted(issue_ids)}; it has {sorted(found)}"
        )
    if any(not str(r.get("cause") or "").strip() for r in rows):
        return None
    return [
        Classification(str(r["issue_id"]), Cause(str(r["cause"]).strip()), str(r.get("note") or ""))
        for r in rows
    ]


def table(classifications: Sequence[Classification]) -> str:
    """Counts by cause, every cause a row, then each case with its sentence."""
    n = len(classifications)
    counts = tabulate(classifications)
    lines = [
        "| Cause | What it means | Cases (95% CI) |",
        "|---|---|---|",
        *(
            f"| {c.value} | {MEANING[c]} | {counts[c]} of {n}, {wilson(counts[c], n).as_percent()} |"
            for c in Cause
        ),
        "",
        "| Task | Cause | Why |",
        "|---|---|---|",
        *(
            f"| {item.issue_id} | {item.cause.value} | {item.note.strip()} |"
            for item in sorted(classifications, key=lambda x: x.issue_id)
        ),
    ]
    return "\n".join(lines)
