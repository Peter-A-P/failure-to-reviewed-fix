# Tried and rejected: record-level clustering for production signals

PLAN.md section 9 asked for one approach tried and rejected, with the evidence. This is it.

## What was tried

The clustering in `mend/cluster/agglomerate.py` compares failures one record at a time. Each
pair of symptoms gets a distance built from three channels: a fingerprint (exception type,
innermost project frame, normalised message), an embedding of the failure text, and code
locality (shared frames and files). Average-linkage clustering cuts the distances into
tickets at a threshold tuned on held-out causes. It was the plan's design (section 2.2), it
was built first, and on a hand-built traceback fixture it recovered every bug exactly.

## The evidence against it

Project 09's chaos campaign is 42 recorded runs of a streaming platform, five each of eight
injected faults and two fault-free controls, read into 373 symptoms by `mend capture
chaos09`. Every one of the 56 ways of holding three faults out was tried, each method tuned
on the other five faults and scored on the held-out three (`mend cluster crossval`,
`results/chaos09/crossval.json`):

| Method | Held-out ARI, mean | Spread across the 56 folds |
|---|---|---|
| Record-level (fingerprint, text, locality) | 0.032 | 0.009 to 0.055 |
| Fingerprint only | 0.021 | 0.004 to 0.044 |
| Two-stage (incidents, then signatures) | 0.636 | 0.136 to 0.991 |

An ARI of 0.03 is chance. The record-level method does not find these faults at any
threshold, on any fold. The two-stage method, which first groups symptoms that began
together into incidents and then groups incidents by the set of their symptoms, is higher on
all 56 folds.

## Why

One fault in a production system shows as many signals at once: a dozen metrics leave their
steady levels in the same few seconds, each a separate record with its own name. Nothing in
a fingerprint, a text embedding or a stack frame says that `verdict_dead_letters_total rose`
and `redpanda_kafka_request_latency_seconds_sum fell` are the same incident. Only time does.
Comparing records one by one was designed for tracebacks, where one bug tends to fail in one
place, and that assumption does not survive contact with metrics.

## What this does not show

That record-level clustering is wrong for tracebacks. Measured there since (2026-10-21,
`docs/clustering.md`): on 40 injected faults it reaches an ARI of 0.568 (0.352 to 0.784),
a little above the fingerprint alone, so it is not rejected for the case it was designed
for. It is not much better than the fingerprint either. And that two-stage
clustering is right in general: it was measured on one set of eight faults whose incidents
never overlapped in time, which is the case it handles best. The spread across folds is
wide because eight faults is few.

## How the measurement changed, in order

The first measurement was a single seeded split, three faults to tune on and five to score.
It gave the two-stage method 0.080, because three faults chose a threshold that merged two
look-alike faults. Cross-validating over every split was adopted after seeing that, and
`docs/clustering.md` keeps both results, the first one first.
