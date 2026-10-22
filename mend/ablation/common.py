"""What the ablations share: their gateway run ids, one review call, and the record they write.

The record has the shape of the main run's (mend.graph.graph.RunRecord as JSON), with the
same "issue" and "state" keys, so the harness adapter and mend.sandbox.harness.outcomes
read it unchanged. It adds "arm", and its state never carries a stage past what the
ablation did: there is no ACTED, because nothing acts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Issue, hop_record
from mend.graph.llm import HopFailed, HopRecord, ModelClient
from mend.graph.machine import PatchAttempt
from mend.graph.parse import MalformedReply
from mend.graph.review import REVIEW_MAX_TOKENS, parse_verdict
from mend.graph.route import Signals, Thresholds, Tier, route


def run_id(arm: str, issue_id: str) -> str:
    """The gateway run id for one task in one arm.

    Not the bare issue id the main run used. The per-issue cap is per run id, and the main
    run already spent part of each task's dollar; an ablation sharing the id would be capped
    by money spent on another arm, and its ledger rows could not be told apart from the
    main run's.
    """
    return f"{arm}:{issue_id}"


@dataclass(frozen=True, slots=True)
class Review:
    """A verdict, or the reason there is none."""

    agrees: bool | None
    objection: str
    provider: str | None
    hops: tuple[HopRecord, ...]
    problem: str = ""


def ask_review(client: ModelClient, role: Role, *, run: str, prompt: str) -> Review:
    """One review, the main run's way: its system prompt, its token limit, and one retry
    on a reply whose verdict cannot be read."""
    hops: list[HopRecord] = []
    problem = ""
    for _ in range(2):
        try:
            reply = client.ask(
                role,
                issue_id=run,
                system=prompts.REVIEWER_SYSTEM,
                prompt=prompt
                + (f"\n\nYour previous reply could not be read: {problem}" if problem else ""),
                max_tokens=REVIEW_MAX_TOKENS,
            )
        except HopFailed as exc:
            return Review(None, "", None, tuple(hops), f"review: {exc}")
        hops.append(hop_record("review", role, reply))
        try:
            agrees, objection = parse_verdict(reply.text)
        except MalformedReply as exc:
            problem = str(exc)
            continue
        return Review(agrees, objection, reply.provider, tuple(hops))
    return Review(None, "", None, tuple(hops), f"review: the verdict could not be read ({problem})")


def tier_for(
    patch: PatchAttempt, *, reviewer_agrees: bool, thresholds: Thresholds | None, test_shown: bool
) -> tuple[Tier, float]:
    """The main run's router, applied to an ablation's evidence.

    test_shown says whether the patch's own failing-then-passing test counts. The main
    run's value; in the no-test-first arm there is no test, and the arm stands for a system
    that takes its patch on trust, so the signal is set as if the test had been shown. That
    is what removing the step means: everything downstream of it behaves as though it had
    succeeded. Uncalibrated thresholds cap at SUGGEST, as in mend.graph.act.
    """
    signals = Signals(
        test_failed_then_passed=test_shown,
        suite_green=patch.suite_green,
        reviewer_agrees=reviewer_agrees,
        touches_traceback_frames=patch.touches_traceback_frames,
        files_touched=len(patch.files_touched),
        lines_changed=patch.lines_changed,
        cluster_size=1,
    )
    if thresholds is None:
        provisional = Thresholds(
            auto_propose=1.0, suggest=0.35, target_confidently_wrong=0.03, calibrated_on="none"
        )
        tier, value = route(signals, provisional)
        return (Tier.SUGGEST if tier is Tier.AUTO_PROPOSE else tier), value
    return route(signals, thresholds)


@dataclass(frozen=True, slots=True)
class ArmRecord:
    """One task in one ablation arm, as one line of the arm's run log."""

    arm: str
    issue: Issue
    stage: str
    suspect_files: tuple[str, ...] = ()
    patch: PatchAttempt | None = None
    review: Mapping[str, Any] | None = None
    tier: str | None = None
    score: float | None = None
    stop_reason: str | None = None
    hops: Sequence[HopRecord] = field(default_factory=tuple)
    duration_s: float = 0.0
    notes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float | None:
        costs = [h.cost_usd for h in self.hops]
        return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "issue": asdict(self.issue),
            "state": {
                "issue_id": self.issue.issue_id,
                "stage": self.stage,
                "suspect_files": list(self.suspect_files),
                "test": None,
                "patch": asdict(self.patch) if self.patch is not None else None,
                "review": dict(self.review) if self.review is not None else None,
                "tier": self.tier,
                "score": self.score,
                "stop_reason": self.stop_reason,
            },
            "hops": [asdict(h) for h in self.hops],
            "cost_usd": self.cost_usd,
            "duration_s": self.duration_s,
            "notes": dict(self.notes),
        }


def issue_from_record(row: Mapping[str, Any]) -> Issue:
    """The Issue a recorded run was given, rebuilt from its run log line."""
    raw = dict(row["issue"])
    raw["frame_files"] = tuple(raw.get("frame_files") or ())
    return Issue(**raw)
