"""Scripted stand-ins for the model client and the workspace. Nothing here runs anything.

ScriptedClient answers each role from its own queue and records every question, so a test
can assert both what the pipeline did and what it never asked (no fixer call without a
failing test). ScriptedWorkspace serves files from a dict and answers run_tests from a
function of what was asked, which is the whole of what the hops can observe.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from mend.gateway import Role
from mend.graph.llm import BudgetExhausted, Reply
from mend.graph.workspace import TestReport

PROVIDERS = {
    Role.LOCALISER: "anthropic",
    Role.TESTER: "anthropic",
    Role.FIXER: "anthropic",
    Role.REVIEWER: "openai",
    Role.SELF_REVIEWER: "anthropic",
}


@dataclass
class Asked:
    role: Role
    issue_id: str
    system: str
    prompt: str


@dataclass
class ScriptedClient:
    script: dict[Role, list[str]]
    providers: dict[Role, str] = field(default_factory=lambda: dict(PROVIDERS))
    budget_calls: int | None = None
    asked: list[Asked] = field(default_factory=list)

    def ask(
        self,
        role: Role,
        *,
        issue_id: str,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> Reply:
        if self.budget_calls is not None and len(self.asked) >= self.budget_calls:
            raise BudgetExhausted("spend cap 'per_run' of US$1.00 would be exceeded")
        self.asked.append(Asked(role, issue_id, system, prompt))
        queue = self.script.get(role, [])
        if not queue:
            raise AssertionError(f"no scripted reply left for {role.name}")
        return Reply(
            text=queue.pop(0),
            provider=self.providers[role],
            model=f"{role.value}-model",
            cost_usd=0.01,
            latency_ms=5.0,
        )

    def roles_asked(self) -> list[Role]:
        return [a.role for a in self.asked]


@dataclass(frozen=True)
class Run:
    test_paths: tuple[str, ...]
    diff: str
    new_files: dict[str, str]


Responder = Callable[[Run], TestReport]


@dataclass
class ScriptedWorkspace:
    contents: dict[str, str]
    respond: Responder
    runs: list[Run] = field(default_factory=list)
    test_style: str = "a pytest test module"

    def files(self) -> tuple[str, ...]:
        return tuple(sorted(self.contents))

    def read(self, path: str) -> str:
        return self.contents[path]

    def run_tests(
        self,
        test_paths: Sequence[str],
        *,
        diff: str = "",
        new_files: Mapping[str, str] | None = None,
    ) -> TestReport:
        run = Run(tuple(test_paths), diff, dict(new_files or {}))
        self.runs.append(run)
        return self.respond(run)


def report(
    passed: Sequence[str] = (),
    failed: Sequence[str] = (),
    errored: Sequence[str] = (),
    output: str = "",
) -> TestReport:
    return TestReport(
        passed=frozenset(passed),
        failed=frozenset(failed),
        errored=frozenset(errored),
        output=output,
    )
