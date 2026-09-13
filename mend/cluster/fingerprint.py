"""The fingerprint channel: exception type, top in-project frame, normalised message.

This is the cheap, exact channel, and on its own it is the Rule C candidate in PLAN.md
section 9.3. The expectation to be tested is that it has high purity and poor
completeness: two symptoms of one bug that surface as different exception types, or from
different call sites, never match, so one bug stays several tickets.

The fingerprint is deliberately three parts rather than one hash, because the distance
function wants partial credit. Two failures that agree on the exception type and the
frame but differ in the message are much closer than two that agree on nothing, and a
single digest cannot say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from mend.capture.normalise import normalise_message
from mend.capture.schema import FailureRecord


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """The three exact-match parts. Any of them may be absent."""

    exception_type: str | None
    top_frame: str | None
    message: str

    @property
    def key(self) -> str:
        """The single string a fingerprint-only baseline groups by."""
        return f"{self.exception_type or '-'}|{self.top_frame or '-'}|{self.message}"


def fingerprint(record: FailureRecord) -> Fingerprint:
    frame = record.top_in_project_frame
    return Fingerprint(
        exception_type=record.exception_type,
        top_frame=frame.location if frame else None,
        message=normalise_message(record.message),
    )


# How much of the fingerprint distance each part carries. The exception type and the
# frame are weighted equally and above the message: the message is the part a normaliser
# can only partly tame, and the part most likely to differ between two reports of one bug.
_WEIGHTS = (0.4, 0.4, 0.2)


def fingerprint_distance(a: Fingerprint, b: Fingerprint) -> float:
    """0.0 for identical fingerprints, 1.0 for nothing in common.

    A part where both sides are absent scores as disagreement, not agreement. Two GitHub
    issues with no traceback both have no top frame, and letting that count as evidence
    they are the same bug would cluster every prose-only report together.
    """
    parts = (
        (a.exception_type, b.exception_type),
        (a.top_frame, b.top_frame),
        (a.message or None, b.message or None),
    )
    similarity = sum(
        weight for weight, (x, y) in zip(_WEIGHTS, parts, strict=True) if x is not None and x == y
    )
    return 1.0 - similarity
