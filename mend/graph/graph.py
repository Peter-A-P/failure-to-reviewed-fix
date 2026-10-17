"""The pipeline as a LangGraph graph: intake, localise, test, patch, review, route, act.

The graph is wiring and nothing else. Every hop is a function in its own module that takes
the issue, the state and the working material and returns new ones, and every move of the
state goes through mend.graph.machine.advance, which is where the rails are. A stopped
issue goes straight to the end from whichever hop stopped it.

There is no node after act, and no node, edge or tier that merges, pushes or applies
anything (tests/test_no_merge_path.py scans this file with the rest).
"""

from __future__ import annotations

import json
import operator
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from mend.graph.act import Proposal, act, route_issue
from mend.graph.context import Deps, HopOutput, Issue, Scratch
from mend.graph.llm import HopRecord
from mend.graph.localise import localise
from mend.graph.machine import IssueState, Stage, advance
from mend.graph.patch import draft_patch
from mend.graph.review import review
from mend.graph.test_first import write_test


class PipelineState(TypedDict):
    issue: Issue
    state: IssueState
    scratch: Scratch
    hops: Annotated[list[HopRecord], operator.add]
    proposal: Proposal | None


Hop = Callable[[Issue, IssueState, Scratch, Deps], HopOutput]

# The order of the pipeline, by node name. Each node hands on to the next unless the
# issue stopped.
_ORDER = ("intake", "localise", "write_test", "draft_patch", "review", "route", "act")


def _intake(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    """An issue arrives already clustered: a benchmark task is a cluster of one, and a
    captured ticket is the cluster. Recorded as a stage so the history says so."""
    return HopOutput(advance(state, Stage.CLUSTERED, ticket_id=issue.issue_id), scratch)


def _node(hop: Hop, deps: Deps) -> Callable[[PipelineState], Any]:
    def run(ps: PipelineState) -> dict[str, Any]:
        out = hop(ps["issue"], ps["state"], ps["scratch"], deps)
        return {"state": out.state, "scratch": out.scratch, "hops": list(out.hops)}

    return run


def _act_node(deps: Deps) -> Callable[[PipelineState], Any]:
    def run(ps: PipelineState) -> dict[str, Any]:
        out, proposal = act(ps["issue"], ps["state"], ps["scratch"], deps)
        return {"state": out.state, "scratch": out.scratch, "proposal": proposal}

    return run


def _next(after: str) -> Callable[[PipelineState], str]:
    following = _ORDER[_ORDER.index(after) + 1]

    def choose(ps: PipelineState) -> str:
        return END if ps["state"].stage is Stage.STOPPED else following

    return choose


def build(deps: Deps) -> Any:
    """The compiled graph for one set of dependencies. Typed Any because LangGraph's
    compiled-graph generics say nothing a caller here can use."""
    hops: dict[str, Hop] = {
        "intake": _intake,
        "localise": localise,
        "write_test": write_test,
        "draft_patch": draft_patch,
        "review": review,
        "route": route_issue,
    }
    graph = StateGraph(PipelineState)
    for name, hop in hops.items():
        # cast: LangGraph types a node as a protocol whose parameter is named "state", and
        # mypy will not match a plain Callable against a parameter that has a name.
        graph.add_node(name, cast(Any, _node(hop, deps)))
    graph.add_node("act", cast(Any, _act_node(deps)))
    graph.add_edge(START, "intake")
    for name in _ORDER[:-1]:
        graph.add_conditional_edges(name, _next(name), [_ORDER[_ORDER.index(name) + 1], END])
    graph.add_edge("act", END)
    return graph.compile()


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Everything one issue produced, for the run log and for mend.eval.results."""

    issue: Issue
    state: IssueState
    hops: tuple[HopRecord, ...]
    proposal: Proposal | None
    duration_s: float

    @property
    def cost_usd(self) -> float | None:
        """Summed from the replies. The ledger is the reported figure (PLAN.md section
        2.6); this is the run log's view of the same calls, for a quick look."""
        costs = [h.cost_usd for h in self.hops]
        return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)

    def to_json(self) -> str:
        """One line of the run log. Everything on the record, nothing summarised away."""
        payload = asdict(self)
        payload["cost_usd"] = self.cost_usd
        return json.dumps(payload, sort_keys=True)


def run_issue(issue: Issue, deps: Deps) -> RunRecord:
    """One issue through the whole pipeline."""
    started = time.monotonic()
    initial: PipelineState = {
        "issue": issue,
        "state": IssueState(issue_id=issue.issue_id),
        "scratch": Scratch(),
        "hops": [],
        "proposal": None,
    }
    final = build(deps).invoke(initial)
    return RunRecord(
        issue=issue,
        state=final["state"],
        hops=tuple(final["hops"]),
        proposal=final["proposal"],
        duration_s=time.monotonic() - started,
    )
