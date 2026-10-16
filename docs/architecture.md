# Architecture

Three figures: the system as a whole, one failure through the pipeline, and how the numbers
will be produced, with what is built today marked against what waits. Each names the module
that implements what it shows; [PLAN.md](../PLAN.md) says why and [boundary.md](boundary.md)
records the public sources the design is built from.

## The system

![Failures arrive as test results, traces and issues and become one kind of record; clustering turns many symptoms into one ticket; a state machine allows no patch except from a test observed to fail, sends the patch to a reviewer from a different vendor, and routes by a calibrated confidence into a draft pull request, a suggestion or silence; every model call goes through the gateway and every comparison through the release gate.](architecture/system.svg)

Failures arrive as pytest JUnit XML, OpenTelemetry spans and logs, or GitHub issues
(`mend.capture`), and become one failure record with the traceback parsed, paths and messages
normalised and stable ids, so re-ingesting a report cannot inflate the symptom count.
Clustering (`mend.cluster`) combines a fingerprint, failure-text embeddings and code locality
into one distance cut by average linkage, giving one ticket per root cause; its quality is
measured against maintainers' duplicate links, injected faults and project 09's chaos traces.
The middle column is the state machine (`mend.graph.machine`): localise the fault with the
cheap model, write a test that must fail on the broken commit or stop, draft a patch that must
pass it and the suite in the sandbox (`mend.sandbox`: one container per task, no network,
limits), and send it to a reviewer whose alias resolves to a different vendor from the fixer,
checked at start-up against `config/mend.routes.yaml`. There is no edge into a patch except
from a failing test and no terminal state that means merged. Routing (`mend.graph.route`)
turns a confidence score into a draft pull request, a suggestion or silence, with thresholds
calibrated to a stated false-positive target. Every model call goes through the gateway with a
cap per issue (`mend.gateway`), and the evaluation (`mend.eval`) scores the hidden-test hit
rate, the confidently-wrong rate and the cost per issue. The four hops that call models, the
SWE-bench harness adapter, the labelled clustering sets and the live workflow are not built
yet; the capture, clustering, rails, routing, sandbox specification and measurement are.

## One failure through the pipeline

![An alert storm is captured as records and clustered into one ticket; the fault is localised, a test is written that must fail on the broken commit or the system stops, a patch is drafted that must pass it and the suite in a sandbox, a reviewer from another vendor tries to break it, and a calibrated confidence decides between a draft pull request, a suggestion and silence.](architecture/one-failure.svg)

Twenty symptoms of one bug arrive, are captured as records and clustered into one ticket. The
localiser, the cheap model, reads the traceback and greps the repository. The tester writes a
test that must be observed to fail on the broken commit; if it does not, the system stops and
says why, because the state machine has no way round it. The fixer drafts a patch that must
pass the new test and the existing suite in the sandbox. The reviewer, a model from another
vendor, tries to break it; a disagreement escalates and never merges. The routing score decides:
above the calibrated threshold a draft pull request is opened for an engineer to approve, or
not; below it the system leaves a suggestion or stays quiet.

## How the numbers will be produced

![The hit rate comes from a stratified subset of SWE-bench Verified sampled before the first run and judged on hidden tests; the confidently-wrong rate and the trade-off curve from the routing scores; clustering quality from three labelled sets; cost per issue from the gateway ledger; and every comparison runs through the release gate with intervals.](architecture/measurement.svg)

The hit rate on hidden tests comes from a stratified subset of SWE-bench Verified
(`mend.data.swebench`), sampled before the first run by a sampler that refuses to be resampled
afterwards, through a harness adapter that is not built because the build laptop has no
Docker. The confidently-wrong rate and the trade-off curve come from the routing scores and
outcomes (`mend.eval.confident_wrong`), and the calibration picks the lowest threshold that
meets the false-positive target without hitting it by proposing almost nothing. Clustering
quality is purity, completeness and the adjusted Rand index with bootstrap intervals
(`mend.cluster.metrics`, `mend.cluster.tune`) against three labelled sets, one of which waits
for project 09's chaos traces. Cost per attempted and per resolved issue comes from the gateway
ledger. The ablations run through project 03's release gate, whose Part B is not yet built.
Wilson and bootstrap intervals (`mend.eval.stats`) go on every number the README will carry.
