"""How each benchmark repository runs its own tests, and how its output is read.

SWE-bench Verified is 46% Django and 15% sympy, and neither runs its suite with pytest:
Django has tests/runtests.py and sympy has bin/test. A sandbox that only knew pytest would
fail the test-first hop on most of the benchmark for reasons that have nothing to do with
the bug, so each repository gets the command its own contributing guide documents.

The commands are written here, from those projects' public documentation, and not taken
from the benchmark. The harness keeps each task's test command inside its eval_script,
next to the hidden test patch, and mend reads no part of that field (mend.data.swebench).

Output is read with the harness's own log parsers where the runner is not pytest, so that
a test the sandbox calls passed is a test the harness would call passed. pytest runs keep
writing JUnit XML, which carries the file on every case. The parsers come from the bench
extra and are imported only when a non-pytest runner is used.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from mend.graph.workspace import TestReport, parse_junit

JUNIT_PATH = "/mend/out/report.xml"


def _pytest_command(paths: Sequence[str]) -> str:
    parts = [
        "python",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={JUNIT_PATH}",
        "-rA",
        *paths,
    ]
    return " ".join(shlex.quote(p) for p in parts)


def django_label(path: str) -> str:
    """tests/admin_views/test_x.py to admin_views.test_x, which is how runtests.py names a
    test module. Django's own tests live under tests/; a path outside it is passed as a
    dotted module path, which runtests.py also accepts."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "tests":
        parts = parts[1:]
    return ".".join(parts)


def _django_command(paths: Sequence[str]) -> str:
    labels = [django_label(p) for p in paths]
    parts = [
        "./tests/runtests.py",
        "--verbosity",
        "2",
        "--settings=test_sqlite",
        "--parallel",
        "1",
        *labels,
    ]
    return " ".join(shlex.quote(p) for p in parts)


def _sympy_command(paths: Sequence[str]) -> str:
    parts = ["bin/test", "-C", "--verbose", *paths]
    return " ".join(shlex.quote(p) for p in parts)


_STATUS = {
    "PASSED": "passed",
    "FAILED": "failed",
    "ERROR": "errored",
    "SKIPPED": "skipped",
    "XFAIL": "skipped",
}


def from_statuses(statuses: Mapping[str, str], *, output: str, timed_out: bool) -> TestReport:
    """A TestReport from a harness parser's {test: status} map."""
    groups: dict[str, set[str]] = {
        "passed": set(),
        "failed": set(),
        "errored": set(),
        "skipped": set(),
    }
    for test, status in statuses.items():
        groups[_STATUS.get(str(status).upper(), "errored")].add(test)
    return TestReport(
        passed=frozenset(groups["passed"]),
        failed=frozenset(groups["failed"]),
        errored=frozenset(groups["errored"]),
        skipped=frozenset(groups["skipped"]),
        timed_out=timed_out,
        output=output[-6000:],
    )


def _harness_parser(name: str) -> Callable[[str], Mapping[str, str]]:
    def parse(log: str) -> Mapping[str, str]:
        from swebench.harness.log_parsers import python as parsers

        result: Mapping[str, str] = getattr(parsers, name)(log, None)
        return result

    return parse


@dataclass(frozen=True, slots=True)
class TestRunner:
    """One repository's test command, and how its result is read."""

    __test__: ClassVar[bool] = False

    name: str
    command: Callable[[Sequence[str]], str]
    log_parser: Callable[[str], Mapping[str, str]] | None = None
    # What the tester is told about the framework, so it writes a test the runner finds.
    style: str = "a pytest test module"

    def report(self, output: str, junit_xml: str, *, timed_out: bool) -> TestReport:
        if self.log_parser is None:
            return parse_junit(junit_xml, output=output, timed_out=timed_out)
        return from_statuses(self.log_parser(output), output=output, timed_out=timed_out)


PYTEST = TestRunner(name="pytest", command=_pytest_command)
DJANGO = TestRunner(
    name="django",
    command=_django_command,
    log_parser=_harness_parser("parse_log_django"),
    style=(
        "a Django test module under tests/<app>/, with unittest-style classes "
        "(django.test.SimpleTestCase or TestCase); it is run by tests/runtests.py"
    ),
)
SYMPY = TestRunner(
    name="sympy",
    command=_sympy_command,
    log_parser=_harness_parser("parse_log_sympy"),
    style="a sympy test module of plain test_ functions with assert, run by bin/test",
)

_BY_REPO = {"django/django": DJANGO, "sympy/sympy": SYMPY}


def runner_for(repo: str | None) -> TestRunner:
    return _BY_REPO.get(repo or "", PYTEST)
