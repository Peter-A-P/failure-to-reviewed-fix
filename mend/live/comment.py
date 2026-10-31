"""What the live workflow says, and where it says it.

Every issue it triages is reported in the job summary, which is the log a person can read
for any run. Only a suggestion is also posted, as a comment on the pull request the failing
run belongs to. An auto-propose verdict is posted the same way, as a suggestion, with the
router's own verdict stated: the main run's confidently-wrong rate missed its target
(README), so this workflow does not open pull requests on that router's say-so.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mend.graph.graph import RunRecord
from mend.graph.route import Tier

MARK = "<!-- mend-live -->"


@dataclass(frozen=True, slots=True)
class Outcome:
    """One triaged issue, as the workflow reports it."""

    issue_id: str
    title: str
    symptoms: int
    tier: Tier | None
    stop_reason: str | None
    cost_usd: float | None
    body: str | None

    @property
    def posts(self) -> bool:
        """Whether this goes on the pull request: a suggestion, whatever the router said
        above the quiet line. A quiet or stopped issue is logged and nothing more."""
        return self.body is not None and self.tier in (Tier.SUGGEST, Tier.AUTO_PROPOSE)

    @classmethod
    def from_record(cls, record: RunRecord) -> Outcome:
        state = record.state
        tier = Tier(state.tier) if state.tier else None
        return cls(
            issue_id=record.issue.issue_id,
            title=record.issue.title,
            symptoms=record.issue.cluster_size,
            tier=tier,
            stop_reason=state.stop_reason,
            cost_usd=record.cost_usd,
            body=record.proposal.body if record.proposal is not None else None,
        )


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"US${value:.2f}"


def comment(outcome: Outcome, *, run_url: str, spent_usd: float, cap_usd: float) -> str:
    """The pull request comment for one suggestion."""
    said = (
        "The router rated this auto-propose; this workflow posts suggestions only."
        if outcome.tier is Tier.AUTO_PROPOSE
        else "The router rated this a suggestion."
    )
    return "\n".join(
        [
            MARK,
            f"### mend: a suggested fix for {outcome.symptoms} failing test(s) in this run",
            "",
            f"{said} Nothing has been pushed, opened or merged; this is a comment. A "
            "person decides whether any of it is right.",
            "",
            outcome.body or "",
            "",
            "---",
            f"Cost of this suggestion: {_money(outcome.cost_usd)}. Spent by mend in this "
            f"repository so far: US${spent_usd:.2f} of US${cap_usd:.2f}. "
            f"[The run and its log]({run_url}).",
        ]
    )


def summary(outcomes: list[Outcome], *, records: int, tickets: int, note: str = "") -> str:
    """The job summary: every issue, posted or not."""
    lines = [
        "## mend live",
        "",
        f"{records} failing test(s) captured in the sandbox, clustered into {tickets} ticket(s).",
    ]
    if note:
        lines += ["", note]
    if outcomes:
        lines += [
            "",
            "| Ticket | Symptoms | Outcome | Cost | Posted |",
            "|---|---|---|---|---|",
            *(
                f"| {o.title} | {o.symptoms} "
                f"| {o.tier.value if o.tier else 'stopped: ' + str(o.stop_reason)} "
                f"| {_money(o.cost_usd)} | {'yes' if o.posts else 'no'} |"
                for o in outcomes
            ),
        ]
    return "\n".join(lines) + "\n"


def post(
    repo: str,
    pull_request: int,
    body: str,
    *,
    execute: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    """Comment on the pull request, with the gh client the runner has. GH_TOKEN is the
    job's own token, which the workflow grants pull-requests: write and nothing more."""
    with tempfile.TemporaryDirectory(prefix="mend-comment-") as tmp:
        path = Path(tmp) / "body.md"
        path.write_text(body, encoding="utf-8", newline="\n")
        command = ["gh", "pr", "comment", str(pull_request), "-R", repo, "--body-file", str(path)]
        if execute is None:
            done = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", check=False
            )
        else:
            done = execute(command)
    if done.returncode != 0:
        raise RuntimeError(f"could not comment on {repo}#{pull_request}: {done.stderr}")
