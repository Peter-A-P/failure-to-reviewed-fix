"""Cross-validation over causes: every fold, tuned only on what it may see."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

import pytest

from mend.capture.schema import FailureRecord, Source
from mend.cluster.crossval import Clusterer, leave_causes_out, paired, spread, summarise


def records(causes: str, per: int = 3) -> list[FailureRecord]:
    return [
        FailureRecord(record_id=f"{c}{i}", source=Source.CHAOS, message=c, true_cause=c)
        for c in causes
        for i in range(per)
    ]


def perfect(train: Sequence[FailureRecord]) -> Clusterer:
    return lambda test: [ord(r.message[0]) if r.message else 0 for r in test]


def lump(train: Sequence[FailureRecord]) -> Clusterer:
    return lambda test: [0] * len(test)


def test_every_combination_is_one_fold_and_the_tuner_never_sees_its_fold() -> None:
    seen: list[tuple[set[str], set[str]]] = []

    def spy(train: Sequence[FailureRecord]) -> Clusterer:
        def apply(test: Sequence[FailureRecord]) -> list[int]:
            seen.append(({r.true_cause or "" for r in train}, {r.true_cause or "" for r in test}))
            return [0] * len(test)

        return apply

    folds = leave_causes_out(records("abcde"), {"spy": spy}, k=2)
    assert len(folds) == 10
    assert all(not (train & test) for train, test in seen)
    assert {f.held_out for f in folds} == set(combinations("abcde", 2))


def test_a_perfect_method_beats_lumping_on_every_fold() -> None:
    folds = leave_causes_out(records("abcde"), {"perfect": perfect, "lump": lump}, k=3)
    assert summarise(folds, "perfect").mean == pytest.approx(1.0)
    assert summarise(folds, "lump").mean == pytest.approx(0.0)
    difference, wins = paired(folds, "perfect", "lump")
    assert wins == len(folds) == 10 and difference.mean == pytest.approx(1.0)


def test_k_must_leave_something_to_tune_on() -> None:
    with pytest.raises(ValueError):
        leave_causes_out(records("abc"), {"lump": lump}, k=3)


def test_the_spread_is_labelled_as_folds_not_a_confidence_interval() -> None:
    text = spread([0.1, 0.2, 0.3]).as_value()
    assert "folds" in text and "CI" not in text
