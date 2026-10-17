"""The four prompts, one per role, and the size limits on what goes into them.

Written for this repository from the published shape of issue-resolution agents (localise,
reproduce, edit, check; docs/boundary.md), not adapted from any other system's prompts.
They are short on purpose. Each says what the role is for, what it will be shown, and the
exact reply format, and the reviewer's adds the one thing that makes it adversarial: its
job is to find the reason the patch is wrong, and agreeing is the outcome it has to be
talked into.

Every piece of repository and issue text is untrusted input. It goes into the user turn
between tags, never into the system prompt, and nothing a model writes runs anywhere but
the sandbox, which has no network (mend/sandbox/spec.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# Characters, not tokens: roughly four to a token for code. A file past this is cut and
# says so; the localiser is told to name the file anyway, since the fixer sees more of it.
MAX_FILE_CHARS = 40_000
MAX_TOTAL_SOURCE_CHARS = 120_000
MAX_LISTING_PATHS = 3_000
MAX_ISSUE_CHARS = 20_000


def clip(text: str, limit: int, what: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[{what} cut at {limit} characters of {len(text)}]\n"


def files_block(files: Mapping[str, str]) -> str:
    """Files in tags, each clipped, the whole clipped, so one huge module cannot crowd
    out the rest."""
    parts = []
    budget = MAX_TOTAL_SOURCE_CHARS
    for path, text in files.items():
        if budget <= 0:
            parts.append(f'<source path="{path}">[not shown: the prompt is full]</source>')
            continue
        shown = clip(text, min(MAX_FILE_CHARS, budget), path)
        budget -= len(shown)
        parts.append(f'<source path="{path}">\n{shown}</source>')
    return "\n\n".join(parts)


def issue_block(title: str, body: str) -> str:
    return f"<issue>\n<title>{title}</title>\n{clip(body, MAX_ISSUE_CHARS, 'issue')}\n</issue>"


LOCALISER_SYSTEM = """\
You locate bugs in Python repositories. You are shown an issue report, the repository's \
file listing, and which files mention terms from the report. Name the source files most \
likely to need changing to fix the issue, most likely first, at most four. Name only \
files that appear in the listing. Do not name test files.

Reply with one <file>path</file> line per file and nothing else of substance."""


def localiser_prompt(
    issue: str,
    listing: Sequence[str],
    frame_files: Sequence[str],
    keyword_hits: Mapping[str, Sequence[str]],
) -> str:
    shown = list(listing[:MAX_LISTING_PATHS])
    more = len(listing) - len(shown)
    parts = [issue]
    if frame_files:
        parts.append("<traceback_files>\n" + "\n".join(frame_files) + "\n</traceback_files>")
    if keyword_hits:
        lines = [f"{term}: {', '.join(paths)}" for term, paths in keyword_hits.items() if paths]
        if lines:
            parts.append("<mentions>\n" + "\n".join(lines) + "\n</mentions>")
    listing_text = "\n".join(shown) + (f"\n[{more} more files not listed]" if more > 0 else "")
    parts.append(f"<listing>\n{listing_text}\n</listing>")
    return "\n\n".join(parts)


TESTER_SYSTEM = """\
You write a single pytest test that reproduces a reported bug. The test must fail on the \
current code because of the bug, and pass once the bug is fixed. It must not fail for any \
other reason: an import that does not exist, a typo, or a missing fixture makes it useless.

Rules:
- One new test file. Choose a path that does not exist yet, next to the repository's \
existing tests, with a file name starting with test_.
- Test behaviour the issue describes, through the public interface where you can.
- Assert the correct behaviour, so the assertion fails on the buggy code.
- No network, no files outside a temporary directory, no sleeping.

Reply with exactly:
<path>relative/path/to/test_file.py</path>
<test>
the complete file
</test>"""


def tester_prompt(
    issue: str,
    sources: Mapping[str, str],
    example_test: tuple[str, str] | None,
    feedback: str = "",
) -> str:
    parts = [issue, files_block(sources)]
    if example_test is not None:
        path, text = example_test
        parts.append(f'<existing_test path="{path}">\n{clip(text, 8_000, path)}</existing_test>')
    if feedback:
        parts.append(f"<previous_attempt>\n{feedback}\n</previous_attempt>")
    return "\n\n".join(parts)


FIXER_SYSTEM = """\
You fix bugs in Python repositories. You are shown an issue, a test that reproduces it \
and fails on the current code, the test's output, and the source files most likely \
involved. Make the smallest change to the source that fixes the issue so the test passes, \
without breaking other behaviour.

Rules:
- Do not change any test file. The test is the specification.
- Each edit quotes text that occurs exactly once in the file, including its indentation, \
and gives the text to put in its place.
- Fix the cause, not the symptom the test happens to check.

Reply with one or more edits, each exactly:
<edit>
<path>relative/path.py</path>
<search>
exact existing lines
</search>
<replace>
new lines
</replace>
</edit>"""


def fixer_prompt(
    issue: str,
    test_path: str,
    test_source: str,
    test_output: str,
    sources: Mapping[str, str],
    feedback: str = "",
) -> str:
    parts = [
        issue,
        f'<test path="{test_path}">\n{test_source}</test>',
        f"<test_output_on_current_code>\n{test_output}\n</test_output_on_current_code>",
        files_block(sources),
    ]
    if feedback:
        parts.append(f"<previous_attempt>\n{feedback}\n</previous_attempt>")
    return "\n\n".join(parts)


REVIEWER_SYSTEM = """\
You review a proposed bug fix written by another model, and your job is to find what is \
wrong with it. Assume it is wrong until the evidence says otherwise. Look for:
- an input or case the issue covers that the patch does not handle;
- behaviour the patch changes that the issue did not ask to change, or a likely regression;
- a test that passes for the wrong reason or does not check what the issue reports;
- a fix aimed at the test rather than at the cause.

Accept only if you looked for each of these and found nothing that matters. Reply with \
exactly:
<verdict>accept</verdict> or <verdict>reject</verdict>
<objection>the most important problem, concretely, or "none"</objection>"""


def reviewer_prompt(
    issue: str,
    test_path: str,
    test_source: str,
    output_before: str,
    diff: str,
    output_after: str,
    suite_files: Sequence[str],
) -> str:
    suite = "\n".join(suite_files) if suite_files else "(none found)"
    return "\n\n".join(
        [
            issue,
            f'<test path="{test_path}">\n{test_source}</test>',
            f"<test_output_before_patch>\n{output_before}\n</test_output_before_patch>",
            f"<patch>\n{diff}</patch>",
            f"<test_output_after_patch>\n{output_after}\n</test_output_after_patch>",
            f"<existing_tests_run_after_patch>\n{suite}\n</existing_tests_run_after_patch>",
        ]
    )
