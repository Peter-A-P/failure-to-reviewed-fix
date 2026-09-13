"""The rails: no patch without a failing test, a different-vendor reviewer, no merge.

These are the tests the design rests on, so they are written against the behaviour a
caller would have to get past rather than against the implementation: every test here
tries to do the forbidden thing by the most convenient route and asserts that it is
refused.
"""

from __future__ import annotations

import pytest

from mend.graph.machine import (
    IssueState,
    NoFailingTest,
    PatchAttempt,
    RailViolation,
    ReviewVerdict,
    SameVendorReview,
    Stage,
    TestAttempt,
    UnreviewedProposal,
    advance,
    stop,
)

FAILING_TEST = TestAttempt(
    test_id="tests/test_bug.py::test_reported_behaviour",
    source="def test_reported_behaviour(): assert parse('x=1') == {'x': 1}",
    ran=True,
    failed_on_broken_commit=True,
)
PASSING_TEST = TestAttempt(
    test_id="tests/test_bug.py::test_nothing",
    source="def test_nothing(): assert True",
    ran=True,
    failed_on_broken_commit=False,
)
UNRUN_TEST = TestAttempt(test_id="tests/test_bug.py::test_x", source="...", ran=False)

GREEN_PATCH = PatchAttempt(
    diff="--- a/pkg/mod.py\n+++ b/pkg/mod.py\n",
    test_passes=True,
    suite_green=True,
    files_touched=("pkg/mod.py",),
    lines_changed=4,
    touches_traceback_frames=True,
)


def localised(issue_id: str = "demo-1") -> IssueState:
    state = IssueState(issue_id=issue_id)
    state = advance(state, Stage.CLUSTERED, ticket_id="T0001")
    return advance(state, Stage.LOCALISED, suspect_files=("pkg/mod.py",))


def test_a_test_that_failed_first_unlocks_patching() -> None:
    state = advance(localised(), Stage.TEST_WRITTEN, test=FAILING_TEST)
    state = advance(state, Stage.TEST_FAILED_AS_EXPECTED)
    state = advance(state, Stage.PATCHED, patch=GREEN_PATCH)
    assert state.stage is Stage.PATCHED
    assert state.had_failing_test


def test_a_test_that_passes_on_the_broken_commit_demonstrates_nothing() -> None:
    state = advance(localised(), Stage.TEST_WRITTEN, test=PASSING_TEST)
    with pytest.raises(NoFailingTest):
        advance(state, Stage.TEST_FAILED_AS_EXPECTED)


def test_a_test_that_was_never_run_demonstrates_nothing() -> None:
    state = advance(localised(), Stage.TEST_WRITTEN, test=UNRUN_TEST)
    with pytest.raises(NoFailingTest):
        advance(state, Stage.TEST_FAILED_AS_EXPECTED)


def test_patching_cannot_skip_the_test_stage() -> None:
    """The shortcut somebody would actually take: straight from localised to patched."""
    with pytest.raises(RailViolation):
        advance(localised(), Stage.PATCHED, patch=GREEN_PATCH)


def test_patching_cannot_skip_from_test_written() -> None:
    state = advance(localised(), Stage.TEST_WRITTEN, test=FAILING_TEST)
    with pytest.raises(RailViolation):
        advance(state, Stage.PATCHED, patch=GREEN_PATCH)


def test_patched_needs_an_actual_patch() -> None:
    state = advance(localised(), Stage.TEST_WRITTEN, test=FAILING_TEST)
    state = advance(state, Stage.TEST_FAILED_AS_EXPECTED)
    with pytest.raises(RailViolation):
        advance(state, Stage.PATCHED)


def patched(issue_id: str = "demo-1") -> IssueState:
    state = advance(localised(issue_id), Stage.TEST_WRITTEN, test=FAILING_TEST)
    state = advance(state, Stage.TEST_FAILED_AS_EXPECTED)
    return advance(state, Stage.PATCHED, patch=GREEN_PATCH)


def test_the_reviewer_must_be_a_different_vendor() -> None:
    state = patched()
    same = ReviewVerdict(reviewer_provider="anthropic", fixer_provider="anthropic", agrees=True)
    with pytest.raises(SameVendorReview) as caught:
        advance(state, Stage.REVIEWED, review=same)
    assert "different vendor" in str(caught.value)


def test_a_different_vendor_reviewer_is_accepted() -> None:
    state = patched()
    verdict = ReviewVerdict(reviewer_provider="openai", fixer_provider="anthropic", agrees=True)
    state = advance(state, Stage.REVIEWED, review=verdict)
    assert state.stage is Stage.REVIEWED


def test_review_needs_a_verdict() -> None:
    with pytest.raises(RailViolation):
        advance(patched(), Stage.REVIEWED)


def test_a_verdict_must_name_both_providers() -> None:
    with pytest.raises(ValueError, match="both providers"):
        ReviewVerdict(reviewer_provider="", fixer_provider="anthropic", agrees=True)


def test_nothing_acts_without_a_review() -> None:
    """Constructed by hand to reach ROUTED with no review, which the ordinary path cannot."""
    state = IssueState(
        issue_id="demo-1",
        stage=Stage.ROUTED,
        test=FAILING_TEST,
        patch=GREEN_PATCH,
        review=None,
    )
    with pytest.raises(UnreviewedProposal):
        advance(state, Stage.ACTED, tier="suggest")


def test_the_full_path_ends_at_acted() -> None:
    state = patched()
    state = advance(
        state,
        Stage.REVIEWED,
        review=ReviewVerdict(reviewer_provider="openai", fixer_provider="anthropic", agrees=True),
    )
    state = advance(state, Stage.ROUTED, tier="auto_propose", score=0.91)
    state = advance(state, Stage.ACTED)
    assert state.stage is Stage.ACTED
    assert state.history[0] is Stage.CAPTURED
    assert state.history[-1] is Stage.ACTED


def test_stopping_is_available_everywhere_and_says_why() -> None:
    for state in (IssueState(issue_id="d"), localised(), patched()):
        stopped = stop(state, "no failing test could be written")
        assert stopped.stage is Stage.STOPPED
        assert stopped.stop_reason


def test_a_stop_must_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        stop(localised(), "")


def test_a_terminal_state_cannot_be_stopped_again() -> None:
    stopped = stop(localised(), "gave up")
    with pytest.raises(RailViolation):
        stop(stopped, "gave up again")


def test_states_are_immutable() -> None:
    """advance returns a new state; the old one still says what it said.

    The property that matters is that a node cannot retroactively make it true that there
    was a failing test.
    """
    before = advance(localised(), Stage.TEST_WRITTEN, test=PASSING_TEST)
    assert not before.had_failing_test
    with pytest.raises(AttributeError):
        before.test = FAILING_TEST  # type: ignore[misc]
    assert not before.had_failing_test
