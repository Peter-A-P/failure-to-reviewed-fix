"""What every hop is given, and what it hands on.

Issue is the input: one ticket's worth of text and evidence, from a benchmark task or from
a cluster of captured failures. Deps is what the hops may use: a model client, a
workspace and the routing thresholds. Scratch is what one hop leaves for the next (the
files read, the test written, the outputs seen), kept apart from IssueState because the
state machine judges evidence and Scratch is working material.

All three are immutable. A hop returns a new Scratch rather than writing into one, for the
reason IssueState is immutable: the question "what did the reviewer see" should not depend
on when it is asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mend.cluster.ticket import Ticket
from mend.data.swebench import Task
from mend.gateway import Role
from mend.graph.llm import HopRecord, ModelClient, Reply
from mend.graph.machine import IssueState
from mend.graph.route import Thresholds
from mend.graph.workspace import TestReport, Workspace


@dataclass(frozen=True, slots=True)
class Issue:
    """One thing to fix, as text a model can read and evidence the router can weigh.

    frame_files are the in-project files the failure's tracebacks pass through, which is
    the routing signal "the patch touches the frames in the traceback" (PLAN.md section
    2.5). A benchmark task has none: its problem statement is prose, and pulling paths out
    of prose would be guessing.
    """

    issue_id: str
    title: str
    body: str
    frame_files: tuple[str, ...] = ()
    cluster_size: int = 1
    repo: str | None = None
    commit: str | None = None

    @classmethod
    def from_task(cls, task: Task) -> Issue:
        """A SWE-bench task. Task carries no hidden test, gold patch or test directive
        (mend.data.swebench), so nothing built from it can show a model one."""
        first_line = (
            task.problem_statement.strip().splitlines()[0] if task.problem_statement else ""
        )
        return cls(
            issue_id=task.instance_id,
            title=first_line[:120] or task.instance_id,
            body=task.problem_statement,
            repo=task.repo,
            commit=task.base_commit,
        )

    @classmethod
    def from_ticket(cls, ticket: Ticket) -> Issue:
        """A cluster of captured failures: the medoid's text and the outliers' tracebacks."""
        parts = []
        for i, record in enumerate(ticket.representatives, start=1):
            lines = [f"Symptom {i}"]
            if record.test_id:
                lines.append(f"test: {record.test_id}")
            if record.title:
                lines.append(f"title: {record.title}")
            if record.body:
                lines.append(record.body.strip())
            if record.traceback_text:
                lines.append(record.traceback_text.strip())
            elif record.exception_type:
                lines.append(f"{record.exception_type}: {record.message or ''}".strip())
            if record.logs:
                lines.append("logs:\n" + "\n".join(record.logs[-10:]))
            parts.append("\n".join(lines))
        header = f"{ticket.size} captured symptoms clustered into this ticket."
        return cls(
            issue_id=ticket.ticket_id,
            title=ticket.title(),
            body=header + "\n\n" + "\n\n".join(parts),
            frame_files=ticket.suspect_files,
            cluster_size=ticket.size,
            repo=ticket.repo,
            commit=ticket.commit,
        )


@dataclass(frozen=True, slots=True)
class Deps:
    """What the hops may use. thresholds None means uncalibrated, and then nothing
    auto-proposes: the router caps every issue at SUGGEST until a validation split exists.

    max_attempts counts the first try, and is the one retry PLAN.md section 6 budgets for
    on the two hops where a retry has new information to work with: the tester sees why
    its test did not fail, and the fixer sees why its patch did not pass.
    """

    client: ModelClient
    workspace: Workspace
    thresholds: Thresholds | None = None
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class Scratch:
    """Working material carried between hops."""

    sources: dict[str, str] = field(default_factory=dict)
    test_path: str | None = None
    test_source: str | None = None
    test_report: TestReport | None = None
    baseline: TestReport | None = None
    patched: TestReport | None = None
    fixer_provider: str | None = None
    objection: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HopOutput:
    """What a hop returns: the next state, the working material, and what it spent."""

    state: IssueState
    scratch: Scratch
    hops: tuple[HopRecord, ...] = ()


def hop_record(hop: str, role: Role, reply: Reply) -> HopRecord:
    return HopRecord(
        hop=hop,
        role=role.value,
        provider=reply.provider,
        model=reply.model,
        cost_usd=reply.cost_usd,
        latency_ms=reply.latency_ms,
        cached=reply.cached,
    )
