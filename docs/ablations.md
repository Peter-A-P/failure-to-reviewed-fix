# Ablations: which parts of the design carry the result

PLAN.md section 1 asks for three ablations, run through project 03's release gate and
paired with the main run: no failing test first, same-vendor review, and fingerprint-only
clustering. This page says how each was run and, once they have run, what they found.

## How they are run

The ablations live in `mend/ablation/`, outside `mend/graph/`. The graph's state machine has
no edge into a patch without a failing test, and refuses a review by the fixer's own vendor.
An ablation switched on by a flag in the graph would leave a switch in the shipped pipeline
that turns those rails off. So each ablation is its own module that writes a record for
the harness and the gate, never builds a proposal, and is never called from the graph.

### No failing test first

`mend ablate no-test-first`, on 40 tasks drawn from the main run's 120 before the arm ran
(`data/subset/ablation.json`, seed 20261021, stratified by repository).

- **Taken out:** the tester. The fixer sees the issue and the source files, with no test
  and no test output, and its prompt is the main run's with the test removed.
- **Kept the same:** localisation, reused from the main run's record for each task
  ("localisation cached", PLAN.md section 6). The fixer's one retry. The baseline rule for
  the existing related tests: a patch is green when nothing that passed before fails, and
  never green when no related test exists. The different-vendor reviewer. The router, with
  the calibrated thresholds.
- **The router's test signal** is set as though a test had been shown. That is what taking
  the step out means: everything after it behaves as if it had succeeded.
- Each patch is scored by the SWE-bench harness, as in the main run. The baseline side is
  the main run's own outcome on the same 40 tasks.

### Same-vendor review

`mend ablate self-review` reviews every patch the main run sent to review (104 of 120)
twice more, on identical input:

- once by `mend-self-reviewer`, which is the fixer's own provider and model;
- once again by `mend-reviewer`, the different vendor.

The patches, their tests and their hidden-test verdicts are the main run's, so no sandbox
or harness run is needed. The run log does not keep the test's output after the patch, so
both arms see one line saying it passed, which every reviewed patch's test did. The
different-vendor reviewer is asked again, not reused, so that both arms see the same input.
How often its fresh verdict matches the main run's verdict is reported too: that is how
much a verdict moves when the same reviewer is asked again.

This sample is larger than the plan's 40. The plan sized the ablations around the sandbox,
and this one needs none, so it uses every reviewed patch for the same few dollars.

### Fingerprint-only clustering

This ablation is not run through the gate. The gate's unit is an item with a right or wrong
outcome, and a clustering is right or wrong as a partition, not record by record. It is
measured the way the clustering itself is: on each labelled set, both methods are tuned
and scored on the same held-out folds, with the paired difference
(`docs/clustering.md`).

## Through the gate

`mend ablate export <ablation>` writes `gate-runs/<ablation>/` from the committed results:

- a spec with two suites, both oriented so that higher is better;
- the main arm as the baseline;
- the ablated arm as the candidate.

For the no-test-first ablation the suites are `resolved` and `not-confidently-wrong`. For
the review ablation they are `verdict-right` (the verdict agrees with the hidden tests) and
`not-confidently-wrong`. Project 03's `gate compare` then decides with its own statistics:

- a paired bootstrap;
- Holm's adjustment across the two suites;
- the power screen;
- a decision recorded to `gate-runs/ledger.jsonl` in this repository.

The margin is ten points, set before either arm ran. At 40 tasks a paired interval on these
measures is about twelve points either side, so a three-point margin could only ever warn.

**How to read a verdict.**

- **Block:** the ablated arm could be worse than the main design by more than ten points,
  so the part taken out may be carrying the result.
- **Pass:** the ablated arm is shown to be no more than ten points worse, so that part is
  not shown to earn its place on this measure.
- **Warn:** the sample cannot decide either way.

## Results

Not yet run.
