"""Ingesting failures from OpenTelemetry spans and their log records.

This is the production-shaped path: no test id, no assertion, just a span that ended in
error with an exception event on it and whatever the service logged around the same trace.
It is the shape project 09's observability emits, which is why the failure record carries
trace and span ids that the pytest path never fills.

The input is OTLP JSON as exported by the standard file exporter: a resourceSpans tree,
and optionally a resourceLogs tree whose records are matched to spans by trace id. Parsing
the exported JSON rather than subscribing to a collector keeps capture offline and makes
a captured incident a file someone can attach to a ticket.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mend.capture.schema import FailureRecord, Source
from mend.capture.traceback_parse import parse_frames

# The OTLP status code for an error. 0 is unset, 1 is ok, 2 is error.
_STATUS_ERROR = 2

_MAX_LOG_LINES = 40


def _attributes(raw: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """OTLP attributes are a list of {key, value: {<type>Value: ...}}; flatten them.

    Unknown value types are kept as their JSON, not dropped: an attribute this code does
    not understand is still evidence a human reading the ticket might want.
    """
    out: dict[str, Any] = {}
    for item in raw:
        key = item.get("key")
        if not isinstance(key, str):
            continue
        value = item.get("value")
        if not isinstance(value, Mapping):
            continue
        for suffix in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if suffix in value:
                out[key] = value[suffix]
                break
        else:
            out[key] = json.dumps(value, sort_keys=True)
    return out


def _timestamp(nanos: Any) -> datetime:
    """OTLP times are nanoseconds since the epoch, as a string in JSON."""
    try:
        return datetime.fromtimestamp(int(nanos) / 1e9, tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _logs_by_trace(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    """Log bodies grouped by trace id, so a span can carry what the service said."""
    out: dict[str, list[str]] = {}
    for resource in payload.get("resourceLogs", []):
        for scope in resource.get("scopeLogs", []):
            for record in scope.get("logRecords", []):
                trace_id = record.get("traceId")
                if not isinstance(trace_id, str):
                    continue
                body = record.get("body", {})
                text = body.get("stringValue") if isinstance(body, Mapping) else None
                if not text:
                    continue
                severity = record.get("severityText", "")
                line = f"{severity} {text}".strip() if severity else text
                out.setdefault(trace_id, []).append(line)
    return out


def ingest_otlp_json(
    path: Path,
    *,
    repo: str | None = None,
    commit: str | None = None,
    env: str | None = None,
    project_markers: tuple[str, ...] = (),
    true_cause_attribute: str | None = None,
) -> list[FailureRecord]:
    """Every error span in an OTLP JSON export, as records.

    `true_cause_attribute` names a span attribute holding the label for a set that has
    ground truth. Project 09's chaos runs tag each span with the scenario that was
    injected, so passing that attribute name turns an export into a labelled set without
    a side file. Nothing else in the pipeline reads it.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    logs = _logs_by_trace(payload)
    records: list[FailureRecord] = []

    for resource in payload.get("resourceSpans", []):
        resource_attrs = _attributes(resource.get("resource", {}).get("attributes", []))
        service = resource_attrs.get("service.name")
        for scope in resource.get("scopeSpans", []):
            for span in scope.get("spans", []):
                record = _span_record(
                    span,
                    service=service if isinstance(service, str) else None,
                    logs=logs,
                    repo=repo,
                    commit=commit,
                    env=env,
                    project_markers=project_markers,
                    true_cause_attribute=true_cause_attribute,
                )
                if record is not None:
                    records.append(record)
    return records


def _span_record(
    span: Mapping[str, Any],
    *,
    service: str | None,
    logs: Mapping[str, list[str]],
    repo: str | None,
    commit: str | None,
    env: str | None,
    project_markers: tuple[str, ...],
    true_cause_attribute: str | None,
) -> FailureRecord | None:
    status = span.get("status", {})
    events = span.get("events", [])
    exception_events = [e for e in events if e.get("name") == "exception"]
    is_error = status.get("code") == _STATUS_ERROR

    # A span is a symptom when it ended in error or recorded an exception. Both, because
    # a handled-and-recorded exception on an ok span is still something that went wrong,
    # and an error status with no exception event (a timeout, a failed health check) is
    # the production failure that has no traceback at all.
    if not is_error and not exception_events:
        return None

    attrs = _attributes(span.get("attributes", []))
    exc_attrs = _attributes(exception_events[0].get("attributes", [])) if exception_events else {}

    stacktrace = exc_attrs.get("exception.stacktrace")
    stacktrace_text = stacktrace if isinstance(stacktrace, str) else None

    exc_type = exc_attrs.get("exception.type")
    message = exc_attrs.get("exception.message") or status.get("message")

    trace_id = span.get("traceId")
    span_logs = logs.get(trace_id, []) if isinstance(trace_id, str) else []

    true_cause = attrs.get(true_cause_attribute) if true_cause_attribute else None

    return FailureRecord(
        record_id=f"otel:{span.get('spanId', '')}",
        source=Source.OTEL,
        captured_at=_timestamp(span.get("endTimeUnixNano") or span.get("startTimeUnixNano")),
        exception_type=exc_type if isinstance(exc_type, str) else None,
        message=str(message) if message else None,
        frames=parse_frames(stacktrace_text, project_markers=project_markers)
        if stacktrace_text
        else (),
        traceback_text=stacktrace_text,
        repo=repo,
        commit=commit if commit else _string_attr(attrs, "service.version"),
        test_id=None,
        env=env if env else _string_attr(attrs, "deployment.environment"),
        logs=tuple(span_logs[-_MAX_LOG_LINES:]),
        trace_id=trace_id if isinstance(trace_id, str) else None,
        span_id=span.get("spanId") if isinstance(span.get("spanId"), str) else None,
        # The span name is the operation that failed, which for a span with no exception
        # event is the only description of the failure there is.
        title=f"{service}: {span.get('name')}" if service else span.get("name"),
        true_cause=str(true_cause) if true_cause is not None else None,
    )


def _string_attr(attrs: Mapping[str, Any], key: str) -> str | None:
    value = attrs.get(key)
    return value if isinstance(value, str) else None
