"""Parsing a Python traceback into frames.

Used by more than one ingester, because a traceback arrives inside JUnit XML, inside an
OpenTelemetry exception event, and pasted into the body of a GitHub issue, and it is the
same text in all three.

This is a parser for text that was produced by a machine and then possibly mangled by a
human pasting it, so it is forgiving: an unparseable line is skipped rather than fatal,
and a traceback with no recognisable frames still yields an exception type and message if
the last line has them.
"""

from __future__ import annotations

import re

from mend.capture.normalise import normalise_path
from mend.capture.schema import Frame

# File "path/to/mod.py", line 42, in function_name
_FRAME = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<function>\S+))?\s*$'
)
# pytest's short-form location, which appears in JUnit XML without the File/line wrapper:
#   path/to/test_mod.py:42: AssertionError
_PYTEST_LOCATION = re.compile(r"^(?P<file>[\w./\-]+\.py):(?P<line>\d+):\s*(?P<exc>\w+)?\s*$")
# The final line: ExceptionType: message, where the type may be dotted.
_EXCEPTION = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt|Fault))"
    r"(?::\s*(?P<message>.*))?$"
)

# Paths that belong to the runtime or the tooling rather than to the code under test.
# A frame in one of these is real, and is kept, but it is not what the bug is about.
_NOT_PROJECT = (
    "/site-packages/",
    "/dist-packages/",
    "/lib/python",
    "<frozen ",
    "/_pytest/",
    "/pluggy/",
    "/runpy.py",
)


def _is_in_project(path: str, project_markers: tuple[str, ...]) -> bool:
    """Whether a frame is inside the code under test.

    Two rules, in order. A frame under site-packages or the standard library is never in
    the project, even when its path happens to contain a marker: an installed copy of the
    project itself is still not the checkout under test. Otherwise a frame is in the
    project when it matches a marker, and when no markers were supplied every remaining
    frame counts, which is the right default for a traceback from an unknown repository.
    """
    lowered = path.replace("\\", "/").lower()
    if any(marker in lowered for marker in _NOT_PROJECT):
        return False
    if not project_markers:
        return True
    return any(marker.lower() in lowered for marker in project_markers)


def parse_frames(text: str, *, project_markers: tuple[str, ...] = ()) -> tuple[Frame, ...]:
    """Every frame in a traceback, outermost first, the order Python prints them."""
    frames: list[Frame] = []
    for raw in text.splitlines():
        match = _FRAME.match(raw)
        if match:
            frames.append(
                Frame(
                    file=normalise_path(match["file"]),
                    line=int(match["line"]),
                    function=match["function"],
                    in_project=_is_in_project(match["file"], project_markers),
                )
            )
            continue
        short = _PYTEST_LOCATION.match(raw)
        if short:
            frames.append(
                Frame(
                    file=normalise_path(short["file"]),
                    line=int(short["line"]),
                    function=None,
                    in_project=_is_in_project(short["file"], project_markers),
                )
            )
    return tuple(frames)


def parse_exception(text: str) -> tuple[str | None, str | None]:
    """The exception type and message from the tail of a traceback.

    Scans upward from the end, because a chained traceback ("During handling of the above
    exception, another exception occurred") ends with the exception that actually escaped,
    and that is the one the failure is about.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    for raw in reversed(lines):
        line = raw[4:].strip() if raw.startswith("E   ") else raw.strip()
        match = _EXCEPTION.match(line)
        if match:
            message = (match["message"] or "").strip()
            return match["type"], message or None
        short = _PYTEST_LOCATION.match(line)
        if short and short["exc"]:
            return short["exc"], None
    return None, None
