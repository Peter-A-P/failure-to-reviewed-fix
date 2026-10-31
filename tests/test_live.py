"""The live workflow: it acts only where it runs and only where it is listed, it comments
and does nothing else, its sandbox has no network, and its budget is a total."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from mend.cli import first_pull_request
from mend.gateway import PER_ISSUE_CAP_USD
from mend.graph.act import Proposal, ProposalKind
from mend.graph.context import Deps, Issue
from mend.graph.graph import RunRecord
from mend.graph.machine import IssueState
from mend.graph.route import Tier
from mend.live import budget, image, scope
from mend.live.budget import Budget, BudgetSpent
from mend.live.comment import MARK, Outcome, comment, post, summary
from mend.live.run import capture, triage
from mend.sandbox.runner import RunResult
from mend.sandbox.spec import RunSpec

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "mend" / "live"


def test_it_acts_only_in_the_repository_it_runs_in() -> None:
    gate = "Peter-A-P/ai-release-gate"
    assert scope.check(gate, running_in=gate) == gate
    assert scope.check(gate.lower(), running_in=gate.upper()) == gate
    with pytest.raises(scope.OutOfScope, match="from a workflow running in"):
        scope.check(gate, running_in="Peter-A-P/compliant-ai-gateway")
    with pytest.raises(scope.OutOfScope, match="unset"):
        scope.check(gate, running_in=None)
    with pytest.raises(scope.OutOfScope, match="not one of"):
        scope.check("someone/else", running_in="someone/else")


def test_the_list_is_peters_two_repositories() -> None:
    assert all(r.startswith("Peter-A-P/") for r in scope.REPOSITORIES)
    assert len(scope.REPOSITORIES) == 2


def test_the_budget_is_a_total_and_matches_the_gateway_cap(tmp_path: Path) -> None:
    caps = yaml.safe_load((ROOT / "config" / "live.caps.yaml").read_text(encoding="utf-8"))
    assert caps["projects"]["mend"]["monthly_usd"] == budget.TOTAL_USD
    assert caps["projects"]["mend"]["per_run_usd"] == PER_ISSUE_CAP_USD
    assert budget.TOTAL_USD * len(scope.REPOSITORIES) <= 3.00

    b = Budget(tmp_path / "spent.json")
    assert b.check() == pytest.approx(1.50)
    b.add("i1", 0.40)
    b.add("i2", None)  # unknown cost counts as the most it could have been
    assert b.spent_usd == pytest.approx(1.40)
    b.add("i3", 0.20)
    with pytest.raises(BudgetSpent):
        b.check()


def test_the_live_gateway_answers_nothing_from_cache() -> None:
    config = yaml.safe_load((ROOT / "config" / "live.boundary.yaml").read_text(encoding="utf-8"))
    assert config["cache"]["enabled"] is False
    assert config["caps"] == "live.caps.yaml"
    assert config["routes"] == "mend.routes.yaml"


def test_the_image_installs_and_the_suite_runs_without_network(tmp_path: Path) -> None:
    text = image.dockerfile("uv sync --frozen --all-extras")
    assert "RUN uv sync --frozen --all-extras" in text
    assert "UV_PROJECT_ENVIRONMENT=/venv" in text  # the environment is not in the copy read

    seen: list[RunSpec] = []

    def execute(spec: RunSpec) -> RunResult:
        seen.append(spec)
        (tmp_path / "out" / "report.xml").write_text("<testsuite/>", encoding="utf-8")
        return RunResult(
            exit_code=0, stdout="", stderr="", timed_out=False, duration_s=1.0, args=()
        )

    report = image.run_suite("mend-live:abc", tmp_path / "out", execute=execute)
    assert report.name == "report.xml"
    assert seen[0].is_isolated and "--network=none" in seen[0].docker_args()


def test_the_build_is_the_repositorys_own_install(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "sha256:x", "")

    assert image.build(tmp_path, "uv sync --frozen", "mend-live:abc", execute=execute)
    assert commands[0][:2] == ["docker", "build"] and str(tmp_path) == commands[0][-1]


def test_the_build_keeps_the_tests_whatever_the_repositorys_dockerignore_says(
    tmp_path: Path,
) -> None:
    seen: dict[str, str] = {}

    def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
        dockerfile = Path(command[command.index("-f") + 1])
        seen["ignore"] = (dockerfile.parent / "Dockerfile.dockerignore").read_text("utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    image.build(tmp_path, "uv sync --frozen", "mend-live:abc", execute=execute)
    rules = seen["ignore"].splitlines()
    assert ".env" in rules and ".env.*" in rules
    assert not any(rule.startswith("tests") for rule in rules)


def test_a_suite_that_ran_nothing_is_not_a_pass(tmp_path: Path) -> None:
    empty = tmp_path / "empty.xml"
    empty.write_text(
        '<testsuites><testsuite name="pytest" tests="0" failures="0"/></testsuites>',
        encoding="utf-8",
    )
    assert image.collected(empty) == 0
    ran = tmp_path / "ran.xml"
    ran.write_text(JUNIT, encoding="utf-8")
    assert image.collected(ran) == 3


JUNIT = """<testsuite name="pytest">
<testcase classname="tests.test_core" name="test_a"><failure message="ZeroDivisionError">
Traceback (most recent call last):
  File "gate/core.py", line 3, in ratio
ZeroDivisionError: division by zero</failure></testcase>
<testcase classname="tests.test_core" name="test_b"><failure message="ZeroDivisionError">
Traceback (most recent call last):
  File "gate/core.py", line 3, in ratio
ZeroDivisionError: division by zero</failure></testcase>
<testcase classname="tests.test_core" name="test_ok"/>
</testsuite>"""


def record_for(issue: Issue, tier: Tier | None, cost: float) -> RunRecord:
    from mend.graph.llm import HopRecord

    state = IssueState(issue_id=issue.issue_id, tier=tier.value if tier else None)
    proposal = (
        Proposal(ProposalKind.COMMENT, issue.issue_id, "t", "the fix", tier, 0.5) if tier else None
    )
    hop = HopRecord("draft_patch", "mend-fixer", "anthropic", "m", cost, 1.0, False)
    return RunRecord(issue=issue, state=state, hops=(hop,), proposal=proposal, duration_s=1.0)


def test_one_ticket_a_run_named_for_the_run_and_charged(tmp_path: Path) -> None:
    junit = tmp_path / "report.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    records, tickets = capture(
        junit, repo="Peter-A-P/ai-release-gate", commit="c", markers=("gate/",)
    )
    assert len(records) == 2 and len(tickets) >= 1

    issues: list[Issue] = []

    def pipeline(issue: Issue, deps: Deps) -> RunRecord:
        issues.append(issue)
        return record_for(issue, Tier.SUGGEST, 0.30)

    spent = Budget(tmp_path / "spent.json")
    deps: Any = object()
    outcomes, _ = triage(tickets * 3, deps=deps, budget=spent, run_id="77", pipeline=pipeline)
    assert len(outcomes) == 1 and issues[0].issue_id.startswith("live-77-")
    assert spent.spent_usd == pytest.approx(0.30)


def test_a_spent_budget_runs_nothing(tmp_path: Path) -> None:
    junit = tmp_path / "report.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    _, tickets = capture(junit, repo="r", commit="c", markers=())
    spent = Budget(tmp_path / "spent.json")
    spent.add("before", 1.50)

    def pipeline(issue: Issue, deps: Deps) -> RunRecord:
        raise AssertionError("no model may be called once the budget is spent")

    deps: Any = object()
    outcomes, note = triage(tickets, deps=deps, budget=spent, run_id="1", pipeline=pipeline)
    assert outcomes == [] and "spent" in note


def outcome(tier: Tier | None) -> Outcome:
    return Outcome("i", "ZeroDivisionError", 2, tier, None, 0.3, "the fix" if tier else None)


def test_auto_propose_is_posted_as_a_suggestion_and_quiet_is_not_posted() -> None:
    assert outcome(Tier.SUGGEST).posts and outcome(Tier.AUTO_PROPOSE).posts
    assert not outcome(Tier.QUIET).posts and not outcome(None).posts
    text = comment(outcome(Tier.AUTO_PROPOSE), run_url="u", spent_usd=0.3, cap_usd=1.5)
    assert text.startswith(MARK)
    assert "posts suggestions only" in text and "Nothing has been pushed, opened or merged" in text
    assert "US$0.30 of US$1.50" in text
    assert "| no |" in summary([outcome(Tier.QUIET)], records=2, tickets=1)


def test_posting_is_a_comment_and_nothing_else(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    post("Peter-A-P/ai-release-gate", 12, "body", execute=execute)
    assert commands[0][:4] == ["gh", "pr", "comment", "12"]


def test_no_live_code_opens_pushes_or_merges() -> None:
    for path in LIVE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for fragment in ("pr create", "pr merge", "git push", "/pulls", "/merges", "draft"):
            assert fragment not in text, f"{path.name} contains {fragment!r}"


def test_the_pull_request_number_comes_from_the_event() -> None:
    assert first_pull_request('[{"number": 12, "head": {}}]') == 12
    assert first_pull_request("[]") is None


def workflow(path: Path) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def test_the_workflows_cannot_push_and_skip_forks() -> None:
    called = workflow(ROOT / ".github" / "workflows" / "live.yml")
    assert called["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert "workflow_call" in called[True]  # YAML reads the key "on" as True
    for caller in sorted((ROOT / "action").glob("*.yml")):
        data = workflow(caller)
        assert data["permissions"] == {"contents": "read", "pull-requests": "write"}
        assert "pull_request_target" not in data[True]
        job = data["jobs"]["suggest"]
        assert "head_repository.full_name == github.repository" in job["if"]
        assert "conclusion == 'failure'" in job["if"]
        assert caller.stem in {r.split("/")[1] for r in scope.REPOSITORIES}
