"""Reading model replies, and turning edits into a diff.

Replies use tags, <file>...</file> and the like, rather than JSON. Code is most of what
comes back, and code inside a JSON string has to have every quote and backslash escaped
by the model, which is a failure mode with nothing to do with whether the fix is right.
Tags need no escaping, read the same from either vendor, and a missing one is easy to
report back to the model in plain words.

Edits are search and replace, not unified diffs: the model quotes the exact text it wants
changed and gives the text to put there. A quoted block either occurs exactly once in the
file or the edit is refused with the reason, which is feedback a model can act on. The
diff the sandbox applies is then computed here, so its hunk headers are always right.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class MalformedReply(ValueError):
    """The reply did not have the shape the prompt asked for. Said in words a model can use."""


def tags(text: str, name: str) -> list[str]:
    """The contents of every <name>...</name> in the text, in order."""
    pattern = re.compile(rf"<{name}>(.*?)</{name}>", re.S)
    return [m.group(1) for m in pattern.finditer(text)]


def one_tag(text: str, name: str) -> str:
    found = tags(text, name)
    if not found:
        raise MalformedReply(f"the reply has no <{name}>...</{name}> block")
    return found[0]


def strip_fence(block: str) -> str:
    """Drop one surrounding Markdown code fence, if the model added one inside a tag."""
    inner = block.strip("\n")
    match = re.fullmatch(r"\s*```[\w+-]*\n(.*?)\n?```\s*", inner, re.S)
    return match.group(1) + "\n" if match else inner + ("\n" if inner else "")


@dataclass(frozen=True, slots=True)
class Edit:
    path: str
    search: str
    replace: str


def parse_edits(text: str) -> list[Edit]:
    blocks = tags(text, "edit")
    if not blocks:
        raise MalformedReply("the reply has no <edit> blocks")
    edits = []
    for i, block in enumerate(blocks, start=1):
        try:
            path = one_tag(block, "path").strip()
            search = one_tag(block, "search")
            replace = one_tag(block, "replace")
        except MalformedReply as exc:
            raise MalformedReply(f"edit {i}: {exc}") from None
        if not path:
            raise MalformedReply(f"edit {i}: the <path> is empty")
        edits.append(Edit(path=path, search=_trim(search), replace=_trim(replace)))
    return edits


def _trim(block: str) -> str:
    """Tags usually sit on their own lines; the newline after the opening tag and the one
    before the closing tag are layout, not content."""
    if block.startswith("\n"):
        block = block[1:]
    if block.endswith("\n"):
        block = block[:-1]
    return block


def apply_edits(files: Mapping[str, str], edits: Sequence[Edit]) -> dict[str, str]:
    """The new text of every file the edits touch, or MalformedReply saying which edit
    could not be placed and why. Edits apply in order, each to the result of the last."""
    out: dict[str, str] = {}
    for i, edit in enumerate(edits, start=1):
        if edit.path in out:
            current = out[edit.path]
        elif edit.path in files:
            current = files[edit.path]
        else:
            raise MalformedReply(f"edit {i}: {edit.path} is not one of the files shown")
        if not edit.search:
            raise MalformedReply(f"edit {i}: the <search> block is empty")
        count = current.count(edit.search)
        if count == 0:
            raise MalformedReply(
                f"edit {i}: the <search> text does not occur in {edit.path}; quote it exactly, "
                "including indentation"
            )
        if count > 1:
            raise MalformedReply(
                f"edit {i}: the <search> text occurs {count} times in {edit.path}; include "
                "more surrounding lines so it occurs once"
            )
        out[edit.path] = current.replace(edit.search, edit.replace, 1)
    return {path: text for path, text in out.items() if text != files.get(path)}


def unified_diff(before: Mapping[str, str], after: Mapping[str, str]) -> str:
    """A git-style diff of every file in after against before, applicable with git apply."""
    chunks: list[str] = []
    for path in sorted(after):
        old = before.get(path, "")
        new = after[path]
        if old == new:
            continue
        lines = difflib.unified_diff(
            _lines(old),
            _lines(new),
            fromfile=f"a/{path}" if path in before else "/dev/null",
            tofile=f"b/{path}",
        )
        body = "".join(lines)
        if body:
            chunks.append(f"diff --git a/{path} b/{path}\n{body}")
    return "".join(chunks)


def _lines(text: str) -> list[str]:
    """Lines with their endings, and a final newline guaranteed, so a file that ended
    without one does not produce a hunk git apply rejects."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def diff_size(diff: str) -> tuple[tuple[str, ...], int]:
    """Files touched and lines changed (added plus removed), read off a diff."""
    files = tuple(dict.fromkeys(re.findall(r"^diff --git a/(\S+) b/", diff, re.M)))
    changed = sum(
        1
        for line in diff.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )
    return files, changed
