"""Scoring with the official harness: what is submitted, and how verdicts become outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mend.graph.context import Deps
from mend.graph.graph import run_issue
from mend.graph.route import Tier
from mend.sandbox.harness import (
    HARNESS_IMAGE,
    HARNESS_VERSION,
    HarnessIncomplete,
    harness_command,
    outcomes,
    predictions,
    read_runs,
    verdicts,
)
from tests.fakes import ScriptedWorkspace
from tests.test_graph import ISSUE, NEW_TEST, REPO, client, sandbox


def a_run() -> dict[str, Any]:
    record = run_issue(
        ISSUE, Deps(client=client(), workspace=ScriptedWorkspace(dict(REPO), sandbox()))
    )
    payload: dict[str, Any] = json.loads(record.to_json())
    return payload


def stopped_run(issue_id: str) -> dict[str, Any]:
    return {
        "issue": {"issue_id": issue_id},
        "state": {
            "stage": "stopped",
            "patch": None,
            "test": None,
            "review": None,
            "tier": None,
            "score": None,
            "stop_reason": "write_test: no test failed",
        },
        "cost_usd": 0.02,
        "duration_s": 30.0,
    }


def test_the_submitted_patch_is_the_source_diff_without_the_generated_test() -> None:
    (row,) = predictions([a_run()])
    assert row["instance_id"] == ISSUE.issue_id
    assert row["model_name_or_path"] == "mend"
    assert "pkg/parser.py" in row["model_patch"]
    assert NEW_TEST not in row["model_patch"]


def test_a_task_without_a_patch_is_not_submitted() -> None:
    assert predictions([stopped_run("x__y-1")]) == []


def test_a_rerun_replaces_the_earlier_record(tmp_path: Path) -> None:
    log = tmp_path / "fix.jsonl"
    first, second = stopped_run("x__y-1"), a_run()
    second["issue"]["issue_id"] = "x__y-1"
    log.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")
    (only,) = read_runs(log)
    assert only["state"]["stage"] == "acted"


def test_verdicts_keep_unjudged_tasks_apart(tmp_path: Path) -> None:
    report = tmp_path / "mend.r.json"
    report.write_text(
        json.dumps(
            {
                "resolved_ids": ["a"],
                "unresolved_ids": ["b", "c"],
                "error_ids": ["d"],
                "infra_failure_ids": ["c"],
                "incomplete_ids": [],
            }
        )
    )
    assert verdicts(report) == {"a": True, "b": False, "c": None, "d": None}


def test_outcomes_refuse_to_count_an_unjudged_patch_as_unresolved() -> None:
    run = a_run()
    with pytest.raises(HarnessIncomplete) as caught:
        outcomes([run], {ISSUE.issue_id: None})
    assert caught.value.missing == (ISSUE.issue_id,)


def test_outcomes_carry_the_harness_verdict_and_the_pipeline_evidence() -> None:
    (judged, stopped) = outcomes([a_run(), stopped_run("x__y-2")], {ISSUE.issue_id: True})
    assert judged.resolved and judged.patch_drafted and judged.test_failed_first
    assert judged.tier is Tier.SUGGEST and judged.reviewer_agreed is True
    assert judged.cost_usd == pytest.approx(0.04)
    assert not stopped.resolved and not stopped.patch_drafted and stopped.tier is Tier.QUIET
    assert stopped.stop_reason == "write_test: no test failed"


def test_the_harness_is_asked_for_exactly_the_submitted_tasks(tmp_path: Path) -> None:
    command = harness_command(
        "predictions.jsonl", run_id="r1", instance_ids=["a__b-1", "c__d-2"], workdir=tmp_path
    )
    assert command[command.index("--instance_ids") + 1 :] == ["a__b-1", "c__d-2"]
    assert command[command.index("--predictions_path") + 1] == "/work/predictions.jsonl"
    assert "SWE-bench/SWE-bench_Verified" in command
    assert "--modal" not in command


def test_the_harness_runs_in_linux_beside_the_host_docker(tmp_path: Path) -> None:
    """On a Windows host the harness writes CRLF scripts that bash cannot run, so it runs
    in its own Linux container, pinned by version, driving the host daemon."""
    command = harness_command("gold", run_id="r1", instance_ids=["a__b-1"], workdir=tmp_path)
    assert command[:3] == ["docker", "run", "--rm"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in command
    assert HARNESS_IMAGE in command and HARNESS_IMAGE.endswith(HARNESS_VERSION)
    assert command[command.index("--predictions_path") + 1] == "gold"
