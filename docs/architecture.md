# Architecture

Four figures: the system as a whole, one failure through the pipeline, how the numbers are
produced, and the live workflow on two of the portfolio's repositories. Each names the module
that implements what it shows; [PLAN.md](../PLAN.md) says why and [boundary.md](boundary.md)
records the public sources the design is built from.

## The system

![Failures arrive as test results, traces, logs and issues and become one kind of record; clustering turns many symptoms into one ticket; a state machine allows no patch except from a test observed to fail, sends the patch to a reviewer from a different vendor, and routes it into a draft pull request, a suggestion or silence; every model call goes through the gateway with a cap per issue, every test runs in a sandbox with no network, and the evaluation scores the outcomes on hidden tests.](architecture/system.svg)

Failures arrive as pytest JUnit XML, OpenTelemetry spans and logs, or GitHub issues, and become
one failure record with the traceback parsed, paths and messages normalised and a stable id, so
reading a report twice cannot inflate the symptom count. Clustering turns many records into one
ticket per root cause: symptoms that began together are first grouped into incidents, then
incidents and tracebacks are compared by fingerprint, failure text and code locality. Its
quality is measured against three labelled sets: project 09's chaos runs, injected faults and
maintainers' duplicate links. The middle column is the state machine. A cheap model localises
the fault; a test is written that must fail on the broken commit, or the run stops; a patch is
drafted that must pass that test and the existing suite in the sandbox (one container per run,
no network, limits); and a reviewer whose alias resolves to a different vendor from the fixer,
checked at start-up, tries to break it. An objection caps the patch at a suggestion. The router
sends what is left to a draft pull request, a suggestion or silence. There is no edge into a
patch except from a failing test and no state that means merged. Every model call goes through
project 04's gateway with a US$1 cap per issue, and the evaluation scores every drafted patch on
the benchmark's hidden tests.

Where it lives: `mend.capture`, `mend.cluster`, `mend.graph.machine`, `mend.graph.graph`, `mend.graph.route`, `mend.sandbox`, `mend.gateway`, `mend.eval`, `config/mend.routes.yaml`, `tests/test_no_merge_path.py`.

## One failure through the pipeline

![An alert storm is captured as records and clustered into one ticket; the fault is localised, a test is written that must fail on the broken commit or the system stops, a patch is drafted that must pass it and the suite in a sandbox, a reviewer from another vendor tries to break it, and the router decides between a draft pull request, a suggestion and silence.](architecture/one-failure.svg)

Twenty symptoms of one bug arrive, are captured as records and clustered into one ticket, and
the largest ticket goes first. The localiser, the cheap model, reads the failure and searches the
repository. The tester writes a test that must be observed to fail on the broken commit; if it
does not, the system stops and says why, because the state machine has no way round it. The
fixer drafts a patch that must pass the new test and the existing suite in the sandbox. The
reviewer, a model from another vendor, tries to break it, and an objection caps the patch at a
suggestion. The router reads the evidence against rules set before the run: above the line a
draft pull request is opened for an engineer to approve, or not; below it the system leaves a
suggestion or stays quiet.

Where it lives: `mend.graph.localise`, `mend.graph.test_first`, `mend.graph.patch`, `mend.graph.review`, `mend.graph.route`, `mend.graph.act`, `mend.sandbox.workspace`.

## How the numbers are produced

![120 SWE-bench Verified tasks, drawn with a fixed seed and committed before any run, go through the pipeline and are judged by the official harness on hidden tests no model reads; the outcomes give the hit rate, the confidently-wrong rate and its five cases classified by hand, the gateway ledger gives the cost, three labelled sets give the clustering quality, and the ablations go through project 03's release gate; the report command writes every README table with Wilson or bootstrap intervals.](architecture/measurement.svg)

The 120 tasks were drawn from SWE-bench Verified with seed 20261017 and committed before the
first run, with a separate 30 for calibrating the router. Each goes through the pipeline and then
the official SWE-bench harness, which judges the patch on the benchmark's hidden tests in a Linux
container; no model ever reads those tests. The outcomes give the hit rate and cost per tier.
The five proposals that failed the hidden tests were classified by Peter against the
maintainers' fixes, into causes fixed before the run. The clustering metrics come from tuning the
cut on some causes and scoring it on causes held out. The two ablations, no failing test first
and the fixer's own vendor as reviewer, go through project 03's release gate as paired
comparisons. One command, `mend report`, writes every README table from those files, and
`mend site` writes this site's numbers from the same files.

Where it lives: `mend.data.swebench`, `mend.sandbox.harness`, `mend.eval.results`, `mend.eval.confident_wrong`, `mend.cluster.crossval`, `mend.ablation`, `mend.eval.report`, `mend.site`.

## The live workflow

![When ci fails on a pull request in project 03's or 04's repository, the caller starts the reusable workflow, which reads earlier runs' spending from their artifacts and stops if the repository's US$1.50 is spent, builds an image from the failing commit, reruns the suite in a container with no network, clusters the failures, sends the largest ticket through the unchanged pipeline with every call through the gateway, and posts the result as a comment; it never pushes, opens a pull request or merges, and uploads its record for the next run.](architecture/live.svg)

When ci fails on a pull request in project 03's or 04's repository, the caller in that
repository starts the reusable workflow. It first reads every earlier run's spending from their
artifacts and stops if the repository's US$1.50 is spent. It builds an image from the failing
commit with the repository's own install command, the one step with network access, and reruns
the suite in a container with the network off. The failures are captured and clustered, and the
largest ticket goes through the same pipeline as the benchmark, every call through the gateway.
The result is posted as a comment on the pull request, and the job's token cannot push, so it
never opens a pull request or merges. Each run uploads its log, its JUnit report and its
spending for the next run to read.

Where it lives: `.github/workflows/live.yml`, `action/`, `mend.live.scope`, `mend.live.budget`, `mend.live.image`, `mend.live.run`, `mend.live.comment`.
