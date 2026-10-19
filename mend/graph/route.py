"""Confidence routing: the score, the three tiers, and where the thresholds come from.

The score is a weighted sum of signals that are all observations, not opinions: did the
test fail and then pass, is the suite green, did the reviewer agree, how big is the diff,
how many files does it touch, does it touch the frames in the traceback, how many symptoms
did the cluster hold (PLAN.md section 2.5). No model is asked how confident it is, because
a model's stated confidence is the one signal here that is free to be wrong at no cost to
itself.

The weights below are a starting point and are deliberately not the deliverable. The
deliverable is the curve in routing_curve(): hit rate and confidently-wrong rate at every
threshold, published so a reader can pick a different false-positive target than the 3%
this project chose and read off what it would cost them.

Two properties the calibration must have, and the reason each is enforced here:

- The thresholds are chosen on a validation split, never on the main run. Choosing them
  on the run they are then reported against is how a 3% target becomes a 3% result by
  construction.
- A reviewer who disagrees caps the tier at SUGGEST however high the score is. The plan
  says disagreement escalates to a person; a score that could override that would make
  the second model decorative.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from mend.graph.machine import IssueState


class Tier(StrEnum):
    """What the system does about an issue. There is no tier above AUTO_PROPOSE.

    AUTO_PROPOSE opens a draft pull request. Draft, and a person merges it or does not:
    there is no merge path anywhere in this package (PLAN.md section 2.8).
    """

    AUTO_PROPOSE = "auto_propose"
    SUGGEST = "suggest"
    QUIET = "quiet"


@dataclass(frozen=True, slots=True)
class Signals:
    """The observations the score is built from, pulled off an IssueState.

    Separate from IssueState so that the calibration can be run over recorded signals from
    a past run without reconstructing the whole pipeline, and so that a test can vary one
    signal at a time.
    """

    test_failed_then_passed: bool
    suite_green: bool
    reviewer_agrees: bool
    touches_traceback_frames: bool
    files_touched: int
    lines_changed: int
    cluster_size: int

    @classmethod
    def from_state(cls, state: IssueState, *, cluster_size: int = 1) -> Signals:
        test = state.test
        patch = state.patch
        review = state.review
        return cls(
            test_failed_then_passed=bool(
                test is not None
                and test.demonstrates_bug
                and patch is not None
                and patch.test_passes
            ),
            suite_green=bool(patch is not None and patch.suite_green),
            reviewer_agrees=bool(review is not None and review.agrees),
            touches_traceback_frames=bool(patch is not None and patch.touches_traceback_frames),
            files_touched=len(patch.files_touched) if patch is not None else 0,
            lines_changed=patch.lines_changed if patch is not None else 0,
            cluster_size=cluster_size,
        )


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """How much each signal carries. Positive weights are evidence the patch is right.

    The three negative ones are not penalties for being a large change as such; they are
    the observation that the further a patch ranges from the frames that produced the
    failure, the less the failing test proves about the rest of it.
    """

    test_failed_then_passed: float = 0.35
    suite_green: float = 0.25
    reviewer_agrees: float = 0.20
    touches_traceback_frames: float = 0.10
    cluster_evidence: float = 0.10
    # Subtracted, scaled by how far past the comfortable size the patch is.
    files_penalty: float = 0.15
    lines_penalty: float = 0.15


# A patch touching up to this many files, or changing up to this many lines, pays nothing.
# Past them the penalty ramps to its full weight. Both are a judgement about what a single
# root cause usually looks like, to be revisited against the validation split.
_COMFORTABLE_FILES = 2
_COMFORTABLE_LINES = 40
_PENALTY_SATURATES_FILES = 8
_PENALTY_SATURATES_LINES = 400
# A cluster of this many symptoms is as much corroboration as size alone can give.
_CLUSTER_SATURATES = 10


def _ramp(value: float, comfortable: float, saturates: float) -> float:
    """0.0 up to comfortable, rising to 1.0 at saturates, flat after."""
    if value <= comfortable:
        return 0.0
    if value >= saturates:
        return 1.0
    return (value - comfortable) / (saturates - comfortable)


def score(signals: Signals, weights: ScoreWeights | None = None) -> float:
    """A confidence score in the unit interval. Higher means more evidence.

    Not a probability. It is monotone in the evidence and nothing more, which is exactly
    what a threshold needs; calling it a probability would invite reading 0.7 as a 70%
    chance of being right, and the curve is what actually says what 0.7 buys.
    """
    w = weights or ScoreWeights()
    positive = (
        w.test_failed_then_passed * signals.test_failed_then_passed
        + w.suite_green * signals.suite_green
        + w.reviewer_agrees * signals.reviewer_agrees
        + w.touches_traceback_frames * signals.touches_traceback_frames
        + w.cluster_evidence * min(signals.cluster_size, _CLUSTER_SATURATES) / _CLUSTER_SATURATES
    )
    penalty = w.files_penalty * _ramp(
        signals.files_touched, _COMFORTABLE_FILES, _PENALTY_SATURATES_FILES
    ) + w.lines_penalty * _ramp(signals.lines_changed, _COMFORTABLE_LINES, _PENALTY_SATURATES_LINES)
    return max(0.0, min(1.0, positive - penalty))


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Where the tiers divide, and the target they were calibrated against.

    target_confidently_wrong is carried with the thresholds rather than kept in a
    document, so that a routing decision can always answer "chosen against what target,
    on what split" without anyone having to go and look.
    """

    auto_propose: float
    suggest: float
    target_confidently_wrong: float
    calibrated_on: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.suggest <= self.auto_propose <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= suggest <= auto_propose <= 1")
        if not 0.0 <= self.target_confidently_wrong <= 1.0:
            raise ValueError("the false-positive target must be a proportion")
        if not self.calibrated_on:
            raise ValueError("a threshold must say which split it was calibrated on")


def route(
    signals: Signals,
    thresholds: Thresholds,
    weights: ScoreWeights | None = None,
) -> tuple[Tier, float]:
    """The tier for one issue, and the score behind it.

    Three hard rules before the score is consulted at all. A patch that does not make its
    failing test pass, or that leaves the suite red, is never proposed however good it
    looks otherwise; and a reviewer who disagrees caps the tier at SUGGEST, because
    disagreement escalates to a person (PLAN.md section 2.4).
    """
    value = score(signals, weights)

    if not signals.test_failed_then_passed or not signals.suite_green:
        return Tier.QUIET, value

    if value >= thresholds.auto_propose:
        tier = Tier.AUTO_PROPOSE
    elif value >= thresholds.suggest:
        tier = Tier.SUGGEST
    else:
        tier = Tier.QUIET

    if tier is Tier.AUTO_PROPOSE and not signals.reviewer_agrees:
        return Tier.SUGGEST, value

    return tier, value


@dataclass(frozen=True, slots=True)
class Outcome:
    """One calibration row: what the system scored, and whether it was actually right.

    resolved comes from the benchmark's hidden tests and from nowhere else. It is never
    available to any part of the pipeline that runs before this point, which is what makes
    the hit rate honest (PLAN.md section 2.1).

    eligible is whether route() could propose the patch at all: its failing test passes and
    the suite stayed green. The curve counts only eligible patches, because a curve that
    counted patches the router would refuse whatever their score would describe a router
    that does not exist (found 2026-10-19, on the first validation run).
    """

    issue_id: str
    score: float
    reviewer_agrees: bool
    resolved: bool
    eligible: bool = True


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """The trade-off at one candidate threshold."""

    threshold: float
    n_auto: int
    n_resolved: int
    hit_rate: float
    confidently_wrong: float
    coverage: float


def routing_curve(outcomes: Sequence[Outcome], *, steps: int = 101) -> list[CurvePoint]:
    """Hit rate and confidently-wrong rate at every candidate threshold.

    This is the published artefact (PLAN.md section 2.5, docs/routing.md). A reader with a
    different tolerance for a wrong auto-proposal reads their own threshold off it rather
    than taking this project's word for the one it chose.

    confidently_wrong is the share of auto-proposals that the hidden tests rejected, which
    is the number that matters: a threshold with a superb hit rate that only fires twice
    is not a system anyone can use, so coverage is reported beside it.
    """
    if steps < 2:
        raise ValueError("a curve needs at least two points")
    total = len(outcomes)
    points: list[CurvePoint] = []

    for i in range(steps):
        threshold = i / (steps - 1)
        auto = [o for o in outcomes if o.eligible and o.score >= threshold and o.reviewer_agrees]
        resolved = sum(1 for o in auto if o.resolved)
        n_auto = len(auto)
        points.append(
            CurvePoint(
                threshold=threshold,
                n_auto=n_auto,
                n_resolved=resolved,
                hit_rate=resolved / n_auto if n_auto else float("nan"),
                confidently_wrong=(n_auto - resolved) / n_auto if n_auto else 0.0,
                coverage=n_auto / total if total else 0.0,
            )
        )
    return points


def calibrate(
    outcomes: Sequence[Outcome],
    *,
    target_confidently_wrong: float = 0.03,
    split_name: str,
    suggest_floor: float = 0.35,
    steps: int = 101,
    min_auto: int = 5,
) -> Thresholds:
    """The lowest auto-propose threshold meeting the false-positive target.

    Lowest, not safest: a threshold of 1.0 has a confidently-wrong rate of zero and
    proposes nothing, so the target is a constraint and coverage is what is maximised
    subject to it.

    min_auto guards against the other way of hitting the target by accident. One
    auto-proposal that happened to be right is a 0% confidently-wrong rate on n = 1, and
    calibrating to that is not calibration. Where no threshold satisfies both, this
    returns 1.0, which means the honest thing: on this evidence, propose nothing
    automatically.
    """
    if not outcomes:
        raise ValueError("calibration needs outcomes")
    if not 0.0 <= target_confidently_wrong <= 1.0:
        raise ValueError("the false-positive target must be a proportion")

    curve = routing_curve(outcomes, steps=steps)
    viable = [
        p for p in curve if p.n_auto >= min_auto and p.confidently_wrong <= target_confidently_wrong
    ]
    auto = min((p.threshold for p in viable), default=1.0)
    return Thresholds(
        auto_propose=auto,
        suggest=min(suggest_floor, auto),
        target_confidently_wrong=target_confidently_wrong,
        calibrated_on=split_name,
    )
