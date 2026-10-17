"""The pipeline end to end, with scripted models and a scripted sandbox.

Each test drives one issue through the real graph, the real hops and the real state
machine, and asserts where it ended and why. The ones that matter most try to get a patch
out of the system without the evidence the design demands, and assert that the fixer was
never even asked.
"""

from __future__ import annotations

import pytest

from mend.gateway import Role
from mend.graph.act import ProposalKind
from mend.graph.context import Deps, Issue
from mend.graph.graph import run_issue
from mend.graph.machine import SameVendorReview, Stage
from mend.graph.route import Thresholds, Tier
from mend.graph.workspace import TestReport
from tests.fakes import Responder, Run, ScriptedClient, ScriptedWorkspace, report

BUGGY = """\
def parse(text):
    key, value = text.split("=")
    return {key: value}
"""

REPO = {
    "pkg/__init__.py": "",
    "pkg/parser.py": BUGGY,
    "pkg/other.py": "def unrelated():\n    return 1\n",
    "tests/test_parser.py": (
        "from pkg.parser import parse\n\n\ndef test_simple():\n"
        "    assert parse('a=b') == {'a': 'b'}\n"
    ),
}

ISSUE = Issue(
    issue_id="demo__pkg-1",
    title="parse() crashes on values containing '='",
    body="Calling `parse` with 'a=b=c' raises ValueError: too many values to unpack.",
    frame_files=("pkg/parser.py",),
)

NEW_TEST = "tests/test_mend_repro.py"
TEST_REPLY = f"""<path>{NEW_TEST}</path>
<test>
from pkg.parser import parse


def test_value_with_equals():
    assert parse("a=b=c") == {{"a": "b=c"}}
</test>"""

PATCH_REPLY = """<edit>
<path>pkg/parser.py</path>
<search>
    key, value = text.split("=")
</search>
<replace>
    key, value = text.split("=", 1)
</replace>
</edit>"""

ACCEPT = "<verdict>accept</verdict><objection>none</objection>"
REJECT = "<verdict>reject</verdict><objection>whitespace around keys is not handled</objection>"

REPRO_ID = f"{NEW_TEST}::test_value_with_equals"
EXISTING_ID = "tests/test_parser.py::test_simple"


def sandbox(*, fails_first: bool = True, fixed: bool = True, regress: bool = False) -> Responder:
    """A sandbox that behaves like the real one on this tiny repository."""

    def respond(run: Run) -> TestReport:
        ids: dict[str, list[str]] = {"passed": [], "failed": [], "errored": []}
        for path in run.test_paths:
            if path == NEW_TEST:
                if not run.diff:
                    ids["failed" if fails_first else "passed"].append(REPRO_ID)
                else:
                    ids["passed" if fixed else "failed"].append(REPRO_ID)
            elif path == "tests/test_parser.py":
                ids["failed" if (run.diff and regress) else "passed"].append(EXISTING_ID)
        return report(
            passed=ids["passed"],
            failed=ids["failed"],
            errored=ids["errored"],
            output="ValueError: too many values to unpack" if ids["failed"] else "ok",
        )

    return respond


def client(**overrides: list[str]) -> ScriptedClient:
    script = {
        Role.LOCALISER: ["<file>pkg/parser.py</file>"],
        Role.TESTER: [TEST_REPLY],
        Role.FIXER: [PATCH_REPLY],
        Role.REVIEWER: [ACCEPT],
    }
    for name, replies in overrides.items():
        script[Role[name.upper()]] = replies
    return ScriptedClient(script)


def deps(c: ScriptedClient, ws: ScriptedWorkspace, thresholds: Thresholds | None = None) -> Deps:
    return Deps(client=c, workspace=ws, thresholds=thresholds)


def test_a_good_patch_goes_all_the_way_but_only_to_suggest_while_uncalibrated() -> None:
    c = client()
    ws = ScriptedWorkspace(dict(REPO), sandbox())
    result = run_issue(ISSUE, deps(c, ws))

    assert result.state.stage is Stage.ACTED
    assert result.state.history == (
        Stage.CAPTURED,
        Stage.CLUSTERED,
        Stage.LOCALISED,
        Stage.TEST_WRITTEN,
        Stage.TEST_FAILED_AS_EXPECTED,
        Stage.PATCHED,
        Stage.REVIEWED,
        Stage.ROUTED,
        Stage.ACTED,
    )
    patch = result.state.patch
    assert patch is not None
    assert patch.test_passes and patch.suite_green
    assert patch.suite_files == ("tests/test_parser.py",)
    assert patch.files_touched == ("pkg/parser.py",)
    assert patch.touches_traceback_frames
    assert 'text.split("=", 1)' in patch.diff
    # Uncalibrated: the score may be high, the tier is not.
    assert result.state.tier == Tier.SUGGEST.value
    assert result.proposal is not None
    assert result.proposal.kind is ProposalKind.COMMENT
    assert "Nothing here merges" in result.proposal.body
    assert c.roles_asked() == [Role.LOCALISER, Role.TESTER, Role.FIXER, Role.REVIEWER]
    assert len(result.hops) == 4 and result.cost_usd == pytest.approx(0.04)


def test_calibrated_thresholds_let_a_strong_patch_become_a_draft_pull_request() -> None:
    thresholds = Thresholds(
        auto_propose=0.6, suggest=0.35, target_confidently_wrong=0.03, calibrated_on="validation"
    )
    result = run_issue(ISSUE, deps(client(), ScriptedWorkspace(dict(REPO), sandbox()), thresholds))
    assert result.state.tier == Tier.AUTO_PROPOSE.value
    assert result.proposal is not None
    assert result.proposal.kind is ProposalKind.DRAFT_PULL_REQUEST


def test_the_new_test_runs_alone_on_the_broken_commit_first() -> None:
    ws = ScriptedWorkspace(dict(REPO), sandbox())
    run_issue(ISSUE, deps(client(), ws))
    first = ws.runs[0]
    assert first.test_paths == (NEW_TEST,)
    assert first.diff == ""
    assert NEW_TEST in first.new_files


def test_a_test_that_passes_on_the_broken_commit_never_reaches_the_fixer() -> None:
    """The rule the design rests on, through the real graph: two tests that demonstrate
    nothing, and the fixer is never asked."""
    c = client(tester=[TEST_REPLY, TEST_REPLY])
    ws = ScriptedWorkspace(dict(REPO), sandbox(fails_first=False))
    result = run_issue(ISSUE, deps(c, ws))

    assert result.state.stage is Stage.STOPPED
    assert "no test failed on the broken commit" in (result.state.stop_reason or "")
    assert Role.FIXER not in c.roles_asked()
    assert c.roles_asked().count(Role.TESTER) == 2
    assert result.state.patch is None


def test_the_tester_retry_is_told_why_its_first_test_was_useless() -> None:
    calls = {"n": 0}

    def respond(run: Run) -> TestReport:
        if run.diff == "" and run.test_paths == (NEW_TEST,):
            calls["n"] += 1
            if calls["n"] == 1:
                return report(passed=[REPRO_ID])
        return sandbox()(run)

    c = client(tester=[TEST_REPLY, TEST_REPLY])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), respond)))
    assert result.state.stage is Stage.ACTED
    second = [a for a in c.asked if a.role is Role.TESTER][1]
    assert "passed on the current code" in second.prompt


def test_a_test_that_errors_is_not_a_failing_test() -> None:
    def respond(run: Run) -> TestReport:
        return report(errored=[f"{NEW_TEST}::"], output="ImportError: cannot import name")

    c = client(tester=[TEST_REPLY, TEST_REPLY])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), respond)))
    assert result.state.stage is Stage.STOPPED
    assert "errored" in (result.state.stop_reason or "")
    assert Role.FIXER not in c.roles_asked()


def test_a_test_path_that_already_exists_is_refused_before_anything_runs() -> None:
    clash = TEST_REPLY.replace(NEW_TEST, "tests/test_parser.py")
    ws = ScriptedWorkspace(dict(REPO), sandbox())
    result = run_issue(ISSUE, deps(client(tester=[clash, clash]), ws))
    assert result.state.stage is Stage.STOPPED
    assert "already exists" in (result.state.stop_reason or "")
    assert ws.runs == []


def test_a_patch_that_edits_the_test_is_refused() -> None:
    cheat = """<edit><path>tests/test_parser.py</path>
<search>
    assert parse('a=b') == {'a': 'b'}
</search>
<replace>
    pass
</replace></edit>"""
    c = client(fixer=[cheat, cheat])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert result.state.stage is Stage.STOPPED
    assert "tests may not change" in (result.state.stop_reason or "")


def test_a_patch_that_does_not_fix_the_test_stops_after_one_retry() -> None:
    c = client(fixer=[PATCH_REPLY, PATCH_REPLY])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox(fixed=False))))
    assert result.state.stage is Stage.STOPPED
    assert "still does not pass" in (result.state.stop_reason or "")
    assert c.roles_asked().count(Role.FIXER) == 2
    assert Role.REVIEWER not in c.roles_asked()


def test_a_regression_keeps_the_patch_quiet() -> None:
    c = client(fixer=[PATCH_REPLY, PATCH_REPLY])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox(regress=True))))
    assert result.state.stage is Stage.ACTED
    assert result.state.patch is not None and not result.state.patch.suite_green
    assert result.state.tier == Tier.QUIET.value
    assert result.proposal is not None and result.proposal.kind is ProposalKind.LOG
    second = [a for a in c.asked if a.role is Role.FIXER][1]
    assert EXISTING_ID in second.prompt


def test_a_reviewer_who_objects_caps_the_tier_and_is_quoted() -> None:
    thresholds = Thresholds(
        auto_propose=0.5, suggest=0.35, target_confidently_wrong=0.03, calibrated_on="validation"
    )
    c = client(reviewer=[REJECT])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox()), thresholds))
    assert result.state.tier == Tier.SUGGEST.value
    assert result.proposal is not None
    assert "whitespace around keys" in result.proposal.body


def test_a_same_vendor_review_is_a_rail_violation_not_a_stop() -> None:
    c = client()
    c.providers[Role.REVIEWER] = "anthropic"
    with pytest.raises(SameVendorReview):
        run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))


def test_the_spend_cap_stops_the_issue_and_says_so() -> None:
    c = client()
    c.budget_calls = 2
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert result.state.stage is Stage.STOPPED
    assert "spend cap" in (result.state.stop_reason or "")
    assert Role.FIXER not in c.roles_asked()


def test_localisation_naming_nothing_real_falls_back_to_the_traceback() -> None:
    c = client(localiser=["<file>does/not/exist.py</file>"])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert result.state.suspect_files == ("pkg/parser.py",)


def test_localisation_with_nothing_to_go_on_stops() -> None:
    issue = Issue(issue_id="x", title="it broke", body="something is wrong")
    c = client(localiser=["<file>nowhere.py</file>"])
    result = run_issue(issue, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert result.state.stage is Stage.STOPPED
    assert "named no file" in (result.state.stop_reason or "")


def test_an_unreadable_verdict_is_retried_then_stops_rather_than_guessed() -> None:
    c = client(reviewer=["looks fine to me", "<verdict>maybe</verdict>"])
    result = run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert result.state.stage is Stage.STOPPED
    assert result.state.review is None
    assert "verdict could not be read" in (result.state.stop_reason or "")


def test_every_call_names_the_issue_so_the_cap_can_bind() -> None:
    c = client()
    run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    assert {a.issue_id for a in c.asked} == {ISSUE.issue_id}


def test_issue_text_goes_in_the_user_turn_never_the_system_prompt() -> None:
    c = client()
    run_issue(ISSUE, deps(c, ScriptedWorkspace(dict(REPO), sandbox())))
    for asked in c.asked:
        assert ISSUE.body not in asked.system
        assert ISSUE.body in asked.prompt


def test_the_run_record_serialises_whole() -> None:
    import json

    result = run_issue(ISSUE, deps(client(), ScriptedWorkspace(dict(REPO), sandbox())))
    payload = json.loads(result.to_json())
    assert payload["state"]["stage"] == "acted"
    assert payload["proposal"]["kind"] == "comment"
    assert [h["hop"] for h in payload["hops"]] == [
        "localise",
        "write_test",
        "draft_patch",
        "review",
    ]
    assert payload["cost_usd"] == pytest.approx(0.04)
