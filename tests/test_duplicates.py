"""The duplicate-link set: which link is believed, and how groups are formed."""

from __future__ import annotations

from typing import Any

from mend.data.duplicates import Mined, Tracker, link_for, records, references, root_of
from mend.eval.report import kfold_table

REPO = "pandas-dev/pandas"


def issue(number: int, *comments: tuple[str, str], event: int | None = None) -> dict[str, Any]:
    timeline = (
        [{"canonical": {"__typename": "Issue", "number": event}}] if event is not None else []
    )
    return {
        "number": number,
        "title": f"issue {number}",
        "body": "",
        "timelineItems": {"nodes": timeline},
        "comments": {"nodes": [{"authorAssociation": a, "body": b} for a, b in comments]},
    }


def test_references_in_every_form_this_repository_uses() -> None:
    text = f"dup of #12, see gh-34 and https://github.com/{REPO}/issues/56 not other/x#78"
    assert references(text, REPO) == {12, 34, 56}


def test_the_event_wins_then_a_maintainer_then_anyone() -> None:
    assert link_for(issue(1, ("MEMBER", "duplicate of #3"), event=2), REPO).original == 2  # type: ignore[union-attr]
    found = link_for(issue(1, ("MEMBER", "duplicate of #3"), ("NONE", "dup of #4")), REPO)
    assert found is not None and (found.original, found.rule) == (3, "maintainer-comment")
    anyone = link_for(issue(1, ("NONE", "Looks like a duplicate of #4")), REPO)
    assert anyone is not None and (anyone.original, anyone.rule) == (4, "comment")


def test_an_ambiguous_or_unrelated_comment_links_nothing() -> None:
    assert link_for(issue(1, ("MEMBER", "duplicate of #3 or #4?")), REPO) is None
    assert link_for(issue(1, ("MEMBER", "related to #3")), REPO) is None
    assert link_for(issue(1, ("MEMBER", "duplicate of #1")), REPO) is None


def test_chains_follow_to_the_root_and_cycles_stop() -> None:
    assert root_of(1, {1: 2, 2: 3}) == 3
    assert root_of(1, {1: 2, 2: 1}) == 1


def test_records_label_by_the_root_and_count_the_librarys_frames_as_project() -> None:
    body = (
        "```\nTraceback (most recent call last):\n"
        '  File "/usr/lib/python3.12/site-packages/pandas/core/frame.py", line 9, in f\n'
        '  File "/home/u/script.py", line 2, in <module>\n'
        "KeyError: 'a'\n```"
    )
    mined = Mined(
        Tracker(REPO, "Duplicate Report", "pandas", 2020),
        2,
        (),
        {5: (5, 6)},
        {5: {**issue(5), "body": body}, 6: issue(6)},
    )
    out = records(mined)
    assert [r.true_cause for r in out] == [f"{REPO}#5", f"{REPO}#5"]
    frames = out[0].frames
    assert [f.in_project for f in frames] == [True, False]


def test_kfold_table_has_intervals_and_the_paired_row() -> None:
    m = {
        "ari": [0.5, 0.4, 0.6],
        "purity": [0.9, 0.8, 1.0],
        "completeness": [0.5, 0.4, 0.6],
        "symptoms_per_ticket": [2.0, 1.5, 2.5],
        "n_true_causes": 4,
        "n_records": 10,
    }
    payload = {
        "pooled": {"record-level": m, "fingerprint": m},
        "folds": [{"ari": {"record-level": 0.6, "fingerprint": 0.5}}],
        "record_level_minus_fingerprint_ari": [0.1, 0.0, 0.2],
    }
    table = kfold_table([("set", payload)])
    assert "0.500 (0.400 to 0.600)" in table and "higher on 1 of 1 folds" in table
