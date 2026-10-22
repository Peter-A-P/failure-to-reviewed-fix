"""Ablation two: the fixer's own vendor reviews its patches (PLAN.md section 9.2).

Every patch the main run sent to review is reviewed twice more, on identical input: once by
the fixer's own model (mend-self-reviewer) and once again by the different-vendor reviewer
(mend-reviewer). The patch, its test and the hidden-test verdict are the main run's, so
the only thing that differs between the two arms is who reviewed, and no sandbox or
harness run is needed.

Why the different-vendor reviewer is asked again rather than its main-run verdict reused:
the input cannot be rebuilt exactly. The run log keeps the test, its output before the
patch, the diff and the suite, but not the test's output after the patch, which is
replaced here by a line saying it passed (every patch that reached review had made its
test pass). Both arms see that same line, so the comparison is fair; how often the fresh
different-vendor verdict matches the main run's is reported as well, and is the floor of
how much a verdict moves on a second asking.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from mend.ablation.common import ArmRecord, ask_review, issue_from_record, run_id, tier_for
from mend.gateway import Role
from mend.graph import prompts
from mend.graph.llm import ModelClient
from mend.graph.machine import PatchAttempt
from mend.graph.route import Thresholds

SAME_VENDOR = "self-review"
OTHER_VENDOR = "review-again"

ARMS = {SAME_VENDOR: Role.SELF_REVIEWER, OTHER_VENDOR: Role.REVIEWER}

AFTER_PATCH = "(not kept in the run log; the test passed with the patch applied)"


def reviewed(main_record: Mapping[str, Any]) -> bool:
    """Whether the main run sent this task's patch to review."""
    state = main_record.get("state") or {}
    return bool(state.get("review") and state.get("patch") and state.get("test"))


def patch_from(state: Mapping[str, Any]) -> PatchAttempt:
    raw = dict(state["patch"])
    raw["files_touched"] = tuple(raw.get("files_touched") or ())
    raw["suite_files"] = tuple(raw.get("suite_files") or ())
    return PatchAttempt(**raw)


def review_prompt(main_record: Mapping[str, Any]) -> str:
    """The reviewer's prompt for a recorded patch, as near the main run's as the log allows."""
    issue = issue_from_record(main_record)
    state = main_record["state"]
    test = state["test"]
    patch = state["patch"]
    return prompts.reviewer_prompt(
        prompts.issue_block(issue.title, issue.body),
        str(test["test_id"]),
        str(test["source"]),
        str(test.get("output") or ""),
        str(patch["diff"]),
        AFTER_PATCH,
        tuple(patch.get("suite_files") or ()),
    )


def review_task(
    main_record: Mapping[str, Any],
    arm: str,
    client: ModelClient,
    thresholds: Thresholds | None,
) -> ArmRecord:
    """One recorded patch, reviewed in one arm, and routed on that verdict."""
    started = time.monotonic()
    issue = issue_from_record(main_record)
    state = main_record["state"]
    patch = patch_from(state)
    review = ask_review(
        client, ARMS[arm], run=run_id(arm, issue.issue_id), prompt=review_prompt(main_record)
    )
    common: dict[str, Any] = {
        "arm": arm,
        "issue": issue,
        "suspect_files": tuple(state.get("suspect_files") or ()),
        "patch": patch,
        "hops": review.hops,
        "notes": {"main_run_reviewer_agreed": bool(state["review"]["agrees"])},
    }
    if review.agrees is None:
        return ArmRecord(
            stage="stopped",
            stop_reason=review.problem,
            duration_s=time.monotonic() - started,
            **common,
        )
    tier, value = tier_for(
        patch, reviewer_agrees=review.agrees, thresholds=thresholds, test_shown=patch.test_passes
    )
    return ArmRecord(
        stage="routed",
        review={
            "agrees": review.agrees,
            "objection": review.objection,
            "reviewer_provider": review.provider,
            "fixer_provider": state["review"]["fixer_provider"],
        },
        tier=tier.value,
        score=value,
        duration_s=time.monotonic() - started,
        **common,
    )
