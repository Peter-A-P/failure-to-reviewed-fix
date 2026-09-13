"""Turning a cluster of symptoms into one ticket.

The ticket is what the rest of the pipeline works on, and what a human reads. It carries
the representative symptoms rather than all of them, because a ticket holding two hundred
near-identical tracebacks is a ticket nobody reads, and because everything downstream is
a model call priced per token.

Representatives are chosen by medoid: the record with the smallest total distance to the
rest of the cluster, which is the one most like all the others. Then the records furthest
from that medoid are added, which is the opposite choice on purpose: the outliers are what
tell a reader whether the cluster is really one bug, and they are exactly what a summary
built from the most typical examples would hide.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from mend.capture.schema import FailureRecord
from mend.cluster.agglomerate import ChannelWeights, Clustering, distance_matrix
from mend.cluster.embed import Embedder
from mend.cluster.locality import files, locations

DEFAULT_REPRESENTATIVES = 5


@dataclass(frozen=True, slots=True)
class Ticket:
    """One root cause, as far as the clustering can tell.

    `size` is the whole cluster; `representatives` is the handful carried forward. Cluster
    size is one of the routing signals in PLAN.md section 2.5, which is why the count is
    kept even though the records are not.
    """

    ticket_id: str
    size: int
    representatives: tuple[FailureRecord, ...]
    member_ids: tuple[str, ...]
    exception_types: tuple[str, ...]
    suspect_locations: tuple[str, ...]
    suspect_files: tuple[str, ...]
    repo: str | None
    commit: str | None

    @property
    def medoid(self) -> FailureRecord:
        """The most typical symptom: the one a ticket title should be written from."""
        return self.representatives[0]

    def title(self) -> str:
        record = self.medoid
        if record.title:
            return record.title
        if record.exception_type:
            suffix = f" in {self.suspect_locations[0]}" if self.suspect_locations else ""
            return f"{record.exception_type}{suffix}"
        return f"Unnamed failure ({self.size} symptoms)"


def _ordered_unique(values: Sequence[str | None]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return tuple(seen)


def _majority(values: Sequence[str | None]) -> str | None:
    """The commonest non-empty value, or None.

    Used for repo and commit, which every member of a cluster should agree on but will not
    when a bug is reported against two versions. The majority is the honest answer and the
    disagreement stays visible in the representatives.
    """
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else None


def build_tickets(
    records: Sequence[FailureRecord],
    clustering: Clustering,
    *,
    representatives: int = DEFAULT_REPRESENTATIVES,
    weights: ChannelWeights | None = None,
    embedder: Embedder | None = None,
) -> list[Ticket]:
    """One ticket per cluster, largest first.

    Largest first because cluster size is the crudest available proxy for blast radius,
    and a triage queue that opens with the bug producing forty symptoms is more useful
    than one in arbitrary order.
    """
    if representatives < 1:
        raise ValueError("a ticket needs at least one representative")
    by_id = {r.record_id: r for r in records}
    tickets: list[Ticket] = []

    for label, member_ids in clustering.groups().items():
        members = [by_id[rid] for rid in member_ids if rid in by_id]
        if not members:
            continue
        chosen = _representatives(members, representatives, weights=weights, embedder=embedder)
        tickets.append(
            Ticket(
                ticket_id=f"T{label:04d}",
                size=len(members),
                representatives=tuple(chosen),
                member_ids=tuple(m.record_id for m in members),
                exception_types=_ordered_unique([m.exception_type for m in members]),
                suspect_locations=_ordered_unique([loc for m in members for loc in locations(m)]),
                suspect_files=_ordered_unique([f for m in members for f in files(m)]),
                repo=_majority([m.repo for m in members]),
                commit=_majority([m.commit for m in members]),
            )
        )

    tickets.sort(key=lambda t: (-t.size, t.ticket_id))
    return tickets


def _representatives(
    members: Sequence[FailureRecord],
    count: int,
    *,
    weights: ChannelWeights | None,
    embedder: Embedder | None,
) -> list[FailureRecord]:
    """Medoid first, then the members furthest from it. See the module docstring."""
    if len(members) <= count:
        return list(members)

    matrix = distance_matrix(members, weights=weights, embedder=embedder)
    totals = matrix.sum(axis=1)
    medoid_index = int(np.argmin(totals))

    furthest = np.argsort(-matrix[medoid_index])
    chosen_indices = [medoid_index]
    for index in furthest:
        if len(chosen_indices) >= count:
            break
        if int(index) != medoid_index:
            chosen_indices.append(int(index))
    return [members[i] for i in chosen_indices]
