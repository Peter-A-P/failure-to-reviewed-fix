"""Hop four: a model from another vendor tries to break the patch.

The reviewer sees what a human reviewer would: the issue, the test, its output before and
after, the diff, and which existing tests were run. It is told to find the reason the patch
is wrong, and to accept only having looked. A reject does not stop the issue; it caps the
tier at SUGGEST (mend.graph.route), so a person sees the patch with the objection beside it.

The verdict carries the providers that actually answered, read off the replies rather than
the configuration, and the state machine refuses REVIEWED when they match. So the
different-vendor rule is checked three times: in the shipped configuration by a test, at
start-up against what the gateway resolves, and here against what really happened.

An unreadable verdict gets one retry. A second one stops the issue rather than being read
as either answer, since guessing a verdict is the one thing a reviewer must not have done
on its behalf.
"""

from __future__ import annotations

from dataclasses import replace

from mend.gateway import Role
from mend.graph import prompts
from mend.graph.context import Deps, HopOutput, Issue, Scratch, hop_record
from mend.graph.llm import HopFailed, HopRecord
from mend.graph.machine import IssueState, ReviewVerdict, Stage, advance, stop
from mend.graph.parse import MalformedReply, one_tag

# Reasoning models count their thinking against this limit, and a review that thinks
# for 4,000 tokens and then has none left to answer in is a wasted call.
REVIEW_MAX_TOKENS = 16_000


def parse_verdict(text: str) -> tuple[bool, str]:
    verdict = one_tag(text, "verdict").strip().lower()
    if verdict not in {"accept", "reject"}:
        raise MalformedReply(f"<verdict> must be accept or reject, not {verdict!r}")
    try:
        objection = one_tag(text, "objection").strip()
    except MalformedReply:
        objection = ""
    if objection.lower() == "none":
        objection = ""
    return verdict == "accept", objection


def review(issue: Issue, state: IssueState, scratch: Scratch, deps: Deps) -> HopOutput:
    patch = state.patch
    test = state.test
    if patch is None or test is None or scratch.fixer_provider is None:
        raise RuntimeError("review reached without a patch, a test and the fixer's provider")
    prompt = prompts.reviewer_prompt(
        prompts.issue_block(issue.title, issue.body),
        test.test_id,
        test.source,
        test.output,
        patch.diff,
        scratch.patched.output if scratch.patched is not None else "",
        patch.suite_files,
    )
    hops: list[HopRecord] = []
    problem = ""
    for _ in range(2):
        try:
            reply = deps.client.ask(
                Role.REVIEWER,
                issue_id=issue.issue_id,
                system=prompts.REVIEWER_SYSTEM,
                prompt=prompt
                + (f"\n\nYour previous reply could not be read: {problem}" if problem else ""),
                max_tokens=REVIEW_MAX_TOKENS,
            )
        except HopFailed as exc:
            return HopOutput(stop(state, f"review: {exc}"), scratch, tuple(hops))
        hops.append(hop_record("review", Role.REVIEWER, reply))
        try:
            agrees, objection = parse_verdict(reply.text)
        except MalformedReply as exc:
            problem = str(exc)
            continue
        verdict = ReviewVerdict(
            reviewer_provider=reply.provider,
            fixer_provider=scratch.fixer_provider,
            agrees=agrees,
            objection=objection,
        )
        return HopOutput(
            advance(state, Stage.REVIEWED, review=verdict),
            replace(scratch, objection=objection),
            tuple(hops),
        )
    return HopOutput(
        stop(state, f"review: the verdict could not be read ({problem})"), scratch, tuple(hops)
    )
