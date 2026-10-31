"""The injected-fault set: mutations are exact, reversible, and leave no trace of the machine."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from mend.data.faults import Mutation, SuiteRun, apply, build, candidates, scrub
from mend.data.faults import Suite as FaultSuite

SOURCE = """\
def clamp(x, low, high):
    if x < low:
        return low
    if x > high and high is not None:
        return high
    return x + 0


FLAG = True
"""


def tree(tmp_path: Path) -> Path:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "core.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_every_operator_finds_its_sites_and_each_mutant_parses(tmp_path: Path) -> None:
    sites = candidates(tree(tmp_path), "src/pkg")
    operators = {m.operator for m in sites}
    assert operators == {"compare", "arithmetic", "boolean", "negate", "constant", "return-none"}
    for m in sites:
        mutated = apply(SOURCE, m)
        assert mutated != SOURCE
        ast.parse(mutated)
    assert sites == candidates(tmp_path, "src/pkg")  # a fixed order, run to run


def test_a_mutation_changes_exactly_its_site(tmp_path: Path) -> None:
    sites = candidates(tree(tmp_path), "src/pkg")
    flip = next(m for m in sites if m.operator == "compare" and m.before == "x < low")
    assert apply(SOURCE, flip).splitlines()[1] == "    if x <= low:"
    assert apply(SOURCE, flip).splitlines()[2:] == SOURCE.splitlines()[2:]


def test_apply_refuses_a_site_that_moved() -> None:
    stale = Mutation("f.py", 2, 7, 2, 14, "compare", "y < low", "y <= low")
    with pytest.raises(ValueError):
        apply(SOURCE, stale)


def test_scrub_takes_the_checkout_and_the_user_out(tmp_path: Path) -> None:
    home = tmp_path / "someone"
    checkout = home / "tmp" / "faults" / "click"
    checkout.mkdir(parents=True)
    sep = os.sep
    text = (
        f'File "{checkout.resolve()}{sep}src{sep}click{sep}core.py", line 3\n'
        f'File "{home}{sep}tmp{sep}faults{sep}click-venv{sep}Lib{sep}site-packages{sep}x.py"\n'
    )
    out = scrub(text, checkout, home=home)
    assert f'File "src{sep}click{sep}core.py"' in out
    assert str(home) not in out and "click-venv" in out


ROOT = Path(__file__).resolve().parent.parent


def test_no_committed_output_names_this_machines_home_folder() -> None:
    """The records are committed, so a path the scrub missed would be published. On CI the
    home folder is the runner's and this passes trivially; it is meant to fail locally."""
    home = str(Path.home())
    forms = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    for folder in ("results", "gate-runs", "docs", "config", "data/subset", "data/duplicates"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".yaml", ".svg"}:
                text = path.read_text(encoding="utf-8")
                assert not any(f in text for f in forms), path.relative_to(ROOT)


def test_build_keeps_faults_by_the_rules_and_hides_the_label(tmp_path: Path) -> None:
    checkout = tree(tmp_path / "co")
    suite = FaultSuite("pkg", "u", "t", "c", "src/pkg")

    def junit(failing: list[str]) -> str:
        cases = "".join(
            f'<testcase classname="tests.test_core" name="{name}">'
            f'<failure message="AssertionError: {name}">Traceback (most recent call last):\n'
            f'  File "tests/test_core.py", line 3, in {name}\nAssertionError: {name}'
            "</failure></testcase>"
            for name in failing
        )
        return f'<testsuite name="pytest">{cases}<testcase classname="a" name="ok"/></testsuite>'

    calls = {"n": 0}

    def runner(co: Path, report: Path) -> SuiteRun:
        calls["n"] += 1
        if calls["n"] == 1:
            return SuiteRun(junit(["test_always_broken"]))
        source = (co / "src/pkg/core.py").read_text(encoding="utf-8")
        if source == SOURCE:
            raise AssertionError("the mutation was not in place while the suite ran")
        width = 1 + calls["n"] % 3
        return SuiteRun(junit(["test_always_broken"] + [f"test_{i}" for i in range(width)]))

    faults, records = build(suite, checkout, runner, faults=3, seed=1, work=tmp_path / "w")
    assert len(faults) == 3 and all(f.failing >= 2 for f in faults)
    assert (checkout / "src/pkg/core.py").read_text(encoding="utf-8") == SOURCE
    assert all(r.test_id and "always_broken" not in r.test_id for r in records)
    for r in records:
        assert r.true_cause and r.true_cause.split(":")[1] not in r.record_id
    assert len({r.captured_at for r in records}) == 1
