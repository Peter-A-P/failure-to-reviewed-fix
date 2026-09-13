"""Ingesting failures reported as GitHub issues.

The hardest of the three sources, because a human report has no structure: the traceback
may be in a fenced code block, in the middle of a sentence, or absent entirely. What this
does is find any traceback in the body, parse what it can, and keep the prose so that the
embedding channel has something to work with when the frames channel has nothing.

The reader takes already-fetched JSON rather than calling the API, so that mining and
ingestion are separate steps: `mend.data.duplicates` does the fetching and caching, and
this module stays offline and deterministic. Issue text is cached locally and never
redistributed (PLAN.md section 3).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mend.capture.schema import FailureRecord, Source
from mend.capture.traceback_parse import parse_exception, parse_frames

# A traceback inside a fenced block, or bare in the prose. Non-greedy to the first blank
# line that follows an exception line, because issue bodies continue after the paste.
_TRACEBACK = re.compile(
    r"(Traceback \(most recent call last\):.*?(?:\n\s*\n|```|\Z))",
    re.DOTALL,
)
_FENCE = re.compile(r"```[\w]*\n(.*?)```", re.DOTALL)


def extract_traceback(body: str) -> str | None:
    """The first traceback in an issue body, fenced or not.

    Fenced blocks are searched first: a body that quotes a traceback in prose and then
    pastes the real one in a fence almost always means the fenced one.
    """
    for fenced in _FENCE.findall(body):
        block = str(fenced)
        if "Traceback (most recent call last)" in block:
            return block.strip()
    match = _TRACEBACK.search(body)
    return match.group(1).strip() if match else None


def _parsed_at(raw: Any) -> datetime:
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def record_from_issue(
    issue: Mapping[str, Any],
    *,
    repo: str | None = None,
    project_markers: tuple[str, ...] = (),
    true_cause: str | None = None,
) -> FailureRecord:
    """One issue as one record.

    `true_cause` is the canonical issue number for a duplicate cluster: the issue an
    issue was closed as a duplicate of, or its own number when it is the canonical one.
    That is the maintainers' own judgement, which is the whole reason this set exists.
    """
    body = str(issue.get("body") or "")
    title = str(issue.get("title") or "")
    number = issue.get("number")
    traceback_text = extract_traceback(body)

    exc_type: str | None = None
    message: str | None = None
    if traceback_text:
        exc_type, message = parse_exception(traceback_text)
    if exc_type is None:
        # Many reports name the exception in the title and nowhere else.
        exc_type, message_from_title = parse_exception(title)
        message = message or message_from_title

    return FailureRecord(
        record_id=f"gh:{repo}#{number}" if repo else f"gh:#{number}",
        source=Source.GITHUB,
        captured_at=_parsed_at(issue.get("created_at")),
        exception_type=exc_type,
        message=message,
        frames=parse_frames(traceback_text, project_markers=project_markers)
        if traceback_text
        else (),
        traceback_text=traceback_text,
        repo=repo,
        title=title or None,
        body=body or None,
        true_cause=true_cause,
    )


def ingest_issues_json(
    path: Path,
    *,
    repo: str | None = None,
    project_markers: tuple[str, ...] = (),
) -> list[FailureRecord]:
    """A cached list of issues, as records.

    Each issue may carry a `mend_true_cause` key written by the mining step; nothing else
    in the pipeline adds keys to the vendor's own JSON, and that name is chosen so a
    reader can see at a glance which field is ours.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    issues = payload if isinstance(payload, list) else payload.get("issues", [])
    return [
        record_from_issue(
            issue,
            repo=repo or issue.get("mend_repo"),
            project_markers=project_markers,
            true_cause=issue.get("mend_true_cause"),
        )
        for issue in issues
    ]
