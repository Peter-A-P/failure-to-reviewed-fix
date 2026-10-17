"""Per-repository test runners: the command each one builds, and how its output is read."""

from __future__ import annotations

import pytest

from mend.sandbox.runners import (
    DJANGO,
    PYTEST,
    SYMPY,
    django_label,
    from_statuses,
    runner_for,
)


def test_each_benchmark_repository_gets_its_own_runner() -> None:
    assert runner_for("django/django") is DJANGO
    assert runner_for("sympy/sympy") is SYMPY
    assert runner_for("astropy/astropy") is PYTEST
    assert runner_for(None) is PYTEST


def test_django_labels_are_dotted_paths_under_tests() -> None:
    assert django_label("tests/admin_views/test_mend_repro.py") == "admin_views.test_mend_repro"
    assert DJANGO.command(["tests/queries/test_q.py"]) == (
        "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 queries.test_q"
    )


def test_sympy_and_pytest_commands_name_the_files() -> None:
    assert SYMPY.command(["sympy/core/tests/test_x.py"]) == (
        "bin/test -C --verbose sympy/core/tests/test_x.py"
    )
    assert "--junitxml=/mend/out/report.xml" in PYTEST.command(["tests/test_a.py"])


def test_statuses_map_onto_a_report() -> None:
    report = from_statuses(
        {"a": "PASSED", "b": "FAILED", "c": "ERROR", "d": "SKIPPED", "e": "XFAIL"},
        output="log",
        timed_out=False,
    )
    assert report.passed == {"a"} and report.failed == {"b"} and report.errored == {"c"}
    assert report.skipped == {"d", "e"}


DJANGO_LOG = """\
Testing against Django installed in '/testbed/django'
test_ok (queries.test_q.QTests) ... ok
test_bug (queries.test_q.QTests) ... FAIL

======================================================================
FAIL: test_bug (queries.test_q.QTests)
----------------------------------------------------------------------
AssertionError: 1 != 2
"""

DJANGO_IMPORT_ERROR = """\
test_q (unittest.loader._FailedTest) ... ERROR

======================================================================
ERROR: test_q (unittest.loader._FailedTest)
----------------------------------------------------------------------
ImportError: Failed to import test module: test_q
"""

SYMPY_LOG = """\
sympy/core/tests/test_x.py[2]
test_fine ok
test_reported F
"""


def test_django_output_is_read_by_the_harness_parser() -> None:
    pytest.importorskip("swebench")
    report = DJANGO.report(DJANGO_LOG, "", timed_out=False)
    assert report.passed == {"test_ok (queries.test_q.QTests)"}
    # The harness parser also records the bare name from the FAIL: summary line; both
    # are failures of the same test, and only the verdict is used.
    assert "test_bug (queries.test_q.QTests)" in report.failed
    assert report.failed_cleanly


def test_a_django_test_module_that_cannot_import_is_not_a_failing_test() -> None:
    pytest.importorskip("swebench")
    report = DJANGO.report(DJANGO_IMPORT_ERROR, "", timed_out=False)
    assert report.errored and not report.failed_cleanly


def test_sympy_output_is_read_by_the_harness_parser() -> None:
    pytest.importorskip("swebench")
    report = SYMPY.report(SYMPY_LOG, "", timed_out=False)
    assert report.passed == {"test_fine"} and report.failed == {"test_reported"}
