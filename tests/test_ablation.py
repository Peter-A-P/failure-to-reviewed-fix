"""The ablations: each takes out exactly the part it names, and nothing else.

The no-test-first arm must never ask the tester and must never show the fixer a test; the
self-review arm must ask the fixer's own model and route on its verdict exactly as the main
run's router would. And neither may reach a proposal: they write records, not pull requests.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mend.ablation import no_test_first, self_review
from mend.ablation.common import tier_for
from mend.eval import gate
from mend.gateway import Role
from mend.graph.context import Deps, Issue
from mend.graph.route import Thresholds
from tests.fakes import Run, ScriptedClient, ScriptedWorkspace, report
from tests.test_graph import ACCEPT, ISSUE, PATCH_REPLY, REJECT, REPO

ROOT = Path(__file__).resolve().parent.parent
CALIBRATED = Thresholds(
    auto_propose=0.0, suggest=0.0, target_confidently_wrong=0.03, calibrated_on="validation"
)
EXISTING_ID = "tests/test_parser.py::test_simple"


def main_record(issue: Issue = ISSUE, suspects: tuple[str, ...] = ("pkg/parser.py",)) -> Any:
    return {
        "issue": asdict(issue),
        "state": {"suspect_files": list(suspects), "stop_reason": None if suspects else "x"},
    }


def suite(*, regress: bool = False, covered: bool = True) -> ScriptedWorkspace:
    repo = dict(REPO) if covered else {k: v for k, v in REPO.items() if "tests/" not in k}

    def respond(run: Run) -> Any:
        broken = bool(run.diff) and regress
        return report(
            passed=[] if broken else [EXISTING_ID], failed=[EXISTING_ID] if broken else []
        )

    return ScriptedWorkspace(repo, respond)


def test_no_test_first_never_asks_the_tester_or_shows_the_fixer_a_test() -> None:
    client = ScriptedClient({Role.FIXER: [PATCH_REPLY], Role.REVIEWER: [ACCEPT]})
    record = no_test_first.run_task(
        main_record(), Deps(client=client, workspace=suite(), thresholds=CALIBRATED)
    )
    assert client.roles_asked() == [Role.FIXER, Role.REVIEWER]
    fixer = client.asked[0]
    assert "<test" not in fixer.prompt and "test" not in fixer.system.split("Rules:")[0].lower()
    assert all(a.issue_id == f"no-test-first:{ISSUE.issue_id}" for a in client.asked)
    assert record.patch is not None and record.patch.suite_green
    assert record.tier == "auto_propose" and record.stage == "routed"
    row = record.to_dict()
    assert row["state"]["test"] is None and row["state"]["patch"]["diff"]


def test_no_test_first_still_needs_a_green_suite_to_propose() -> None:
    client = ScriptedClient({Role.FIXER: [PATCH_REPLY, PATCH_REPLY], Role.REVIEWER: [ACCEPT]})
    record = no_test_first.run_task(
        main_record(), Deps(client=client, workspace=suite(regress=True), thresholds=CALIBRATED)
    )
    assert record.patch is not None and not record.patch.suite_green
    assert record.tier == "quiet"


def test_no_test_first_holds_back_a_patch_no_existing_test_covers() -> None:
    client = ScriptedClient({Role.FIXER: [PATCH_REPLY], Role.REVIEWER: [ACCEPT]})
    record = no_test_first.run_task(
        main_record(),
        Deps(client=client, workspace=suite(covered=False), thresholds=CALIBRATED),
    )
    assert record.tier == "quiet"
    assert client.roles_asked() == [Role.FIXER, Role.REVIEWER]


def test_a_task_the_main_run_could_not_localise_stops_without_a_call() -> None:
    record = no_test_first.run_task(main_record(suspects=()), None)
    assert record.stage == "stopped" and record.hops == ()
    assert "localise" in (record.stop_reason or "")


def reviewed_main_record() -> dict[str, Any]:
    return {
        "issue": asdict(ISSUE),
        "state": {
            "suspect_files": ["pkg/parser.py"],
            "test": {"test_id": "t.py", "source": "def test(): ...", "output": "1 failed"},
            "patch": {
                "diff": "--- a\n+++ b\n",
                "test_passes": True,
                "suite_green": True,
                "files_touched": ["pkg/parser.py"],
                "lines_changed": 1,
                "touches_traceback_frames": True,
                "suite_files": ["tests/test_parser.py"],
            },
            "review": {"agrees": True, "fixer_provider": "anthropic"},
        },
    }


def test_self_review_asks_the_fixers_own_model_and_routes_on_its_verdict() -> None:
    client = ScriptedClient({Role.SELF_REVIEWER: [REJECT]})
    record = self_review.review_task(
        reviewed_main_record(), self_review.SAME_VENDOR, client, CALIBRATED
    )
    assert client.roles_asked() == [Role.SELF_REVIEWER]
    assert self_review.AFTER_PATCH in client.asked[0].prompt
    assert record.review is not None and record.review["agrees"] is False
    assert record.review["reviewer_provider"] == record.review["fixer_provider"] == "anthropic"
    assert record.tier == "suggest"  # an objection caps the tier, whoever made it


def test_the_review_again_arm_asks_the_different_vendor() -> None:
    client = ScriptedClient({Role.REVIEWER: [ACCEPT]})
    record = self_review.review_task(
        reviewed_main_record(), self_review.OTHER_VENDOR, client, CALIBRATED
    )
    assert client.roles_asked() == [Role.REVIEWER]
    assert record.tier == "auto_propose"


def test_the_ablation_router_reproduces_every_main_run_tier() -> None:
    """tier_for on the main run's own verdicts gives the tiers the main run recorded, so a
    difference between arms is the reviewer's and not the re-implementation's."""
    rows = [
        json.loads(line)
        for line in (ROOT / "results/main/fix.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    checked = 0
    for row in rows:
        if not self_review.reviewed(row):
            continue
        patch = self_review.patch_from(row["state"])
        tier, _ = tier_for(
            patch,
            reviewer_agrees=row["state"]["review"]["agrees"],
            thresholds=CALIBRATED,
            test_shown=patch.test_passes,
        )
        assert tier.value == row["state"]["tier"], row["issue"]["issue_id"]
        checked += 1
    assert checked > 50


def test_gate_sides_are_in_the_adapters_shape_and_grade_the_right_way_up() -> None:
    runs = [
        {"issue": {"issue_id": "a"}, "state": {"tier": "auto_propose", "review": {"agrees": True}}},
        {"issue": {"issue_id": "b"}, "state": {"tier": "auto_propose", "review": {"agrees": True}}},
        {"issue": {"issue_id": "c"}, "state": {"tier": "quiet", "review": {"agrees": False}}},
        {"issue": {"issue_id": "d"}, "state": {"stage": "stopped", "patch": {}, "review": None}},
    ]
    passed = {"a": True, "b": False, "c": False, "d": False}
    side = gate.side("self-review", "x", runs, passed, source={})
    assert set(side) == {"label", "source", "suites"}
    wrong = side["suites"]["not-confidently-wrong"]
    assert wrong["outcomes"] == {"a": True, "b": False, "c": True}
    assert wrong["ungradeable_items"] == 1
    verdict = side["suites"]["verdict-right"]
    assert verdict["outcomes"] == {"a": True, "b": False, "c": True}
    assert set(verdict) == {
        "suite",
        "outcomes",
        "ungradeable_items",
        "calls",
        "latency_p50_ms",
        "cost_usd",
        "uncosted_calls",
    }
    assert gate.spec("self-review")["suites"][0]["source"]["kind"] == "outcomes_file"


def test_the_ablation_tables_count_what_the_arms_did() -> None:
    from mend.eval.ablation import agreement, first_test_table, review_table

    def run(i: str, agrees: bool | None, tier: str, diff: str = "d") -> dict[str, Any]:
        review = None if agrees is None else {"agrees": agrees}
        return {
            "issue": {"issue_id": i},
            "state": {"review": review, "tier": tier, "patch": {"diff": diff}},
            "cost_usd": 0.1,
        }

    passed = {"a": True, "b": False, "c": False}
    a = [run("a", True, "auto_propose"), run("b", True, "auto_propose"), run("c", False, "x")]
    b = [run("a", True, "auto_propose"), run("b", False, "x"), run("c", False, "x")]
    table = review_table([("one", a), ("two", b)], passed)
    assert "| one | 33.3% (" in table and "| two | 66.7% (" in table
    assert "50.0% (" in table  # one of two auto-proposals wrong in arm one
    assert agreement(a, b).startswith("66.7%")
    first = first_test_table(a, passed, b, {"a": True, "b": True, "c": False})
    assert "1 resolved by both, 0 only with the test first, 1 only without it" in first
