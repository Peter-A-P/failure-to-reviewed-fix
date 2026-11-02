# The live workflow

The benchmark shows what the pipeline does with a task somebody else wrote down. This shows
it on a repository's own CI: a pull request's tests fail, and a few minutes later a comment
on that pull request suggests a fix, with the failing test it wrote first, the existing
tests it reran and a second vendor's review. Nothing else happens. A person reads it and
decides.

## Where it runs, and what it may do

| | |
|---|---|
| Repositories | `Peter-A-P/ai-release-gate` (project 03) and `Peter-A-P/compliant-ai-gateway` (project 04), listed in `mend/live/scope.py` |
| Trigger | the repository's `ci` workflow finishing with a failure, on a pull request from the repository itself |
| What it does | reruns the suite in a sandbox, clusters the failures, triages the largest ticket, comments on the pull request |
| What it never does | open a pull request, push, merge, or act on any repository but the one it runs in |
| Token | the job's own, with `contents: read`, `pull-requests: write` and `actions: read` (for earlier runs' artifacts): it cannot push |
| Spend | US$1.00 an issue and US$1.50 in all per repository, US$3.00 across the two |

**Comments only.** The plan allowed a draft pull request when the router says
auto-propose. The main run's confidently-wrong rate missed its target, 9.8% (4.3% to 21.0%)
against 3%, so this workflow posts every verdict above the quiet line as a comment, and says
in the comment when the router would have proposed. A quiet or stopped ticket goes in the
job summary only. Peter chose this on 2026-10-31.

**Scope.** `mend live` refuses unless the repository it is asked about is the one
`GITHUB_REPOSITORY` names and is on the list in `mend/live/scope.py`. Installing it
somewhere new is therefore a reviewed change to that file, not a copied YAML file. The
caller's condition skips pull requests from forks, which GitHub would not give the secrets
to anyway.

## How a run goes

1. **The failing commit is checked out** and an image built from it: Python 3.13, the
   repository at `/repo`, and its own install command (`uv sync --frozen ...`). The build
   is the one step with network access, and it runs only the repository's own code and its
   locked dependencies, nothing a model wrote.
2. **The suite runs in the sandbox,** network off, writing JUnit XML. A CI failure in lint
   or type checking, or one that does not reproduce, leaves nothing to triage, and the
   summary says so.
3. **Capture and clustering** are the measured ones (`mend capture pytest`, `mend cluster
   run` at its default cut). The tickets come out largest first.
4. **The largest ticket goes through the pipeline,** unchanged from the benchmark: localise,
   a failing test first, the patch, the other vendor's review, routing with the thresholds
   calibrated on the validation split. Every test run is in the sandbox. One ticket a run,
   so a run that fails five ways does not spend five times.
5. **The comment** is the proposal's body with a header saying it is a suggestion, and a
   footer with its cost, the repository's running total, and a link to the run.
6. **The record:** the job summary lists every ticket, posted or not; the run log, the JUnit
   report and the running total are kept as the run's artifact for 90 days. The next run
   reads the running totals from those artifacts before it starts.

## The budget

Three lines, each of which stops a run on its own:

- **The gateway's caps** (`config/live.caps.yaml`): US$1.00 an issue, checked before every
  call. Its ledger lasts one run, so its US$1.50 a month caps a single run.
- **The running total** (`mend/live/budget.py`): `mend live` keeps the total of every
  issue it has run in the repository and starts nothing once it reaches US$1.50; a new
  month does not refill it. Each run uploads its `spent.json` in its artifact, and the
  next run first downloads every unexpired `mend-live-*` artifact in the repository and
  merges their totals by issue (`--earlier`). If the listing or a download fails, the run
  fails before any model call rather than starting from nothing. An issue whose cost is
  unknown is counted at the per-issue cap.
- **The vendor consoles'** own hard limits.

An artifact lasts 90 days, so an issue older than that drops out of the running total. At
one ticket a run, on Peter's own pull requests, that is a small and known leak, and the
third line does not expire.

**Before v0.1.2 the total was not carried, found 2026-11-02.** The total and the gateway's
ledger were kept in the Actions cache, and the cache was never saved. Every run that got
as far as the save step logged "cache write denied: token has no writable scopes": the
caller grants `contents: read` and `pull-requests: write`, and the job's token is not
allowed to write the cache under them. So each run starts from an empty ledger, the
gateway's monthly cap and the running total see only that run, and the comment's "spent
so far" is that run's cost alone (04's third comment says US$0.23 of US$1.50; the
repository's true total is US$0.45). What has held: US$1.00 an issue before every call,
one ticket a run, a run only when Peter's own pull request fails ci, and the vendor
consoles' limits. Actual live spend, from the run artifacts: US$0.14 in 03 and US$0.45 in
04, US$0.59 of US$3.00. v0.1.2 carries the total in the run artifacts instead, which
already held every run's cost, so the three earlier runs count from its first run on.

## The demonstration

Each repository has a branch with one planted bug, `demo/mend-live-1`, made on 2026-10-31
and labelled as staged in its commit message:

| Repository | The bug |
|---|---|
| ai-release-gate | Holm's adjustment multiplies by one fewer than it should (`gate/stats.py`) |
| compliant-ai-gateway | long-prompt rates start one token early (`boundary/config.py`) |

A draft pull request from that branch makes `ci` fail and the workflow comment. Neither
pull request is ever merged.

The first runs, on 2026-10-31:

| Repository | What happened |
|---|---|
| ai-release-gate ([#2](https://github.com/Peter-A-P/ai-release-gate/pull/2)) | All 10 CI failures reproduced in the sandbox, 5 tickets; the largest (4 symptoms) went to auto-propose at US$0.14, with a failing Holm test first and the planted line reverted, accepted by the other vendor. Posted as a comment |
| compliant-ai-gateway ([#1](https://github.com/Peter-A-P/compliant-ai-gateway/pull/1)) | On v0.1.0 the sandbox ran no tests and reported a pass: the repository's `.dockerignore` leaves `tests/` out of its image. Fixed in v0.1.1, which builds with its own ignore file and treats a suite that ran nothing as a failed run |
| compliant-ai-gateway, rerun on v0.1.1 | All 5 CI failures reproduced, 3 tickets. The largest was not the planted bug: 4 tests refused by a one-cent cap that 04's main had carried since 2026-10-29. mend's patch raised the cap; the other vendor objected that it weakened a deliberate safeguard to pass mocked tests, so it went out as a suggestion with the objection quoted, at US$0.22. The planted bug was the smaller ticket, not triaged (one a run) |
| compliant-ai-gateway, 2026-11-02 (UTC), with 04's main merged into the branch | 2 CI failures reproduced, 2 tickets, and the largest was the planted bug. A failing boundary test first; the patch compensated in `cost_usd` by passing one token fewer instead of fixing the comparison in `PriceEntry.for_prompt`. The other vendor objected, naming the right place, and it went out as a suggestion at score 0.61, at US$0.23 |

The build ignores the repository's own `.dockerignore`, which is written for that
repository's image, and uses `IGNORE` in `mend/live/image.py`: `.env` files, local
databases, the virtual environment and `.git` stay out, the tests stay in.

## Installing it

Installed in both on 2026-10-31. The caller names the reusable workflow by its release tag,
now `v0.1.2`, and grants it `actions: read`. In a new listed repository:

1. Copy `action/<repository>.yml` from this repository to `.github/workflows/mend-live.yml`
   there, on the default branch, which is the only branch `workflow_run` reads.
2. The repository needs the secrets `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`. Both already
   have them.
3. Open the draft pull request from `demo/mend-live-1`.

## What this does not show

Two repositories and planted bugs are a demonstration, not a measurement: the benchmark
tables are the measurement. The suite in the sandbox has no network, so a repository
whose tests need it would show failures the sandbox caused, and the summary would list
them as tickets.
