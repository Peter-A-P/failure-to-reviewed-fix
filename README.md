# From Failure to Reviewed Fix, in Minutes

When a production system fails, this captures the failure with full context, drafts the
fix, has a second AI review it adversarially, and hands an engineer a ready-to-approve pull
request. Triage in minutes instead of days, engineers back on new work, and nothing changes
without a person saying yes.

**Status: building. The validation run is done; the main run is next.** Capture,
clustering, the four model hops, the rails between them, routing, scoring on the
benchmark's hidden tests and the evaluation machinery are built and tested. The 30-task
validation split has run and the routing thresholds were calibrated on it
([docs/routing.md](docs/routing.md)); it is the calibration split, so its numbers are not
the results below. The 120-task main run, which fills the tables, has not started. The plan is in [PLAN.md](PLAN.md): a build measured against real
open-source issues with hidden tests.

The interesting engineering is the clustering and knowing when not to act, not the model
call. The numbers below are reported as they fall.

## Result

Not yet measured. The build fills these tables.

**Resolution and restraint, on a stratified subset of SWE-bench Verified**

| Tier | Issues | Hit rate on hidden tests (95% CI) | Confidently wrong (95% CI) | Cost per attempted | Cost per resolved |
|---|---|---|---|---|---|
| Auto-propose (draft PR) | _not yet_ | | | | |
| Suggest | | | | | |
| Stay quiet | | | | | |

**Clustering and review**

| Labelled set | Symptoms per root cause | Purity / completeness | ARI (95% CI) | Test-first rate | Reviewer disagreement rate | Share of disagreements where the fixer was wrong |
|---|---|---|---|---|---|---|
| _not yet_ | | | | | | |

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

Not built yet: the duplicate-link and injected-fault clustering sets, and the live
workflow. Those are in [PLAN.md](PLAN.md) section 5.
Until the validation split has run, routing is uncalibrated and nothing auto-proposes: the
top tier is held at a suggestion.

Nothing here waits on anything outside this repository now. The chaos-trace clustering
set is recorded and read, and needs the two-stage clustering described in
[docs/clustering.md](docs/clustering.md), which is the next piece of work.

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

One of fifteen projects. It calls models through the Compliant AI
Gateway, is measured with the AI Release Gate, uses the failure traces from the Real-Time
Risk Platform's chaos runs, and inherits its agent patterns from Overload.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command and the benchmark's containers, and that reproducibility is
the evidence that matters.
