"""What the hops may do to a repository: read it, and run tests in the sandbox.

The hops never touch a container or a filesystem directly. They are given a Workspace,
which can do three things: list the repository's files, read one, and run a set of tests
against the broken commit with a diff and some new files applied. Reading is the only
thing that happens on the host; running always happens somewhere that is not the host.
The Docker implementation is mend.sandbox.workspace.DockerWorkspace. The tests use a
scripted one that runs nothing.

There is deliberately no host-side implementation that runs tests. A model-written test
executed on the laptop is model-written code executed with the laptop's network and the
laptop's credentials (mend/sandbox/spec.py), and the way to make sure that never happens
is for no such code path to exist.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar, Protocol
from xml.etree import ElementTree

# How much test output is kept on a report. Enough for a model to see the assertion that
# failed and the frames above it; past this it is the same traceback repeated.
_MAX_OUTPUT_CHARS = 6000


@dataclass(frozen=True, slots=True)
class TestReport:
    """One run of some tests, by outcome.

    errored holds tests that broke in setup, teardown or collection rather than in the
    test body. The distinction carries the test-first rule: a generated test that fails
    demonstrates something about the code, and one that errors demonstrates only that it
    is broken itself (mend.graph.machine.TestAttempt).
    """

    __test__: ClassVar[bool] = False

    passed: frozenset[str] = frozenset()
    failed: frozenset[str] = frozenset()
    errored: frozenset[str] = frozenset()
    skipped: frozenset[str] = frozenset()
    timed_out: bool = False
    output: str = ""

    @property
    def ran(self) -> bool:
        """Something was collected and run to the end."""
        return not self.timed_out and bool(self.passed or self.failed or self.errored)

    @property
    def failed_cleanly(self) -> bool:
        """At least one test failed in its body and nothing errored.

        What a demonstrating test has to do on the broken commit.
        """
        return self.ran and bool(self.failed) and not self.errored

    @property
    def all_passed(self) -> bool:
        return self.ran and bool(self.passed) and not self.failed and not self.errored


class Workspace(Protocol):
    """One task's repository at its broken commit.

    test_style says what kind of test file the repository's own runner picks up (a pytest
    module, a Django TestCase module, a sympy test module), for the tester's prompt.
    """

    @property
    def test_style(self) -> str: ...

    def files(self) -> tuple[str, ...]:
        """Every tracked file, as repository-relative POSIX paths."""
        ...

    def read(self, path: str) -> str:
        """One file's text. Raises KeyError for a path that is not in files()."""
        ...

    def run_tests(
        self,
        test_paths: Sequence[str],
        *,
        diff: str = "",
        new_files: Mapping[str, str] | None = None,
    ) -> TestReport:
        """Run the named test files in the sandbox, on the broken commit plus the diff
        and the new files. Never on the host."""
        ...


def parse_junit(xml_text: str, *, output: str = "", timed_out: bool = False) -> TestReport:
    """A TestReport from pytest's JUnit XML.

    A test id is file::name when the report carries the file, classname.name otherwise,
    matching mend.capture.pytest_ingest so that a sandbox run and a CI run name the same
    test the same way.
    """
    if not xml_text.strip():
        return TestReport(timed_out=timed_out, output=_clip(output))
    root = ElementTree.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    passed: set[str] = set()
    failed: set[str] = set()
    errored: set[str] = set()
    skipped: set[str] = set()
    for suite in suites:
        for case in suite.iter("testcase"):
            file_attr = case.get("file")
            name = case.get("name", "")
            classname = case.get("classname", "")
            test_id = f"{file_attr}::{name}" if file_attr else f"{classname}.{name}".strip(".")
            if case.find("error") is not None:
                errored.add(test_id)
            elif case.find("failure") is not None:
                failed.add(test_id)
            elif case.find("skipped") is not None:
                skipped.add(test_id)
            else:
                passed.add(test_id)
    # A collection error is reported by pytest as a testcase with an empty name and an
    # <error>; it lands in errored above, which is where it belongs.
    return TestReport(
        passed=frozenset(passed),
        failed=frozenset(failed),
        errored=frozenset(errored),
        skipped=frozenset(skipped),
        timed_out=timed_out,
        output=_clip(output),
    )


def _clip(text: str) -> str:
    """Keep the tail: pytest puts the short summary and the failing assertion last."""
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return "[earlier output cut]\n" + text[-_MAX_OUTPUT_CHARS:]


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path.endswith(".py") and (
        name.startswith("test_") or name.endswith("_test.py") or name == "tests.py"
    )


def source_files(workspace: Workspace) -> tuple[str, ...]:
    """The Python files a fix could live in: not tests, not docs, not build scaffolding."""
    out = []
    for path in workspace.files():
        if not path.endswith(".py") or is_test_file(path):
            continue
        parts = PurePosixPath(path).parts
        if any(p in {"tests", "test", "testing", "docs", "doc", "examples"} for p in parts[:-1]):
            continue
        out.append(path)
    return tuple(out)


def module_name(path: str) -> str:
    """pkg/sub/mod.py to pkg.sub.mod; a package's __init__.py to the package. Leading
    src/ and lib/ layout directories are dropped, since they are not part of the import."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"}:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def related_tests(
    workspace: Workspace, touched: Sequence[str], *, limit: int = 5
) -> tuple[str, ...]:
    """Existing test files that exercise the touched modules, for the regression check.

    Two signals, in order. A test file named for the module (test_mod.py, mod_test.py)
    comes first. Then any test file that imports the module by its dotted name. Nothing
    here reads the benchmark's hidden tests: these are files that exist at the broken
    commit, found by name and by import, which is what an engineer would run before
    pushing.
    """
    tests = [p for p in workspace.files() if is_test_file(p)]
    chosen: list[str] = []

    def add(path: str) -> None:
        if path not in chosen and len(chosen) < limit:
            chosen.append(path)

    stems = {PurePosixPath(p).stem for p in touched if not is_test_file(p)}
    for path in tests:
        name = PurePosixPath(path).stem
        if any(name in (f"test_{s}", f"{s}_test") for s in stems if s != "__init__"):
            add(path)

    modules = [module_name(p) for p in touched if not is_test_file(p)]
    patterns = [
        re.compile(rf"(?:^|\s)(?:from\s+{re.escape(m)}\s+import|import\s+{re.escape(m)}\b)", re.M)
        for m in modules
        if m
    ]
    if patterns:
        for path in tests:
            if len(chosen) >= limit:
                break
            if path in chosen:
                continue
            try:
                text = workspace.read(path)
            except KeyError:
                continue
            if any(p.search(text) for p in patterns):
                add(path)
    return tuple(chosen)


def search(workspace: Workspace, needle: str, *, limit: int = 20) -> list[str]:
    """Source files containing a literal string, for localisation's keyword pass."""
    hits: list[str] = []
    if not needle:
        return hits
    for path in source_files(workspace):
        if len(hits) >= limit:
            break
        try:
            if needle in workspace.read(path):
                hits.append(path)
        except KeyError:
            continue
    return hits
