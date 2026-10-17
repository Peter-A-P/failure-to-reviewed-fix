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
and it logs little, so most of what distinguishes one fault from another will be in the
metrics; the ingesters for both are the next piece of work here. (Updated 2026-10-17.)

## Reproducing the table above

```
mend cluster metrics <records> --threshold 0.6
mend cluster metrics <records> --fingerprint-only
```
