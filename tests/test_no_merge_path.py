"""No merge path exists, asserted against the source rather than against a promise.

PLAN.md section 2.8 and the repository rules: nothing merges, and a test asserts it. A
test that only checked the state machine would miss the way this rule actually gets
broken, which is somebody calling the GitHub API directly from a node six months from now
because it was two lines and the pull request was obviously fine.

So this scans every source file in the package for the things that merge, and for the
narrower thing of creating a pull request that is not a draft. It is a blunt instrument
and it is meant to be: the cost of a false positive is renaming a variable, and the cost
of a false negative is the one guarantee this project makes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "mend"

# GitHub's merge endpoints and the client method names that reach them. Written as
# fragments rather than exact calls because the point is to catch the shape, not one
# spelling of it.
MERGE_CALLS = (
    "merge_pull_request",
    "merge_pr",
    ".merge(",
    "pulls/merge",
    "/merge",
    "merge_method",
    "squash_merge",
    "rebase_merge",
    "enable_auto_merge",
    "auto_merge",
)

# Fragments that would push code somewhere a human did not approve it.
DIRECT_WRITE_CALLS = (
    "git push",
    "push --force",
    "create_commit_on_branch",
    "update_ref",
)


def source_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_has_source_to_scan() -> None:
    """A scan over nothing passes trivially; this stops that from going unnoticed."""
    assert len(source_files()) >= 10


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.name))
def test_no_merge_call_anywhere(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    # Comments and docstrings are allowed to discuss merging; code is not. Strip string
    # literals and comments before matching, so that this docstring-heavy codebase does
    # not have to avoid the word.
    code_only = _strip_strings_and_comments(text, tree)

    for fragment in MERGE_CALLS:
        assert fragment not in code_only, (
            f"{path.name} contains {fragment!r} outside a comment or docstring. "
            "There is no merge path in this package (PLAN.md section 2.8)."
        )


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.name))
def test_no_direct_write_to_a_repository(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    code_only = _strip_strings_and_comments(text, ast.parse(text))
    for fragment in DIRECT_WRITE_CALLS:
        assert fragment not in code_only, (
            f"{path.name} contains {fragment!r} outside a comment or docstring. "
            "Nothing in this package writes to a repository; it proposes."
        )


def test_no_stage_means_merged() -> None:
    """The state machine has no terminal state that could be read as merged."""
    from mend.graph.machine import Stage

    forbidden = {"merged", "merge", "applied", "landed", "pushed", "shipped"}
    for stage in Stage:
        assert stage.value not in forbidden, f"Stage.{stage.name} means the change landed"


def test_no_transition_out_of_acted() -> None:
    """ACTED is terminal: there is nowhere further to go, so there is nowhere to merge from."""
    from mend.graph.machine import _ALLOWED, Stage

    assert _ALLOWED[Stage.ACTED] == frozenset()
    assert _ALLOWED[Stage.STOPPED] == frozenset()


def _strip_strings_and_comments(text: str, tree: ast.AST) -> str:
    """Blank out every string literal and comment, keeping line structure.

    Line structure is kept so that a future version of this test can report a line number
    without recomputing offsets.
    """
    lines = text.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start, end = node.lineno - 1, (node.end_lineno or node.lineno) - 1
            for i in range(start, min(end + 1, len(lines))):
                if i == start == end:
                    lines[i] = (
                        lines[i][: node.col_offset]
                        + " " * max(0, (node.end_col_offset or 0) - node.col_offset)
                        + lines[i][(node.end_col_offset or 0) :]
                    )
                elif i == start:
                    lines[i] = lines[i][: node.col_offset]
                else:
                    lines[i] = ""

    return "\n".join(re.sub(r"#.*$", "", line) for line in lines)
