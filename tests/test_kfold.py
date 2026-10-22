"""K-fold by cause: every record held out once, tuned without its fold, groups kept apart."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from mend.capture.schema import FailureRecord, Source
from mend.cluster.kfold import assign_folds, kfold


def records(causes: str, per: int = 4, repo: str = "r") -> list[FailureRecord]:
    return [
        FailureRecord(
            record_id=f"{repo}{c}{i}",
            source=Source.INJECTED,
            exception_type="E",
            message=f"{c} {'pqrs'[i]}",
            repo=repo,
            true_cause=f"{repo}:{c}",
        )
        for c in causes
        for i in range(per)
    ]


def by_cause(recs: Sequence[FailureRecord]) -> np.ndarray:
    """A matrix that knows the answer: near within a cause, far across."""
    n = len(recs)
    out = np.ones((n, n))
    for i in range(n):
        for j in range(n):
            if recs[i].true_cause == recs[j].true_cause:
                out[i, j] = 0.1
        out[i, i] = 0.0
    return out


def test_folds_are_balanced_and_seeded() -> None:
    folds = assign_folds(list("abcdefghij"), k=3, seed=1)
    sizes = sorted(np.bincount(list(folds.values())))
    assert sizes == [3, 3, 4]
    assert folds == assign_folds(list("abcdefghij"), k=3, seed=1)
    with pytest.raises(ValueError):
        assign_folds(list("ab"), k=3, seed=1)


def test_every_record_is_held_out_once_and_a_good_distance_is_found() -> None:
    recs = records("abcdef") + records("ghij", repo="s")
    result = kfold(recs, k=3, seed=7, matrix_for=by_cause)
    assert sum(f.held_out_records for f in result.folds) == len(recs)
    assert len(result.labels["record-level"]) == len(recs)
    assert result.pooled["record-level"].ari == pytest.approx(1.0)
    # Each message differs, so the fingerprint baseline gives every record its own ticket.
    assert result.pooled["fingerprint"].ari == pytest.approx(0.0)
    assert result.difference.estimate == pytest.approx(1.0)


def test_groups_never_share_a_ticket() -> None:
    lumped = lambda recs: np.zeros((len(recs), len(recs)))  # noqa: E731
    recs = records("ab", repo="r") + records("cd", repo="s")
    result = kfold(recs, k=2, seed=3, matrix_for=lumped)
    labels = result.labels["record-level"]
    repos = [r.repo for r in recs]
    for i in range(len(recs)):
        for j in range(len(recs)):
            if labels[i] == labels[j]:
                assert repos[i] == repos[j]
