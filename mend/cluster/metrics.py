"""Clustering metrics against a labelled set: purity, completeness, ARI.

Three numbers because no one of them can be trusted alone, and the failure mode of this
whole stage is a number that looks good for the wrong reason.

- Purity punishes merging: put two bugs in one ticket and it falls. Alone it is maximised
  by giving every symptom its own ticket, which is the system doing nothing.
- Completeness punishes splitting: leave one bug spread over five tickets and it falls.
  Alone it is maximised by putting everything in one ticket, which is worse than nothing.
- Adjusted Rand index is the one that cannot be gamed by either, because it is corrected
  for the agreement a random labelling of the same shape would get by chance. It is the
  number the Rule C comparison in PLAN.md section 9.3 turns on.

Symptoms per root cause is reported beside them, not instead of them, for the same reason:
it is a description of the output, and on its own it is maximised by being wrong.

These are standard definitions, implemented here rather than imported so that the
measurement and its tests are in the repository that reports the number. They are checked
against hand-worked fixtures in tests/test_cluster_metrics.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mend.eval.stats import Interval, bootstrap

Labels = Sequence[int]
Truth = Sequence[str]


@dataclass(frozen=True, slots=True)
class ClusterMetrics:
    """One labelled set, measured. Intervals are bootstrapped over the records."""

    n_records: int
    n_clusters: int
    n_true_causes: int
    purity: float
    completeness: float
    ari: float
    symptoms_per_cause: float
    ari_interval: Interval
    purity_interval: Interval
    completeness_interval: Interval
    ratio_interval: Interval


def _contingency(labels: Labels, truth: Truth) -> dict[tuple[int, str], int]:
    table: dict[tuple[int, str], int] = {}
    for label, cause in zip(labels, truth, strict=True):
        key = (label, cause)
        table[key] = table.get(key, 0) + 1
    return table


def purity(labels: Labels, truth: Truth) -> float:
    """Weighted mean over clusters of the share held by the cluster's commonest cause.

    In words: if a maintainer opens a ticket, what fraction of the symptoms in it are
    actually the bug the ticket is about.
    """
    if not labels:
        return float("nan")
    table = _contingency(labels, truth)
    best: dict[int, int] = {}
    for (label, _cause), count in table.items():
        best[label] = max(best.get(label, 0), count)
    return sum(best.values()) / len(labels)


def completeness(labels: Labels, truth: Truth) -> float:
    """Weighted mean over causes of the share of that cause landing in one cluster.

    In words: when a bug produces twenty symptoms, how many of them ended up in the same
    ticket. This is the number the headline claim rests on.
    """
    if not labels:
        return float("nan")
    table = _contingency(labels, truth)
    best: dict[str, int] = {}
    for (_label, cause), count in table.items():
        best[cause] = max(best.get(cause, 0), count)
    return sum(best.values()) / len(labels)


def _comb2(n: int) -> float:
    """Pairs from n items. Float, because the products below overflow int64 in numpy and
    Python ints are exact but the surrounding arithmetic is not."""
    return n * (n - 1) / 2.0


def adjusted_rand_index(labels: Labels, truth: Truth) -> float:
    """Rand index corrected for chance. 0.0 is a random labelling; 1.0 is exact agreement.

    Can be negative, which means the labelling agrees with the truth less than chance
    would. That is a real result and is not clamped.
    """
    n = len(labels)
    if n < 2:
        return float("nan")

    table = _contingency(labels, truth)
    label_totals: dict[int, int] = {}
    cause_totals: dict[str, int] = {}
    for (label, cause), count in table.items():
        label_totals[label] = label_totals.get(label, 0) + count
        cause_totals[cause] = cause_totals.get(cause, 0) + count

    sum_cells = sum(_comb2(c) for c in table.values())
    sum_labels = sum(_comb2(c) for c in label_totals.values())
    sum_causes = sum(_comb2(c) for c in cause_totals.values())
    total_pairs = _comb2(n)

    expected = sum_labels * sum_causes / total_pairs
    maximum = (sum_labels + sum_causes) / 2.0
    if math.isclose(maximum, expected):
        # Every item in one cluster and one cause, or every item in its own: agreement is
        # perfect and the correction is undefined. 1.0 is the conventional answer.
        return 1.0
    return (sum_cells - expected) / (maximum - expected)


def symptoms_per_cause(labels: Labels, truth: Truth) -> float:
    """Records divided by clusters. The headline ratio in PLAN.md section 1."""
    del truth
    return len(labels) / len(set(labels)) if labels else float("nan")


def evaluate(
    labels: Labels,
    truth: Truth,
    *,
    resamples: int = 2000,
    seed: int = 20270705,
) -> ClusterMetrics:
    """Every metric with a bootstrap interval over the records.

    Resampling records rather than clusters, because a record is the unit that was
    sampled: the labelled sets are collections of symptoms, and a different draw of the
    same size would be a different draw of symptoms.
    """
    if len(labels) != len(truth):
        raise ValueError("labels and truth must be the same length")

    pairs = list(zip(labels, truth, strict=True))

    def _ari(sample: Sequence[tuple[int, str]]) -> float:
        return adjusted_rand_index([x for x, _ in sample], [y for _, y in sample])

    def _purity(sample: Sequence[tuple[int, str]]) -> float:
        return purity([x for x, _ in sample], [y for _, y in sample])

    def _completeness(sample: Sequence[tuple[int, str]]) -> float:
        return completeness([x for x, _ in sample], [y for _, y in sample])

    def _ratio(sample: Sequence[tuple[int, str]]) -> float:
        return symptoms_per_cause([x for x, _ in sample], [y for _, y in sample])

    return ClusterMetrics(
        n_records=len(labels),
        n_clusters=len(set(labels)),
        n_true_causes=len(set(truth)),
        purity=purity(labels, truth),
        completeness=completeness(labels, truth),
        ari=adjusted_rand_index(labels, truth),
        symptoms_per_cause=symptoms_per_cause(labels, truth),
        ari_interval=bootstrap(pairs, _ari, resamples=resamples, seed=seed),
        purity_interval=bootstrap(pairs, _purity, resamples=resamples, seed=seed),
        completeness_interval=bootstrap(pairs, _completeness, resamples=resamples, seed=seed),
        ratio_interval=bootstrap(pairs, _ratio, resamples=resamples, seed=seed),
    )
