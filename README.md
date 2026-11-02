# From Failure to Reviewed Fix, in Minutes

When a production system fails, this captures the failure with full context, drafts the
fix, has a second AI review it adversarially, and hands an engineer a ready-to-approve pull
request. Triage in minutes instead of days, engineers back on new work, and nothing changes
without a person saying yes.

**Status: measured.** The 120-task main run on SWE-bench Verified is done and scored on
the benchmark's hidden tests, the routing was calibrated beforehand on a separate 30-task
validation split, and the clustering is measured on all three labelled sets the plan names:
project 09's recorded chaos runs, injected faults, and maintainers' duplicate links. Two
ablations, no failing test first and same-vendor review, went through project 03's release
gate. The
tables below are written by `mend report` from the files in [results/](results/), not by
hand. The plan is in [PLAN.md](PLAN.md).

The interesting engineering is the clustering and knowing when not to act, not the model
call. The numbers below are reported as they fell.

## Result

**Resolution and restraint: 120 tasks from SWE-bench Verified, sampled before any run
(seed 20261017), judged by the benchmark's hidden tests**

<!-- report:resolution -->
| Tier | Issues | Hit rate on hidden tests (95% CI) | Confidently wrong (95% CI) | Cost per attempted (95% CI) | Cost per resolved (95% CI) |
|---|---|---|---|---|---|
| Auto-propose (draft PR) | 51 | 90.2% (79.0% to 95.7%, n = 51) | 9.8% (4.3% to 21.0%, n = 51) | US$0.151 (0.130 to 0.173, n = 51) | US$0.168 (0.141 to 0.198, n = 51) |
| Suggest | 34 | 61.8% (45.0% to 76.1%, n = 34) |  | US$0.176 (0.151 to 0.202, n = 34) | US$0.285 (0.221 to 0.395, n = 34) |
| Stay quiet | 35 | 40.0% (25.6% to 56.4%, n = 35) |  | US$0.147 (0.116 to 0.181, n = 19) | US$0.423 (0.269 to 0.754, n = 35) |
| **All** | 120 | 67.5% (58.7% to 75.2%, n = 120) | 9.8% (4.3% to 21.0%, n = 51) of auto-proposals | US$0.159 (0.144 to 0.175, n = 104) | US$0.242 (0.208 to 0.288, n = 120) |
<!-- /report:resolution -->

**Test-first and review, same 120 tasks**

<!-- report:review -->
| Test-first rate (95% CI) | Reviewer objected (95% CI) | Patch wrong when the reviewer objected | Patch wrong when it agreed | Stay-quiet precision (95% CI) |
|---|---|---|---|---|
| 96.7% (91.7% to 98.7%, n = 120) | 38.5% (29.7% to 48.1%, n = 104) | 40.0% (26.3% to 55.4%, n = 40) | 10.9% (5.4% to 20.9%, n = 64) | 26.3% (11.8% to 48.8%, n = 19) |
<!-- /report:review -->

**Clustering: project 09's chaos runs, 8 injected faults, 373 symptoms, every way of
holding 3 faults out**

<!-- report:clustering -->
| Labelled set | Method | Held-out ARI, mean | Spread across folds (not a CI) |
|---|---|---|---|
| 09 chaos runs (8 faults, 373 symptoms) | Record-level (fingerprint, text, locality) | 0.032 | 0.009 to 0.055 |
| 09 chaos runs (8 faults, 373 symptoms) | Fingerprint only | 0.021 | 0.004 to 0.044 |
| 09 chaos runs (8 faults, 373 symptoms) | Two-stage (incidents, then signatures) | 0.636 | 0.136 to 0.991 |
| 09 chaos runs (8 faults, 373 symptoms) | Two-stage minus record-level, paired | 0.604 | 0.125 to 0.956; higher on 56 of 56 folds |
<!-- /report:clustering -->

**Clustering: injected faults in two libraries' test suites, and issues maintainers closed
as duplicates in three trackers; five folds by cause, 95% intervals from a delete-one-cause
jackknife ([docs/clustering.md](docs/clustering.md))**

<!-- report:clustering-sets -->
| Labelled set | Method | ARI (95% CI) | Purity (95% CI) | Completeness (95% CI) | Symptoms per ticket (95% CI) |
|---|---|---|---|---|---|
| Injected faults (40 causes, 404 symptoms) | Record-level (fingerprint, text, locality) | 0.568 (0.352 to 0.784) | 96.8% (93.2% to 100.0%) | 51.7% (36.9% to 66.5%) | 2.07 (1.42 to 2.73) |
| Injected faults (40 causes, 404 symptoms) | Fingerprint only | 0.522 (0.291 to 0.753) | 99.3% (97.8% to 100.0%) | 45.0% (30.0% to 60.1%) | 1.65 (1.23 to 2.07) |
| Injected faults (40 causes, 404 symptoms) | Record-level minus fingerprint, paired | 0.046 (-0.004 to 0.096) | higher on 5 of 5 folds | | |
| Injected faults, sentence encoder (40 causes, 404 symptoms) | Record-level (fingerprint, text, locality) | 0.568 (0.353 to 0.783) | 96.3% (92.7% to 99.8%) | 52.0% (37.1% to 66.9%) | 2.09 (1.41 to 2.78) |
| Injected faults, sentence encoder (40 causes, 404 symptoms) | Record-level minus fingerprint, paired | 0.046 (-0.003 to 0.096) | higher on 5 of 5 folds | | |
| Duplicate links (639 causes, 1378 symptoms) | Record-level (fingerprint, text, locality) | 0.086 (0.059 to 0.112) | 96.9% (95.7% to 98.1%) | 49.3% (48.2% to 50.5%) | 1.06 (1.05 to 1.08) |
| Duplicate links (639 causes, 1378 symptoms) | Fingerprint only | 0.017 (0.016 to 0.019) | 13.2% (11.3% to 15.1%) | 93.6% (92.3% to 95.0%) | 11.11 (9.19 to 13.04) |
| Duplicate links (639 causes, 1378 symptoms) | Record-level minus fingerprint, paired | 0.069 (0.042 to 0.095) | higher on 5 of 5 folds | | |
| Duplicate links, sentence encoder (639 causes, 1378 symptoms) | Record-level (fingerprint, text, locality) | 0.516 (0.470 to 0.562) | 92.2% (90.1% to 94.4%) | 71.8% (69.7% to 73.8%) | 1.47 (1.42 to 1.53) |
| Duplicate links, sentence encoder (639 causes, 1378 symptoms) | Record-level minus fingerprint, paired | 0.499 (0.453 to 0.545) | higher on 5 of 5 folds | | |
<!-- /report:clustering-sets -->

**Ablations: one part of the design taken out, everything else unchanged, decided by
project 03's release gate at a ten-point margin set before the runs
([docs/ablations.md](docs/ablations.md))**

<!-- report:gate -->
| Ablation | Suite | Paired tasks | Main design | Ablated | Ablated minus main (95% CI) | Gate verdict at a 10-point margin |
|---|---|---|---|---|---|---|
| No failing test first | resolved | 40 | 65.0% | 67.5% | +2.5 (-12.5 to +17.5) points | block |
| No failing test first | not-confidently-wrong | 40 | 95.0% | 95.0% | +0.0 (-7.5 to +7.5) points | pass |
| Same-vendor review | verdict-right | 104 | 67.3% | 76.0% | +8.7 (-1.0 to +18.3) points | pass |
| Same-vendor review | not-confidently-wrong | 104 | 95.2% | 92.3% | -2.9 (-7.7 to +1.0) points | pass |
<!-- /report:gate -->

*Same-vendor review: all 104 patches the main run reviewed, reviewed again on identical
input by each vendor; the patches and their hidden-test verdicts are the main run's*

<!-- report:ablation-review -->
| Reviewer | Objected | Caught: objected to a patch the hidden tests failed | False alarm: objected to a patch they passed | Verdict matched the hidden tests | Confidently wrong among auto-proposals |
|---|---|---|---|---|---|
| Different vendor, main run | 38.5% (29.7% to 48.1%, n = 104) | 69.6% (49.1% to 84.4%, n = 23) | 29.6% (20.8% to 40.3%, n = 81) | 70.2% (60.8% to 78.1%, n = 104) | 9.8% (4.3% to 21.0%, n = 51) |
| Different vendor, asked again | 41.3% (32.4% to 51.0%, n = 104) | 69.6% (49.1% to 84.4%, n = 23) | 33.3% (24.0% to 44.1%, n = 81) | 67.3% (57.8% to 75.6%, n = 104) | 10.2% (4.4% to 21.8%, n = 49) |
| Same vendor: the fixer's own model | 26.9% (19.3% to 36.2%, n = 104) | 56.5% (36.8% to 74.4%, n = 23) | 18.5% (11.6% to 28.3%, n = 81) | 76.0% (66.9% to 83.2%, n = 104) | 12.7% (6.6% to 23.1%, n = 63) |

The different-vendor reviewer gave the same verdict when asked again on 93.3% (86.8% to 96.7%, n = 104) of the patches; the two vendors agreed on 77.9% (69.0% to 84.8%, n = 104).
<!-- /report:ablation-review -->

*No failing test first: 40 of the main run's tasks, drawn before the arm ran (seed
20261021), localisation reused from the main run, each patch scored on the hidden tests*

<!-- report:ablation-test-first -->
| Arm | Resolved on hidden tests | Patches drafted | Auto-proposed | Confidently wrong among auto-proposals | Model cost per task |
|---|---|---|---|---|---|
| Failing test first (main run, same tasks) | 65.0% (49.5% to 77.9%, n = 40) | 36 | 18 | 11.1% (3.1% to 32.8%, n = 18) | US$0.170 |
| No failing test first | 67.5% (52.0% to 79.9%, n = 40) | 40 | 21 | 9.5% (2.7% to 28.9%, n = 21) | US$0.080 |

Task by task: 22 resolved by both, 4 only with the test first, 5 only without it.
<!-- /report:ablation-test-first -->

### The honest limitation

**The confidently-wrong target was missed.** The plan set at most 3% of auto-proposed
patches failing the hidden tests. The main run auto-proposed 51 and 5 of them failed, 9.8%
(4.3% to 21.0%). The thresholds were calibrated on 30 tasks where every patch that passed
the router's rules was right, so the score had nothing to separate and the calibration
could not have caught this; [docs/routing.md](docs/routing.md) said so before the main
run. A 3% rate is not demonstrated here, and on this evidence the system should open
suggestions, not draft pull requests.

Why each of the five was wrong, classified by hand against the benchmark's own fix and
tests into causes fixed before the first run
([docs/false-positives.md](docs/false-positives.md)):

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

**Four of the five did what the issue asked.** They were fair readings of an issue that
left out what the maintainers' tests check: a field order, an internal cache key, every
case wrapped rather than the one shown, and a regex the issue itself proposed. The fifth
fixed one of the two places the bug lived. Five cases are too few to rank the causes; they
do say the generated test is only as good as the issue it is written from.

**Restraint costs a lot.** Of the 35 tasks routed to silence, 14 had a patch the hidden
tests accepted. Most were patches with no related existing test to check against, which
the router reads, cautiously, as "not shown safe".

**The different-vendor rule is not shown to matter.** All 104 reviewed patches were
reviewed again by the fixer's own model. Its objections are as good a sign of a wrong
patch as the other vendor's: 46% of the patches it objected to were wrong, against 37%. It
objects less often, so it lets three more wrong patches through to auto-propose. The
release gate could not tell the two reviewers apart at a ten-point margin, so the rule
stays as a design choice the evidence leans towards, not one it proves.

**The failing test first is not shown to make the fixes better.** On 40 of the main run's
tasks, the same pipeline without the tester:

- resolved 27 against the main run's 26;
- auto-proposed 21 patches with 2 wrong, against 18 with 2 wrong;
- cost half as much in model calls.

The release gate blocked only because 40 tasks leave a wide interval. Its estimate
favoured the arm without the test. The test stays because it is what the pull request
shows a person, and because the graph refuses to patch without one. It is not what makes
the patches right.

**Where it is weak.** Sympy resolved 6 of 18; the fixer often could not make its own
failing test pass. Django, 55 of the 120, resolved 42.

**What the clustering results do and do not show.**

- **Production signals (09's chaos runs).** Comparing symptoms one at a time does not find
  root causes, and grouping them into incidents first does. That set has eight faults, so
  the spread is wide.
- **Tracebacks from injected faults.** The full method finds about half of each fault, and
  the fingerprint alone does nearly as well.
- **Human reports of one bug.** Only 8% of these reports hold a traceback, so the text is
  all there is. The full method finds about half of the duplicate pairs with a trained
  sentence encoder, ARI 0.516. With the default hashed text embedding it finds almost
  none, 0.086. The encoder was tried after the hashing result was seen.

None of the sets has incidents that overlap in time.

**Rejected:** record-level clustering for production signals, in
[docs/rejected.md](docs/rejected.md).

## What is built, and what is not

Built, tested, and reproducible today with `uv sync && uv run pytest`:

- **Capture.** A failure record shared by three ingesters: pytest JUnit XML, OpenTelemetry
  spans and logs, and GitHub issues. Traceback parsing, path and message normalisation,
  and stable record ids so re-ingesting a report does not inflate the symptom count.
- **Clustering.** Fingerprint, failure-text embeddings and code locality, combined into one
  distance and cut by average linkage. Purity, completeness and adjusted Rand index with
  bootstrap intervals, and a tuner that chooses the threshold on a validation split by root
  cause and publishes the whole sweep. See [docs/clustering.md](docs/clustering.md).
- **The rails.** A state machine with no edge into a patch except from a test that was run
  and observed to fail, no terminal state that means merged, and a refusal to review a
  patch with a model from the fixer's own vendor.
- **Routing.** The confidence score, the three tiers, the trade-off curve, and a
  calibration that picks the lowest threshold meeting a stated false-positive target and
  will not hit that target by proposing almost nothing.
- **The sandbox specification.** One container per task, no network, memory, process and
  time limits, asserted as properties of the specification so they hold without a daemon.
- **The measurement.** Wilson and bootstrap intervals, the tier table, reviewer value, the
  false-positive taxonomy, and the subset sampler that refuses to be resampled after a run.

- **The pipeline.** A LangGraph graph of intake, localise, write the failing test, draft
  the patch, review, route and act, with every move made through the state machine above.
  The localiser reads paths and identifier mentions on the cheap model; the tester writes
  one new test file that must fail in its body (not error) on the broken commit, with one
  retry that is told why; the fixer returns search-and-replace edits, may not touch a test
  file, and its patch must pass the new test without breaking any existing test that
  passed before; the reviewer, on another vendor, is told to find what is wrong. Tested
  end to end with scripted models and a scripted sandbox, including the attempts to get a
  patch out without a failing test, which never reach the fixer.
- **09's chaos captures as a labelled set.** Log errors and metric departures from each
  of project 09's chaos runs become records, labelled by the injected fault. The reader
  finds each run's steady state from the metrics and never reads when the fault was
  injected. See [docs/clustering.md](docs/clustering.md).
- **The sandbox workspace.** A host copy of the task image's repository for reading, and
  a fresh no-network container per test run, with the diff and the new test mounted
  read-only. No code path runs a model's test on the host.

- **Scoring on the hidden tests.** `mend score` submits every drafted patch, whatever its
  tier, to the official SWE-bench harness and reads back one verdict per task. A task the
  harness could not judge is never counted as unresolved; it has to be run again. The
  harness runs in a Linux container of its own, because on a Windows host it writes scripts
  bash cannot run and even the benchmark's reference patches fail.
- **Resumable runs over a committed subset.** `mend run` works through a subset file task
  by task: fix, score on the hidden tests, remove the image. A crash costs one task, and a
  resume never runs a task's fix twice. The subset (seed 20261017, 30 validation and 120
  main) is committed in [data/subset/](data/subset/).
- **Each repository's own test runner.** Django and sympy, 61% of SWE-bench Verified, do
  not run their tests with pytest; the sandbox uses each project's documented runner and
  reads its output with the harness's own parsers.

- **The other two labelled sets.** Injected faults: two libraries checked out at pinned
  commits, one mutation at a time, and every test it breaks kept as a symptom of that
  fault. Duplicate links: issues the pandas, matplotlib and numpy maintainers closed as
  duplicates, linked to their originals. Only the ids and links are committed; the issue
  text stays local.
- **The ablations.** No failing test first, and the fixer's own model as the reviewer, both
  run outside the graph so the graph keeps no switch that turns a rail off, and both handed
  to project 03's release gate. See [docs/ablations.md](docs/ablations.md).

- **The live workflow.** A failing pull request in 03's or 04's repository is rerun in the
  sandbox, triaged, and answered with a comment: comments only, scoped to the repository it
  runs in, US$1.00 an issue. Installed in both on 2026-10-31; three runs have commented,
  for US$0.59 in all. The US$1.50 running total per repository does not yet survive from
  one run to the next: the job's token may not write the Actions cache it is kept in. See
  [docs/live.md](docs/live.md).

## What this does not do

- It does not merge. There is no merge path in the code, and
  [a test](tests/test_no_merge_path.py) scans every source file to assert it.
- It does not patch without proof. A failing test that demonstrates the bug comes first, or
  the system stops and says why. The state machine has no way round it.
- It does not review its own vendor's work. The reviewer alias resolves to a different
  provider than the fixer, checked at start-up and asserted against the shipped
  configuration.
- It does not chase a leaderboard. The hit rate on hidden tests is what it is; the
  confidently-wrong analysis matters more.
- It is Python only in this version, because the benchmark and the sandbox are.

## How it works

Failures arrive as test results, traces and logs and become structured records. Clustering
by fingerprint, failure-text embeddings and code locality turns many symptoms into one
ticket, measured against maintainers' own duplicate links, injected faults with known
causes, and recorded chaos runs. For each ticket the system localises the fault, writes a
test that must fail on the broken commit, drafts a patch that must pass it and the existing
suite, and sends the result to a reviewer model from a different vendor whose job is to
break it. A routing score with thresholds calibrated against a stated false-positive target
decides whether to open a draft pull request, leave a suggestion, or stay quiet. Every
model call goes through the portfolio gateway with a spend cap per issue; every comparison
runs through the release gate with intervals.

[docs/boundary.md](docs/boundary.md) records what the design is built from, with sources. Three
architecture diagrams, the system, one failure through the pipeline and how the numbers are produced, are
in [docs/architecture.md](docs/architecture.md).

## Installing and running

```
uv sync
uv run pytest
uv run mend --help
```

That installs the offline half, which needs no keys and makes no network call. The hops
that call models need the portfolio gateway as well:

```
uv sync --extra gateway
uv run mend roles          # resolves the four aliases, checks the vendor split, calls nothing
uv run mend ping           # one short paid call per role, capped and ledgered
```

The keys come from the environment or a gitignored `.env`: `ANTHROPIC_API_KEY` for the
localiser, tester and fixer, `OPENAI_API_KEY` for the reviewer. One benchmark task through
the whole pipeline, in its sandbox (needs Docker and the task's harness image):

```
uv run mend fix data/swebench/verified.jsonl --instance django__django-11099
```

A committed subset, end to end and resumable, removing each task's image after it is
scored:

```
uv run mend run data/subset/validation.json
```

Scoring a run log on the hidden tests, with the official harness (needs Docker; the
harness runs in a container `mend score` builds once):

```
uv run mend score runs/fix.jsonl --run-id my-run
```

Clustering a set of captured records, and measuring it against known causes:

```
uv run mend capture pytest report.xml --out records.jsonl --marker pkg/
uv run mend cluster run records.jsonl --threshold 0.6
uv run mend cluster metrics records.jsonl --threshold 0.6
```

## Part of a portfolio

One of 16 projects. It calls models through the
[Compliant AI Gateway](https://github.com/Peter-A-P/compliant-ai-gateway), is measured with
the [AI Release Gate](https://github.com/Peter-A-P/ai-release-gate), uses the failure traces
from the [Real-Time Risk Platform](https://github.com/Peter-A-P/realtime-risk-platform)'s
chaos runs, and inherits its agent patterns from Overload.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command and the benchmark's containers, and that reproducibility is
the evidence that matters.
