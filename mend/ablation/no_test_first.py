"""Ablation one: the same pipeline with the failing test taken out (PLAN.md section 9.1).

What changes, and nothing else:

- No tester. The fixer is shown the issue and the source files, not a test or its output,
  and its system prompt is the main run's with every mention of the test removed.
- The patch is judged on the existing related tests only, with the same baseline rule as
  the main run (mend.graph.patch): green when nothing that passed before fails, and never
  green when no related test was found.
- The reviewer is the main run's, a different vendor, shown the same things less the test.
- The router is the main run's, with its calibrated thresholds, and with the test signal
  set as though a test had been shown (mend.ablation.common.tier_for).

What is held fixed: localisation. Each task reuses the files the main run's localiser named
(PLAN.md section 6, "localisation cached"), so the two arms start from the same files and
differ only from the test onwards. A task the main run stopped at localisation stops here
too, at no cost.

The question is the one Rule C candidate 1 asks: whether patches that nothing forced to
demonstrate the bug fail the hidden tests more often, and whether the router, with nothing
but the suite and the reviewer to go on, auto-proposes more of the wrong ones.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from mend.ablation.common import ArmRecord, Review, ask_review, issue_from_record, run_id, tier_for
from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Deps, Issue, hop_record
from mend.graph.llm import HopFailed, HopRecord
from mend.graph.machine import PatchAttempt
from mend.graph.parse import MalformedReply, apply_edits, diff_size, parse_edits, unified_diff
from mend.graph.patch import regressions
from mend.graph.workspace import TestReport, is_test_file, related_tests

ARM = "no-test-first"

FIXER_SYSTEM = """\
You fix bugs in Python repositories. You are shown an issue and the source files most \
likely involved. Make the smallest change to the source that fixes the issue, without \
breaking other behaviour.

Rules:
- Do not change any test file.
- Each edit quotes text that occurs exactly once in the file, including its indentation, \
and gives the text to put in its place.
- Fix the cause, not the symptom.

Reply with one or more edits, each exactly:
<edit>
<path>relative/path.py</path>
<search>
exact existing lines
</search>
<replace>
new lines
</replace>
</edit>"""

# What the reviewer is told in place of the test, so it is not left to guess why the test
# fields are empty.
NO_TEST = "(no test was written for this patch)"


def fixer_prompt(issue: str, sources: Mapping[str, str], feedback: str = "") -> str:
    parts = [issue, prompts.files_block(sources)]
    if feedback:
        parts.append(f"<previous_attempt>\n{feedback}\n</previous_attempt>")
    return "\n\n".join(parts)


def _rank(attempt: PatchAttempt) -> bool:
    return attempt.suite_green


def draft(
    issue: Issue, sources: dict[str, str], deps: Deps, *, run: str
) -> tuple[PatchAttempt | None, str, tuple[HopRecord, ...], str | None]:
    """The fixer without a test: (best patch, last problem, hops, fixer provider).

    One retry, as in the main run, when the edits did not apply or the suite went red.
    """
    workspace = deps.workspace
    known = set(workspace.files())
    hops: list[HopRecord] = []
    feedback = ""
    problem = "no attempt was made"
    baselines: dict[tuple[str, ...], TestReport] = {}
    best: PatchAttempt | None = None
    provider: str | None = None

    for _ in range(deps.max_attempts):
        try:
            reply = deps.client.ask(
                Role.FIXER,
                issue_id=run,
                system=FIXER_SYSTEM,
                prompt=fixer_prompt(
                    prompts.issue_block(issue.title, issue.body), sources, feedback
                ),
                max_tokens=8192,
            )
        except HopFailed as exc:
            return best, f"draft_patch: {exc}", tuple(hops), provider
        hops.append(hop_record("draft_patch", Role.FIXER, reply))
        provider = reply.provider
        try:
            edits = parse_edits(reply.text)
            for edit in edits:
                if is_test_file(edit.path):
                    raise MalformedReply(f"{edit.path} is a test file, and tests may not change")
                if edit.path not in sources and edit.path in known:
                    sources[edit.path] = workspace.read(edit.path)
            changed = apply_edits(sources, edits)
        except MalformedReply as exc:
            problem = str(exc)
            feedback = f"Your edits could not be applied: {exc}."
            continue
        if not changed:
            problem = "the edits changed nothing"
            feedback = "Your edits left every file as it was."
            continue

        diff = unified_diff(sources, changed)
        touched, lines = diff_size(diff)
        suite = related_tests(workspace, touched)
        if suite not in baselines:
            baselines[suite] = workspace.run_tests(list(suite)) if suite else TestReport()
        patched = workspace.run_tests(list(suite), diff=diff) if suite else TestReport()
        broken = regressions(baselines[suite], patched)
        attempt = PatchAttempt(
            diff=diff,
            # No test: nothing to pass. The router is told otherwise (tier_for).
            test_passes=False,
            suite_green=bool(suite) and not broken and not patched.timed_out,
            files_touched=touched,
            lines_changed=lines,
            touches_traceback_frames=bool(set(touched) & set(issue.frame_files)),
            suite_files=suite,
        )
        if best is None or _rank(attempt) >= _rank(best):
            best = attempt
        if attempt.suite_green:
            break
        if not suite:
            problem = "no existing test covers the touched files"
            break
        problem = f"{len(broken)} previously passing tests now fail"
        feedback = (
            f"Your patch:\n{diff}\nproblem: {problem}\n"
            + (f"now failing: {', '.join(sorted(broken)[:10])}\n" if broken else "")
            + f"output:\n{patched.output}"
        )
    return best, problem, tuple(hops), provider


def run_task(main_record: Mapping[str, Any], deps: Deps | None) -> ArmRecord:
    """One task in this arm, starting from the main run's localisation of it.

    deps may be None only for a task the main run stopped at localisation, which stops
    here before anything is read, run or asked."""
    started = time.monotonic()
    issue = issue_from_record(main_record)
    run = run_id(ARM, issue.issue_id)
    main_state = main_record.get("state") or {}
    suspects = tuple(main_state.get("suspect_files") or ())

    def done(stage: str, **kwargs: Any) -> ArmRecord:
        return ArmRecord(
            arm=ARM,
            issue=issue,
            stage=stage,
            suspect_files=suspects,
            duration_s=time.monotonic() - started,
            **kwargs,
        )

    if not suspects:
        reason = main_state.get("stop_reason") or "no files"
        return done("stopped", stop_reason=f"localise (from the main run): {reason}")
    if deps is None:
        raise ValueError(f"{issue.issue_id} was localised, so it needs a workspace and a client")

    known = set(deps.workspace.files())
    sources = {p: deps.workspace.read(p) for p in suspects if p in known}
    patch, problem, fixer_hops, provider = draft(issue, sources, deps, run=run)
    if patch is None:
        return done(
            "stopped",
            stop_reason=f"draft_patch: no patch could be applied ({problem})",
            hops=fixer_hops,
        )

    review: Review = ask_review(
        deps.client,
        Role.REVIEWER,
        run=run,
        prompt=prompts.reviewer_prompt(
            prompts.issue_block(issue.title, issue.body),
            NO_TEST,
            NO_TEST,
            NO_TEST,
            patch.diff,
            NO_TEST,
            patch.suite_files,
        ),
    )
    hops = fixer_hops + review.hops
    if review.agrees is None:
        return done("stopped", patch=patch, stop_reason=review.problem, hops=hops)
    tier, value = tier_for(
        patch, reviewer_agrees=review.agrees, thresholds=deps.thresholds, test_shown=True
    )
    return done(
        "routed",
        patch=patch,
        review={
            "agrees": review.agrees,
            "objection": review.objection,
            "reviewer_provider": review.provider,
            "fixer_provider": provider,
        },
        tier=tier.value,
        score=value,
        hops=hops,
    )
