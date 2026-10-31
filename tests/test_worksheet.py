"""The false-positive worksheet: the visible half never carries the hidden half, and the
answers file cannot change the denominator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mend.eval.confident_wrong import Cause, hint, read, table, template, wrong_auto_proposals
from mend.eval.worksheet import hidden, pull_request, worksheet


def run(issue_id: str, tier: str = "auto_propose") -> dict[str, Any]:
    return {
        "issue": {
            "issue_id": issue_id,
            "repo": "owner/proj",
            "commit": "0123456789abcdef",
            "title": "Something breaks",
            "body": "Steps to reproduce.",
            "frame_files": [],
        },
        "state": {
            "tier": tier,
            "score": 0.9,
            "patch": {
                "diff": "--- a/x.py\n+++ b/x.py\n",
                "files_touched": ["x.py"],
                "lines_changed": 2,
                "touches_traceback_frames": False,
                "suite_green": True,
                "test_passes": True,
            },
            "test": {"test_id": "tests/test_x.py", "source": "def test_x(): ...", "output": "F"},
            "review": {"agrees": True, "objection": "", "reviewer_provider": "openai"},
        },
    }


def test_only_failed_auto_proposals_are_cases() -> None:
    runs = [run("p-1"), run("p-2"), run("p-3", tier="suggest")]
    cases = wrong_auto_proposals(runs, {"p-1": True, "p-2": False, "p-3": False})
    assert [c["issue"]["issue_id"] for c in cases] == ["p-2"]


def test_the_answers_file_must_cover_exactly_the_cases(tmp_path: Path) -> None:
    path = tmp_path / "answers.yaml"
    path.write_text(template(["a-1", "b-2"]), encoding="utf-8")
    assert read(path, ["a-1", "b-2"]) is None  # blank: not yet classified
    with pytest.raises(ValueError, match="exactly"):
        read(path, ["a-1"])

    path.write_text(
        "- {issue_id: a-1, cause: wrong_location, note: edited the caller}\n"
        "- {issue_id: b-2, cause: symptom_not_cause, note: guarded the None}\n",
        encoding="utf-8",
    )
    classified = read(path, ["b-2", "a-1"])
    assert classified is not None
    assert {c.cause for c in classified} == {Cause.WRONG_LOCATION, Cause.SYMPTOM_NOT_CAUSE}

    path.write_text("- {issue_id: a-1, cause: wrong_location, note: ''}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must say why"):
        read(path, ["a-1"])
    path.write_text("- {issue_id: a-1, cause: bad_luck, note: x}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read(path, ["a-1"])


def test_the_table_shows_every_cause_with_an_interval(tmp_path: Path) -> None:
    path = tmp_path / "answers.yaml"
    path.write_text("- {issue_id: a-1, cause: wrong_location, note: edited the caller}\n")
    classified = read(path, ["a-1"])
    assert classified is not None
    out = table(classified)
    for cause in Cause:
        assert f"| {cause.value} |" in out
    assert "1 of 1, 100.0%" in out and "n = 1" in out and "edited the caller" in out


def test_the_worksheet_carries_nothing_hidden() -> None:
    sheet = worksheet([run("owner__proj-42")], answers="a.yaml", five="f.jsonl", rerun_dir="r")
    assert "https://github.com/owner/proj/pull/42" in sheet
    assert "def test_x(): ..." in sheet
    for field in ("FAIL_TO_PASS", "PASS_TO_PASS", "test_patch"):
        assert f"**{field}**" not in sheet


def test_the_hidden_side_has_the_fix_and_the_tests() -> None:
    task = {
        "instance_id": "owner__proj-42",
        "repo": "owner/proj",
        "patch": "GOLD FIX",
        "test_patch": "HIDDEN TESTS",
        "FAIL_TO_PASS": '["tests/test_x.py::test_new"]',
        "PASS_TO_PASS": ["tests/test_x.py::test_old"],
        "hints_text": "",
    }
    out = hidden([task], ["owner__proj-42"])
    assert "GOLD FIX" in out and "HIDDEN TESTS" in out and "test_new" in out and "test_old" in out
    with pytest.raises(KeyError):
        hidden([task], ["other__proj-1"])


def test_a_pull_request_is_named_by_the_task() -> None:
    assert pull_request("django__django-10999", "django/django").endswith("/pull/10999")


def test_no_traceback_says_nothing_about_location() -> None:
    causes = hint(
        files_touched=1,
        lines_changed=2,
        touches_traceback_frames=False,
        suite_green=True,
        reviewer_objected=False,
        issue_has_traceback=False,
    )
    assert Cause.WRONG_LOCATION not in causes
