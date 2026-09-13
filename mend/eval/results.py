"""The reported numbers: hit rate, confidently wrong, stay-quiet precision, reviewer value.

One record type, IssueOutcome, carries everything one issue produced, and every headline
number in PLAN.md section 1 is a function of a list of them. That shape is the point: a
table that cannot be recomputed from the stored outcomes is a table nobody can check, and
the report command in mend.cli writes the README's tables from exactly this.

Two rules the plan insists on, implemented here rather than trusted:

- Report the hit rate as it falls. There is no filtering argument anywhere in this module.
  A subset is chosen before the run and its ids committed (mend.data.swebench); there is
  no supported way to drop the hard tasks afterwards.
- Every number carries a confidence interval. Each function returns an Interval, not a
  float, so a caller who wants a bare percentage has to throw the interval away on
  purpose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mend.eval.stats import Interval, bootstrap, wilson
from mend.graph.route import Tier


@dataclass(frozen=True, slots=True)
class IssueOutcome:
    """Everything one issue produced, including the parts that only the harness knows.

    resolved is the benchmark's hidden tests, and reached the system's own reasoning at no
    point: the fixer, the tester and the reviewer never see it, and no threshold is tuned
    on it (PLAN.md section 2.1). It is set by the harness after the fact.

    patch_drafted is separate from resolved because the interesting failure is a patch the
    system was confident about and the hidden tests rejected. stay-quiet precision needs
    the same thing from the other direction: for an issue routed to silence, was the patch
    the system declined to propose in fact wrong.
    """

    issue_id: str
    tier: Tier
    score: float
    test_written: bool
    test_failed_first: bool
    patch_drafted: bool
    reviewer_agreed: bool | None
    resolved: bool
    cost_usd: float | None = None
    duration_s: float | None = None
    stop_reason: str | None = None

    @property
    def attempted(self) -> bool:
        """An issue the system got as far as drafting a patch for."""
        return self.patch_drafted


def hit_rate(outcomes: Sequence[IssueOutcome], *, tier: Tier | None = None) -> Interval:
    """Share of issues resolved, judged by the hidden tests. Wilson interval.

    The denominator is every issue in the subset, not every issue the system attempted.
    Attempted-only would let the system raise its own hit rate by attempting less, which
    is precisely the behaviour the stay-quiet tier is for, and it would be measured twice.
    """
    considered = [o for o in outcomes if tier is None or o.tier is tier]
    return wilson(sum(1 for o in considered if o.resolved), len(considered))


def test_first_rate(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Share of issues where a test was produced that failed on the broken commit.

    The denominator is every issue, because failing to write a demonstrating test is one
    of the things this measures, not a reason to leave the issue out.
    """
    return wilson(sum(1 for o in outcomes if o.test_failed_first), len(outcomes))


# The test-first rate is the name the plan uses, and it is the right one. pytest would
# otherwise collect this as a test case from any test module that imports it.
test_first_rate.__test__ = False  # type: ignore[attr-defined]


def confidently_wrong_rate(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Share of auto-proposals that the hidden tests rejected.

    The number that matters more than the hit rate (PLAN.md section 1). A draft pull
    request on an engineer's desk that does not fix the bug costs more of their attention
    than no pull request at all, and unlike a miss it arrives wearing a suit.

    The denominator is auto-proposals only. An issue the system suggested rather than
    proposed was not a confident claim, and folding those in would flatter the number.
    """
    auto = [o for o in outcomes if o.tier is Tier.AUTO_PROPOSE]
    return wilson(sum(1 for o in auto if not o.resolved), len(auto))


def quiet_precision(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Of issues routed to silence, the share where the drafted fix was in fact wrong.

    Knowing when not to act, measured. High is good: it means the system stayed quiet
    about patches that would not have worked.

    Only issues where a patch was actually drafted count. An issue that stopped earlier,
    with no failing test, was never a judgement about a patch, and counting those as
    correct silences would inflate this number with the cases the system never reached.
    """
    quiet = [o for o in outcomes if o.tier is Tier.QUIET and o.patch_drafted]
    return wilson(sum(1 for o in quiet if not o.resolved), len(quiet))


@dataclass(frozen=True, slots=True)
class ReviewerValue:
    """Whether the second model earns its cost (PLAN.md section 1).

    disagreement_rate alone says nothing: a reviewer that objects to everything has a
    magnificent disagreement rate and no value. fixer_wrong_when_disagreed is the number
    that decides it, and caught is what it means in practice: patches that would have been
    proposed, that the reviewer stopped, that the hidden tests confirm were wrong.

    The plan commits to a consequence for this number: if disagreements do not predict
    wrong patches, the reviewer becomes an ablation rather than a gate, and the README
    says so.
    """

    n_reviewed: int
    n_disagreed: int
    disagreement_rate: Interval
    fixer_wrong_when_disagreed: Interval
    fixer_wrong_when_agreed: Interval
    caught: int
    false_alarms: int


def reviewer_value(outcomes: Sequence[IssueOutcome]) -> ReviewerValue:
    """The reviewer's disagreement rate and whether it predicts a wrong patch."""
    reviewed = [o for o in outcomes if o.reviewer_agreed is not None and o.patch_drafted]
    disagreed = [o for o in reviewed if o.reviewer_agreed is False]
    agreed = [o for o in reviewed if o.reviewer_agreed is True]

    return ReviewerValue(
        n_reviewed=len(reviewed),
        n_disagreed=len(disagreed),
        disagreement_rate=wilson(len(disagreed), len(reviewed)),
        fixer_wrong_when_disagreed=wilson(
            sum(1 for o in disagreed if not o.resolved), len(disagreed)
        ),
        fixer_wrong_when_agreed=wilson(sum(1 for o in agreed if not o.resolved), len(agreed)),
        caught=sum(1 for o in disagreed if not o.resolved),
        false_alarms=sum(1 for o in disagreed if o.resolved),
    )


def cost_per_attempted(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Mean cost of an attempted issue, bootstrapped.

    Costs come from the gateway ledger, never from an estimate (PLAN.md section 2.6).
    Outcomes with no recorded cost are excluded and the n says how many were left, rather
    than being treated as free.
    """
    costs = [o.cost_usd for o in outcomes if o.attempted and o.cost_usd is not None]
    return bootstrap(costs, lambda s: sum(s) / len(s) if s else float("nan"))


def cost_per_resolved(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Total spend divided by issues resolved, bootstrapped over issues.

    The ratio, not the mean cost of the resolved ones, because the spend on the issues
    that were not resolved is part of what a resolution costs. A system that spends a
    dollar on each of a hundred issues and fixes ten has a cost per resolved issue of ten
    dollars, not one.
    """
    priced = [o for o in outcomes if o.cost_usd is not None]

    def ratio(sample: Sequence[IssueOutcome]) -> float:
        resolved = sum(1 for o in sample if o.resolved)
        if resolved == 0:
            return float("nan")
        return sum(o.cost_usd or 0.0 for o in sample) / resolved

    return bootstrap(priced, ratio)


def minutes_per_issue(outcomes: Sequence[IssueOutcome]) -> Interval:
    """Median wall-clock minutes per attempted issue, bootstrapped.

    Median rather than mean: the distribution has a long tail of sandbox timeouts, and the
    claim being checked is "triage in minutes", which is a claim about the typical issue.
    """
    durations = [o.duration_s / 60.0 for o in outcomes if o.attempted and o.duration_s is not None]

    def median(sample: Sequence[float]) -> float:
        if not sample:
            return float("nan")
        ordered = sorted(sample)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    return bootstrap(durations, median)


@dataclass(frozen=True, slots=True)
class TierRow:
    """One row of the README's headline table."""

    tier: Tier
    n: int
    hit_rate: Interval
    confidently_wrong: Interval | None
    cost_per_attempted: Interval
    cost_per_resolved: Interval


def tier_table(outcomes: Sequence[IssueOutcome]) -> list[TierRow]:
    """The README's resolution-and-restraint table, one row per tier.

    Confidently wrong is only meaningful for the auto-propose tier, so the other rows
    carry None rather than a number that would be read as the same thing.
    """
    rows: list[TierRow] = []
    for tier in (Tier.AUTO_PROPOSE, Tier.SUGGEST, Tier.QUIET):
        subset = [o for o in outcomes if o.tier is tier]
        rows.append(
            TierRow(
                tier=tier,
                n=len(subset),
                hit_rate=hit_rate(subset),
                confidently_wrong=confidently_wrong_rate(subset)
                if tier is Tier.AUTO_PROPOSE
                else None,
                cost_per_attempted=cost_per_attempted(subset),
                cost_per_resolved=cost_per_resolved(subset),
            )
        )
    return rows
