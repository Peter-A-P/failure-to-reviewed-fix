"""Two-stage clustering: symptoms into incidents by when they began, incidents into
tickets by what they looked like.

The record-level clustering in agglomerate.py compares one symptom with another: its
fingerprint, its text, the code it passed through. That is the right comparison for
tracebacks, where one bug tends to fail in one place. It is the wrong one for production
signals. A fault in 09's streaming platform shows as a dozen metrics leaving their steady
level at once, each a record with its own name, and nothing in any channel says two of
them belong together except that they happened together (docs/clustering.md).

So this works in two steps, the way an operator reads a dashboard.

1. Incidents. Symptoms are ordered by onset, and a new incident starts wherever the gap
   since the previous onset is longer than gap_s. Only the time is used: not the host, not
   the run, nothing a label could leak through. Two faults that overlap in time would be
   merged into one incident, which is a real limitation and is stated as one.
2. Tickets. Each incident is described by the set of its symptoms' fingerprint keys (which
   metric moved and which way, which exception was raised where), and incidents are joined
   by average linkage on the Jaccard distance between those sets. Every symptom takes its
   incident's ticket.

Both parameters are chosen on a validation split held out by cause, never on the records
they are reported against (cluster/tune.py has the reasons).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from mend.capture.schema import FailureRecord
from mend.cluster.fingerprint import fingerprint
from mend.cluster.metrics import adjusted_rand_index, completeness, purity


@dataclass(frozen=True, slots=True)
class TwoStage:
    record_ids: tuple[str, ...]
    incidents: tuple[int, ...]
    labels: tuple[int, ...]
    gap_s: float
    threshold: float

    @property
    def n_incidents(self) -> int:
        return len(set(self.incidents))

    @property
    def n_clusters(self) -> int:
        return len(set(self.labels))


def incidents(records: Sequence[FailureRecord], *, gap_s: float) -> list[int]:
    """An incident number per record, in the records' own order."""
    if gap_s <= 0:
        raise ValueError("gap_s must be positive")
    order = sorted(range(len(records)), key=lambda i: records[i].captured_at)
    out = [0] * len(records)
    current = 0
    previous = None
    for i in order:
        when = records[i].captured_at
        if previous is not None and (when - previous).total_seconds() > gap_s:
            current += 1
        out[i] = current
        previous = when
    return out


def jaccard_distances(signatures: Sequence[frozenset[str]]) -> np.ndarray:
    n = len(signatures)
    out = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            a, b = signatures[i], signatures[j]
            union = len(a | b)
            d = 1.0 - (len(a & b) / union if union else 0.0)
            out[i, j] = out[j, i] = d
    return out


def cluster_two_stage(
    records: Sequence[FailureRecord], *, gap_s: float, threshold: float
) -> TwoStage:
    incident_of = incidents(records, gap_s=gap_s)
    ids = sorted(set(incident_of))
    signature = {
        k: frozenset(
            fingerprint(r).key for r, inc in zip(records, incident_of, strict=True) if inc == k
        )
        for k in ids
    }
    if len(ids) == 1:
        ticket_of = {ids[0]: 0}
    else:
        matrix = jaccard_distances([signature[k] for k in ids])
        tree = linkage(squareform(matrix, checks=False), method="average")
        assigned = fcluster(tree, t=threshold, criterion="distance")
        ticket_of = {k: int(a) for k, a in zip(ids, assigned, strict=True)}
    return TwoStage(
        record_ids=tuple(r.record_id for r in records),
        incidents=tuple(incident_of),
        labels=tuple(ticket_of[i] for i in incident_of),
        gap_s=gap_s,
        threshold=threshold,
    )


@dataclass(frozen=True, slots=True)
class TwoStagePoint:
    gap_s: float
    threshold: float
    n_incidents: int
    n_clusters: int
    purity: float
    completeness: float
    ari: float


def sweep_two_stage(
    records: Sequence[FailureRecord],
    *,
    gaps: Sequence[float],
    thresholds: Sequence[float],
) -> list[TwoStagePoint]:
    truth = [r.true_cause or "" for r in records]
    points = []
    for gap in gaps:
        for threshold in thresholds:
            result = cluster_two_stage(records, gap_s=gap, threshold=threshold)
            points.append(
                TwoStagePoint(
                    gap_s=gap,
                    threshold=threshold,
                    n_incidents=result.n_incidents,
                    n_clusters=result.n_clusters,
                    purity=purity(result.labels, truth),
                    completeness=completeness(result.labels, truth),
                    ari=adjusted_rand_index(result.labels, truth),
                )
            )
    return points


def tune_two_stage(
    validation: Sequence[FailureRecord],
    *,
    gaps: Sequence[float],
    thresholds: Sequence[float],
) -> tuple[TwoStagePoint, list[TwoStagePoint]]:
    """The best (gap, threshold) by ARI on the validation records, and the whole sweep.

    Ties break toward the shorter gap and the lower threshold, the more conservative
    choices: more incidents and more tickets, for the reason tune.tune gives.
    """
    points = sweep_two_stage(validation, gaps=gaps, thresholds=thresholds)
    usable = [p for p in points if p.ari == p.ari]
    if not usable:
        raise ValueError("no candidate produced a defined ARI")
    best = max(usable, key=lambda p: (p.ari, -p.gap_s, -p.threshold))
    return best, points
