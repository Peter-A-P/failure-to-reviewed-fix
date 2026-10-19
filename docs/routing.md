# Routing: the thresholds, and the curve they were read from

**Calibrated 2026-10-19 on the validation split** (`data/subset/validation.json`, 30 tasks
from SWE-bench Verified, seed 20261017), with `mend calibrate runs/validation`. The chosen
thresholds are in `config/mend.thresholds.yaml`, which refuses to be overwritten; the run
they were chosen on is committed in [results/validation/](../results/validation/). The main
run uses them without having seen its own outcomes.

## What was chosen

The target is at most 3% confidently wrong among auto-proposed patches (PLAN.md section
2.5). The procedure, fixed in September before any run (`mend.graph.route.calibrate`), takes
the lowest threshold that meets the target with at least five auto-proposals.

| | Value |
|---|---|
| Auto-propose (draft pull request) at a score of | 0.00 |
| Suggest at a score of | 0.00 |
| Auto-proposed on validation | 15 of 30 |
| Confidently wrong among them (95% CI) | 0.0% (0.0% to 20.4%, n = 15) |

Read the interval, not the point. Fifteen proposals cannot demonstrate a 3% rate; the
upper bound is 20%. What the validation split shows is that nothing contradicted the
target, and the main run is where it is tested.

## The curve

Only patches the router could propose at all are counted: the failing test now passes, the
existing suite stayed green, and the reviewer agreed. A reviewer who objects caps a patch at
a suggestion, and a patch whose suite is not green is never proposed, whatever it scores.

| Threshold from | Auto-proposed | Resolved | Confidently wrong (95% CI) | Coverage |
|---|---|---|---|---|
| 0.00 | 15 | 15 | 0.0% (0.0% to 20.4%, n = 15) | 50% |
| 0.82 | 0 | 0 | none proposed | 0% |

## What the curve says, plainly

**On this split the score does no work; the rules do.** The fifteen patches that passed
every rule all scored 0.81, so every threshold from 0.00 to 0.81 proposes the same fifteen,
and the procedure's "lowest" rule lands on 0.00. Choosing anything else now would be a
choice made after seeing the result, so the procedure's answer stands. The consequence for
the main run is stated in advance: any patch there that passes every rule is proposed as a
draft pull request whatever its size, because nothing on validation gave the size penalties
in the score a case to answer. If large patches turn out to be the confidently wrong ones,
that will show in the main run's false-positive analysis, and it will be reported there.

The rest of the validation split, for context (`results/validation/`):

| Evidence on the patch | Reviewer | Tasks | Resolved on hidden tests |
|---|---|---|---|
| Test fixed, suite green | agreed | 15 | 15 |
| Test fixed, suite green | objected | 7 | 5 |
| Test fixed, suite not shown green | agreed | 3 | 2 |
| Test fixed, suite not shown green | objected | 2 | 0 |
| No patch: the fixer could not make its test pass | | 3 | 0 |

Two things in that table are worth carrying forward. The reviewer's objections were right
2 times in 7 when the suite was green, so a suggestion is the right place for an objected
patch: most of them are fine and a person should look. And four of the five "suite not
shown green" patches had no related existing test found at all (`suite_files` is empty),
not a regression; the router treats "nothing to check against" as "not shown green", which
is the cautious reading, and one of those four was in fact right. The fifth had related
tests that failed after the patch, and the hidden tests passed it anyway.
