"""Confidence routing: the score, the hard rules, and the calibration.

The tests that matter here are the ones about restraint, because the score is easy to get
right and the refusals are what the design is actually claiming. A patch that leaves the
suite red must never be proposed however high it scores; a reviewer who disagrees must cap
the tier; and the calibration must not be able to hit its false-positive target by
proposing almost nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from mend.graph.route import (
    Outcome,
    ScoreWeights,
    Signals,
    Thresholds,
    Tier,
    calibrate,
    route,
    routing_curve,
    score,
)

THRESHOLDS = Thresholds(
    auto_propose=0.75,
    suggest=0.35,
    target_confidently_wrong=0.03,
    calibrated_on="fixture",
)


def good(**overrides: Any) -> Signals:
    base: dict[str, Any] = {
        "test_failed_then_passed": True,
        "suite_green": True,
        "reviewer_agrees": True,
        "touches_traceback_frames": True,
        "files_touched": 1,
        "lines_changed": 6,
        "cluster_size": 4,
    }
    base.update(overrides)
    return Signals(**base)


def test_the_best_case_scores_high_and_is_proposed() -> None:
    tier, value = route(good(), THRESHOLDS)
    assert tier is Tier.AUTO_PROPOSE
    assert value > 0.75


def test_a_red_suite_is_never_proposed_however_good_it_looks() -> None:
    """The hard rule: no score can buy a proposal on top of a failing suite."""
    tier, _ = route(good(suite_green=False), THRESHOLDS)
    assert tier is Tier.QUIET


def test_a_patch_that_does_not_pass_its_own_test_is_never_proposed() -> None:
    tier, _ = route(good(test_failed_then_passed=False), THRESHOLDS)
    assert tier is Tier.QUIET


def test_a_disagreeing_reviewer_caps_the_tier_at_suggest() -> None:
    """Disagreement escalates to a person (PLAN.md section 2.4), whatever the score says."""
    tier, value = route(good(reviewer_agrees=False), THRESHOLDS)
    assert tier is Tier.SUGGEST
    # And not because the score fell below the threshold; with a permissive threshold it
    # would still be capped.
    permissive = Thresholds(
        auto_propose=0.0, suggest=0.0, target_confidently_wrong=0.03, calibrated_on="fixture"
    )
    assert route(good(reviewer_agrees=False), permissive)[0] is Tier.SUGGEST
    assert value > 0.0


def test_the_score_falls_as_the_patch_ranges_further() -> None:
    """A wide patch is less proven by one failing test than a narrow one."""
    narrow = score(good(files_touched=1, lines_changed=5))
    wide = score(good(files_touched=9, lines_changed=500))
    assert wide < narrow


def test_the_score_stays_in_the_unit_interval() -> None:
    extremes = [
        good(files_touched=200, lines_changed=10_000),
        good(
            test_failed_then_passed=False,
            suite_green=False,
            reviewer_agrees=False,
            touches_traceback_frames=False,
            cluster_size=0,
        ),
        good(cluster_size=10_000),
    ]
    for signals in extremes:
        assert 0.0 <= score(signals) <= 1.0


def test_a_patch_away_from_the_traceback_scores_lower() -> None:
    assert score(good(touches_traceback_frames=False)) < score(good())


def test_cluster_evidence_saturates() -> None:
    """Forty symptoms is not four times the evidence of ten."""
    assert score(good(cluster_size=10)) == pytest.approx(score(good(cluster_size=400)))


def test_weights_are_configurable_without_changing_the_shape() -> None:
    """A signal is worth its weight, where the total has room for it.

    Deliberately a small weight: with a large one the best case saturates at 1.0 and the
    difference is the headroom rather than the weight, which is correct behaviour and a
    confusing thing to assert here. test_the_score_stays_in_the_unit_interval covers the
    saturation.
    """
    light_reviewer = ScoreWeights(reviewer_agrees=0.05)
    with_reviewer = score(good(), light_reviewer)
    without = score(good(reviewer_agrees=False), light_reviewer)
    assert with_reviewer < 1.0
    assert with_reviewer - without == pytest.approx(0.05)


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="suggest <= auto_propose"):
        Thresholds(
            auto_propose=0.3,
            suggest=0.8,
            target_confidently_wrong=0.03,
            calibrated_on="fixture",
        )


def test_a_threshold_must_say_where_it_came_from() -> None:
    with pytest.raises(ValueError, match="calibrated on"):
        Thresholds(auto_propose=0.8, suggest=0.3, target_confidently_wrong=0.03, calibrated_on="")


LIAR = 22  # The one high-scoring issue the hidden tests reject.


def outcomes() -> list[Outcome]:
    """Forty issues where the score is honest: high scores are usually right.

    Built so that the 3% target actually binds. Everything scoring above 0.5 resolved,
    except one issue at index 22, which scored 0.56 and did not. A threshold at or below
    0.56 therefore includes a wrong auto-proposal and misses the target; a threshold just
    above it meets the target with seventeen proposals still in scope, which is enough
    coverage to be a real choice rather than an evasion.
    """
    rows: list[Outcome] = []
    for i in range(40):
        value = i / 39
        resolved = value > 0.5 and i != LIAR
        rows.append(Outcome(issue_id=f"i{i}", score=value, reviewer_agrees=True, resolved=resolved))
    return rows


def test_the_curve_covers_the_whole_range() -> None:
    curve = routing_curve(outcomes(), steps=11)
    assert [p.threshold for p in curve] == pytest.approx([i / 10 for i in range(11)])
    # Coverage falls as the threshold rises; that is what the trade-off is.
    coverage = [p.coverage for p in curve]
    assert coverage == sorted(coverage, reverse=True)


def test_a_higher_threshold_never_increases_the_confidently_wrong_rate_much() -> None:
    """On honest scores, restraint buys precision. The direction is the claim."""
    curve = routing_curve(outcomes(), steps=21)
    populated = [p for p in curve if p.n_auto >= 5]
    assert populated[0].confidently_wrong >= populated[-1].confidently_wrong


def test_calibration_picks_the_lowest_threshold_meeting_the_target() -> None:
    thresholds = calibrate(outcomes(), target_confidently_wrong=0.03, split_name="validation")
    assert thresholds.calibrated_on == "validation"
    assert thresholds.target_confidently_wrong == 0.03

    curve = {p.threshold: p for p in routing_curve(outcomes())}
    chosen = curve[thresholds.auto_propose]
    assert chosen.confidently_wrong <= 0.03
    assert chosen.n_auto >= 5

    # And it is the lowest such threshold: one step down misses the target, which is what
    # makes this a calibration rather than an arbitrarily safe choice.
    below = [p for p in curve.values() if p.threshold < thresholds.auto_propose and p.n_auto >= 5]
    assert below, "the fixture must contain a threshold that fails the target"
    assert max(p.confidently_wrong for p in below) > 0.03


def test_calibration_will_not_hit_its_target_by_proposing_nothing() -> None:
    """min_auto is the guard against a 0% rate on n = 1.

    Every issue here is wrong except the single highest scorer. A calibration without the
    guard would happily choose a threshold that auto-proposes exactly that one and report
    a perfect false-positive rate.
    """
    rows = [
        Outcome(issue_id=f"i{i}", score=i / 19, reviewer_agrees=True, resolved=(i == 19))
        for i in range(20)
    ]
    thresholds = calibrate(rows, target_confidently_wrong=0.03, split_name="validation")
    assert thresholds.auto_propose == 1.0, "expected calibration to refuse to propose anything"


def test_calibration_refuses_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="needs outcomes"):
        calibrate([], split_name="validation")


def test_a_threshold_of_one_means_propose_nothing() -> None:
    """The honest answer when no threshold is safe enough, wired end to end."""
    refuse = Thresholds(
        auto_propose=1.0, suggest=0.35, target_confidently_wrong=0.03, calibrated_on="validation"
    )
    tier, _ = route(good(), refuse)
    assert tier is Tier.SUGGEST


def test_the_curve_never_counts_a_patch_the_router_would_refuse() -> None:
    """A patch whose suite went red is QUIET at any score; the curve must agree."""
    from mend.graph.route import Outcome, routing_curve

    outcomes = [
        Outcome(issue_id="good", score=0.8, reviewer_agrees=True, resolved=True),
        Outcome(issue_id="red", score=0.9, reviewer_agrees=True, resolved=False, eligible=False),
    ]
    point = next(p for p in routing_curve(outcomes) if p.threshold == 0.5)
    assert point.n_auto == 1 and point.confidently_wrong == 0.0
