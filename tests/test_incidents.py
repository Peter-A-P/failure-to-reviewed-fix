"""Two-stage clustering: incidents from onset times, tickets from incident signatures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mend.capture.schema import FailureRecord, Source
from mend.cluster.incidents import cluster_two_stage, incidents, jaccard_distances, tune_two_stage

T0 = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


def symptom(n: int, at_s: float, metric: str, cause: str, direction: str = "rose") -> FailureRecord:
    return FailureRecord(
        record_id=f"r{n}",
        source=Source.CHAOS,
        captured_at=T0 + timedelta(seconds=at_s),
        exception_type="MetricDeparture",
        message=f"{metric} rate {direction} from its steady level",
        env=f"run-{n}",
        true_cause=cause,
    )


def two_faults_three_times() -> list[FailureRecord]:
    """Fault A moves metrics a and b; fault B moves c and d. Six runs, five minutes apart."""
    out = []
    n = 0
    for run in range(6):
        cause, metrics = ("A", ("a", "b")) if run % 2 == 0 else ("B", ("c", "d"))
        for k, metric in enumerate(metrics):
            out.append(symptom(n, run * 300 + k * 4, metric, cause))
            n += 1
    return out


def test_symptoms_close_in_time_are_one_incident() -> None:
    records = two_faults_three_times()
    assert len(set(incidents(records, gap_s=30))) == 6
    assert len(set(incidents(records, gap_s=1000))) == 1


def test_incidents_with_the_same_symptoms_become_one_ticket() -> None:
    result = cluster_two_stage(two_faults_three_times(), gap_s=30, threshold=0.5)
    assert result.n_incidents == 6 and result.n_clusters == 2
    by_cause: dict[str, set[int]] = {}
    for record, label in zip(two_faults_three_times(), result.labels, strict=True):
        by_cause.setdefault(record.true_cause or "", set()).add(label)
    assert all(len(labels) == 1 for labels in by_cause.values())
    assert by_cause["A"] != by_cause["B"]


def test_neither_the_label_nor_the_run_is_read() -> None:
    """Scrambling true_cause and env changes nothing: only onset and fingerprint count."""
    records = two_faults_three_times()
    scrambled = [r.model_copy(update={"true_cause": "same", "env": "same"}) for r in records]
    assert (
        cluster_two_stage(records, gap_s=30, threshold=0.5).labels
        == cluster_two_stage(scrambled, gap_s=30, threshold=0.5).labels
    )


def test_jaccard() -> None:
    d = jaccard_distances([frozenset("ab"), frozenset("ab"), frozenset("bc"), frozenset()])
    assert d[0, 1] == 0.0 and d[0, 2] == pytest.approx(2 / 3) and d[3, 3] == 0.0


def test_tuning_picks_the_conservative_end_of_a_tie() -> None:
    best, points = tune_two_stage(
        two_faults_three_times(), gaps=[30, 60], thresholds=[0.3, 0.5, 0.7]
    )
    assert best.ari == pytest.approx(1.0)
    assert (best.gap_s, best.threshold) == (30, 0.3)
    assert len(points) == 6


def test_a_bad_gap_is_refused() -> None:
    with pytest.raises(ValueError):
        incidents(two_faults_three_times(), gap_s=0)
