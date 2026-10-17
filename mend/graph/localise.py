"""Hop one: which files is the bug in. The cheap model's job.

Two deterministic passes feed one model call. The traceback's in-project files come first,
because when a failure has a traceback the bug is usually within a frame or two of it. A
keyword pass then finds which source files mention the identifiers the report names. The
model sees both, plus the file listing, and names at most four files. Anything it names
that is not in the repository is dropped rather than trusted.

This is the highest-token, lowest-judgement hop (config/mend.routes.yaml), so it runs on
the small model and reads paths and mentions, not file contents.
"""

from __future__ import annotations

import re

from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Deps, HopOutput, Issue, Scratch, hop_record
from mend.graph.llm import HopFailed
from mend.graph.machine import IssueState, Stage, advance, stop
from mend.graph.parse import tags
from mend.graph.workspace import is_test_file, source_files

MAX_SUSPECTS = 4
_MAX_TERMS = 8
_MAX_HITS_PER_TERM = 10

# Identifiers worth searching for: backticked spans, dotted names, CamelCase and
# snake_case. Plain English words are not, and would match every file.
_TERM_PATTERNS = (
    re.compile(r"`([^`\n]{3,60})`"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b"),
    re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"),
    re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b"),
)


def terms(text: str) -> list[str]:
    """Identifier-like terms from an issue, most specific kinds first, deduplicated."""
    found: list[str] = []
    for pattern in _TERM_PATTERNS:
        for match in pattern.finditer(text):
            term = match.group(1).strip()
            # The last part of a dotted name is what appears in the defining file.
            if "." in term and " " not in term:
                term = term.rsplit(".", 1)[-1]
            if len(term) >= 4 and term not in found:
                found.append(term)
    return found[:_MAX_TERMS]


def keyword_hits(deps: Deps, issue: Issue) -> dict[str, list[str]]:
    """Which source files mention each term. One read per file, not one per term."""
    wanted = terms(issue.title + "\n" + issue.body)
    hits: dict[str, list[str]] = {t: [] for t in wanted}
    if not wanted:
        return hits
    for path in source_files(deps.workspace):
        try:
            text = deps.workspace.read(path)
        except KeyError:
            continue
        for term in wanted:
            if len(hits[term]) < _MAX_HITS_PER_TERM and term in text:
                hits[term].append(path)
    return hits


def localise(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    listing = source_files(deps.workspace)
    known = set(deps.workspace.files())
    frames = tuple(f for f in issue.frame_files if f in known and not is_test_file(f))

    try:
        reply = deps.client.ask(
            Role.LOCALISER,
            issue_id=issue.issue_id,
            system=prompts.LOCALISER_SYSTEM,
            prompt=prompts.localiser_prompt(
                prompts.issue_block(issue.title, issue.body),
                listing,
                frames,
                keyword_hits(deps, issue),
            ),
            max_tokens=1024,
        )
    except HopFailed as exc:
        return HopOutput(stop(state, f"localise: {exc}"), scratch)

    named = [p.strip() for p in tags(reply.text, "file")]
    suspects = tuple(dict.fromkeys(p for p in named if p in known and not is_test_file(p)))[
        :MAX_SUSPECTS
    ]
    if not suspects:
        suspects = frames[:MAX_SUSPECTS]
    hops = (hop_record("localise", Role.LOCALISER, reply),)
    if not suspects:
        reason = "localise: the model named no file that exists in the repository"
        return HopOutput(stop(state, reason), scratch, hops)

    sources = {p: deps.workspace.read(p) for p in suspects}
    return HopOutput(
        advance(state, Stage.LOCALISED, suspect_files=suspects),
        Scratch(sources=sources),
        hops,
    )
