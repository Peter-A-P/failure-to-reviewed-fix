"""The report command: tables between markers, from results, and nothing else touched."""

from __future__ import annotations

import pytest

from mend.cluster.crossval import Fold
from mend.eval.report import clustering_table, replace_section, resolution_table, review_table
from mend.eval.results import IssueOutcome
from mend.graph.route import Tier

README = """# Title

Prose before.

<!-- report:resolution -->
<!-- /report:resolution -->

Prose after.
"""


def outcome(i: int, tier: Tier, resolved: bool) -> IssueOutcome:
    return IssueOutcome(
        issue_id=f"t{i}",
        tier=tier,
        score=0.8,
        test_written=True,
        test_failed_first=True,
        patch_drafted=True,
        reviewer_agreed=tier is Tier.AUTO_PROPOSE,
        resolved=resolved,
        cost_usd=0.1,
        duration_s=60.0,
    )


def outcomes() -> list[IssueOutcome]:
    return [outcome(i, Tier.AUTO_PROPOSE, i != 0) for i in range(5)] + [
        outcome(10 + i, Tier.QUIET, False) for i in range(3)
    ]


def test_only_the_section_between_the_markers_changes_and_twice_is_once() -> None:
    once = replace_section(README, "resolution", "TABLE")
    assert once.startswith("# Title\n\nProse before.") and once.endswith("Prose after.\n")
    assert "<!-- report:resolution -->\nTABLE\n<!-- /report:resolution -->" in once
    assert replace_section(once, "resolution", "TABLE") == once


def test_missing_markers_are_an_error_not_a_silent_no_op() -> None:
    with pytest.raises(ValueError):
        replace_section("no markers here", "resolution", "TABLE")


def test_every_number_in_the_resolution_table_carries_its_interval() -> None:
    table = resolution_table(outcomes())
    assert "| Auto-propose (draft PR) | 5 | 80.0% (" in table
    assert "20.0% (" in table  # one of five auto-proposals wrong
    assert table.count("n = ") >= 8


def test_review_and_clustering_tables_render() -> None:
    assert "Test-first rate" in review_table(outcomes())
    folds = [
        Fold(
            held_out=("a", "b", "c"),
            ari={"record-level": 0.0, "fingerprint": 0.0, "two-stage": 0.5},
        ),
        Fold(
            held_out=("a", "b", "d"),
            ari={"record-level": 0.1, "fingerprint": 0.0, "two-stage": 0.7},
        ),
    ]
    table = clustering_table(folds, label="set")
    assert "higher on 2 of 2 folds" in table and "(not a CI)" in table
