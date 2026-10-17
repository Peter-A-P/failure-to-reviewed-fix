"""Hop two: a test that fails on the broken commit, or no patch at all.

The tester writes one new test file. It runs in the sandbox against the broken commit, and
it has to fail in its body: fail, not error. A test that passes demonstrates nothing; one
that errors (a bad import, a missing fixture, a syntax error) demonstrates that it is
broken itself. Either way the tester gets one more attempt with the output in front of it,
and if that fails too the issue stops here and says why. The state machine has no edge
into a patch from anywhere else (mend/graph/machine.py), so there is no way round this
hop, only through it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Deps, HopOutput, Issue, Scratch, hop_record
from mend.graph.llm import HopFailed, HopRecord
from mend.graph.machine import IssueState, Stage, TestAttempt, advance, stop
from mend.graph.parse import MalformedReply, one_tag, strip_fence
from mend.graph.workspace import TestReport, Workspace, is_test_file, related_tests


def check_test_path(path: str, workspace: Workspace) -> str | None:
    """Why a proposed test path is unacceptable, or None if it is fine."""
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not path:
        return f"{path!r} must be a relative path inside the repository"
    if not is_test_file(path) or not pure.name.startswith("test_"):
        return f"{path} must be a .py file whose name starts with test_"
    if path in set(workspace.files()):
        return f"{path} already exists; the test must be a new file"
    return None


def why_not(report: TestReport) -> str:
    """What to tell the tester about a run that did not demonstrate the bug."""
    if report.timed_out:
        return "the test timed out"
    if report.errored:
        return "the test errored instead of failing (collection, import, or fixture problem)"
    if not report.ran:
        return "no test was collected from the file"
    if not report.failed:
        return "the test passed on the current code, so it does not reproduce the bug"
    return "the test did not fail cleanly"


def write_test(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    workspace = deps.workspace
    nearby = related_tests(workspace, state.suspect_files, limit=1)
    example = (nearby[0], workspace.read(nearby[0])) if nearby else None
    hops: list[HopRecord] = []
    feedback = ""
    last_problem = "no attempt was made"
    last_written: IssueState | None = None

    for _ in range(deps.max_attempts):
        try:
            reply = deps.client.ask(
                Role.TESTER,
                issue_id=issue.issue_id,
                system=prompts.TESTER_SYSTEM,
                prompt=prompts.tester_prompt(
                    prompts.issue_block(issue.title, issue.body),
                    scratch.sources,
                    example,
                    feedback,
                ),
            )
        except HopFailed as exc:
            return HopOutput(stop(state, f"write_test: {exc}"), scratch, tuple(hops))
        hops.append(hop_record("write_test", Role.TESTER, reply))

        try:
            path = one_tag(reply.text, "path").strip()
            source = strip_fence(one_tag(reply.text, "test"))
        except MalformedReply as exc:
            last_problem = str(exc)
            feedback = f"Your reply could not be used: {exc}."
            continue
        problem = check_test_path(path, workspace)
        if problem is not None:
            last_problem = problem
            feedback = f"Your test path was refused: {problem}."
            continue

        report = workspace.run_tests([path], new_files={path: source})
        attempt = TestAttempt(
            test_id=path,
            source=source,
            ran=report.ran,
            failed_on_broken_commit=report.failed_cleanly,
            output=report.output,
        )
        written = advance(state, Stage.TEST_WRITTEN, test=attempt)
        if attempt.demonstrates_bug:
            return HopOutput(
                advance(written, Stage.TEST_FAILED_AS_EXPECTED),
                replace(scratch, test_path=path, test_source=source, test_report=report),
                tuple(hops),
            )
        # The state moves to TEST_WRITTEN only on the attempt that is kept. A retry starts
        # again from LOCALISED, with the failed attempt carried in the feedback instead.
        last_problem = why_not(report)
        last_written = written
        feedback = (
            f"Your test at {path}:\n{source}\nproblem: {last_problem}\noutput:\n{report.output}"
        )

    final = last_written if last_written is not None else state
    return HopOutput(
        stop(final, f"write_test: no test failed on the broken commit ({last_problem})"),
        scratch,
        tuple(hops),
    )
