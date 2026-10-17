"""The batch runner: order, cleanup after every task, and resuming without re-drawing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from mend.data.swebench import Task
from mend.sandbox.batch import RunPaths, recorded_runs, recorded_verdicts, run_subset

IDS = ["a__a-1", "b__b-2", "c__c-3"]
TASKS = {
    i: Task(instance_id=i, repo="x/x", base_commit="c", problem_statement="", image=f"img-{i}")
    for i in IDS
}


def record(instance_id: str, *, drafted: bool = True) -> dict[str, Any]:
    patch = {"diff": f"diff --git a/f.py b/f.py\n+fix {instance_id}\n"} if drafted else None
    return {"issue": {"issue_id": instance_id}, "state": {"stage": "acted", "patch": patch}}


class Calls:
    def __init__(self) -> None:
        self.fixed: list[str] = []
        self.scored: list[str] = []
        self.cleaned: list[str] = []

    def fix(self, task: Task) -> dict[str, Any]:
        self.fixed.append(task.instance_id)
        return record(task.instance_id, drafted=task.instance_id != "b__b-2")

    def score(self, run: Mapping[str, Any]) -> bool | None:
        self.scored.append(str(run["issue"]["issue_id"]))
        return True

    def cleanup(self, task: Task) -> None:
        self.cleaned.append(task.instance_id)


def go(paths: RunPaths, calls: Calls) -> None:
    run_subset(
        IDS,
        TASKS,
        paths,
        fix=calls.fix,
        score=calls.score,
        cleanup=calls.cleanup,
        echo=lambda _s: None,
    )


def test_every_task_is_fixed_scored_and_cleaned_in_order(tmp_path: Path) -> None:
    paths, calls = RunPaths(tmp_path), Calls()
    go(paths, calls)
    assert calls.fixed == IDS and calls.cleaned == IDS
    assert calls.scored == ["a__a-1", "c__c-3"]  # no patch, nothing to submit
    assert recorded_verdicts(paths) == {"a__a-1": True, "b__b-2": False, "c__c-3": True}


def test_a_resume_skips_judged_tasks_and_never_re_draws_a_fix(tmp_path: Path) -> None:
    paths = RunPaths(tmp_path)
    first = Calls()

    def crash(run: Mapping[str, Any]) -> bool | None:
        if run["issue"]["issue_id"] == "c__c-3":
            raise RuntimeError("harness died")
        return True

    with pytest.raises(RuntimeError):
        run_subset(
            IDS,
            TASKS,
            paths,
            fix=first.fix,
            score=crash,
            cleanup=first.cleanup,
            echo=lambda _s: None,
        )
    assert first.cleaned == IDS  # cleaned up even on the task that crashed
    assert set(recorded_runs(paths)) == set(IDS)

    second = Calls()
    go(paths, second)
    assert second.fixed == []  # c was fixed already: scored again, not drawn again
    assert second.scored == ["c__c-3"]
    assert recorded_verdicts(paths)["c__c-3"] is True


def test_an_unjudged_task_is_scored_again_on_resume(tmp_path: Path) -> None:
    paths = RunPaths(tmp_path)
    unsure = Calls()
    unsure.score = lambda run: None  # type: ignore[method-assign]
    go(paths, unsure)
    assert recorded_verdicts(paths)["a__a-1"] is None

    again = Calls()
    go(paths, again)
    assert again.fixed == [] and again.scored == ["a__a-1", "c__c-3"]
