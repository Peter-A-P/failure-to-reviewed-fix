"""Ingestion: a pytest report, an OTLP export and a GitHub issue become the same record.

The tests worth having here are about the parts that are easy to get quietly wrong: which
frame counts as the project's, whether a chained traceback reports the right exception,
and whether re-ingesting the same report doubles the symptom count. The last one matters
more than it looks: symptoms per root cause is a headline number, and duplicate records
inflate it without changing anything a reader could see.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mend.capture.github_ingest import extract_traceback, record_from_issue
from mend.capture.normalise import normalise_message, normalise_path, normalise_text
from mend.capture.otel_ingest import ingest_otlp_json
from mend.capture.pytest_ingest import ingest_junit_xml
from mend.capture.schema import Source
from mend.capture.traceback_parse import parse_exception, parse_frames

TRACEBACK = """Traceback (most recent call last):
  File "/testbed/pkg/api.py", line 30, in handle
    return load(config)
  File "/usr/lib/python3.13/json/__init__.py", line 346, in loads
    return _default_decoder.decode(s)
  File "/testbed/pkg/config.py", line 88, in lookup
    raise KeyError(key)
KeyError: 'user_id'
"""

CHAINED = """Traceback (most recent call last):
  File "/testbed/pkg/a.py", line 1, in first
    raise ValueError("inner")
ValueError: inner

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/testbed/pkg/b.py", line 2, in second
    raise RuntimeError("outer")
RuntimeError: outer
"""


def test_frames_are_parsed_in_order() -> None:
    frames = parse_frames(TRACEBACK, project_markers=("pkg/",))
    assert [f.file for f in frames] == ["pkg/api.py", "json/__init__.py", "pkg/config.py"]
    assert [f.function for f in frames] == ["handle", "loads", "lookup"]


def test_the_standard_library_is_never_in_the_project() -> None:
    frames = parse_frames(TRACEBACK, project_markers=("pkg/",))
    by_file = {f.file: f.in_project for f in frames}
    assert by_file["pkg/api.py"]
    assert by_file["pkg/config.py"]
    assert not by_file["json/__init__.py"]


def test_an_installed_copy_of_the_project_is_not_the_project() -> None:
    """A marker that matches under site-packages must not promote the frame.

    This is the case that makes a traceback look like it failed in the checkout when it
    failed in an installed copy, and it would point localisation at the wrong tree.
    """
    text = 'File "/usr/lib/python3.13/site-packages/pkg/config.py", line 4, in lookup'
    frames = parse_frames(text, project_markers=("pkg/",))
    assert len(frames) == 1
    assert not frames[0].in_project


def test_a_chained_traceback_reports_the_exception_that_escaped() -> None:
    assert parse_exception(CHAINED) == ("RuntimeError", "outer")


def test_the_exception_and_message_are_separated() -> None:
    assert parse_exception(TRACEBACK) == ("KeyError", "'user_id'")


def test_an_unparseable_traceback_is_not_fatal() -> None:
    assert parse_frames("nothing useful here") == ()
    assert parse_exception("nothing useful here") == (None, None)


def test_normalisation_removes_what_changes_between_runs() -> None:
    text = (
        "<pkg.Model object at 0x7f3c8a1b2d50> failed at 2026-09-13T10:00:00Z "
        "in /tmp/pytest-of-peter/test_0/data.json after 42 tries"
    )
    out = normalise_text(text)
    assert "0x7f3c8a1b2d50" not in out
    assert "2026-09-13" not in out
    assert "pytest-of-peter" not in out
    assert "<ADDR>" in out and "<TIME>" in out and "<TMP>" in out and "<N>" in out


def test_normalisation_keeps_what_identifies_the_bug() -> None:
    """The over-eager normaliser failure: two different keys are two different bugs."""
    a = normalise_message("KeyError: 'user_id'")
    b = normalise_message("KeyError: 'account_id'")
    assert a != b
    assert "user_id" in a


def test_a_message_is_truncated_to_a_fingerprintable_length() -> None:
    assert len(normalise_message("x" * 5000)) <= 200


def test_paths_normalise_across_environments() -> None:
    """The same file captured in a sandbox and on a laptop compares equal."""
    assert normalise_path("/testbed/pkg/config.py") == "pkg/config.py"
    assert normalise_path(r"C:\work\src\pkg\config.py") == "pkg/config.py"
    assert normalise_path("/usr/lib/python3.13/site-packages/pkg/config.py") == "pkg/config.py"


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" tests="3">
    <testcase classname="tests.test_api" name="test_handle" file="tests/test_api.py" time="0.1">
      <failure message="KeyError: 'user_id'">{traceback}</failure>
      <system-out>loading config</system-out>
    </testcase>
    <testcase classname="tests.test_api" name="test_ok" file="tests/test_api.py" time="0.1"/>
    <testcase classname="tests.test_cli" name="test_main" file="tests/test_cli.py" time="0.1">
      <error message="collection failure"/>
    </testcase>
  </testsuite>
</testsuites>
"""


@pytest.fixture
def junit(tmp_path: Path) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(JUNIT.format(traceback=TRACEBACK), encoding="utf-8")
    return path


def test_only_failures_and_errors_become_records(junit: Path) -> None:
    records = ingest_junit_xml(junit, project_markers=("pkg/",))
    assert len(records) == 2
    assert {r.source for r in records} == {Source.PYTEST}


def test_a_record_carries_enough_to_reproduce(junit: Path) -> None:
    records = ingest_junit_xml(junit, repo="acme/pkg", commit="abc123", project_markers=("pkg/",))
    failure = next(r for r in records if r.exception_type == "KeyError")
    assert failure.test_id == "tests/test_api.py::test_handle"
    assert failure.repro_command == "pytest tests/test_api.py::test_handle"
    assert failure.repo == "acme/pkg"
    assert failure.commit == "abc123"
    assert "loading config" in failure.logs
    frame = failure.top_in_project_frame
    assert frame is not None and frame.file == "pkg/config.py"


def test_an_error_with_no_traceback_is_still_named(junit: Path) -> None:
    """Otherwise every unparseable error shares a blank fingerprint and clusters together."""
    records = ingest_junit_xml(junit)
    error = next(r for r in records if r.test_id == "tests/test_cli.py::test_main")
    assert error.exception_type == "CollectionError"


def test_ingesting_twice_does_not_double_the_symptom_count(junit: Path) -> None:
    """Record ids are stable across re-ingestion, so symptoms per root cause stays honest."""
    first = ingest_junit_xml(junit)
    second = ingest_junit_xml(junit)
    assert [r.record_id for r in first] == [r.record_id for r in second]
    assert len({r.record_id for r in [*first, *second]}) == len(first)


def test_a_content_hash_ignores_when_it_was_captured(junit: Path) -> None:
    records = ingest_junit_xml(junit)
    later = records[0].model_copy(update={"record_id": "other"})
    assert records[0].content_hash() == later.content_hash()


OTLP = {
    "resourceSpans": [
        {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "aaaa",
                            "spanId": "bbbb",
                            "name": "POST /orders",
                            "endTimeUnixNano": "1789000000000000000",
                            "status": {"code": 2, "message": "upstream timeout"},
                            "attributes": [
                                {"key": "chaos.scenario", "value": {"stringValue": "db-latency"}},
                                {
                                    "key": "deployment.environment",
                                    "value": {"stringValue": "staging"},
                                },
                            ],
                            "events": [],
                        },
                        {
                            "traceId": "cccc",
                            "spanId": "dddd",
                            "name": "GET /health",
                            "status": {"code": 1},
                            "attributes": [],
                            "events": [],
                        },
                    ]
                }
            ],
        }
    ],
    "resourceLogs": [
        {
            "scopeLogs": [
                {
                    "logRecords": [
                        {
                            "traceId": "aaaa",
                            "severityText": "ERROR",
                            "body": {"stringValue": "connection pool exhausted"},
                        }
                    ]
                }
            ]
        }
    ],
}


def test_an_error_span_with_no_exception_is_still_a_symptom(tmp_path: Path) -> None:
    """The production failure that has no traceback: a timeout, a failed health check."""
    path = tmp_path / "export.json"
    path.write_text(json.dumps(OTLP), encoding="utf-8")

    records = ingest_otlp_json(path, true_cause_attribute="chaos.scenario")
    assert len(records) == 1, "only the error span is a symptom"

    record = records[0]
    assert record.source is Source.OTEL
    assert record.trace_id == "aaaa"
    assert record.message == "upstream timeout"
    assert record.env == "staging"
    assert record.true_cause == "db-latency"
    assert "ERROR connection pool exhausted" in record.logs
    assert record.failure_text


ISSUE_BODY = """Running the parser on a config with no user id blows up.

```python-traceback
Traceback (most recent call last):
  File "pkg/config.py", line 88, in lookup
    raise KeyError(key)
KeyError: 'user_id'
```

Happens on 2.1.0 and on main.
"""


def test_a_traceback_is_found_inside_a_fenced_block() -> None:
    found = extract_traceback(ISSUE_BODY)
    assert found is not None
    assert found.startswith("Traceback")
    assert "KeyError" in found


def test_an_issue_with_a_traceback_gets_frames() -> None:
    record = record_from_issue(
        {"number": 12, "title": "KeyError on missing user id", "body": ISSUE_BODY},
        repo="acme/pkg",
        project_markers=("pkg/",),
        true_cause="12",
    )
    assert record.record_id == "gh:acme/pkg#12"
    assert record.exception_type == "KeyError"
    assert record.frames
    assert record.true_cause == "12"


def test_an_issue_with_only_prose_still_becomes_a_record() -> None:
    """The case the locality channel has to abstain on rather than object to."""
    record = record_from_issue(
        {"number": 13, "title": "Crash when the user id is missing", "body": "It just crashes."}
    )
    assert record.frames == ()
    assert record.failure_text
    assert record.exception_type is None


def test_an_exception_named_only_in_the_title_is_found() -> None:
    record = record_from_issue({"number": 14, "title": "TypeError: cannot concatenate", "body": ""})
    assert record.exception_type == "TypeError"
