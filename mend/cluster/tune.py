"""Choosing the agglomeration threshold from a validation split, and reporting the sweep.

PLAN.md section 2.2 says the threshold is tuned on a validation split and reported. Both
halves matter. Tuned on a split, because a threshold chosen on the set it is then measured
on is a threshold that was fitted to its own score. Reported, because the sweep is more
informative than the winner: a metric with a broad plateau means the threshold barely
matters and a sharp peak means it matters a great deal, and a reader deserves to know
which they are looking at.

Split by root cause, not by record. Records of one bug are not independent, and a random
split by record would put four symptoms of one cause on both sides, which lets a threshold
tuned on one half look good on the other for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from mend.capture.schema import FailureRecord
from mend.cluster.agglomerate import ChannelWeights, cluster_records
from mend.cluster.embed import Embedder
from mend.cluster.metrics import adjusted_rand_index, completeness, purity


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """The metrics at one candidate threshold."""

    threshold: float
    n_clusters: int
    purity: float
    completeness: float
    ari: float
    symptoms_per_cause: float


@dataclass(frozen=True, slots=True)
class Tuning:
    """A chosen threshold, the sweep it came from, and the split it was chosen on."""

    threshold: float
    ari: float
    sweep: tuple[SweepPoint, ...]
    n_validation: int
    n_causes: int
    embedder: str

    @property
    def plateau(self) -> tuple[float, float]:
        """The range of thresholds within 0.01 ARI of the best.

        Published beside the chosen value because a wide plateau means the exact number is
        not load-bearing, and a reader who sees only the winner cannot tell.
        """
        best = self.ari
        near = [p.threshold for p in self.sweep if p.ari >= best - 0.01]
        return (min(near), max(near)) if near else (self.threshold, self.threshold)


def split_by_cause(
    records: Sequence[FailureRecord],
    *,
    validation_fraction: float = 0.4,
    seed: int = 20270705,
) -> tuple[list[FailureRecord], list[FailureRecord]]:
    """Split into (validation, held out), keeping every record of a cause on one side.

    Returns validation first because that is the half the threshold is allowed to see.
    """
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be strictly between 0 and 1")
    labelled = [r for r in records if r.true_cause]
    if not labelled:
        raise ValueError("tuning needs records carrying true_cause")

    causes = sorted({r.true_cause or "" for r in labelled})
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(causes))
    take = max(1, round(len(causes) * validation_fraction))
    validation_causes = {causes[int(i)] for i in order[:take]}

    validation = [r for r in labelled if r.true_cause in validation_causes]
    held_out = [r for r in labelled if r.true_cause not in validation_causes]
    return validation, held_out


def sweep(
    records: Sequence[FailureRecord],
    *,
    candidates: Sequence[float] | None = None,
    weights: ChannelWeights | None = None,
    embedder: Embedder | None = None,
) -> list[SweepPoint]:
    """Every metric at every candidate threshold, on the records given.

    The distance matrix is recomputed per candidate rather than cached. At the sizes here
    that is seconds, and a cache keyed on anything less than the full parameter set is how
    a sweep quietly reports the metrics of the wrong configuration.
    """
    grid = list(candidates) if candidates is not None else [i / 40 for i in range(1, 40)]
    truth = [r.true_cause or "" for r in records]
    points: list[SweepPoint] = []

    for threshold in grid:
        clustering = cluster_records(
            records, threshold=threshold, weights=weights, embedder=embedder
        )
        points.append(
            SweepPoint(
                threshold=threshold,
                n_clusters=clustering.n_clusters,
                purity=purity(clustering.labels, truth),
                completeness=completeness(clustering.labels, truth),
                ari=adjusted_rand_index(clustering.labels, truth),
                symptoms_per_cause=clustering.symptoms_per_cause,
            )
        )
    return points


def tune(
    validation: Sequence[FailureRecord],
    *,
    candidates: Sequence[float] | None = None,
    weights: ChannelWeights | None = None,
    embedder: Embedder | None = None,
) -> Tuning:
    """The threshold with the best ARI on the validation records.

    ARI rather than purity or completeness, because it is the only one of the three that
    cannot be won by a degenerate answer, and a tuning objective that can be won by doing
    nothing will be.

    Ties break toward the lower threshold: fewer merges, more tickets. When the evidence
    cannot choose, the failure that leaves a maintainer with two tickets for one bug is
    cheaper than the one that buries a second bug inside a ticket about the first.
    """
    points = sweep(validation, candidates=candidates, weights=weights, embedder=embedder)
    usable = [p for p in points if not _is_nan(p.ari)]
    if not usable:
        raise ValueError("no candidate threshold produced a defined ARI")

    best = max(usable, key=lambda p: (p.ari, -p.threshold))
    reference = cluster_records(
        validation, threshold=best.threshold, weights=weights, embedder=embedder
    )
    return Tuning(
        threshold=best.threshold,
        ari=best.ari,
        sweep=tuple(points),
        n_validation=len(validation),
        n_causes=len({r.true_cause for r in validation}),
        embedder=reference.embedder,
    )


def _is_nan(value: float) -> bool:
    return value != value
