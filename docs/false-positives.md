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
Not yet classified.
<!-- /report:false-positives -->

Five cases put every count's interval wide; the table says which causes occurred, not how
often each would in general.
