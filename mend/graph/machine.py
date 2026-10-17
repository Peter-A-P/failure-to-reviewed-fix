"""The state machine, and the rails it enforces.

This module is the referee. Everything the plan says the system must never do is refused
here, in code, rather than being left to the prompt, the reviewer, or the person wiring
the graph together:

- No patch without a failing test first (PLAN.md section 2.3). A transition into PATCHED
  is refused unless the state carries a test that was run and observed to fail on the
  broken commit.
- No merge, ever (PLAN.md section 2.8). There is no terminal state that means merged, and
  no transition that could reach one. tests/test_no_merge_path.py asserts the absence
  against the source rather than trusting this sentence.
- The reviewer is a different vendor than the fixer (PLAN.md section 2.4). A transition
  into REVIEWED is refused when the two resolved to the same provider.
- Nothing is proposed that was not reviewed, and nothing acts before it is routed.

Keeping the rails in a plain state machine rather than inside the graph framework is
deliberate: the invariants are then testable without a model, a network or a container,
which means they are tested on every commit rather than on the days a full run happens.
The graph wiring calls advance() for every hop, so there is one place to get right.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar


class Stage(StrEnum):
    """Where an issue has got to. The order here is the order of the pipeline."""

    CAPTURED = "captured"
    CLUSTERED = "clustered"
    LOCALISED = "localised"
    TEST_WRITTEN = "test_written"
    TEST_FAILED_AS_EXPECTED = "test_failed_as_expected"
    PATCHED = "patched"
    REVIEWED = "reviewed"
    ROUTED = "routed"
    ACTED = "acted"
    # Terminal, and the honest answer more often than not.
    STOPPED = "stopped"


# The only transitions that exist. Anything not listed is refused by advance().
#
# Note what is missing and cannot be added without editing this table in a commit: any
# edge into PATCHED from anywhere but TEST_FAILED_AS_EXPECTED, and any stage at all that
# means the change was merged.
_ALLOWED: Mapping[Stage, frozenset[Stage]] = {
    Stage.CAPTURED: frozenset({Stage.CLUSTERED, Stage.STOPPED}),
    Stage.CLUSTERED: frozenset({Stage.LOCALISED, Stage.STOPPED}),
    Stage.LOCALISED: frozenset({Stage.TEST_WRITTEN, Stage.STOPPED}),
    Stage.TEST_WRITTEN: frozenset({Stage.TEST_FAILED_AS_EXPECTED, Stage.STOPPED}),
    Stage.TEST_FAILED_AS_EXPECTED: frozenset({Stage.PATCHED, Stage.STOPPED}),
    Stage.PATCHED: frozenset({Stage.REVIEWED, Stage.STOPPED}),
    Stage.REVIEWED: frozenset({Stage.ROUTED, Stage.STOPPED}),
    Stage.ROUTED: frozenset({Stage.ACTED, Stage.STOPPED}),
    Stage.ACTED: frozenset(),
    Stage.STOPPED: frozenset(),
}


class RailViolation(Exception):
    """A transition the design forbids. Never caught inside the package.

    Caught nowhere on purpose: a rail violation is a bug in the wiring, and a pipeline
    that swallows it and carries on is a pipeline whose guarantees are decorative.
    """


class NoFailingTest(RailViolation):
    """A patch was attempted without a test that failed on the broken commit first."""


class SameVendorReview(RailViolation):
    """The reviewer resolved to the same provider as the fixer."""


class UnreviewedProposal(RailViolation):
    """An action was attempted on a patch no reviewer saw."""


@dataclass(frozen=True, slots=True)
class TestAttempt:
    """A generated test and what happened when it ran on the broken commit.

    failed_on_broken_commit is the whole point. A test that passes on the broken commit
    demonstrates nothing, and a test that errors demonstrates only that it is broken
    itself; both leave the state machine at TEST_WRITTEN, which has no edge to PATCHED.
    """

    # Not a test case. The name is right for what this is, and pytest would otherwise try
    # to collect it out of any test module that imports it.
    __test__: ClassVar[bool] = False

    test_id: str
    source: str
    ran: bool = False
    failed_on_broken_commit: bool = False
    output: str = ""

    @property
    def demonstrates_bug(self) -> bool:
        return self.ran and self.failed_on_broken_commit


@dataclass(frozen=True, slots=True)
class PatchAttempt:
    """A candidate diff and what the sandbox said about it.

    suite_files names the existing test files that suite_green was judged on. "The suite
    stayed green" is a claim about some set of tests, and a claim that does not say which
    one cannot be checked; an empty tuple means no existing test was found to run, and the
    patch hop then refuses to call the suite green at all.
    """

    diff: str
    test_passes: bool = False
    suite_green: bool = False
    files_touched: tuple[str, ...] = ()
    lines_changed: int = 0
    touches_traceback_frames: bool = False
    suite_files: tuple[str, ...] = ()

    @property
    def is_green(self) -> bool:
        return self.test_passes and self.suite_green


@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    """What the different-vendor reviewer said.

    agrees is the reviewer accepting the patch. Disagreement escalates to a person rather
    than proceeding (PLAN.md section 2.4), which the routing implements by capping the
    tier; the machine insists only that a review happened at all, and by whom.
    """

    reviewer_provider: str
    fixer_provider: str
    agrees: bool
    objection: str = ""

    def __post_init__(self) -> None:
        if not self.reviewer_provider or not self.fixer_provider:
            raise ValueError("both providers must be named")


@dataclass(frozen=True, slots=True)
class IssueState:
    """Everything known about one issue, and where it has got to.

    Immutable: advance() returns a new state. A pipeline whose steps mutate shared state
    is a pipeline where the question "was there a failing test" depends on when you ask.
    """

    issue_id: str
    stage: Stage = Stage.CAPTURED
    ticket_id: str | None = None
    suspect_files: tuple[str, ...] = ()
    test: TestAttempt | None = None
    patch: PatchAttempt | None = None
    review: ReviewVerdict | None = None
    tier: str | None = None
    score: float | None = None
    stop_reason: str | None = None
    history: tuple[Stage, ...] = field(default_factory=lambda: (Stage.CAPTURED,))

    @property
    def had_failing_test(self) -> bool:
        return self.test is not None and self.test.demonstrates_bug


def advance(state: IssueState, to: Stage, **updates: Any) -> IssueState:
    """Move to the given stage, refusing anything the design forbids.

    Raises RailViolation (or a subclass) rather than returning an error, because every
    caller of this function is a node in the pipeline and none of them has a sensible
    thing to do with a refusal except stop.
    """
    if to not in _ALLOWED[state.stage]:
        raise RailViolation(f"{state.stage} cannot advance to {to}")

    candidate = replace(state, stage=to, history=(*state.history, to), **updates)

    if to is Stage.TEST_FAILED_AS_EXPECTED and not candidate.had_failing_test:
        raise NoFailingTest(
            f"{state.issue_id}: a test must be run and observed to fail on the broken commit"
        )

    if to is Stage.PATCHED:
        # Belt and braces with the transition table above. The table says this edge can
        # only come from TEST_FAILED_AS_EXPECTED; this says the evidence must still be on
        # the state when it does, so that a later edit to the table cannot quietly drop
        # the rule the whole design rests on.
        if not candidate.had_failing_test:
            raise NoFailingTest(f"{state.issue_id}: no patch without a failing test first")
        if candidate.patch is None:
            raise RailViolation(f"{state.issue_id}: PATCHED needs a patch")

    if to is Stage.REVIEWED:
        review = candidate.review
        if review is None:
            raise RailViolation(f"{state.issue_id}: REVIEWED needs a verdict")
        if review.reviewer_provider == review.fixer_provider:
            raise SameVendorReview(
                f"{state.issue_id}: reviewer and fixer both resolved to "
                f"{review.reviewer_provider}; the review must come from a different vendor"
            )

    if to is Stage.ACTED and candidate.review is None:
        raise UnreviewedProposal(f"{state.issue_id}: nothing acts on an unreviewed patch")

    return candidate


def stop(state: IssueState, reason: str) -> IssueState:
    """Stop and say why. Available from every non-terminal stage, and used often.

    Stopping is a result, not a failure: PLAN.md section 1 reports stay-quiet precision
    precisely because declining to act is the behaviour under test.
    """
    if not reason:
        raise ValueError("a stop must carry a reason")
    if state.stage in (Stage.ACTED, Stage.STOPPED):
        raise RailViolation(f"{state.issue_id}: already terminal at {state.stage}")
    return replace(
        state,
        stage=Stage.STOPPED,
        stop_reason=reason,
        history=(*state.history, Stage.STOPPED),
    )
