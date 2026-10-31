"""The worksheet a person classifies the confidently-wrong patches from.

Two files, kept apart on purpose. worksheet() holds only what the pipeline itself saw or
wrote: the issue, the generated test and its output, the patch, the reviewer's verdict and
the hint's shortlist. hidden() holds the benchmark's own fix and its evaluation tests, read
from the local copy of SWE-bench Verified. No model in this project reads the second file,
which is why it is written by a command a person runs (mend wrong hidden), into runs/,
which git ignores, and never printed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from mend.eval.confident_wrong import MEANING, Cause, hint

HF_VIEWER = "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/viewer/default/test"
RERUN_ID = "fp-rerun"


def pull_request(issue_id: str, repo: str) -> str:
    """SWE-bench names each task after the pull request that fixed it."""
    return f"https://github.com/{repo}/pull/{issue_id.rsplit('-', 1)[1]}"


def _fence(text: str, lang: str = "") -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


GUIDE = f"""\
## How to decide, in this order

Take the first question that answers yes. Look at the maintainers' fix and tests
(`hidden.md`, or the pull request link) next to mend's patch and test below.

1. **Did the maintainers change a different function or file?** Then `wrong_location`.
2. **Does mend's test check something other than what the hidden FAIL_TO_PASS tests check?**
   It passed, so it pinned the wrong behaviour. Then `test_proved_nothing`.
3. **Did only PASS_TO_PASS tests fail** (the fix worked, something else broke)? Then
   `regression_elsewhere`. Step 2 above tells you which tests failed.
4. **Did the maintainers fix it further upstream** than mend's guard or special case? Then
   `symptom_not_cause`.
5. **Do the hidden tests expect something the issue never asked for?** Then
   `issue_underspecified`.
6. **Are both behaviours reasonable and the tests pin one choice** (a message's wording, an
   order, a default, a repr)? Then `defensible_disagreement`.
7. None of these: `unclassified`, and say why in the note.

| Cause | Meaning |
|---|---|
{chr(10).join(f"| `{c.value}` | {MEANING[c]} |" for c in Cause)}
"""


def worksheet(
    cases: Sequence[Mapping[str, Any]], *, answers: str, five: str, rerun_dir: str
) -> str:
    ids = [str(r["issue"]["issue_id"]) for r in cases]
    out = [
        "# Why the confident patches were wrong: worksheet",
        "",
        f"{len(cases)} patches were auto-proposed in the main run and failed the benchmark's "
        "hidden tests. For each, pick one cause and write one sentence. About 15 to 30 minutes "
        "a case.",
        "",
        "## Steps",
        "",
        "1. Write the hidden side (the maintainers' fix and tests) next to this file. It stays "
        "out of git and out of any model's sight:",
        "",
        "   ```powershell",
        "   uv run mend wrong hidden",
        "   ```",
        "",
        "   then open [hidden.md](hidden.md). Each case below also links the upstream pull "
        "request and the Hugging Face row, if you prefer the browser.",
        "2. Optional, but it settles question 3 below: rerun the harness on these five to see "
        "which hidden tests failed. No model calls; needs Docker Desktop running and about "
        "15 minutes:",
        "",
        "   ```powershell",
        "   uv sync --extra bench",
        f"   uv run mend score {five} --run-id {RERUN_ID}",
        "   ```",
        "",
        f"   Each case's log is then at `{rerun_dir}/<task>/test_output.txt`, with "
        "`report.json` beside it listing every hidden test as passed or failed.",
        f"3. Fill in [{Path(answers).name}](../../{answers}): `cause` and `note` for each case.",
        "4. Tell Claude it is done. It runs `mend report`, which checks the file and writes the "
        "table into the README and docs/false-positives.md.",
        "",
        GUIDE,
        "## Cases",
        "",
        *(f"- [{i}](#{i.replace('.', '')})" for i in ids),
        "",
    ]
    for run in cases:
        out += _case(run, rerun_dir)
    return "\n".join(out)


def _case(run: Mapping[str, Any], rerun_dir: str) -> list[str]:
    issue = run["issue"]
    state = run["state"]
    patch = state.get("patch") or {}
    test = state.get("test") or {}
    review = state.get("review") or {}
    issue_id = str(issue["issue_id"])
    repo = str(issue["repo"])
    commit = str(issue["commit"])
    pr = pull_request(issue_id, repo)
    shortlist = hint(
        files_touched=len(patch.get("files_touched") or ()),
        lines_changed=int(patch.get("lines_changed") or 0),
        touches_traceback_frames=bool(patch.get("touches_traceback_frames")),
        suite_green=bool(patch.get("suite_green")),
        reviewer_objected=review.get("agrees") is False,
        issue_has_traceback=bool(issue.get("frame_files")),
    )
    files = patch.get("files_touched") or []
    lines = [
        f"## {issue_id}",
        "",
        f"- Upstream fix and tests: [{pr}]({pr}) ([files changed]({pr}/files))",
        f"- Hidden side, local: [hidden.md](hidden.md#{issue_id.replace('.', '')})",
        f"- Benchmark row: [{HF_VIEWER}?q={issue_id}]({HF_VIEWER}?q={issue_id})",
        f"- Code before the fix: [{repo} at {commit[:10]}](https://github.com/{repo}/tree/{commit})",
        *(f"  - [{f}](https://github.com/{repo}/blob/{commit}/{f})" for f in files),
        f"- Harness log after step 2: `{rerun_dir}/{issue_id}/test_output.txt`",
        "",
        "**What the record says.** "
        f"{len(files)} file(s), {patch.get('lines_changed')} lines changed; the related "
        f"existing tests {'passed' if patch.get('suite_green') else 'did not all pass'}; "
        f"the reviewer ({review.get('reviewer_provider')}) "
        f"{'agreed' if review.get('agrees') else 'objected'}"
        + (f": {review['objection'].strip()}" if (review.get("objection") or "").strip() else "")
        + ". Routed to auto-propose at score "
        f"{float(state.get('score') or 0):.2f}.",
        "",
        "**Shortlist from the evidence** (a starting point, not a decision): "
        + (
            "none; the evidence on the record does not narrow it"
            if len(shortlist) == len(Cause)
            else ", ".join(f"`{c.value}`" for c in shortlist)
        )
        + (
            ". The issue had no traceback, so location is not narrowed."
            if not issue.get("frame_files")
            else "."
        ),
        "",
        "### The issue, as the pipeline saw it",
        "",
        f"**{issue.get('title')}**",
        "",
        "<details><summary>Issue text</summary>",
        "",
        _fence(str(issue.get("body") or "")),
        "",
        "</details>",
        "",
        f"### mend's test: `{test.get('test_id')}`",
        "",
        f"Failed on the broken commit: {test.get('failed_on_broken_commit')}. Passed after the "
        f"patch: {patch.get('test_passes')}.",
        "",
        _fence(str(test.get("source") or ""), "python"),
        "",
        "<details><summary>Its output on the broken commit</summary>",
        "",
        _fence(str(test.get("output") or "")),
        "",
        "</details>",
        "",
        "### mend's patch",
        "",
        _fence(str(patch.get("diff") or ""), "diff"),
        "",
        "### Your call",
        "",
        "In the answers file: `cause:` one of the values above, `note:` one sentence.",
        "",
    ]
    return lines


def hidden(tasks: Iterable[Mapping[str, Any]], issue_ids: Sequence[str]) -> str:
    """The benchmark's fix and evaluation tests for issue_ids. For a person only."""
    by_id = {str(t["instance_id"]): t for t in tasks}
    missing = [i for i in issue_ids if i not in by_id]
    if missing:
        raise KeyError(f"not in the local SWE-bench Verified copy: {missing}")
    out = [
        "# The hidden side: the maintainers' fix and the benchmark's tests",
        "",
        "For the person classifying. Never committed, never shown to a model. Go back to "
        "[the worksheet](worksheet.md).",
        "",
    ]
    for issue_id in issue_ids:
        t = by_id[issue_id]
        fail_to_pass = _tests(t["FAIL_TO_PASS"])
        pass_to_pass = _tests(t["PASS_TO_PASS"])
        out += [
            f"## {issue_id}",
            "",
            f"Upstream: {pull_request(issue_id, str(t['repo']))}. Difficulty as labelled: "
            f"{t.get('difficulty')}.",
            "",
            f"**FAIL_TO_PASS** ({len(fail_to_pass)}): these must go from failing to passing.",
            "",
            *(f"- `{name}`" for name in fail_to_pass),
            "",
            f"<details><summary>PASS_TO_PASS ({len(pass_to_pass)}): must keep passing</summary>",
            "",
            *(f"- `{name}`" for name in pass_to_pass),
            "",
            "</details>",
            "",
            "### The maintainers' fix",
            "",
            _fence(str(t["patch"]), "diff"),
            "",
            "### The hidden tests",
            "",
            _fence(str(t["test_patch"]), "diff"),
            "",
        ]
        if str(t.get("hints_text") or "").strip():
            out += [
                "<details><summary>Discussion on the issue before the fix</summary>",
                "",
                _fence(str(t["hints_text"])),
                "",
                "</details>",
                "",
            ]
    return "\n".join(out)


def _tests(value: Any) -> list[str]:
    return [str(x) for x in (json.loads(value) if isinstance(value, str) else value)]
