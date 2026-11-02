# Why the confident patches were wrong

The main run auto-proposed 51 patches and 5 failed the benchmark's hidden tests, 9.8%
(4.3% to 21.0%). A rate says how often; this says which way. Each of the five is put into
one cause from a list fixed before the first run (`mend/eval/confident_wrong.py`), or into
`unclassified`, which is counted rather than forced into a neighbour.

## Who classifies, and from what

A person, not a model. Saying why a patch was wrong means reading the maintainers' fix and
the benchmark's evaluation tests, and no model in this project reads those. The two halves
are kept in separate files:

- `uv run mend wrong worksheet` writes `runs/false-positives/worksheet.md` from the
  committed run log: the issue, mend's test and its output, the patch, the reviewer's
  verdict, a shortlist of causes from that evidence, and links to the upstream pull request
  and the benchmark row. It also writes `results/main/false-positives.yaml`, the answers
  file, if there is none yet, and the five tasks as a run log for rescoring.
- `uv run mend wrong hidden` writes `runs/false-positives/hidden.md`: the maintainers' fix,
  the hidden tests and their FAIL_TO_PASS and PASS_TO_PASS lists, from the local copy of
  SWE-bench Verified. `runs/` is ignored by git, and the command prints nothing of it.
- Optionally, `uv run mend score runs/false-positives/five.jsonl --run-id fp-rerun` reruns
  the harness on the five, with no model calls, so the per-test log shows which hidden
  tests failed. That is what separates a fix that broke something else from a fix that did
  not fix.

The answers file holds a cause and one sentence per case; a case with no sentence is
refused, so every call here is one a reader can check against the diff and disagree with.
`mend report` reads it, refuses a file that does not cover exactly the five, and writes the
table below and the one in the README.

## The causes

| Cause | Meaning |
|---|---|
| `test_proved_nothing` | the generated test passed after the patch but tested something other than the reported bug |
| `symptom_not_cause` | guarded the point of failure instead of fixing where the bad value came from |
| `regression_elsewhere` | fixed the reported case and broke one the visible suite does not cover |
| `wrong_location` | changed the wrong place |
| `issue_underspecified` | a fair reading of the issue as written, not what the maintainers meant |
| `defensible_disagreement` | reasonable behaviour the project decided differently: wording, an order, a default |
| `unclassified` | none of the above |

The shortlist in the worksheet comes from `confident_wrong.hint`. None of the five issues
carried a traceback, so the hint does not offer `wrong_location` from frame evidence; it
narrows, it does not decide.

## Result

<!-- report:false-positives -->
| Cause | What it means | Cases (95% CI) |
|---|---|---|
| test_proved_nothing | the generated test passed after the patch but tested something other than the reported bug | 0 of 5, 0.0% (0.0% to 43.4%, n = 5) |
| symptom_not_cause | guarded the point of failure instead of fixing where the bad value came from | 0 of 5, 0.0% (0.0% to 43.4%, n = 5) |
| regression_elsewhere | fixed the reported case and broke one the visible suite does not cover | 0 of 5, 0.0% (0.0% to 43.4%, n = 5) |
| wrong_location | changed the wrong place | 1 of 5, 20.0% (3.6% to 62.4%, n = 5) |
| issue_underspecified | a fair reading of the issue as written, not what the maintainers meant | 4 of 5, 80.0% (37.6% to 96.4%, n = 5) |
| defensible_disagreement | reasonable behaviour the project decided differently: wording, an order, a default | 0 of 5, 0.0% (0.0% to 43.4%, n = 5) |
| unclassified | none of the above | 0 of 5, 0.0% (0.0% to 43.4%, n = 5) |

| Task | Cause | Why |
|---|---|---|
| django__django-10999 | issue_underspecified | Mend applied the regex proposed in the issue, and its test pinned -1:-2:-3 as valid, while the hidden tests require one leading - to negate the whole duration (-15:30 is -930s) and reject inner signs like -01:-01. |
| pytest-dev__pytest-5840 | issue_underspecified | Mend's patch does load conftests with their original casing, but the FAIL_TO_PASS tests assert that _conftestpath2mod is keyed by Path(...).resolve(), an internal detail the casing issue never asked for. |
| scikit-learn__scikit-learn-14983 | issue_underspecified | Mend's repr follows the issue's expected output (n_splits, n_repeats, random_state), but the hidden test expects _build_repr's alphabetical order (n_repeats=6, n_splits=2, ...). |
| sphinx-doc__sphinx-7462 | wrong_location | Mend's empty-tuple guard in sphinx/domains/python.py matches the maintainers', but they also fixed unparse in sphinx/pycode/ast.py, which test_unparse[()-()] needs. |
| sympy__sympy-18763 | issue_underspecified | Mend's parenthesize(expr, PRECEDENCE["Mul"], strict=True) handles the issue's -x + y example, but it leaves x y bare, and the hidden test expects every Subs expression wrapped in \left(...\right), which the issue never asked for. |
<!-- /report:false-positives -->

Five cases put every count's interval wide; the table says which causes occurred, not how
often each would in general.
