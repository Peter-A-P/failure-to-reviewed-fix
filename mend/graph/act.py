"""Hops five and six: choose the tier, then write down what would be done about it.

Routing is mend.graph.route applied to the state's evidence. Until the thresholds have
been calibrated on a validation split, Deps.thresholds is None and nothing auto-proposes:
every issue that would have scored into the top tier is held at SUGGEST, because a
threshold nobody has measured is a guess, and a guess should not open pull requests.

Acting produces a Proposal and nothing else. A Proposal is the text of a draft pull
request, of a comment, or of a log line, for whatever runs the live workflow to post or
not. Nothing in this module talks to GitHub, and there is no tier, kind or field here that
means the change landed (tests/test_no_merge_path.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mend.graph.context import Deps, HopOutput, Issue, Scratch
from mend.graph.machine import IssueState, Stage, advance
from mend.graph.route import Signals, Thresholds, Tier, route

# What an uncalibrated router uses for the SUGGEST line. The same floor calibrate()
# defaults to, so an uncalibrated run and a calibrated one differ only at the top tier.
UNCALIBRATED_SUGGEST = 0.35


class ProposalKind(StrEnum):
    DRAFT_PULL_REQUEST = "draft_pull_request"
    COMMENT = "comment"
    LOG = "log"


_KIND = {
    Tier.AUTO_PROPOSE: ProposalKind.DRAFT_PULL_REQUEST,
    Tier.SUGGEST: ProposalKind.COMMENT,
    Tier.QUIET: ProposalKind.LOG,
}


@dataclass(frozen=True, slots=True)
class Proposal:
    """What a person would be shown. Draft pull requests only: a person merges, or not."""

    kind: ProposalKind
    issue_id: str
    title: str
    body: str
    tier: Tier
    score: float


def choose_tier(
    state: IssueState, issue: Issue, thresholds: Thresholds | None
) -> tuple[Tier, float]:
    signals = Signals.from_state(state, cluster_size=issue.cluster_size)
    if thresholds is None:
        provisional = Thresholds(
            auto_propose=1.0,
            suggest=UNCALIBRATED_SUGGEST,
            target_confidently_wrong=0.03,
            calibrated_on="uncalibrated",
        )
        tier, value = route(signals, provisional)
        return (Tier.SUGGEST if tier is Tier.AUTO_PROPOSE else tier), value
    return route(signals, thresholds)


def route_issue(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    tier, value = choose_tier(state, issue, deps.thresholds)
    return HopOutput(advance(state, Stage.ROUTED, tier=tier.value, score=value), scratch)


def proposal_body(issue: Issue, state: IssueState, scratch: Scratch) -> str:
    """The text a reviewer of the pull request reads: evidence first, then the diff."""
    test, patch, verdict = state.test, state.patch, state.review
    lines = [f"Proposed by mend for: {issue.title}", ""]
    if test is not None:
        lines += [
            f"**Failing test first.** `{test.test_id}` fails on the current code and passes "
            "with this change."
            if patch is not None and patch.test_passes
            else f"**Test.** `{test.test_id}`",
            "",
        ]
    if patch is not None:
        suite = ", ".join(f"`{p}`" for p in patch.suite_files) or "none found"
        green = "still pass" if patch.suite_green else "do not all still pass"
        lines += [f"**Existing tests run:** {suite}; they {green}.", ""]
    if verdict is not None:
        stance = "accepted" if verdict.agrees else "objected"
        lines += [
            f"**Review by a second model ({verdict.reviewer_provider}):** {stance}.",
            *([f"> {verdict.objection}"] if verdict.objection else []),
            "",
        ]
    lines += [
        f"Routing: {state.tier} at score {state.score:.2f}"
        if state.score is not None
        else "Routing: not scored",
        "",
        "Nothing here merges. A person reviews this and decides.",
    ]
    if patch is not None:
        lines += ["", "```diff", patch.diff.rstrip("\n"), "```"]
    if test is not None:
        lines += ["", "```python", test.source.rstrip("\n"), "```"]
    return "\n".join(lines)


def act(
    issue: Issue, state: IssueState, scratch: Scratch, deps: Deps
) -> tuple[HopOutput, Proposal]:
    tier = Tier(state.tier) if state.tier else Tier.QUIET
    proposal = Proposal(
        kind=_KIND[tier],
        issue_id=issue.issue_id,
        title=f"mend: {issue.title}"[:200],
        body=proposal_body(issue, state, scratch),
        tier=tier,
        score=state.score or 0.0,
    )
    return HopOutput(advance(state, Stage.ACTED), scratch), proposal
