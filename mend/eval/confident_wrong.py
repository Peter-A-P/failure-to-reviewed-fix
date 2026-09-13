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

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


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
) -> tuple[Cause, ...]:
    """Causes worth looking at first, from the evidence already on the record.

    A shortlist for the person classifying, in no particular order of likelihood, and
    explicitly not a decision. Returns every cause when the evidence says nothing, which
    is the honest answer rather than a confident guess.
    """
    candidates: list[Cause] = []
    if not touches_traceback_frames:
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
