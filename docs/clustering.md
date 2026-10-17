# Clustering: how many symptoms become one ticket

**Status as of 2026-09-13: the mechanism is built and tested; nothing is calibrated.** The
channel weights and the agglomeration threshold in the code are a starting point, not a
result. They are tuned on a validation split of the labelled sets, and those sets do not
exist yet. Every number on this page that came from the nine-record fixture says so.

## The three channels

A pair of failure records gets one distance, which is a weighted mean over the channels
that had something to say about that pair.

**Fingerprint** (`mend/cluster/fingerprint.py`), weight 0.4. Exception type, the top
in-project frame, and the normalised message, compared for exact equality, with partial
credit for agreeing on some of the three. This is the cheap, exact channel, and on its own
it is the Rule C baseline.

**Text** (`mend/cluster/embed.py`), weight 0.3. Cosine distance between embeddings of the
normalised failure text. The default embedder hashes character n-grams into 2048 buckets:
deterministic, offline, no model download, and fast enough to bootstrap a thousand
resamples in CI. Character n-grams rather than word tokens because failure text is full of
identifiers, and `get_user_id`, `UserIdError` and `user-id` share almost no words and a
great many character n-grams. A sentence-transformer backend is available behind the `st`
extra; any reported number names the embedder that produced it, and `Clustering.embedder`
carries it on the result object so it cannot be lost.

**Locality** (`mend/cluster/locality.py`), weight 0.3. Three parts: whether the two
failures broke at the same innermost project frame (0.45), the Jaccard overlap of all
in-project frame locations (0.35), and the same over files (0.20). Frames outside the
project are ignored, because every failure in a repository shares its test runner and its
standard library.

### Why the innermost frame needs its own term

A bug in one function reached from four call sites produces four symptoms whose frame sets
are `{caller_i, faulty}`. The Jaccard overlap of any two of those is one in three, which
reads as mostly different, when in fact they agree on the only frame that identifies the
bug. Overlap alone systematically understates exactly the case this project exists to get
right, which is why the innermost frame is scored separately rather than folded in.

This was found by building the fixture before tuning anything: with overlap alone the
four-symptom config bug in `tests/fixtures.py` stayed split at every threshold that kept
the other two bugs apart.

### A channel that cannot speak abstains

`locality_distance` returns `None`, not 1.0, when either record has no in-project frames.
The distinction is the whole ball game for issue reports. A GitHub issue written in prose
has not told us that its code path is different; it has told us nothing, and scoring
silence as maximum distance would push every prose-only report away from the traceback
that explains it. The combined distance renormalises over the channels that spoke, and
`tests/test_clustering.py::test_a_channel_that_abstains_does_not_count_as_disagreement`
asserts that raising the locality weight does not move a pair where locality abstained.

## Average linkage, and why not the other two

Single linkage chains: one ambiguous record sitting between two bugs merges both into one
ticket, which is the failure that destroys purity. Complete linkage is the opposite and
splits a genuinely diverse bug into several tickets, destroying completeness. Average
linkage degrades gracefully in both directions, and the threshold is what trades between
them.

## Three metrics, never one

- **Purity** punishes merging. Alone it is maximised by giving every symptom its own
  ticket, which is the system doing nothing.
- **Completeness** punishes splitting. Alone it is maximised by putting everything in one
  ticket, which is worse than nothing.
- **Adjusted Rand index** is corrected for the agreement a random labelling of the same
  shape would get by chance, so neither degenerate answer wins it. It is the tuning
  objective and the number the Rule C comparison turns on.

**Symptoms per root cause is reported beside them, never instead of them.** It is a
description of the output. A system that puts everything in one ticket has a magnificent
ratio and is useless.

Every metric carries a bootstrap interval over records, seeded at 20270705 and stated, so
a published interval is reproducible to the digit.

## How the threshold gets chosen

`mend/cluster/tune.py`. The split is **by root cause, not by record**: records of one bug
are not independent, and a random split by record would put four symptoms of one cause on
both sides, which lets a threshold tuned on one half look good on the other for the wrong
reason.

The tuner reports the whole sweep, not only the winner, and the plateau: the range of
thresholds within 0.01 ARI of the best. A broad plateau means the exact number is not
load-bearing and a sharp peak means it is, and a reader who sees only the winner cannot
tell which they are looking at.

Ties break toward the **lower** threshold: fewer merges, more tickets. When the evidence
cannot choose, leaving a maintainer with two tickets for one bug is cheaper than burying a
second bug inside a ticket about the first.

## What the fixture shows, and what it does not

`tests/fixtures.py` holds eight records over three known causes: a config bug surfacing as
three different exception types from three call sites, a paginator bug, and a serialiser
bug reported once as a test failure and once as prose with no traceback.

| Method | Tickets | Symptoms per cause | Purity | Completeness | ARI |
|---|---|---|---|---|---|
| Fingerprint only | 6 | 1.33 | 100% | 62.5% | 0.323 |
| Three channels, threshold 0.6 | 3 | 2.67 | 100% | 100% | 1.000 |

**This is a sanity check, not a result.** Eight hand-built records, whose difficulty was
chosen by the person who then designed the channels. It demonstrates that the mechanism
works and that the fingerprint baseline fails in the predicted direction, which is worth
having on every commit. It says nothing about real data, and the numbers above will not
appear in the README.

The real measurement needs the three labelled sets in PLAN.md section 2.2: maintainer
duplicate links from three large public repositories, injected faults on two open-source
test suites, and project 09's chaos traces. None of those exist yet. Project 09 has run its
chaos faults (2026-09-22) and is live, but each run kept a summary report (counts, lag,
catch-up time) rather than the traces and logs this would cluster. On 2026-10-17 09 began
recording them again: eight scenarios at five repeats each plus two fault-free controls, each
run keeping its JSON-lines logs and a full Prometheus range dump, with the injected scenario
in a manifest kept apart from the signals. 09 has no OpenTelemetry, so there are no traces,
and it logs little, so most of what distinguishes one fault from another is in the metrics.
(Updated 2026-10-17.)

`mend.data.chaos09` (`mend capture chaos09`) turns a campaign into records. A log record at
WARNING or above is a symptom, kept up to three times per message shape per run with the
count noted, so that the one fault that logs 441 late events does not outweigh the rest by
volume. A metric is a symptom when it leaves its own steady level by more than six robust
scales for at least three seconds. The steady level is seconds 1 to 7 of traffic, and the
start of traffic is the broker's first accepted record, read off the metrics. The search
stops when sending stops, at 90 seconds, so the end of the stream is never a symptom.
Counters are judged by their rate, and so is a gauge that only climbs, such as a committed
offset. Prometheus's own scrape timings are left out, because they follow the shared
capture machine's load rather than 09's. From each manifest it reads the run id and the
scenario, and nothing else: the injection times would let a detector find the fault by
knowing when to look.

The full campaign arrived on 2026-10-17: 42 runs, 373 symptoms, none from the two control
runs and at least one from every faulted run. A first look, on the whole set and not
tuned on a held-out split, so not a result: the record-level clustering above does not
recover the faults at any threshold, and neither does the fingerprint baseline. The reason
is structural. One fault here shows as a dozen different metrics, each a record with its
own name, and nothing in the fingerprint, the text or the code-locality channel says that
two of them happened together. A traceback set never posed this problem, because one bug
tends to fail in one place.

What does recover them, in the same first look, is two stages: group symptoms that began
together into incidents, then group incidents whose sets of symptoms are alike. That is
being built as part of the clustering, with incidents found from onset times rather than
from the run they came from, and its threshold tuned on a split held out by fault. With
eight faults, a held-out split is two or three of them, and the intervals will be wide; the
report will say so. The record-level clustering failing on production signals is the
evidence for the rejected approach PLAN.md section 9 asks for, measured as a paired
comparison once both exist.

### The first held-out measurement, as it fell (2026-10-17)

`mend.cluster.incidents` is the two-stage clustering. It was measured the way
`cluster/tune.py` prescribes: `split_by_cause` with its committed seed put three faults in
the validation split (duplicates, pause, scorer-stall; 148 records) and five in the
held-out half (clock-skew, out-of-order, poison, schema-change, throttle; 225 records).
Each method's parameters were chosen on the validation split by ARI and scored once on the
held-out half, with bootstrap intervals over the records.

| Method, tuned on the validation split | Chosen | Tickets | Purity | Completeness | ARI (95% CI) |
|---|---|---|---|---|---|
| Record-level (fingerprint, text, locality) | threshold 0.525 | 8 | 50.7% | 41.8% | 0.034 (0.011 to 0.080) |
| Fingerprint only | none to choose | 65 | | | 0.015 (0.020 to 0.046) |
| Two-stage (incidents, then signatures) | gap 45 s, threshold 0.85 | 7 | 54.2% | 87.1% | 0.080 (0.030 to 0.136) |

(The fingerprint-only point estimate sits below its own bootstrap interval, which is what a
percentile bootstrap does to a statistic as skewed as ARI near zero; both are as computed.)

The two-stage method beats the record-level one, but by little, and the reason is visible
in the sweep. On the validation split, ARI rose steadily to its best at a threshold of
0.85, where pause and scorer-stall, two faults that both make the scorer fall behind, are
merged; there was nothing in three faults to argue against merging. On the held-out half,
which was looked at only after the choice was fixed and is reported here so a reader can
see it, the same method scores 0.83 at thresholds of 0.50 to 0.55 and collapses above 0.70.
So the method separates faults it was not tuned on, and three faults are too few to tune
it with.

Changing the tuning procedure now would be a decision taken after seeing the held-out
half, and is not done silently. Whatever is adopted next is reported beside this table,
with that said, and this table stays.

### Cross-validated over causes (adopted 2026-10-17, after the table above)

Adopted after the single-split result had been seen, for the reason that result showed:
three causes are too few to choose two parameters from, and the answer depended on which
three a seed picked. The procedure was fixed before it was run, and was not changed after:
every one of the 56 ways of holding three of the eight faults out, each method tuned on the
other five and scored on the three, the methods paired by fold
(`mend.cluster.crossval`). The tuning grids are the ones the single split used.

| Method | Mean held-out ARI | Spread across the 56 folds (2.5th to 97.5th percentile) |
|---|---|---|
| Record-level (fingerprint, text, locality) | 0.032 | 0.009 to 0.055 |
| Fingerprint only | 0.021 | 0.004 to 0.044 |
| Two-stage (incidents, then signatures) | 0.636 | 0.136 to 0.991 |
| Two-stage minus record-level, paired | 0.604 | 0.125 to 0.956; two-stage higher on all 56 folds |

The spread is how much the answer depends on which faults were held out. The folds share
causes, so it is not a confidence interval and is not labelled as one; with eight faults,
there is no honest interval narrower than this to give. The weakest folds are the ones
that hold out faults with few or similar symptoms (duplicates, poison and schema-change
together; pause with scorer-stall), and the single split's 0.080 sits at the bottom of this
range, not outside it.

What this supports: on production-shaped signals, comparing symptoms one by one does not
find root causes at all, and grouping by incident first does, most of the time. What it
does not support: a claim about traceback-shaped failures, where the record-level method
was designed and is still to be measured on the duplicate-link and injected-fault sets; or
about overlapping incidents, which this campaign never produced.

Reproduce with `mend cluster crossval runs/chaos09-2026-10-17.jsonl --k 3` after
`mend capture chaos09` on the campaign (about 25 minutes).

## Reproducing the table above

```
mend cluster metrics <records> --threshold 0.6
mend cluster metrics <records> --fingerprint-only
```
