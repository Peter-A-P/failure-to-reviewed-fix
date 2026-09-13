"""Ingesting a pytest run from its JUnit XML report.

JUnit XML rather than a pytest plugin on purpose: every CI system already produces it,
including the GitHub Actions runs this is meant to watch, so capture needs no cooperation
from the project whose tests are failing. The cost is that the XML carries less than a
plugin would (no fixtures, no parametrisation detail beyond the test id), which is why
`repro_command` is reconstructed rather than recorded.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from mend.capture.schema import FailureRecord, Source
from mend.capture.traceback_parse import parse_exception, parse_frames


def _record_id(prefix: str, test_id: str, detail: str) -> str:
    """Stable across re-ingestion of the same report.

    The detail is hashed in because a parametrised test that fails twice with different
    arguments under one id is two symptoms, and dropping one of them would understate the
    symptom count.
    """
    digest = hashlib.sha256(f"{test_id}\x00{detail}".encode()).hexdigest()[:12]
    return f"{prefix}:{digest}"


def ingest_junit_xml(
    path: Path,
    *,
    repo: str | None = None,
    commit: str | None = None,
    env: str | None = None,
    project_markers: tuple[str, ...] = (),
    true_cause: str | None = None,
) -> list[FailureRecord]:
    """Every failure and error in a JUnit XML report, as records.

    Skipped tests and passes produce nothing: a symptom is something that went wrong.
    """
    return list(
        _iter_junit(
            ElementTree.parse(path).getroot(),
            prefix=path.stem,
            repo=repo,
            commit=commit,
            env=env,
            project_markers=project_markers,
            true_cause=true_cause,
        )
    )


def _iter_junit(
    root: ElementTree.Element,
    *,
    prefix: str,
    repo: str | None,
    commit: str | None,
    env: str | None,
    project_markers: tuple[str, ...],
    true_cause: str | None,
) -> Iterator[FailureRecord]:
    # A report is either <testsuites> wrapping <testsuite>, or a bare <testsuite>.
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        for case in suite.iter("testcase"):
            for kind in ("failure", "error"):
                for node in case.findall(kind):
                    yield _record(
                        case,
                        node,
                        kind=kind,
                        prefix=prefix,
                        repo=repo,
                        commit=commit,
                        env=env,
                        project_markers=project_markers,
                        true_cause=true_cause,
                    )


def _record(
    case: ElementTree.Element,
    node: ElementTree.Element,
    *,
    kind: str,
    prefix: str,
    repo: str | None,
    commit: str | None,
    env: str | None,
    project_markers: tuple[str, ...],
    true_cause: str | None,
) -> FailureRecord:
    classname = case.get("classname", "")
    name = case.get("name", "")
    file_attr = case.get("file")
    test_id = f"{file_attr}::{name}" if file_attr else f"{classname}.{name}".strip(".")

    body = (node.text or "").strip()
    # The message attribute is pytest's one-line summary; the element text is the full
    # traceback. Either may be missing, and a failure with neither is still a failure.
    summary = node.get("message", "").strip()
    detail = body or summary

    exc_type, message = parse_exception(detail)
    if exc_type is None and summary:
        exc_type, message = parse_exception(summary)
    if exc_type is None and kind == "error":
        # An <error> with no parseable exception is still an error; naming it after the
        # element is more honest than leaving the type blank and letting the fingerprint
        # channel treat every such failure as identical to every other.
        exc_type = "CollectionError"
    if message is None and summary:
        message = summary

    logs = tuple(
        line
        for tag in ("system-out", "system-err")
        for element in case.findall(tag)
        for line in (element.text or "").splitlines()
        if line.strip()
    )

    return FailureRecord(
        record_id=_record_id(prefix, test_id, detail),
        source=Source.PYTEST,
        exception_type=exc_type,
        message=message,
        frames=parse_frames(detail, project_markers=project_markers),
        traceback_text=detail or None,
        repo=repo,
        commit=commit,
        test_id=test_id,
        env=env,
        logs=logs[-40:],
        repro_command=f"pytest {test_id}" if test_id else None,
        true_cause=true_cause,
    )
