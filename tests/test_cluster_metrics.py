"""Clustering metrics against fixtures with known labels.

Hand-worked cases, not property tests, because the thing worth checking is that these
implementations agree with the standard definitions on cases where the answer can be
computed on paper. A metric that is subtly wrong here would make every number in the
README wrong in the same direction and nothing would flag it.
"""

from __future__ import annotations

import math

import pytest

from mend.cluster.metrics import (
    adjusted_rand_index,
    completeness,
    evaluate,
    purity,
    symptoms_per_cause,
)


def test_perfect_clustering() -> None:
    labels = [1, 1, 2, 2]
    truth = ["a", "a", "b", "b"]
    assert purity(labels, truth) == 1.0
    assert completeness(labels, truth) == 1.0
    assert adjusted_rand_index(labels, truth) == pytest.approx(1.0)


def test_labels_need_not_match_truth_names() -> None:
    """Cluster ids are arbitrary; only the partition matters."""
    assert adjusted_rand_index([7, 7, 99, 99], ["a", "a", "b", "b"]) == pytest.approx(1.0)


def test_everything_in_one_ticket_is_complete_and_impure() -> None:
    """The degenerate failure that a good symptoms-per-cause ratio would hide.

    Completeness is a perfect 1.0 here and that is correct: no cause has been split, they
    have been merged. This is exactly why completeness is never reported alone.
    """
    labels = [1, 1, 1, 1]
    truth = ["a", "a", "b", "b"]
    assert purity(labels, truth) == 0.5
    assert completeness(labels, truth) == 1.0
    assert symptoms_per_cause(labels, truth) == 4.0
    # The ratio looks magnificent and the ARI says the labelling is worthless.
    assert adjusted_rand_index(labels, truth) == pytest.approx(0.0)


def test_every_symptom_its_own_ticket_is_pure_and_incomplete() -> None:
    """The opposite degenerate case: the system doing nothing scores 1.0 on purity."""
    labels = [1, 2, 3, 4]
    truth = ["a", "a", "b", "b"]
    assert purity(labels, truth) == 1.0
    assert completeness(labels, truth) == 0.5
    assert symptoms_per_cause(labels, truth) == 1.0
    assert adjusted_rand_index(labels, truth) == pytest.approx(0.0)


def test_a_worked_partial_case() -> None:
    """Six symptoms, two causes, one cluster contaminated. Computed by hand.

    Clusters: {1,2,3} holds a,a,b and {4,5,6} holds b,b,b.
    Purity: (2 + 3) / 6.
    Completeness: cause a is best held 2 of its 2 in cluster 1; cause b is best held 3 of
    its 4 in cluster 2; (2 + 3) / 6.
    """
    labels = [1, 1, 1, 2, 2, 2]
    truth = ["a", "a", "b", "b", "b", "b"]
    assert purity(labels, truth) == pytest.approx(5 / 6)
    assert completeness(labels, truth) == pytest.approx(5 / 6)
    assert 0.0 < adjusted_rand_index(labels, truth) < 1.0


def test_ari_of_a_worked_example() -> None:
    """The textbook case, worked through the formula by hand.

    Contingency: cluster 1 holds 2 of a and 1 of b; cluster 2 holds 0 of a and 3 of b.
    sum over cells of C(n,2)   = C(2,2) + C(1,2) + C(3,2) = 1 + 0 + 3 = 4
    sum over clusters          = C(3,2) + C(3,2) = 3 + 3 = 6
    sum over causes            = C(2,2) + C(4,2) = 1 + 6 = 7
    total pairs                = C(6,2) = 15
    expected = 6 * 7 / 15 = 2.8;  max = (6 + 7) / 2 = 6.5
    ARI = (4 - 2.8) / (6.5 - 2.8) = 1.2 / 3.7
    """
    labels = [1, 1, 1, 2, 2, 2]
    truth = ["a", "a", "b", "b", "b", "b"]
    assert adjusted_rand_index(labels, truth) == pytest.approx(1.2 / 3.7)


def test_ari_can_be_negative() -> None:
    """A labelling that is worse than chance is reported as such, not clamped to zero."""
    labels = [1, 2, 1, 2]
    truth = ["a", "a", "b", "b"]
    assert adjusted_rand_index(labels, truth) < 0.0


def test_metrics_are_undefined_rather_than_wrong_on_tiny_samples() -> None:
    assert math.isnan(adjusted_rand_index([1], ["a"]))
    assert math.isnan(purity([], []))


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        evaluate([1, 2], ["a"])


def test_evaluate_carries_intervals_that_bracket_the_estimate() -> None:
    labels = [1, 1, 1, 2, 2, 2, 3, 3]
    truth = ["a", "a", "b", "b", "b", "b", "c", "c"]
    result = evaluate(labels, truth, resamples=300)

    for interval, point in (
        (result.purity_interval, result.purity),
        (result.completeness_interval, result.completeness),
        (result.ari_interval, result.ari),
        (result.ratio_interval, result.symptoms_per_cause),
    ):
        assert interval.estimate == pytest.approx(point)
        assert interval.low <= interval.estimate <= interval.high
        assert interval.n == len(labels)


def test_evaluate_is_reproducible() -> None:
    """A published interval has to be the same interval next time it is computed."""
    labels = [1, 1, 2, 2, 3, 3]
    truth = ["a", "a", "b", "b", "c", "c"]
    first = evaluate(labels, truth, resamples=200)
    second = evaluate(labels, truth, resamples=200)
    assert first.ari_interval == second.ari_interval
