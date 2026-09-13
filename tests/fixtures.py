"""Failure records built by hand, with known root causes.

The clustering tests need a set where the right answer is known and the difficulty is
realistic: one bug surfacing as several exception types from several call sites, and two
different bugs that look superficially alike. Those are the two cases the design claims to
handle and the two a fingerprint cannot.

Every record here carries true_cause, which nothing but the metrics ever reads.
"""

from __future__ import annotations

from mend.capture.schema import FailureRecord, Frame, Source

# Bug one: a config loader returns None for a missing key instead of raising. It surfaces
# as three different exceptions, in three different callers, all going through
# pkg/config.py:lookup. A fingerprint sees three bugs. Locality sees one.
CONFIG_BUG = [
    FailureRecord(
        record_id="c1",
        source=Source.PYTEST,
        exception_type="TypeError",
        message="unsupported operand type(s) for +: 'NoneType' and 'int'",
        frames=(
            Frame(file="pkg/api.py", line=41, function="handle_request", in_project=True),
            Frame(file="pkg/config.py", line=88, function="lookup", in_project=True),
        ),
        test_id="tests/test_api.py::test_handle_request",
        true_cause="config-lookup-returns-none",
    ),
    FailureRecord(
        record_id="c2",
        source=Source.PYTEST,
        exception_type="AttributeError",
        message="'NoneType' object has no attribute 'strip'",
        frames=(
            Frame(file="pkg/cli.py", line=17, function="main", in_project=True),
            Frame(file="pkg/config.py", line=88, function="lookup", in_project=True),
        ),
        test_id="tests/test_cli.py::test_main",
        true_cause="config-lookup-returns-none",
    ),
    FailureRecord(
        record_id="c3",
        source=Source.PYTEST,
        exception_type="ValueError",
        message="invalid literal for int() with base 10: 'None'",
        frames=(
            Frame(file="pkg/worker.py", line=93, function="start", in_project=True),
            Frame(file="pkg/config.py", line=88, function="lookup", in_project=True),
        ),
        test_id="tests/test_worker.py::test_start",
        true_cause="config-lookup-returns-none",
    ),
    FailureRecord(
        record_id="c4",
        source=Source.PYTEST,
        exception_type="TypeError",
        message="unsupported operand type(s) for +: 'NoneType' and 'int'",
        frames=(
            Frame(file="pkg/api.py", line=52, function="handle_batch", in_project=True),
            Frame(file="pkg/config.py", line=88, function="lookup", in_project=True),
        ),
        test_id="tests/test_api.py::test_handle_batch",
        true_cause="config-lookup-returns-none",
    ),
]

# Bug two: an off-by-one in a paginator. Two symptoms, same exception type as one of the
# config-bug symptoms, entirely different code path. A channel that leaned on the exception
# type would merge these into bug one.
PAGINATOR_BUG = [
    FailureRecord(
        record_id="p1",
        source=Source.PYTEST,
        exception_type="IndexError",
        message="list index out of range",
        frames=(Frame(file="pkg/paginate.py", line=22, function="page", in_project=True),),
        test_id="tests/test_paginate.py::test_last_page",
        true_cause="paginator-off-by-one",
    ),
    FailureRecord(
        record_id="p2",
        source=Source.PYTEST,
        exception_type="IndexError",
        message="list index out of range",
        frames=(Frame(file="pkg/paginate.py", line=22, function="page", in_project=True),),
        test_id="tests/test_paginate.py::test_single_item",
        true_cause="paginator-off-by-one",
    ),
]

# Bug three: a serialiser that cannot handle a datetime. One symptom, reported twice: once
# as a test failure with a traceback and once as a GitHub issue in prose with no traceback
# at all. The prose report is the case the locality channel has to stay silent about.
SERIALISER_BUG = [
    FailureRecord(
        record_id="s1",
        source=Source.PYTEST,
        exception_type="TypeError",
        message="Object of type datetime is not JSON serializable",
        frames=(Frame(file="pkg/serialise.py", line=61, function="dump", in_project=True),),
        test_id="tests/test_serialise.py::test_datetime",
        true_cause="serialiser-rejects-datetime",
    ),
    FailureRecord(
        record_id="s2",
        source=Source.GITHUB,
        title="Cannot serialise a datetime",
        body=(
            "Calling dump() on anything holding a datetime raises a TypeError saying the "
            "object of type datetime is not JSON serializable. Happens every time."
        ),
        exception_type="TypeError",
        message="Object of type datetime is not JSON serializable",
        true_cause="serialiser-rejects-datetime",
    ),
]

LABELLED_SET = [*CONFIG_BUG, *PAGINATOR_BUG, *SERIALISER_BUG]


def truth(records: list[FailureRecord]) -> list[str]:
    return [r.true_cause or "" for r in records]
