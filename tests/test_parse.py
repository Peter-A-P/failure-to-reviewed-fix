"""Reading replies and placing edits: the failures a model actually produces."""

from __future__ import annotations

import pytest

from mend.graph.parse import (
    Edit,
    MalformedReply,
    apply_edits,
    diff_size,
    parse_edits,
    strip_fence,
    tags,
    unified_diff,
)
from mend.graph.review import parse_verdict

SOURCE = "def f(x):\n    return x + 1\n\n\ndef g(x):\n    return x + 1\n"


def test_tags_reads_every_block_in_order() -> None:
    assert tags("<file>a.py</file> and <file>b.py</file>", "file") == ["a.py", "b.py"]


def test_a_fence_inside_a_tag_is_dropped() -> None:
    assert strip_fence("\n```python\nx = 1\n```\n") == "x = 1\n"
    assert strip_fence("\nx = 1\n") == "x = 1\n"


def test_edits_keep_indentation_and_drop_only_the_layout_newlines() -> None:
    reply = "<edit><path>m.py</path><search>\n    return x + 1\n</search><replace>\n    return x + 2\n</replace></edit>"
    assert parse_edits(reply) == [Edit("m.py", "    return x + 1", "    return x + 2")]


def test_an_edit_missing_a_part_says_which() -> None:
    with pytest.raises(MalformedReply, match=r"edit 1: .*<replace>"):
        parse_edits("<edit><path>m.py</path><search>x</search></edit>")


def test_an_ambiguous_search_is_refused_with_a_reason_a_model_can_use() -> None:
    with pytest.raises(MalformedReply, match="occurs 2 times"):
        apply_edits({"m.py": SOURCE}, [Edit("m.py", "    return x + 1", "    return x")])


def test_a_search_that_does_not_occur_is_refused() -> None:
    with pytest.raises(MalformedReply, match="does not occur"):
        apply_edits({"m.py": SOURCE}, [Edit("m.py", "return x - 1", "return x")])


def test_an_edit_to_a_file_not_shown_is_refused() -> None:
    with pytest.raises(MalformedReply, match="not one of the files shown"):
        apply_edits({"m.py": SOURCE}, [Edit("other.py", "a", "b")])


def test_edits_apply_in_sequence_to_the_same_file() -> None:
    edits = [
        Edit("m.py", "def f(x):\n    return x + 1", "def f(x):\n    return x + 2"),
        Edit("m.py", "def g(x):\n    return x + 1", "def g(x):\n    return x + 3"),
    ]
    out = apply_edits({"m.py": SOURCE}, edits)
    assert "x + 2" in out["m.py"] and "x + 3" in out["m.py"]


def test_the_diff_is_git_style_and_measured() -> None:
    after = apply_edits(
        {"m.py": SOURCE},
        [Edit("m.py", "def f(x):\n    return x + 1", "def f(x):\n    return x * 2")],
    )
    diff = unified_diff({"m.py": SOURCE}, after)
    assert diff.startswith("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@")
    assert diff_size(diff) == (("m.py",), 2)


def test_a_file_without_a_final_newline_still_diffs_cleanly() -> None:
    diff = unified_diff({"m.py": "x = 1"}, {"m.py": "x = 2"})
    assert diff.endswith("+x = 2\n")


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("<verdict>accept</verdict><objection>none</objection>", (True, "")),
        ("<verdict> Reject </verdict><objection>misses None</objection>", (False, "misses None")),
        ("<verdict>accept</verdict>", (True, "")),
    ],
)
def test_verdicts(reply: str, expected: tuple[bool, str]) -> None:
    assert parse_verdict(reply) == expected


def test_a_verdict_that_is_neither_is_not_read_as_either() -> None:
    with pytest.raises(MalformedReply):
        parse_verdict("<verdict>probably fine</verdict>")
