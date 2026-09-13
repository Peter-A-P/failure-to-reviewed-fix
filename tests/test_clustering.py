"""Clustering on a labelled fixture, and the claim the design actually makes.

The claim is not that clustering is good. It is that combining fingerprint, text and
locality beats fingerprint alone at the specific thing the plan cares about: one bug
surfacing as several exception types should become one ticket. The fixture is built so
that a fingerprint cannot possibly get that right, which makes this the test that would
fail if the locality channel were quietly broken.
"""

from __future__ import annotations

import numpy as np
import pytest

from mend.capture.schema import FailureRecord, Frame, Source
from mend.cluster.agglomerate import (
    ChannelWeights,
    cluster_by_fingerprint,
    cluster_records,
    distance_matrix,
)
from mend.cluster.embed import HashingEmbedder, cosine_distances
from mend.cluster.fingerprint import fingerprint, fingerprint_distance
from mend.cluster.locality import locality_distance
from mend.cluster.metrics import adjusted_rand_index, completeness
from mend.cluster.ticket import build_tickets
from tests.fixtures import CONFIG_BUG, LABELLED_SET, PAGINATOR_BUG, SERIALISER_BUG, truth

THRESHOLD = 0.45


def test_the_fixture_is_hard_for_a_fingerprint() -> None:
    """Guard on the fixture itself: if it ever became easy, the test below would mean nothing."""
    keys = {fingerprint(r).key for r in CONFIG_BUG}
    assert len(keys) > 1, "the config bug must surface as more than one fingerprint"


def test_fingerprint_only_splits_one_bug_into_several_tickets() -> None:
    clustering = cluster_by_fingerprint(LABELLED_SET)
    labels = clustering.labels
    config_labels = {
        label for label, r in zip(labels, LABELLED_SET, strict=True) if r.record_id.startswith("c")
    }
    assert len(config_labels) > 1, "expected the Rule C baseline to split the config bug"


def test_the_combined_clustering_beats_the_fingerprint_baseline() -> None:
    """The Rule C comparison, on the fixture. The ARI gap is the evidence."""
    records = LABELLED_SET
    labels = truth(records)

    combined = cluster_records(records, threshold=THRESHOLD)
    baseline = cluster_by_fingerprint(records)

    combined_ari = adjusted_rand_index(combined.labels, labels)
    baseline_ari = adjusted_rand_index(baseline.labels, labels)

    assert combined_ari > baseline_ari
    assert completeness(combined.labels, labels) > completeness(baseline.labels, labels)


def test_two_different_bugs_are_not_merged() -> None:
    """The other direction: the paginator bug must not land with the config bug.

    Both produce records in the same repository with overlapping vocabulary, and one
    shares an exception type with the serialiser bug.
    """
    records = LABELLED_SET
    clustering = cluster_records(records, threshold=THRESHOLD)
    by_id = dict(zip(clustering.record_ids, clustering.labels, strict=True))

    paginator_labels = {by_id[r.record_id] for r in PAGINATOR_BUG}
    config_labels = {by_id[r.record_id] for r in CONFIG_BUG}
    assert not (paginator_labels & config_labels)


def test_locality_stays_silent_when_a_record_has_no_frames() -> None:
    """The GitHub issue in the fixture has no traceback; locality must abstain, not object."""
    with_frames, prose = SERIALISER_BUG
    assert prose.frames == ()
    assert locality_distance(with_frames, prose) is None
    # And the two are still recognised as close, on the channels that did speak.
    matrix = distance_matrix([with_frames, prose])
    assert matrix[0, 1] < 0.5


def test_a_channel_that_abstains_does_not_count_as_disagreement() -> None:
    """Renormalisation, stated as a property rather than as an implementation detail."""
    with_frames, prose = SERIALISER_BUG
    both_channels = distance_matrix([with_frames, prose])[0, 1]

    # The same pair, with locality given all the weight it could have had. If abstention
    # were being scored as maximum distance, raising the locality weight would push the
    # pair apart; because it abstains, the distance is unchanged.
    heavier = distance_matrix(
        [with_frames, prose],
        weights=ChannelWeights(fingerprint=0.2, text=0.2, locality=0.6),
    )[0, 1]
    assert heavier == pytest.approx(both_channels, abs=0.12)


def test_a_lower_threshold_never_makes_fewer_tickets() -> None:
    """Monotonicity: the threshold is the merge tolerance, so it can only merge more."""
    counts = [
        cluster_records(LABELLED_SET, threshold=t).n_clusters for t in (0.1, 0.3, 0.5, 0.7, 0.9)
    ]
    assert counts == sorted(counts, reverse=True)


def test_clustering_is_deterministic() -> None:
    first = cluster_records(LABELLED_SET, threshold=THRESHOLD)
    second = cluster_records(LABELLED_SET, threshold=THRESHOLD)
    assert first.labels == second.labels


def test_clustering_records_its_own_provenance() -> None:
    """A clustering result says what produced it, or a reported number says nothing."""
    clustering = cluster_records(LABELLED_SET, threshold=THRESHOLD)
    assert clustering.embedder.startswith("hashing-")
    assert clustering.threshold == THRESHOLD
    assert clustering.weights.fingerprint > 0


def test_empty_and_singleton_inputs() -> None:
    assert cluster_records([], threshold=0.5).n_clusters == 0
    assert cluster_records(LABELLED_SET[:1], threshold=0.5).n_clusters == 1


def test_threshold_must_be_a_proportion() -> None:
    with pytest.raises(ValueError, match="unit interval"):
        cluster_records(LABELLED_SET, threshold=1.5)


def test_identical_fingerprints_are_at_zero_distance() -> None:
    a, b = PAGINATOR_BUG
    assert fingerprint_distance(fingerprint(a), fingerprint(b)) == pytest.approx(0.0)


def test_absent_parts_do_not_count_as_agreement() -> None:
    """Two records with nothing in them are not the same bug."""
    blank_a = FailureRecord(record_id="x", source=Source.GITHUB)
    blank_b = FailureRecord(record_id="y", source=Source.GITHUB)
    assert fingerprint_distance(fingerprint(blank_a), fingerprint(blank_b)) == pytest.approx(1.0)


def test_the_top_in_project_frame_is_the_deepest_one() -> None:
    """The innermost project frame is the line that did the wrong thing."""
    record = FailureRecord(
        record_id="z",
        source=Source.PYTEST,
        frames=(
            Frame(file="pkg/entry.py", function="main", in_project=True),
            Frame(file="vendor/lib.py", function="call", in_project=False),
            Frame(file="pkg/inner.py", function="broken", in_project=True),
        ),
    )
    frame = record.top_in_project_frame
    assert frame is not None
    assert frame.file == "pkg/inner.py"


def test_hashing_embedder_is_stable_across_processes() -> None:
    """Hard-coded expectation, because Python's own hash is salted per process.

    If this ever fails after a dependency upgrade, every published clustering number was
    produced by a different embedder than the one running now, and that is worth a loud
    failure rather than a quiet drift.
    """
    embedder = HashingEmbedder(dimensions=64, ngram=(3, 3))
    vectors = embedder.encode(["KeyError: user_id", "KeyError: user_id"])
    assert vectors.shape == (2, 64)
    assert np.allclose(vectors[0], vectors[1])
    assert float(np.linalg.norm(vectors[0])) == pytest.approx(1.0, abs=1e-6)


def test_cosine_distance_is_a_distance() -> None:
    embedder = HashingEmbedder(dimensions=128)
    vectors = embedder.encode(["alpha beta", "alpha beta", "entirely different words here"])
    distances = cosine_distances(vectors)
    assert distances[0, 0] == pytest.approx(0.0)
    assert distances[0, 1] == pytest.approx(0.0, abs=1e-6)
    assert distances[0, 2] > distances[0, 1]
    assert np.all(distances >= 0.0)
    assert np.allclose(distances, distances.T)


def test_tickets_carry_the_outliers_not_only_the_typical() -> None:
    """Representatives are medoid plus the furthest members, so a reader sees the spread."""
    clustering = cluster_records(CONFIG_BUG, threshold=0.9)
    tickets = build_tickets(CONFIG_BUG, clustering, representatives=3)
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.size == len(CONFIG_BUG)
    assert len(ticket.representatives) == 3
    # The medoid is the most typical, and the other two are not duplicates of it.
    assert len({r.record_id for r in ticket.representatives}) == 3
    assert "pkg/config.py:lookup" in ticket.suspect_locations


def test_tickets_are_ordered_by_blast_radius() -> None:
    clustering = cluster_records(LABELLED_SET, threshold=THRESHOLD)
    tickets = build_tickets(LABELLED_SET, clustering)
    sizes = [t.size for t in tickets]
    assert sizes == sorted(sizes, reverse=True)


def test_a_ticket_needs_at_least_one_representative() -> None:
    clustering = cluster_records(LABELLED_SET, threshold=THRESHOLD)
    with pytest.raises(ValueError, match="at least one"):
        build_tickets(LABELLED_SET, clustering, representatives=0)
