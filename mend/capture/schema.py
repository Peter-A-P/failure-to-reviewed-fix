"""The failure record: one observed symptom, with enough context to reproduce it.

This is the shape every ingester produces and every later stage consumes, so it is
deliberately wider than any one source fills. A pytest run gives a traceback and a test
id and no trace id; an OpenTelemetry span gives a trace id and logs and no test id; a
GitHub issue gives prose and sometimes neither. The record carries what the source had
and says nothing about what it did not, because a clustering channel that cannot tell
"absent" from "empty" quietly treats every issue report as sharing a blank fingerprint.

PLAN.md section 4 names this schema as the piece that carries forward: it is the shape
project 09's observability could emit.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Source(StrEnum):
    """Where a record came from. Kept on the record because the clustering metrics are
    reported per labelled set, and a mixed set has to be separable again afterwards."""

    PYTEST = "pytest"
    OTEL = "otel"
    GITHUB = "github"
    INJECTED = "injected"
    CHAOS = "chaos"


class Frame(BaseModel):
    """One stack frame, already split into the parts the later stages compare.

    `in_project` is the frame's most useful property and the one no traceback states: a
    failure in a dependency called from three places in the project is one bug, and the
    top in-project frame is what says so.
    """

    model_config = ConfigDict(frozen=True)

    file: str
    line: int | None = None
    function: str | None = None
    in_project: bool = False

    @property
    def location(self) -> str:
        """file:function, without the line number. Line numbers move when code around
        them moves, so they are kept on the record and left out of every comparison."""
        return f"{self.file}:{self.function}" if self.function else self.file


class FailureRecord(BaseModel):
    """One symptom. Many of these become one ticket.

    Identity is `record_id`, which the ingester sets from the source's own identifier
    where there is one, so that ingesting the same JUnit file twice does not double the
    symptom count and inflate symptoms-per-root-cause.
    """

    model_config = ConfigDict(frozen=True)

    record_id: str
    source: Source
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # What failed.
    exception_type: str | None = None
    message: str | None = None
    frames: tuple[Frame, ...] = ()
    traceback_text: str | None = None

    # Where it failed.
    repo: str | None = None
    commit: str | None = None
    test_id: str | None = None
    env: str | None = None

    # What else was going on. Logs are the lines near the failure, not the whole run.
    logs: tuple[str, ...] = ()
    trace_id: str | None = None
    span_id: str | None = None

    # Free text from a human report, which is all a GitHub issue has.
    title: str | None = None
    body: str | None = None

    # How to make it happen again, when the source knew.
    repro_command: str | None = None

    # Ground truth, when the set has any. Never read by the clustering itself; the
    # metrics module is the only consumer. Keeping it on the record rather than in a
    # side table is what makes a fixture a single file.
    true_cause: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return v.astimezone(UTC)

    @property
    def top_in_project_frame(self) -> Frame | None:
        """The deepest frame inside the project under test.

        Deepest, not shallowest: the innermost project frame is the line that did the
        wrong thing, while the outermost is usually the test runner or the entry point,
        which every failure in the repository shares.
        """
        for frame in reversed(self.frames):
            if frame.in_project:
                return frame
        return None

    @property
    def failure_text(self) -> str:
        """The text the embedding channel reads: what a human would read first.

        Deliberately not the whole traceback. The frames are their own channel, and
        putting them in the text channel too counts the same evidence twice.
        """
        parts = [self.title, self.exception_type, self.message, self.body]
        return "\n".join(p for p in parts if p).strip()

    def content_hash(self) -> str:
        """A stable digest of the comparable content, for deduplication before clustering.

        Excludes captured_at, record_id and true_cause: two identical symptoms captured a
        minute apart are one symptom seen twice.
        """
        h = hashlib.sha256()
        for part in (
            self.source.value,
            self.exception_type or "",
            self.message or "",
            self.test_id or "",
            self.repo or "",
            self.commit or "",
            "|".join(f.location for f in self.frames),
            self.failure_text,
        ):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()[:16]
