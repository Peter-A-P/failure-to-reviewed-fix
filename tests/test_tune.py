"""Tuning the threshold on a validation split.

What is under test is the tuner, not the threshold. The value it picks on a nine-record
fixture is not a calibrated threshold and nothing in the repository treats it as one; the
properties that have to hold are that it splits by cause rather than by record, that it
optimises a metric a degenerate answer cannot win, and that it reports the sweep and not
only the winner.
"""

from __future__ import annotations

import pytest

from mend.cluster.tune import split_by_cause, sweep, tune
from tests.fixtures import LABELLED_SET


def test_the_split_never_puts_one_cause_on_both_sides() -> None:
    """The property that makes the split worth having."""
    validation, held_out = split_by_cause(LABELLED_SET, validation_fraction=0.4)
    validation_causes = {r.true_cause for r in validation}
    held_out_causes = {r.true_cause for r in held_out}
    assert validation_causes
    assert held_out_causes
    assert not (validation_causes & held_out_causes)


def test_the_split_keeps_every_labelled_record() -> None:
    validation, held_out = split_by_cause(LABELLED_SET, validation_fraction=0.4)
    assert len(validation) + len(held_out) == len(LABELLED_SET)


def test_the_split_is_reproducible() -> None:
    first = split_by_cause(LABELLED_SET, seed=7)[0]
    second = split_by_cause(LABELLED_SET, seed=7)[0]
    assert [r.record_id for r in first] == [r.record_id for r in second]


def test_the_split_needs_labels() -> None:
    unlabelled = [r.model_copy(update={"true_cause": None}) for r in LABELLED_SET]
    with pytest.raises(ValueError, match="true_cause"):
        split_by_cause(unlabelled)


def test_a_sweep_reports_every_candidate() -> None:
    points = sweep(LABELLED_SET, candidates=[0.2, 0.4, 0.6, 0.8])
    assert [p.threshold for p in points] == [0.2, 0.4, 0.6, 0.8]
    # Ticket counts fall as the merge tolerance rises.
    assert [p.n_clusters for p in points] == sorted([p.n_clusters for p in points], reverse=True)


def test_tuning_finds_the_threshold_that_recovers_the_fixture() -> None:
    """The fixture has a threshold at which the three bugs become three tickets.

    This asserts the tuner can find it, not that the value it finds generalises. The
    fixture is nine records built by hand; a threshold for real data comes from the
    labelled sets in PLAN.md section 2.2 and has not been measured yet.
    """
    tuning = tune(LABELLED_SET)
    assert tuning.ari == pytest.approx(1.0)
    assert tuning.n_causes == 3
    assert tuning.n_validation == len(LABELLED_SET)
    assert tuning.embedder.startswith("hashing-")


def test_tuning_reports_the_plateau_not_only_the_winner() -> None:
    """A reader has to be able to tell a broad plateau from a sharp peak."""
    tuning = tune(LABELLED_SET)
    low, high = tuning.plateau
    assert low <= tuning.threshold <= high
    assert len(tuning.sweep) > 10


def test_ties_break_toward_fewer_merges() -> None:
    """When two thresholds score the same, the lower one wins: more tickets, less burying."""
    tuning = tune(LABELLED_SET)
    best = [p.threshold for p in tuning.sweep if p.ari == pytest.approx(tuning.ari)]
    assert tuning.threshold == min(best)
