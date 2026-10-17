"""Cross-validation over causes: every way of holding k causes out, tuned on the rest.

A single validation split by cause leaves a labelled set with few causes (09's chaos runs
have eight) choosing its parameters from two or three of them, and the choice then depends
on which two or three the seed happened to pick (docs/clustering.md has the case where it
did). This removes the seed: every combination of k causes is held out once, each method
is tuned on the remaining causes and scored on the held-out ones, and the result is the
spread of held-out ARI over all the folds.

It was adopted on 2026-10-17 after the first single-split result had been seen, and is
reported beside that result, not instead of it.

The folds overlap, since every cause is held out in many of them, so the spread across
folds is a description of how much the answer depends on which causes were held out. It is
not a confidence interval, and is not labelled as one. The comparison between two methods
is paired: both are tuned and scored on the same fold.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from mend.capture.schema import FailureRecord
from mend.cluster.metrics import adjusted_rand_index

# A method is a tuner, given the training records, that returns a clusterer for new ones.
Clusterer = Callable[[Sequence[FailureRecord]], Sequence[int]]
Method = Callable[[Sequence[FailureRecord]], Clusterer]


@dataclass(frozen=True, slots=True)
class Fold:
    held_out: tuple[str, ...]
    ari: dict[str, float]


@dataclass(frozen=True, slots=True)
class Spread:
    mean: float
    low: float
    high: float
    n_folds: int

    def as_value(self, places: int = 3) -> str:
        return (
            f"{self.mean:.{places}f} (folds {self.low:.{places}f} to {self.high:.{places}f}, "
            f"{self.n_folds} folds)"
        )


def spread(values: Sequence[float]) -> Spread:
    """Mean, with the 2.5th and 97.5th percentiles across folds."""
    arr = np.asarray(values, dtype=float)
    return Spread(
        mean=float(arr.mean()),
        low=float(np.percentile(arr, 2.5)),
        high=float(np.percentile(arr, 97.5)),
        n_folds=len(arr),
    )


def leave_causes_out(
    records: Sequence[FailureRecord],
    methods: Mapping[str, Method],
    *,
    k: int = 3,
) -> list[Fold]:
    labelled = [r for r in records if r.true_cause]
    causes = sorted({r.true_cause or "" for r in labelled})
    if not 2 <= k < len(causes):
        raise ValueError(f"k must be at least 2 and less than the {len(causes)} causes")
    folds = []
    for held in combinations(causes, k):
        train = [r for r in labelled if r.true_cause not in held]
        test = [r for r in labelled if r.true_cause in held]
        truth = [r.true_cause or "" for r in test]
        scores = {
            name: adjusted_rand_index(list(tune(train)(test)), truth)
            for name, tune in methods.items()
        }
        folds.append(Fold(held_out=held, ari=scores))
    return folds


def summarise(folds: Sequence[Fold], method: str) -> Spread:
    return spread([f.ari[method] for f in folds])


def paired(folds: Sequence[Fold], a: str, b: str) -> tuple[Spread, int]:
    """a minus b on every fold, and on how many folds a scored higher."""
    differences = [f.ari[a] - f.ari[b] for f in folds]
    return spread(differences), sum(1 for d in differences if d > 0)
