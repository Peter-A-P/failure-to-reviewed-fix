"""Combining the three channels into one distance, and cutting the tree into tickets.

The combined distance is a weighted mean over the channels that had something to say
about a given pair. A channel that is silent (locality, when either side has no
traceback) is dropped from that pair and the remaining weights are renormalised, rather
than being scored as maximum distance. See locality_distance for why that distinction is
the whole ball game for issue reports.

Average linkage rather than single or complete. Single linkage chains: one ambiguous
record between two bugs merges both into one ticket, which is the failure mode that
destroys purity. Complete linkage is the opposite and splits a genuinely diverse bug into
several tickets, which destroys completeness. Average linkage is the one that degrades
gracefully in both directions, and the threshold is what trades between them, tuned on a
validation split and reported (PLAN.md section 2.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from mend.capture.schema import FailureRecord
from mend.cluster.embed import Embedder, HashingEmbedder, cosine_distances
from mend.cluster.fingerprint import fingerprint, fingerprint_distance
from mend.cluster.locality import locality_distance


@dataclass(frozen=True, slots=True)
class ChannelWeights:
    """How much each channel carries. Defaults are the starting point, not a result.

    The tuned values belong in docs/clustering.md next to the validation split they were
    tuned on, and are passed in here rather than edited in place, so that a reported
    number always names the weights that produced it.
    """

    fingerprint: float = 0.4
    text: float = 0.3
    locality: float = 0.3

    def __post_init__(self) -> None:
        total = self.fingerprint + self.text + self.locality
        if total <= 0:
            raise ValueError("channel weights must sum to something positive")
        if min(self.fingerprint, self.text, self.locality) < 0:
            raise ValueError("channel weights must not be negative")


@dataclass(frozen=True, slots=True)
class Clustering:
    """Cluster labels for a set of records, and how they were produced."""

    record_ids: tuple[str, ...]
    labels: tuple[int, ...]
    threshold: float
    weights: ChannelWeights
    embedder: str

    @property
    def n_clusters(self) -> int:
        return len(set(self.labels))

    @property
    def symptoms_per_cause(self) -> float:
        """The headline ratio: records ingested divided by tickets opened.

        This is a description of the output, not a score. A system that puts everything
        in one ticket has a magnificent ratio and is useless, which is why it is always
        reported beside purity and completeness.
        """
        return len(self.record_ids) / self.n_clusters if self.n_clusters else 0.0

    def groups(self) -> dict[int, tuple[str, ...]]:
        out: dict[int, list[str]] = {}
        for record_id, label in zip(self.record_ids, self.labels, strict=True):
            out.setdefault(label, []).append(record_id)
        return {label: tuple(ids) for label, ids in sorted(out.items())}


def distance_matrix(
    records: Sequence[FailureRecord],
    *,
    weights: ChannelWeights | None = None,
    embedder: Embedder | None = None,
) -> npt.NDArray[np.float64]:
    """The combined pairwise distance, in the unit interval.

    O(n squared) in both time and memory, which is the right trade at the sizes here: the
    largest labelled set in the plan is a few thousand issues, and a dense matrix over
    that is tens of megabytes and lets every channel be inspected directly.
    """
    weights = weights or ChannelWeights()
    embedder = embedder or HashingEmbedder()
    n = len(records)
    out = np.zeros((n, n), dtype=np.float64)
    if n < 2:
        return out

    fingerprints = [fingerprint(r) for r in records]
    text_distance = cosine_distances(embedder.encode([r.failure_text for r in records]))

    for i in range(n):
        for j in range(i + 1, n):
            channels: list[tuple[float, float]] = [
                (weights.fingerprint, fingerprint_distance(fingerprints[i], fingerprints[j])),
                (weights.text, float(text_distance[i, j])),
            ]
            local = locality_distance(records[i], records[j])
            if local is not None:
                channels.append((weights.locality, local))

            total_weight = sum(w for w, _ in channels)
            distance = sum(w * d for w, d in channels) / total_weight if total_weight > 0 else 1.0
            out[i, j] = out[j, i] = distance
    return out


def cluster_records(
    records: Sequence[FailureRecord],
    *,
    threshold: float,
    weights: ChannelWeights | None = None,
    embedder: Embedder | None = None,
) -> Clustering:
    """Cluster by average linkage, cut at `threshold`.

    A threshold of 0.0 would put every record in its own cluster and 1.0 would put them
    all in one; the useful range is narrow and is what the validation split decides.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in the unit interval")
    weights = weights or ChannelWeights()
    embedder = embedder or HashingEmbedder()
    ids = tuple(r.record_id for r in records)

    if len(records) == 0:
        return Clustering((), (), threshold, weights, embedder.name)
    if len(records) == 1:
        return Clustering(ids, (1,), threshold, weights, embedder.name)

    matrix = distance_matrix(records, weights=weights, embedder=embedder)
    # squareform wants an exactly symmetric matrix with a zero diagonal; the construction
    # above guarantees it, and checks=False saves a second pass over the whole matrix.
    tree = linkage(squareform(matrix, checks=False), method="average")
    labels = fcluster(tree, t=threshold, criterion="distance")
    return Clustering(ids, tuple(int(x) for x in labels), threshold, weights, embedder.name)


def cluster_by_fingerprint(records: Sequence[FailureRecord]) -> Clustering:
    """The Rule C baseline: group by exact fingerprint key, nothing else.

    Reported beside the full clustering so that the ARI gap is the evidence for or against
    the extra two channels (PLAN.md section 9.3).
    """
    keys: dict[str, int] = {}
    labels: list[int] = []
    for record in records:
        key = fingerprint(record).key
        labels.append(keys.setdefault(key, len(keys) + 1))
    return Clustering(
        tuple(r.record_id for r in records),
        tuple(labels),
        threshold=0.0,
        weights=ChannelWeights(fingerprint=1.0, text=0.0, locality=0.0),
        embedder="none",
    )
