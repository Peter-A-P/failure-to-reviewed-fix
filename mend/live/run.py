"""One live run: the failing suite captured, clustered, and the largest tickets triaged.

The pipeline is the one the benchmark measured, unchanged: the same graph, the same rails,
the same calibrated thresholds, a gateway client capped per issue. What is live-specific
is only around it: where the failures come from (the repository's own suite, rerun in the
sandbox), how many tickets one run may spend money on, and the running total.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

from mend.capture.pytest_ingest import ingest_junit_xml
from mend.capture.schema import FailureRecord
from mend.cluster.agglomerate import cluster_records
from mend.cluster.ticket import Ticket, build_tickets
from mend.graph.context import Deps, Issue
from mend.graph.graph import RunRecord, run_issue
from mend.live.budget import Budget, BudgetSpent
from mend.live.comment import Outcome

# The distance mend cluster run cuts at by default. The live tickets are not scored, so
# there is nothing to tune it on here; the measured sets are in docs/clustering.md.
CLUSTER_THRESHOLD = 0.45

# How many tickets one failing run may spend on, largest first. A planted bug is one
# ticket; a run that fails in five unrelated ways gets its largest cluster triaged and the
# rest listed in the summary, rather than five charges against a US$1.50 budget.
MAX_TICKETS = 1


def capture(
    junit: Path, *, repo: str, commit: str, markers: Sequence[str]
) -> tuple[list[FailureRecord], list[Ticket]]:
    records = ingest_junit_xml(junit, repo=repo, commit=commit, project_markers=tuple(markers))
    if not records:
        return records, []
    clustering = cluster_records(records, threshold=CLUSTER_THRESHOLD)
    return records, build_tickets(records, clustering)


def issue_for(ticket: Ticket, run_id: str) -> Issue:
    """The ticket as an issue, named for this workflow run as well as the ticket, so the
    per-issue cap binds per run: the same failure seen again next week is a new issue with
    a new cap, not the remainder of last week's."""
    issue = Issue.from_ticket(ticket)
    return dataclasses.replace(issue, issue_id=f"live-{run_id}-{ticket.ticket_id}")


def triage(
    tickets: Sequence[Ticket],
    *,
    deps: Deps,
    budget: Budget,
    run_id: str,
    run_url: str = "",
    max_tickets: int = MAX_TICKETS,
    log: Callable[[RunRecord], None] = lambda record: None,
    pipeline: Callable[[Issue, Deps], RunRecord] = run_issue,
) -> tuple[list[Outcome], str]:
    """Triage the largest tickets while the budget lasts. Returns the outcomes and a note
    for the summary saying what was not triaged and why."""
    outcomes: list[Outcome] = []
    notes: list[str] = []
    for ticket in tickets[:max_tickets]:
        try:
            budget.check()
        except BudgetSpent as spent:
            notes.append(f"Not triaged: {spent}.")
            break
        record = pipeline(issue_for(ticket, run_id), deps)
        log(record)
        budget.add(record.issue.issue_id, record.cost_usd, run_url=run_url)
        outcomes.append(Outcome.from_record(record))
    skipped = len(tickets) - len(outcomes)
    if skipped > 0 and not notes:
        notes.append(f"{skipped} smaller ticket(s) not triaged: at most {max_tickets} a run.")
    return outcomes, " ".join(notes)
