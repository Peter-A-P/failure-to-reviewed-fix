"""Hop three: a patch that makes the failing test pass and breaks nothing that passed.

Reached only from TEST_FAILED_AS_EXPECTED; the state machine refuses PATCHED from anywhere
else. The fixer returns search-and-replace edits, which are placed here (mend.graph.parse)
and turned into a diff. Edits to test files are refused: the test is the specification,
and a patch that edits it has changed the question rather than answered it.

"Breaks nothing" is judged against a baseline. The existing test files related to the
touched modules (mend.graph.workspace.related_tests) run once on the broken commit and
again with the patch; the suite is green when everything that passed before still passes.
A test that was already failing is not counted against the patch. When no related test
file exists, the suite is not called green, because a claim about no tests is not a claim,
and the router then keeps the issue out of the top tier.

One retry, with the failure in front of the fixer: a search block that did not match, a
test still failing, or a regression by name.
"""

from __future__ import annotations

from dataclasses import replace

from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Deps, HopOutput, Issue, Scratch, hop_record
from mend.graph.llm import HopFailed, HopRecord
from mend.graph.machine import IssueState, PatchAttempt, Stage, advance, stop
from mend.graph.parse import MalformedReply, apply_edits, diff_size, parse_edits, unified_diff
from mend.graph.workspace import TestReport, is_test_file, related_tests


def regressions(baseline: TestReport, patched: TestReport) -> frozenset[str]:
    """Tests that passed on the broken commit and do not pass with the patch."""
    return baseline.passed - patched.passed


def _rank(attempt: PatchAttempt) -> tuple[bool, bool]:
    """Which of two attempts to keep: a passing test first, then a green suite."""
    return attempt.test_passes, attempt.suite_green


def draft_patch(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    if scratch.test_path is None or scratch.test_source is None or scratch.test_report is None:
        # Not a stop: the state machine would refuse PATCHED anyway, and reaching here
        # without a test is a wiring bug that should be loud.
        raise RuntimeError("draft_patch reached without the test written by the previous hop")
    workspace = deps.workspace
    known = set(workspace.files())
    sources = dict(scratch.sources)
    hops: list[HopRecord] = []
    feedback = ""
    last_problem = "no attempt was made"
    baselines: dict[tuple[str, ...], TestReport] = {}
    best: PatchAttempt | None = None
    best_report: TestReport | None = None
    fixer_provider: str | None = None

    for _ in range(deps.max_attempts):
        try:
            reply = deps.client.ask(
                Role.FIXER,
                issue_id=issue.issue_id,
                system=prompts.FIXER_SYSTEM,
                prompt=prompts.fixer_prompt(
                    prompts.issue_block(issue.title, issue.body),
                    scratch.test_path,
                    scratch.test_source,
                    scratch.test_report.output,
                    sources,
                    feedback,
                ),
                max_tokens=8192,
            )
        except HopFailed as exc:
            return HopOutput(stop(state, f"draft_patch: {exc}"), scratch, tuple(hops))
        hops.append(hop_record("draft_patch", Role.FIXER, reply))
        fixer_provider = reply.provider

        try:
            edits = parse_edits(reply.text)
            for edit in edits:
                if is_test_file(edit.path):
                    raise MalformedReply(f"{edit.path} is a test file, and tests may not change")
                if edit.path not in sources and edit.path in known:
                    # A file the fixer was not shown but which exists: let it be edited,
                    # and show it from now on.
                    sources[edit.path] = workspace.read(edit.path)
            changed = apply_edits(sources, edits)
        except MalformedReply as exc:
            last_problem = str(exc)
            feedback = f"Your edits could not be applied: {exc}."
            continue
        if not changed:
            last_problem = "the edits changed nothing"
            feedback = "Your edits left every file as it was."
            continue

        diff = unified_diff(sources, changed)
        touched, lines = diff_size(diff)
        suite = related_tests(workspace, touched)
        if suite not in baselines:
            baselines[suite] = workspace.run_tests(list(suite)) if suite else TestReport()
        baseline = baselines[suite]
        # The new test and the existing ones run separately. Each runner names its tests its
        # own way (a pytest id, a Django dotted name, a bare sympy function), so picking the
        # new test's results out of one combined run would mean trusting a naming format.
        own = workspace.run_tests(
            [scratch.test_path],
            diff=diff,
            new_files={scratch.test_path: scratch.test_source},
        )
        patched = workspace.run_tests(list(suite), diff=diff) if suite else TestReport()
        broken = regressions(baseline, patched)
        attempt = PatchAttempt(
            diff=diff,
            test_passes=own.all_passed,
            suite_green=bool(suite) and not broken and not patched.timed_out,
            files_touched=touched,
            lines_changed=lines,
            touches_traceback_frames=bool(set(touched) & set(issue.frame_files)),
            suite_files=suite,
        )
        if best is None or _rank(attempt) >= _rank(best):
            best, best_report = attempt, own
        if attempt.is_green:
            break
        if not attempt.test_passes:
            last_problem = "the failing test still does not pass"
        elif not suite:
            last_problem = "no existing test covers the touched files"
            break  # another draft cannot conjure a regression suite
        else:
            last_problem = f"{len(broken)} previously passing tests now fail"
        feedback = (
            f"Your patch:\n{diff}\nproblem: {last_problem}\n"
            + (f"now failing: {', '.join(sorted(broken)[:10])}\n" if broken else "")
            + f"output:\n{patched.output if attempt.test_passes else own.output}"
        )

    if best is None or best_report is None:
        return HopOutput(
            stop(state, f"draft_patch: no patch could be applied ({last_problem})"),
            scratch,
            tuple(hops),
        )
    out = replace(
        scratch,
        sources=sources,
        patched=best_report,
        fixer_provider=fixer_provider,
        baseline=baselines.get(best.suite_files),
    )
    if not best.test_passes:
        return HopOutput(stop(state, f"draft_patch: {last_problem}"), out, tuple(hops))
    # Patched even when the suite is not green: the router reads suite_green and keeps such
    # a patch at QUIET whatever else it scores, and the reviewer still sees it, because
    # whether the reviewer catches a patch the suite already condemned is part of what
    # reviewer value measures.
    return HopOutput(advance(state, Stage.PATCHED, patch=best), out, tuple(hops))
