"""The code-locality channel: how much of the failing code path two symptoms share.

This is the channel that does the work the plan is actually claiming. A single bug in one
function is reached from many call sites and raises through many wrappers, so the
exception type differs, the message differs, and the test ids differ, but the deep frames
are the same file and the same function. Fingerprinting sees three bugs. Locality sees one.

Three signals, combined:

- the innermost frame: whether the two failures broke at the same line of project code.
  The strongest single piece of evidence there is at this level, and the one the other
  two dilute, which is why it is scored separately rather than folded into the overlap.
- frame overlap: the Jaccard overlap of in-project frame locations. Broad evidence that
  the two failures travelled the same path, and the part that survives when the innermost
  frames differ by a wrapper.
- file overlap: the same, over files rather than file-and-function. Weakest and most
  forgiving, so that two symptoms entering the same module at different functions are
  still closer than two that share nothing.

Why the innermost frame needs its own term: a bug in one function reached from four call
sites gives four symptoms whose frame sets are {caller_i, faulty}. The Jaccard overlap of
any two of those is one in three, which reads as mostly different, when in fact they agree
on the only frame that identifies the bug. Overlap alone systematically understates
exactly the case this project exists to get right.

Frames from outside the project are ignored on purpose. Every failure in a repository
shares its test runner and its standard library, and counting those as shared code path
would pull the whole corpus into one cluster.
"""

from __future__ import annotations

from mend.capture.normalise import shared_prefix_ratio
from mend.capture.schema import FailureRecord

# Most specific claim first. These are a starting point to be tuned on the validation
# split with the rest of the clustering parameters, and are reported with any number they
# produced; see docs/clustering.md.
_INNERMOST_WEIGHT = 0.45
_FRAME_WEIGHT = 0.35
_FILE_WEIGHT = 0.20


def locations(record: FailureRecord) -> tuple[str, ...]:
    """In-project frame locations, deduplicated, order preserved.

    Deduplicated because a recursive failure repeats one location twenty times, and the
    Jaccard overlap would otherwise be computed over a set that says the same thing once
    anyway. Keeping the order makes the value readable in a ticket.
    """
    seen: dict[str, None] = {}
    for frame in record.frames:
        if frame.in_project:
            seen.setdefault(frame.location, None)
    return tuple(seen)


def files(record: FailureRecord) -> tuple[str, ...]:
    """In-project files, deduplicated, order preserved."""
    seen: dict[str, None] = {}
    for frame in record.frames:
        if frame.in_project:
            seen.setdefault(frame.file, None)
    return tuple(seen)


def locality_distance(a: FailureRecord, b: FailureRecord) -> float | None:
    """0.0 for the same code path, 1.0 for no shared code, None when one side has no frames.

    None rather than 1.0 is the important part. A record with no traceback has not told us
    that its code path is different, it has told us nothing, and scoring silence as maximum
    distance would push every prose-only issue away from the traceback that explains it.
    The combined distance renormalises over the channels that spoke.
    """
    a_locs, b_locs = locations(a), locations(b)
    if not a_locs or not b_locs:
        return None

    innermost_a, innermost_b = a.top_in_project_frame, b.top_in_project_frame
    innermost_similarity = float(
        innermost_a is not None
        and innermost_b is not None
        and innermost_a.location == innermost_b.location
    )
    frame_similarity = shared_prefix_ratio(a_locs, b_locs)
    file_similarity = shared_prefix_ratio(files(a), files(b))

    return 1.0 - (
        _INNERMOST_WEIGHT * innermost_similarity
        + _FRAME_WEIGHT * frame_similarity
        + _FILE_WEIGHT * file_similarity
    )
