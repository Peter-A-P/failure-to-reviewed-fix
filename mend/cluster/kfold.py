"""K-fold by cause, for the labelled sets with many causes, and one pooled measurement.

mend.cluster.crossval holds out every combination of three causes, which suits 09's eight
faults (56 folds) and does not suit a set with forty faults or hundreds of duplicate
groups, where the combinations run to the thousands. Here the causes are dealt into k folds
by a seeded shuffle; each fold is held out once, the threshold is tuned on the other
folds, and the held-out fold is clustered with it.

Every record is held out exactly once, so the held-out labellings join into one labelling
of the whole set, with cluster labels kept apart by fold and group, and that labelling is
measured once: purity, completeness, ARI and symptoms per ticket, each with a bootstrap
interval from a delete-one-cause jackknife (mend.cluster.metrics.jackknife_by_cause,
which says why that and not a bootstrap). The comparison of two methods is paired on the same records,
with its own jackknife interval, and reported per fold too.

Records cluster only within their group (a suite, a repository). Two libraries' failures
never share a cause, and pooling them would let a method score by telling the libraries
apart, which is not the question.

The pairwise distances do not depend on the fold, so each group's matrix is computed once
and sliced, and the tree for each training set is built once and cut at every candidate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from mend.capture.schema import FailureRecord
from mend.cluster.agglomerate import cluster_by_fingerprint, distance_matrix
from mend.cluster.metrics import (
    ClusterMetrics,
    adjusted_rand_index,
    evaluate_by_cause,
    jackknife_by_cause,
    normal_interval,
)
from mend.eval.stats import Interval

Matrix = npt.NDArray[np.float64]
GRID = tuple(i / 40 for i in range(1, 40))
METHODS = ("record-level", "fingerprint")


def assign_folds(causes: Sequence[str], *, k: int, seed: int) -> dict[str, int]:
    """Each cause to one of k folds, by a seeded shuffle, sizes differing by at most one."""
    unique = sorted(set(causes))
    if not 2 <= k <= len(unique):
        raise ValueError(f"k must be between 2 and the {len(unique)} causes")
    order = np.random.default_rng(seed).permutation(len(unique))
    return {unique[int(i)]: position % k for position, i in enumerate(order)}


def _tree(matrix: Matrix) -> Any:
    return linkage(squareform(matrix, checks=False), method="average")


def _cut(tree: Any, n: int, threshold: float) -> list[int]:
    if n == 1:
        return [1]
    return [int(x) for x in fcluster(tree, t=threshold, criterion="distance")]


def tune_threshold(
    parts: Sequence[tuple[Matrix, Sequence[str]]], grid: Sequence[float] = GRID
) -> float:
    """The threshold with the best ARI over the training records of every group at once.

    One threshold per fold, not one per group: a group with three training causes would
    otherwise choose its threshold from almost nothing. Ties go to the lower threshold, as
    in mend.cluster.tune, for the reason given there.
    """
    trees = [(_tree(m) if len(t) > 1 else None, len(t), t) for m, t in parts]
    best: tuple[float, float] | None = None
    for threshold in grid:
        labels: list[str] = []
        truth: list[str] = []
        for g, (tree, n, t) in enumerate(trees):
            labels += [f"{g}:{x}" for x in _cut(tree, n, threshold)]
            truth += list(t)
        score = adjusted_rand_index([hash(x) for x in labels], truth)
        if best is None or score > best[1]:
            best = (threshold, score)
    if best is None:
        raise ValueError("no threshold to choose from")
    return best[0]


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold: int
    held_out_causes: int
    held_out_records: int
    threshold: float
    ari: dict[str, float]


@dataclass(frozen=True, slots=True)
class KFold:
    folds: tuple[FoldResult, ...]
    pooled: dict[str, ClusterMetrics]
    difference: Interval
    record_ids: tuple[str, ...]
    labels: dict[str, tuple[int, ...]]

    def to_json(self) -> dict[str, Any]:
        def metrics(m: ClusterMetrics) -> dict[str, Any]:
            def iv(i: Interval) -> list[float]:
                return [i.estimate, i.low, i.high]

            return {
                "n_records": m.n_records,
                "n_clusters": m.n_clusters,
                "n_true_causes": m.n_true_causes,
                "purity": iv(m.purity_interval),
                "completeness": iv(m.completeness_interval),
                "ari": iv(m.ari_interval),
                "symptoms_per_ticket": iv(m.ratio_interval),
            }

        return {
            "folds": [
                {
                    "fold": f.fold,
                    "held_out_causes": f.held_out_causes,
                    "held_out_records": f.held_out_records,
                    "threshold": f.threshold,
                    "ari": f.ari,
                }
                for f in self.folds
            ],
            "pooled": {name: metrics(m) for name, m in self.pooled.items()},
            "record_level_minus_fingerprint_ari": [
                self.difference.estimate,
                self.difference.low,
                self.difference.high,
            ],
        }


def kfold(
    records: Sequence[FailureRecord],
    *,
    k: int = 5,
    seed: int,
    group: Callable[[FailureRecord], str] = lambda r: r.repo or "",
    grid: Sequence[float] = GRID,
    matrix_for: Callable[[Sequence[FailureRecord]], Matrix] = distance_matrix,
) -> KFold:
    labelled = [r for r in records if r.true_cause]
    folds_of = assign_folds([r.true_cause or "" for r in labelled], k=k, seed=seed)
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(labelled):
        groups.setdefault(group(r), []).append(i)
    matrices = {g: matrix_for([labelled[i] for i in idx]) for g, idx in groups.items()}

    predicted: dict[str, dict[int, str]] = {m: {} for m in METHODS}
    results: list[FoldResult] = []
    for fold in range(k):
        train_parts: list[tuple[Matrix, Sequence[str]]] = []
        for g, idx in groups.items():
            local = [j for j, i in enumerate(idx) if folds_of[labelled[i].true_cause or ""] != fold]
            if local:
                train_parts.append(
                    (
                        matrices[g][np.ix_(local, local)],
                        [labelled[idx[j]].true_cause or "" for j in local],
                    )
                )
        threshold = tune_threshold(train_parts, grid)
        held: list[int] = []
        for g, idx in groups.items():
            local = [j for j, i in enumerate(idx) if folds_of[labelled[i].true_cause or ""] == fold]
            if not local:
                continue
            sub = matrices[g][np.ix_(local, local)]
            cut = _cut(_tree(sub) if len(local) > 1 else None, len(local), threshold)
            prints = cluster_by_fingerprint([labelled[idx[j]] for j in local]).labels
            for j, a, b in zip(local, cut, prints, strict=True):
                predicted["record-level"][idx[j]] = f"{fold}:{g}:{a}"
                predicted["fingerprint"][idx[j]] = f"{fold}:{g}:{b}"
                held.append(idx[j])
        truth = [labelled[i].true_cause or "" for i in held]
        results.append(
            FoldResult(
                fold=fold,
                held_out_causes=len(set(truth)),
                held_out_records=len(held),
                threshold=threshold,
                ari={
                    m: adjusted_rand_index([hash(predicted[m][i]) for i in held], truth)
                    for m in METHODS
                },
            )
        )

    order = list(range(len(labelled)))
    truth_all = [labelled[i].true_cause or "" for i in order]
    numbered: dict[str, list[int]] = {}
    for m in METHODS:
        ids: dict[str, int] = {}
        numbered[m] = [ids.setdefault(predicted[m][i], len(ids) + 1) for i in order]
    pooled = {m: evaluate_by_cause(numbered[m], truth_all) for m in METHODS}

    def gap(full: Sequence[int], prints_only: Sequence[int], truth: Sequence[str]) -> float:
        return adjusted_rand_index(full, truth) - adjusted_rand_index(prints_only, truth)

    point, se = jackknife_by_cause(
        [numbered["record-level"], numbered["fingerprint"]], truth_all, gap
    )

    return KFold(
        folds=tuple(results),
        pooled=pooled,
        difference=normal_interval(point, se, len(set(truth_all)), low=-2.0, high=2.0),
        record_ids=tuple(r.record_id for r in labelled),
        labels={m: tuple(numbered[m]) for m in METHODS},
    )
