# Self-Healing Production AI

When a production system fails, this captures the failure with full context, drafts the
fix, has a second AI review it adversarially, and hands an engineer a ready-to-approve pull
request. Triage in minutes instead of days, engineers back on new work, and nothing changes
without a person saying yes.

**Status: building. The offline half works; nothing has been measured.** The capture,
clustering, routing and evaluation machinery is built, typed and tested. Nothing has called
a model, nothing has run against the benchmark, and every results table below is still
empty. The plan is in [PLAN.md](PLAN.md): a build measured against real open-source issues
with hidden tests.

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

Not built yet: the four hops that call models (localise, write the failing test, draft the
patch, review it), the SWE-bench harness adapter, the labelled clustering sets, and the
live workflow. Those are in [PLAN.md](PLAN.md) section 5.

Three things this is waiting on rather than choosing to skip: the benchmark harness needs
Docker, which the build laptop does not have; the chaos-trace clustering set needs project
09, which has not got there yet; and the ablations run through project 03's release
gate, whose Part B is not built.

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

[docs/boundary.md](docs/boundary.md) records what the design is built from, with sources.

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
