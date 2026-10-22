# Plan: From Failure to Reviewed Fix, in Minutes

**Written:** 2026-09-07. **Status:** plan only, nothing built.

**Build:** three weeks, Jul 5 to Jul 25 2027, slack to Jul 31 (July is shared with 08's two
weeks per the sequence). **Package:** `mend`. **Fed by:** 03 (the gate runs every
comparison with intervals; graders are tests, not judges), 04 (every model call through the
gateway, with the fixer and the reviewer on different providers by alias and a spend cap
per issue), 09 (its chaos runs left labelled failure traces, used as a capture-stage
dataset), 11 (LangGraph patterns). **Feeds:** nothing in the ten.

> **Employer boundary, before anything else.** This project is close to an agentic layer
> built inside the Government of Newfoundland and Labrador. It is built against public
> repositories and public issue histories only, from public sources (the SWE-bench line of
> work and published agent designs), with no internal architecture, prompts, thresholds or
> code. Open question 02 in the plan repository was closed on 2026-09-06 on exactly this
> basis. The design here differs on purpose: failing test first, adversarial review by a
> different vendor, clustering learned from maintainers' own duplicate links. If any part
> starts to resemble the internal system, the substitute named in the plan repository (a
> quantisation implementation) takes the slot. Rule G applies to every commit.

---

## 1. What this produces

When a production system fails, the failure is captured with its context, twenty symptoms
of one bug become one ticket, a failing test that demonstrates the bug is written before
any fix, a patch is drafted and run against that test and the whole suite, a second model
from a different vendor reviews the patch adversarially, and only then does an engineer
receive a ready-to-approve pull request, or a suggestion, or nothing, depending on a
confidence threshold justified by measurement. Nothing changes without a person saying
yes.

The interesting engineering is the clustering and knowing when not to act. Anyone can wire
a model to a stack trace.

The numbers a stranger can check:

| Number | What it shows |
|---|---|
| Symptoms per root cause: failures ingested against tickets opened, on labelled sets (maintainer duplicate links, injected faults, 09's chaos traces), with cluster purity, completeness and adjusted Rand index, 95% CIs | Twenty symptoms became one ticket, or did not |
| Test-first rate: share of issues where a test was produced that fails on the broken commit and demonstrates the reported behaviour | No patch without proof of the bug |
| **Honest hit rate**: share of issues resolved, judged by the benchmark's hidden tests, overall and per routing tier, with CIs | The claim, verified by tests the system never saw |
| **Confidently wrong rate**: patches the system would have auto-proposed that failed the hidden tests, with the false-positive analysis by cause | The number that matters more than the hit rate |
| Reviewer value: disagreement rate between fixer and reviewer, and the share of disagreements where the fixer was wrong | Whether the second model earns its cost |
| Routing trade-off: hit rate and confidently-wrong rate at every threshold, and the threshold chosen against a stated false-positive target | Thresholds justified by data, not feel |
| Stay-quiet precision: of issues routed to silence, the share where the drafted fix was in fact wrong | Knowing when not to act, measured |
| Cost per attempted issue and per resolved issue from the gateway ledger; minutes per issue by hop | Triage in minutes, priced |
| Ablations through the gate: without test-first, with same-vendor self-review, with fingerprint-only clustering, paired | Which parts of the design carry the result |

## 2. Design decisions

### 2.1 Real targets, hidden tests

The patch stage is evaluated on a stratified subset of SWE-bench Verified, the
human-validated set of real issues from public Python repositories, using its official
containerised harness: a resolution counts only if the benchmark's hidden tests pass and
nothing that passed before fails. The system never sees those tests. This is what makes the
hit rate honest, and it is why the number will be modest.

### 2.2 Clustering has ground truth, from three places

| Set | Truth | What it exercises |
|---|---|---|
| Maintainer duplicate links mined from public issue trackers of three large repositories (issues closed as duplicates of another) | The maintainers' own judgement | Real symptom diversity in human reports |
| Injected faults on two open-source test suites: one fault, many failing tests | Known by construction | Traceback-level symptoms of a single root cause |
| 09's chaos runs: recorded traces and logs from each injected failure scenario | The scenario that was injected | Production-shaped signals: traces, logs, metrics, not only exceptions |

Clustering combines a fingerprint (exception type, top in-project frame, normalised
message), embeddings of the normalised failure text, and code locality (shared frames and
files), with an agglomerative threshold tuned on a validation split and reported. The
fingerprint-only baseline is a Rule C candidate.

### 2.3 Failing test first, or no patch

For each ticket the system must produce a test that fails on the broken commit and
expresses the reported behaviour, run in the sandbox. If it cannot, it stops and says why.
Only then does it draft a patch, which must make that test pass and leave the existing
suite green. A patch without a demonstrating test is the most common way an automated fix
is confidently wrong, and the ablation measures exactly that.

### 2.4 Adversarial review by a different vendor

The reviewer is a model from a different provider than the fixer, addressed through the
gateway by alias so the pairing is a configuration, given the issue, the test, the patch
and the test output, and asked to break it: find the case the patch misses, the regression
it risks, the test that proves nothing. Disagreement escalates to a person instead of
proceeding. Same-vendor self-review is a Rule C candidate.

### 2.5 Confidence routing, calibrated

A routing score combines signals: test written and fails-then-passes, suite green,
reviewer verdict, cluster size, diff size, files touched, whether the patch touches the
frames in the traceback. Thresholds for the three tiers (auto-propose as a draft pull
request, suggest as a comment, stay quiet) are set on the validation split against a
stated target of at most 3% confidently-wrong auto-proposals, and the full trade-off curve
is published so a reader can choose a different target.

### 2.6 Bounded cost, always

The gateway enforces a spend cap per issue (US$1.00 at plan time) and a project cap;
localisation uses a small model, drafting and review mid-tier; development caching is on
for everything except the final evaluation runs. Cost per attempted and per resolved issue
come from the ledger, not from estimates.

### 2.7 The live demonstration acts only on Peter's own repositories

A GitHub Actions workflow in this repository and in two of the portfolio's public
repositories runs `mend` on CI failure in suggest mode: capture, cluster, propose as a
comment, and open a draft pull request only when the routing says so and only in those
repositories. It never acts on anyone else's repository. Every action is logged and visible.

### 2.8 Out of scope, on purpose

- Merging anything. There is no merge path; a person approves every pull request.
- Languages beyond Python for this version. The benchmark and the sandbox are Python.
- Runtime hot-patching, config changes in production, restarts. This proposes code
  changes for review, nothing else.
- Learning from outcomes across runs. Every run is stateless by design; the audit is the
  memory.
- Beating the leaderboard. The hit rate is reported as it falls; capability is not the
  differentiator, the measurement is.

## 3. Data

| Source | Size | What it gives | Access and terms |
|---|---|---|---|
| SWE-bench Verified | 500 issues; a stratified subset of about 120 for the main run | Real issues with hidden tests in a containerised harness | MIT-licensed dataset; underlying repositories under their own open licences; images built locally |
| Public issue trackers of three large Python repositories | Several thousand issues with duplicate links | Clustering truth from maintainers | GitHub API under its terms; issue text cached, not redistributed; ids and labels published |
| Injected faults on two open-source test suites | About 40 faults, hundreds of failing tests | Clustering truth by construction | Repositories under open licences; faults are local mutations, never proposed upstream |
| 09's chaos run traces and logs | Eight scenarios, multiple runs | Production-shaped failure signals with known causes | Own |
| Portfolio repositories for the live demonstration | Two public repositories plus this one | Real CI failures in suggest mode | Own |

Nothing raw is committed; loaders verify checksums; every licence is recorded.

## 4. Architecture

```
mend/
  capture/     schema.py (FailureRecord: fingerprint, traceback, logs, trace ids, commit, test id, env, repro
               context), pytest_ingest.py (JUnit XML), otel_ingest.py (traces and logs), github_ingest.py
               (issue text and CI logs), normalise.py
  cluster/     fingerprint.py, embed.py (local), locality.py (shared frames and files), agglomerate.py
               (threshold from validation), metrics.py (purity, completeness, ARI, symptoms per root cause),
               ticket.py (one ticket per cluster with representative symptoms)
  graph/       localise.py (traceback frames plus repository search; small model), test_first.py (write, run,
               must fail), patch.py (draft, apply, run test and suite), review.py (different-vendor reviewer
               via alias; adversarial rubric), route.py (score, thresholds, tier), act.py (draft PR, comment,
               or log), graph.py (LangGraph; no merge node exists)
  sandbox/     docker runner per task; SWE-bench harness adapter; timeouts; resource limits
  data/        swebench.py (subset sampling, stratified by repository), duplicates.py (mining duplicate links),
               faults.py (injection on two suites), chaos09.py (09's traces)
  eval/        gate/ (eval specs: main run, ablations; graders are test outcomes), hitrate.py, confident_wrong.py
               (false-positive taxonomy), reviewer_value.py, routing_curve.py, quiet_precision.py, cost.py
               (from the gateway ledger), latency.py
  cli.py       mend capture | cluster | fix | review | route | eval | report
  action/      GitHub Actions workflow for the live demonstration (suggest mode; own repositories only)
docs/          boundary.md (what this is and is not built from, with sources), routing.md (the curve and the
               chosen threshold), false-positives.md, clustering.md
```

### Tests that matter

No merge path exists (a test scans the GitHub client usage); a patch is never proposed
without a test that failed first (asserted in the graph's state machine); the reviewer
alias resolves to a different provider than the fixer alias (configuration test); the
spend cap per issue is enforced before the first call; clustering metrics against a fixture
with known labels; the sandbox refuses network access from task containers; the live
workflow is scoped to the repository it runs in.

## 5. Week by week

| Dates | Built | Done when |
|---|---|---|
| Jul 5 to 11 | Failure record and ingestion (pytest, OpenTelemetry, GitHub); the three clustering sets built; clustering and metrics with threshold from validation; SWE-bench harness running locally with the stratified subset sampled; gateway aliases (localiser, fixer, tester, reviewer on a different provider) and the per-issue cap; gate eval specs | Symptoms-per-root-cause table with CIs on all three sets; one benchmark task runs end to end in the sandbox |
| Jul 12 to 18 | LangGraph graph: localise, test-first, patch, run, review, route, act; validation run on 30 tasks; routing thresholds calibrated against the 3% target; routing curve | Validation hit rate and confidently-wrong rate; `docs/routing.md` |
| Jul 19 to 25 | Main run on about 120 tasks through the gate; ablations (no test-first, same-vendor review, fingerprint-only clustering) on 40 tasks each; false-positive taxonomy; reviewer value; cost and latency; live workflow on own repositories in suggest mode; Rule C; README; `v0.1.0`; repository public | Every table in section 1 filled |
| Jul 26 to 31 | Slack (shared with 08) | |

First to drop if behind: the injected-fault clustering set (duplicates and 09's traces
stay); ablation samples from 40 to 25; the live workflow on one repository instead of
three. The hidden-test hit rate, the confidently-wrong analysis, test-first, the
different-vendor reviewer, the routing curve and cost per issue are not droppable.

## 6. Cost

Prices as of 2026-09-07 (Anthropic list per million tokens: Haiku 4.5 at $1 in and $5 out,
Sonnet 5 at $2 in and $10 out; the reviewer is a mid-tier model from another vendor at a
comparable price). Per-issue cap US$1.00 enforced by the gateway.

**Models moved on 2026-10-17** (section 12): Haiku 5.5 for localisation at US$0.10 in and
US$0.50 out, Sonnet 5.5 for the tester and fixer at the same US$2 and US$10 as Sonnet 5, and
GPT-6.1 Sol as the reviewer at US$2 and US$10, the fixer's own rate. The table below is left
at the 2026-09-07 prices it was written with. On its own token profile the change saves about
US$0.036 a task on localisation and adds about US$0.023 on review, so a task is about a cent
cheaper than budgeted; the validation run replaces both with ledger figures. Sandbox runs on the
laptop's Docker; a rented CPU box for the main run if the laptop is too slow (about CA$10).

| Item | Basis | US$ | CA$ |
|---|---|---:|---:|
| Main run | About 120 tasks; localisation about 40k tokens on the small model, test and patch about 60k in and 6k out on the mid-tier model, review about 30k on the other vendor; about US$0.45 per task with one retry allowed | 54 | 73 |
| Validation run | 30 tasks, same profile | 14 | 19 |
| Ablations | Three ablations, 40 tasks each, localisation cached | 36 | 49 |
| Clustering | Embeddings local; ticket summaries on the small model | 3 | 4 |
| Live workflow, July | Suggest mode on own repositories, capped | 3 | 4 |
| Sandbox compute | Rented CPU box if needed | 7 | 10 |
| **Total** | | **117** | **159** |

Right at the CA$160 line. If the validation run shows a higher per-task cost, the main run
shrinks to 100 tasks before anything else moves, and the plan repository's STATUS records
it. Actuals go there next to the estimate.

## 7. Handover

`mend` v0.1.0 on Jul 25 2027. Nothing in the ten imports it. What carries forward: the
failure record schema as the shape 09's observability could emit; the routing-curve method
as the pattern for any "should the system act" decision in the portfolio; and the live
workflow, which keeps running on the portfolio's own repositories after the build as a
standing demonstration.

## 8. Risks

| Risk | Handling |
|---|---|
| Employer boundary, second highest in the plan | Public repositories and public sources only; `docs/boundary.md` lists what the design is built from; the design differs deliberately (test-first, different-vendor review, duplicate-link clustering); substitute named; Rule G on every commit |
| The hit rate is low | Published as it falls. A system resolving a fifth of issues with a 3% confidently-wrong rate is useful; one claiming most of them is not believable |
| Agent cost runs away | Per-issue cap in the gateway before the first call; one retry; caching in development; the main run shrinks before the budget moves |
| The sandbox is slow on the laptop | The harness images are built once; a rented CPU box is budgeted; the subset is stratified so a smaller run still covers every repository |
| The category moves monthly | Differentiate on measurement, not capability; the README leads with the confidently-wrong analysis |
| Duplicate links are noisy truth | Reported as maintainers' judgement, with the injected-fault set as the by-construction check |
| The reviewer rubber-stamps | Reviewer value is measured; if disagreements do not predict wrong patches, the plan says so and the reviewer becomes an ablation, not a gate |
| The live workflow acts where it should not | Scoped to the repository it runs in; suggest mode; draft pull requests only; every action logged |

## 9. Rule C candidates

1. **Patching without a failing test first.** Expected: a higher confidently-wrong rate,
   because patches that satisfy the model's own reading of the issue fail the hidden tests
   more often when nothing forced the bug to be demonstrated.
2. **Self-review by the same vendor.** Expected: higher agreement and a lower catch rate of
   wrong patches than the different-vendor reviewer, on the same tasks.
3. **Fingerprint-only clustering.** Expected: high purity, poor completeness: one bug
   across several exception types stays several tickets. The ARI gap is the evidence.

Whichever produces the clearest evidence becomes `docs/rejected.md`.

## 10. Definition of done

- [ ] Symptoms-per-root-cause ratio with purity, completeness and ARI on three labelled sets, with CIs
- [ ] Failing test generated and verified to fail before every patch proposal; test-first rate reported
- [ ] Adversarial review by a different vendor's model, escalation on disagreement; reviewer value measured
- [ ] Routing thresholds calibrated against a stated false-positive target; the trade-off curve published
- [ ] Honest hit rate on hidden tests, overall and per tier, with CIs
- [ ] Confidently-wrong rate and the false-positive analysis by cause
- [ ] Stay-quiet precision reported
- [ ] Cost per attempted and per resolved issue from the gateway ledger; minutes per issue by hop
- [ ] Ablations through the 03 gate: no test-first, same-vendor review, fingerprint-only clustering
- [ ] Live workflow running in suggest mode on the portfolio's own repositories; no merge path, asserted by a test
- [ ] `docs/boundary.md` published
- [ ] One rejected approach documented with evidence (Rule C)
- [ ] Repository public, `v0.1.0` tagged

## 11. Deferred

| Deferred | Kept so the door stays open |
|---|---|
| Other languages | The sandbox is a container per task; the harness adapter is the only Python-specific part outside test generation |
| Learning across runs (which clusters recur, which fixes held) | The failure records and routing decisions are stored; a memory would read them |
| Production hooks beyond CI (error trackers, on-call pagers) | The capture module takes OpenTelemetry already; an error-tracker webhook is one more ingester |
| Root-cause explanation as a deliverable in itself | The ticket carries the representative symptoms and the frames; an explanation step would consume the same record |
| Auto-merge for the lowest-risk class | Never in this repository; the routing curve gives a reader the data to argue about it elsewhere |

---

## 12. Build log: what was built early, and where this plan changed

**2026-09-13.** The offline half was built ten months ahead of the July 2027 slot, because
none of it needs money, a benchmark container, or anything from projects 09 and 03 that
does not exist yet. Built: capture and its three ingesters, clustering with its metrics and
a threshold tuner, the state machine that carries the rails, routing with calibration and
the trade-off curve, the sandbox specification, the evaluation statistics, the subset
sampler, the configuration, and 204 tests. `mypy --strict` and `ruff` clean. No model has
been called and nothing has been measured.

Five places where the code does not match section 4, and why. Each was a decision taken
while building, not a drift noticed later.

**The rails live in `graph/machine.py`, not inside the graph framework.** Section 4 lists
`graph.py (LangGraph; no merge node exists)`. The LangGraph wiring still lands with the
node bodies, because a node body is a model call and there are none yet. What changed is
that the invariants (no patch without a failing test, no merge, a different-vendor
reviewer) were pulled out into a plain typed state machine that `advance()` enforces on
every hop. The reason is testability: the rails are now asserted on every commit without a
model, a network or a container, rather than only on the days a full run happens. The graph
calls `advance()` and has no other way to move an issue forward.

**The locality channel has three parts, not two.** Section 2.2 says code locality is
"shared frames and files". Building the fixture first showed that overlap alone
systematically understates the case this project exists to get right: a bug reached from
four call sites gives frame sets that overlap one in three, which reads as mostly different
when they agree on the only frame that identifies the bug. Whether the two failures broke
at the same innermost project frame is now scored separately, at the largest of the three
weights. With overlap alone the four-symptom fixture bug stayed split at every threshold
that kept the other bugs apart; with the new term the fixture resolves exactly.
`docs/clustering.md` records this.

**The default embedder hashes character n-grams; a trained encoder is optional.** Section 4
says `embed.py (local)`. Both are local. The default needs nothing but numpy, is
deterministic across processes and machines, and is fast enough to bootstrap a thousand
resamples in CI, which is what makes the clustering metrics a per-commit check rather than
an occasional one. A sentence-transformer backend sits behind the `st` extra, and every
clustering result carries the name of the embedder that produced it, so no reported number
can be ambiguous about which one ran. Which becomes the default for the measured runs is
itself a measurement, on the labelled sets, not a decision to take now.

**Threshold tuning is its own module, `cluster/tune.py`.** Section 4 folds "threshold from
validation" into `agglomerate.py`. It is separate because the validation split has a
property worth its own tests: it splits by root cause, not by record. Records of one bug
are not independent, and a random split by record puts symptoms of one cause on both sides,
which lets a threshold look good on the held-out half for the wrong reason.

**The eval modules are consolidated.** Section 4 lists `hitrate.py`, `confident_wrong.py`,
`reviewer_value.py`, `routing_curve.py`, `quiet_precision.py`, `cost.py` and `latency.py`.
All but the false-positive taxonomy are functions over one `IssueOutcome` record type and
live in `eval/results.py`; the routing curve lives with the routing it describes, in
`graph/route.py`. Seven files whose contents are each one function over the same list was
more structure than the thing has, and the shape that matters is that every headline number
is recomputable from the stored outcomes.

One smaller thing: `config/prices/` holds a copy of project 04's dated price list rather
than a path into it, so that a public checkout can reproduce the cost numbers without a
second private repository beside it. Repricing stays a new dated file in both places.

**2026-10-17.** The hops that call models, and the graph that wires them. Built:
`graph/localise.py`, `test_first.py`, `patch.py`, `review.py`, `act.py` and `graph.py` (LangGraph,
no merge node), the Docker-backed workspace in `sandbox/workspace.py`, and `mend ping` and
`mend fix`. Tested end to end with scripted models and a scripted sandbox; `mypy --strict` and
`ruff` clean. The first live calls went through the gateway the same day (`mend ping`, one word
per role). The same day the roles moved to current models: Haiku 5.5 for the localiser,
Sonnet 5.5 for the tester and fixer, and GPT-6.1 Sol for the reviewer, replacing Haiku 4.5,
Sonnet 5 and GPT-5, which were a year old by then. GPT-6.1 Sol costs exactly what Sonnet 5.5
does per token, which keeps the reviewer comparison about judgement rather than price. All
four roles answered on the new models, and the ledger's total for every live call that day
is US$0.0003. The prices are in `config/prices/2026-10-16.yaml`, copied from project 04's
list of that date without its long-prompt surcharges, which the pinned gateway does not read
and which mend's prompt caps keep it well under.

Six places where the code does not match section 4, and why.

**Four small modules section 4 does not list.** `graph/llm.py` is the one interface the hops
ask a model through, so the wiring is tested without keys and only `GatewayClient` touches the
gateway. `graph/parse.py` reads tagged replies and builds diffs. `graph/prompts.py` holds the
four prompts and the size limits on what goes into them. `graph/context.py` holds the issue,
the dependencies and the working material handed from hop to hop. The route node lives in
`act.py` beside the act node, since routing is `graph/route.py` applied to the state.

**Edits, not diffs, from the fixer.** The fixer quotes the exact text to change and gives the
replacement; an edit whose quoted text does not occur exactly once is refused with the
reason. The diff the sandbox applies is computed from the edits, so a malformed hunk header
cannot be why a patch failed. Replies are tagged rather than JSON because code inside JSON
has to be escaped by the model.

**"The existing suite stays green" needed a definition.** The benchmark's own lists of tests
to run are derived from the hidden test patch, so they cannot be used. The patch hop picks
the existing test files related to the touched modules (named for them, or importing them),
runs them on the broken commit and again with the patch, and calls the suite green when
everything that passed before still passes. When no related test file exists the suite is
not called green, and the router keeps the issue at QUIET. `PatchAttempt.suite_files` records
which files the claim is about.

**A patch that breaks the suite is still reviewed.** It is routed to QUIET whatever the
review says, but whether the reviewer catches a patch the suite already condemned is part of
what reviewer value measures, and the review costs a few cents.

**Until the validation split exists, nothing auto-proposes.** With no calibrated thresholds
the router holds the top tier at SUGGEST. A threshold nobody has measured should not open
pull requests.

**Test runs use pytest.** That covers most of SWE-bench Verified but not Django, whose suite
runs through its own runner. The harness adapter, not yet built, is where a repository's test
command will come from.

**2026-10-17, later.** `data/chaos09.py`, the reader for 09's re-recorded chaos runs, as
section 4 names it. Section 2.2 expected traces and logs; 09 has no traces and logs little,
so most symptoms are metric departures, each judged against the run's own first seconds of
traffic. Checked against the first eleven runs, the symptoms are the ones each fault should
produce: dead letters for poison, broker request and I/O rates for pause and throttle, the
committed-offset rate for a scorer stall, late-event errors for out-of-order. No clustering
number is reported from a partial campaign; the set is measured once all 42 runs are in.

**2026-10-17, gateway.** mend moved from project 04's gateway 0.2.0 to 1.4.2, the current
release. 1.0 froze 04's interface, and nothing mend calls had changed: the tests, the role
check and a live call per role passed unaltered. What 1.4 adds that mend uses is long-prompt
pricing, so `config/prices/2026-10-17.yaml` carries the surcharges `2026-10-16.yaml` had to
omit. `mend ping` now sends a fresh request each time, since an answer from the development
cache proves nothing about the keys. Ledger total after the upgrade's live check: US$0.00053.

**2026-10-17, scoring.** `sandbox/harness.py` and `mend score`: the drafted patches go to the
official SWE-bench harness (5.0.2) and one verdict per task comes back. Four things found
while building it.

**The harness does not run on a Windows host.** It writes its eval script and the patch
with CRLF line endings, bash in the task container cannot run the script, and the
benchmark's own reference patch for pallets__flask-5014 scored as unresolved. The harness
now runs in a small Linux container of its own (the image tag carries the harness version
and a hash of its recipe), driving the laptop's Docker through its socket, and the same
reference patch resolves.

**Section 4's sandbox assumed pytest.** SWE-bench Verified is 46% Django and 15% sympy, and
neither runs its suite with pytest. The sandbox now uses each project's documented runner
(`sandbox/runners.py`) and reads Django and sympy output with the harness's own parsers, so
a test the sandbox calls failing is one the harness would call failing. The new test and
the related existing tests run in separate containers, because the three runners name
tests three different ways.

**Harness 5.x keeps each task's test command inside its eval_script, beside the hidden test
patch.** mend reads no part of that field, so the commands in `sandbox/runners.py` are
written from each project's documentation instead. `Task` now carries the task's image
name, which the dataset row gives and which is the broken commit's environment, not its
evaluation.

**A task the harness cannot judge is not a failure.** `sandbox.harness.outcomes` refuses
to build the results while any submitted patch lacks a verdict, so an infrastructure error
is run again rather than counted against the hit rate.

The first end-to-end run, on 2026-10-17, was a plumbing smoke test on pallets__flask-5014,
chosen as the smallest repository in the set before anything was known about how mend
would do on it: localise, a test that failed first, a three-line patch with the existing
blueprint tests still green, a different-vendor review that agreed, routed to SUGGEST, 25
seconds and US$0.15; the harness judged it resolved. It is one task picked by hand and is
not a result. The subset has not been sampled, and this task is not excluded from it.

**2026-10-17, the subset.** Drawn once with `mend subset`, seed 20261017 (the date it was
drawn, chosen before any run), from the 500 tasks of SWE-bench Verified: 150 tasks
stratified by repository, then a validation split of 30 drawn from those by the same method
and seed, and the other 120 as the main run. The ids are committed in
`data/subset/validation.json` and `data/subset/main.json`, and `write_subset` refuses to
overwrite either. Every one of the twelve repositories is in the validation split; pallets
and its single task fell there by the one-per-repository floor, so the main run has eleven
repositories. That single task is pallets__flask-5014, the plumbing smoke test above: it is
in the validation split, where thresholds are calibrated, and not in the main run, where
the headline numbers come from.

**Each task's image is removed once it is scored** (decided 2026-10-17), because the laptop
has about 50 GB free and the images are about four gigabytes each. `mend run` takes a
committed subset file and, for each task in order, pulls the image, runs the pipeline,
scores the drafted patch with the harness while the image is still there, then removes the
image and the repository copy. It resumes after a crash without running any task's fix
twice: a second draw of a fix, kept if it came out better, is exactly the selection the
rules forbid. The repository copies now go to the system's temporary directory, outside
the OneDrive-synced tree.

**2026-10-17, clustering production signals.** On 09's chaos campaign the record-level
clustering of section 2.2 does not recover the faults (held-out ARI 0.032 averaged over
every way of holding three of eight faults out) and the fingerprint baseline does no
better (0.021). A two-stage method, symptoms into incidents by onset time and incidents
into tickets by the Jaccard distance between their symptom sets (`cluster/incidents.py`),
averages 0.636 and is higher on all 56 folds. The first measurement, a single seeded split,
gave 0.080; the cross-validation was adopted after seeing it, and `docs/clustering.md`
reports both, in that order, with the reason. This is the clearest Rule C evidence so far
(section 9, candidate 3, broadened from fingerprint-only to record-level clustering) and is
the likely subject of `docs/rejected.md`, pending the ablations.

**2026-10-17 to 19, the validation run.** All 30 tasks of the validation split, through
the pipeline uncalibrated and scored by the harness, committed in `results/validation/`.
Resolved on the hidden tests 22 of 30, 73.3% (55.6% to 85.8%); a test that failed first on
all 30; US$5.62 in all, US$0.17 per attempted task, about two minutes of pipeline time per
task. The reviewer objected to 9 of 27 patches and was right about 4 of them; when it agreed,
the fixer was wrong once in 18. This is the calibration split and not a result: it is small,
Django is half of it, and the thresholds were chosen on it.

Calibrated on it with `mend calibrate` (`docs/routing.md`, `config/mend.thresholds.yaml`):
auto-propose at 0.00 and suggest at 0.00. Every patch that passed the router's rules (test
fixed, suite green, reviewer agreeing) scored 0.81 and was resolved, so every threshold from
0 to 0.81 does the same and the September procedure's "lowest" lands on 0. The score does no
work on this split and the rules do all of it; that is stated in advance of the main run,
and the procedure was not changed after seeing it. Building the calibration also found that
the routing curve counted patches the router would refuse (a red suite, whatever the
score); it now counts only patches the router could propose, and a test asserts it.

It took four starts to finish, none of them about a task: a dropped TLS session mid-pull,
Django's symlinks on a Windows host, a missed Docker health check, and Docker Desktop's
engine failing overnight, after which a pull waited ten hours with no deadline. Each has a
fix in the sandbox code and a commit saying so. One task (django__django-13590) was cut off
mid-hop by the health check before any record was written and ran again from the start; its
first, partial attempt's model calls are in the ledger.

**2026-10-19 to 20, the main run.** All 120 tasks of `data/subset/main.json`, routed with
the thresholds calibrated on validation, scored by the harness, committed in
`results/main/`; the README's tables are written from those files by `mend report`.
Resolved 81 of 120, 67.5% (58.7% to 75.2%). A test that failed first on 116 of 120.
US$0.159 per attempted task, US$0.242 per resolved, about a minute of pipeline time per
task; the ledger's total for the whole project to date is US$25.97.

**The 3% confidently-wrong target was missed.** 51 patches were auto-proposed and 5
failed the hidden tests, 9.8% (4.3% to 21.0%). The validation split could not have caught
it: every patch that passed the router's rules there was right, so the score had nothing to
separate, which `docs/routing.md` said before this run. The five are
django__django-10999, pytest-dev__pytest-5840, scikit-learn__scikit-learn-14983,
sphinx-doc__sphinx-7462 and sympy__sympy-18763. Classifying them by cause
(`eval/confident_wrong.py`) needs the hidden tests or the gold patch, which no model in
this project may read, so it is Peter's to do; `confident_wrong.hint` gives the shortlist
from the evidence on each record.

**Restraint was expensive.** 35 tasks went to silence; 14 of them had a patch the hidden
tests accepted, 12 of those because no related existing test was found, which the router
reads as "not shown safe". The reviewer objected to 40 patches and was right about 16; when
it agreed, the patch was wrong 7 times in 64.

**Incidents during the run, none of them about a task.** Three tasks stopped because a
model reached its output limit before returning any text (the tester twice at 4,096
tokens, the fixer once at 8,192); left as configured for the whole run rather than
changed mid-run, and counted as unresolved. Task 71 (psf__requests-5414) printed a
character the Windows code page could not decode, which crashed the patch hop; the retry
wrapper then re-ran it from the start ten times before the bug was found, about US$1.50 of
model calls on attempts that left no record. Fixed (`e259edc`) and the wrapper now stops
after two attempts with no progress. The run was paused twice at Peter's request and
resumed without re-running any finished task.

**Definition of done, as it stands.** Done: test-first before every patch, with the rate
reported; the different-vendor reviewer and its value measured; thresholds calibrated
against a stated target with the curve published; the hidden-test hit rate overall and per
tier with intervals; the confidently-wrong rate; stay-quiet precision; cost per attempted
and per resolved from the ledger; clustering measured on one of the three labelled sets;
`docs/boundary.md`; the rejected approach in `docs/rejected.md`. Not done: the false-
positive analysis by cause (needs Peter, above), the duplicate-link and injected-fault
clustering sets, the ablations through 03's gate, the live workflow, and `v0.1.0` with the
repository made public.

**2026-10-21, the ablations built and their tasks drawn.** `mend/ablation/` holds them,
outside the graph, so the graph has no switch that turns a rail off (`docs/ablations.md`).
They depart from section 5 in three ways, each decided before any arm ran:

- **No failing test first** runs on 40 tasks drawn from the main run's 120
  (`data/subset/ablation.json`, seed 20261021, committed before the run). It reuses each
  task's localisation from the main run, as section 6 budgeted.
- **Same-vendor review** reviews all 104 patches the main run reviewed rather than 40,
  because it needs no sandbox. It runs two arms on identical input: the fixer's own model
  through a new alias, `mend-self-reviewer`, and the different-vendor reviewer asked again.
  The new alias is pinned to the fixer by a test, and a second test checks that nothing
  under `mend/graph` names it.
- **Fingerprint-only clustering** is not put through the gate. The gate decides on items
  that are each right or wrong, and a clustering is right or wrong only as a whole
  partition. It is measured by the clustering cross-validation instead, paired by fold, on
  each labelled set.

The gate margin is ten points, because at 40 tasks a three-point margin can only warn.

### What is blocked, and on what

Updated 2026-10-17, twice: once for where projects 03 and 09 stood, and again when the hops
were built.

- The benchmark runs are no longer blocked: Docker runs on the build laptop and the harness
  scores there (2026-10-17). Disk is handled by removing each task's image once it is
  scored, so the rented box section 6 budgets for is not needed for space. The sandbox specification and the runner's refusals are tested
  without it; the one test that needs a real daemon is marked `docker` and runs in CI.
  Project 09's chaos runs were made on a machine with Docker; whether that machine can run
  the benchmark harness has not been tried.
- The chaos-trace clustering set needs project 09's chaos runs in a form this can cluster.
  09 is live and ran its chaos faults on 2026-09-22 (`verdict chaos run`: broker pause,
  throttle, scorer stall), with every failure mode in its plan written up. Each run kept a
  summary report (counts, lag, catch-up time), not the traces and logs section 2.2 assumes,
  and 09 exports Prometheus metrics rather than OpenTelemetry. Chosen 2026-10-17: 09 is
  recording the runs again (eight scenarios, five repeats each, two controls) with its logs
  and a full Prometheus dump kept per run and the label in a separate manifest, and this
  repository reads those logs and metrics (`mend capture chaos09`, built the same day).
  There are no traces to read. The set is measured once the campaign finishes.
- The ablations are no longer blocked from outside. Project 03's release gate, Part B
  included, was built from 2026-09-19 and released as v0.1.0 on 2026-10-06. What the
  ablations wait on now is the harness adapter and a running Docker daemon.
- Spend so far is US$25.97 (the ledger's total, 2026-10-20), about CA$35, against the US$1.00 per-issue
  cap and the US$130 monthly cap in `config/mend.caps.yaml`.
