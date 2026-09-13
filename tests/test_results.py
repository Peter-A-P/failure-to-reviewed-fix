"""The reported numbers, and the denominators they are computed over.

Almost every way of overstating a result like this one is a choice of denominator, so that
is what these test: the hit rate is over every issue in the subset and not over the ones
the system chose to attempt; the confidently-wrong rate is over auto-proposals only;
stay-quiet precision is over the silences where a patch actually existed; cost per resolved
issue includes the money spent on the issues that were not resolved.
"""

from __future__ import annotations

import math

import pytest

from mend.eval.confident_wrong import Cause, Classification, hint, tabulate
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
from mend.eval.stats import Interval, wilson
from mend.graph.route import Tier


def outcome(
    issue_id: str,
    tier: Tier,
    *,
    resolved: bool,
    patch: bool = True,
    reviewer: bool | None = True,
    cost: float | None = 0.40,
    test_first: bool = True,
) -> IssueOutcome:
    return IssueOutcome(
        issue_id=issue_id,
        tier=tier,
        score=0.8,
        test_written=test_first,
        test_failed_first=test_first,
        patch_drafted=patch,
        reviewer_agreed=reviewer,
        resolved=resolved,
        cost_usd=cost,
        duration_s=180.0,
    )


def test_the_hit_rate_counts_the_issues_the_system_declined() -> None:
    """Attempting less must not raise the hit rate.

    Two runs over the same ten issues resolve two each. The one that quietly declined six
    of them does not get a better number for having done less.
    """
    tried_everything = [outcome(f"a{i}", Tier.AUTO_PROPOSE, resolved=i < 2) for i in range(10)]
    declined_most = [
        *[outcome(f"b{i}", Tier.AUTO_PROPOSE, resolved=i < 2) for i in range(4)],
        *[outcome(f"b{i}", Tier.QUIET, resolved=False, patch=False) for i in range(4, 10)],
    ]
    assert hit_rate(tried_everything).estimate == pytest.approx(hit_rate(declined_most).estimate)


def test_confidently_wrong_is_over_auto_proposals_only() -> None:
    """A suggestion was never a confident claim; folding them in would flatter the number."""
    outcomes = [
        outcome("a1", Tier.AUTO_PROPOSE, resolved=True),
        outcome("a2", Tier.AUTO_PROPOSE, resolved=False),
        *[outcome(f"s{i}", Tier.SUGGEST, resolved=False) for i in range(20)],
    ]
    assert confidently_wrong_rate(outcomes).estimate == pytest.approx(0.5)


def test_confidently_wrong_is_undefined_rather_than_zero_with_no_proposals() -> None:
    """A system that proposed nothing has not earned a 0% false-positive rate."""
    outcomes = [outcome(f"s{i}", Tier.SUGGEST, resolved=False) for i in range(10)]
    interval = confidently_wrong_rate(outcomes)
    assert interval.n == 0
    assert (interval.low, interval.high) == (0.0, 1.0)


def test_quiet_precision_only_counts_silences_about_a_patch() -> None:
    """An issue that stopped before drafting anything was never a judgement about a patch."""
    outcomes = [
        # Rightly silent: a patch existed and it was wrong.
        outcome("q1", Tier.QUIET, resolved=False, patch=True),
        outcome("q2", Tier.QUIET, resolved=False, patch=True),
        # Wrongly silent: a patch existed and it was right.
        outcome("q3", Tier.QUIET, resolved=True, patch=True),
        # Never got there; must not count as a correct silence.
        *[outcome(f"q{i}", Tier.QUIET, resolved=False, patch=False) for i in range(4, 20)],
    ]
    interval = quiet_precision(outcomes)
    assert interval.n == 3
    assert interval.estimate == pytest.approx(2 / 3)


def test_test_first_rate_is_over_every_issue() -> None:
    outcomes = [
        *[outcome(f"t{i}", Tier.AUTO_PROPOSE, resolved=True) for i in range(6)],
        *[
            outcome(f"n{i}", Tier.QUIET, resolved=False, patch=False, test_first=False)
            for i in range(4)
        ],
    ]
    assert test_first_rate(outcomes).estimate == pytest.approx(0.6)
    assert test_first_rate(outcomes).n == 10


def test_cost_per_resolved_includes_the_issues_that_were_not_resolved() -> None:
    """A dollar on each of ten issues, one fixed, costs ten dollars a fix, not one."""
    outcomes = [outcome(f"c{i}", Tier.AUTO_PROPOSE, resolved=(i == 0), cost=1.0) for i in range(10)]
    assert cost_per_resolved(outcomes).estimate == pytest.approx(10.0)
    assert cost_per_attempted(outcomes).estimate == pytest.approx(1.0)


def test_an_uncosted_issue_is_excluded_rather_than_treated_as_free() -> None:
    outcomes = [
        outcome("c1", Tier.AUTO_PROPOSE, resolved=True, cost=1.0),
        outcome("c2", Tier.AUTO_PROPOSE, resolved=True, cost=None),
    ]
    interval = cost_per_attempted(outcomes)
    assert interval.n == 1
    assert interval.estimate == pytest.approx(1.0)


def test_reviewer_value_needs_disagreements_to_predict_wrongness() -> None:
    """A reviewer that objects at random has a disagreement rate and no value.

    The number that decides it is whether the fixer was actually wrong more often when the
    reviewer objected than when it agreed.
    """
    useful = [
        *[outcome(f"d{i}", Tier.SUGGEST, resolved=False, reviewer=False) for i in range(8)],
        *[outcome(f"a{i}", Tier.AUTO_PROPOSE, resolved=True, reviewer=True) for i in range(12)],
    ]
    value = useful_value = reviewer_value(useful)
    assert value.n_reviewed == 20
    assert value.n_disagreed == 8
    assert value.caught == 8
    assert value.false_alarms == 0
    assert (
        useful_value.fixer_wrong_when_disagreed.estimate
        > useful_value.fixer_wrong_when_agreed.estimate
    )

    rubber_stamp = [
        outcome(f"a{i}", Tier.AUTO_PROPOSE, resolved=i < 10, reviewer=True) for i in range(20)
    ]
    stamped = reviewer_value(rubber_stamp)
    assert stamped.n_disagreed == 0
    assert stamped.disagreement_rate.estimate == 0.0


def test_an_unreviewed_issue_is_not_counted_as_agreement() -> None:
    outcomes = [
        outcome("r1", Tier.QUIET, resolved=False, reviewer=None),
        outcome("r2", Tier.AUTO_PROPOSE, resolved=True, reviewer=True),
    ]
    assert reviewer_value(outcomes).n_reviewed == 1


def test_the_tier_table_covers_every_tier_even_when_empty() -> None:
    """An empty tier is a finding; a table that omits the row hides it."""
    outcomes = [outcome("a1", Tier.AUTO_PROPOSE, resolved=True)]
    rows = tier_table(outcomes)
    assert [r.tier for r in rows] == [Tier.AUTO_PROPOSE, Tier.SUGGEST, Tier.QUIET]
    assert rows[1].n == 0
    assert rows[1].confidently_wrong is None
    assert rows[0].confidently_wrong is not None


def test_wilson_stays_inside_the_unit_interval_at_the_extremes() -> None:
    """The reason for Wilson rather than the normal approximation, asserted.

    Zero successes out of forty is not evidence of a zero rate, and the interval has to
    say so without running below zero.
    """
    zero = wilson(0, 40)
    assert zero.estimate == 0.0
    assert zero.low == 0.0
    assert 0.0 < zero.high < 0.15

    all_of_them = wilson(40, 40)
    assert all_of_them.high == 1.0
    assert 0.85 < all_of_them.low < 1.0


def test_wilson_with_no_observations_is_the_whole_range() -> None:
    interval = wilson(0, 0)
    assert (interval.low, interval.high, interval.n) == (0.0, 1.0, 0)


def test_wilson_refuses_impossible_counts() -> None:
    with pytest.raises(ValueError, match="between 0 and n"):
        wilson(5, 3)


def test_an_interval_prints_its_sample_size() -> None:
    """A percentage without its n invites the reader to guess how solid it is."""
    assert "n = 40" in wilson(10, 40).as_percent()


def test_the_taxonomy_reports_its_empty_categories() -> None:
    counts = tabulate([Classification("i1", Cause.SYMPTOM_NOT_CAUSE, "patched the None check")])
    assert set(counts) == set(Cause)
    assert counts[Cause.SYMPTOM_NOT_CAUSE] == 1
    assert counts[Cause.WRONG_LOCATION] == 0


def test_a_classification_must_say_why() -> None:
    with pytest.raises(ValueError, match="must say why"):
        Classification("i1", Cause.WRONG_LOCATION, "   ")


def test_the_hint_narrows_but_does_not_decide() -> None:
    narrow = hint(
        files_touched=1,
        lines_changed=2,
        touches_traceback_frames=True,
        suite_green=True,
        reviewer_objected=False,
    )
    assert Cause.SYMPTOM_NOT_CAUSE in narrow
    assert len(narrow) < len(Cause)

    # With nothing to go on, every cause is offered rather than one guessed.
    silent = hint(
        files_touched=2,
        lines_changed=20,
        touches_traceback_frames=True,
        suite_green=True,
        reviewer_objected=False,
    )
    assert set(silent) == set(Cause)


def test_no_number_is_reported_without_an_interval() -> None:
    """Every public result function returns an Interval, not a float (Rule E)."""
    outcomes = [outcome("a1", Tier.AUTO_PROPOSE, resolved=True)]
    for function in (hit_rate, test_first_rate, confidently_wrong_rate, quiet_precision):
        result = function(outcomes)
        assert isinstance(result, Interval)
        assert result.low <= result.estimate <= result.high
        assert result.method


def test_a_ratio_that_cannot_be_computed_is_nan_not_zero() -> None:
    """No resolutions means cost per resolved issue is undefined, not free."""
    outcomes = [outcome(f"c{i}", Tier.QUIET, resolved=False, cost=1.0) for i in range(5)]
    assert math.isnan(cost_per_resolved(outcomes).estimate)
