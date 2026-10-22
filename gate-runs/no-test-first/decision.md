## Gate: BLOCK

Spec `mend-no-test-first` (a3ad09f7d4d326e3).

Baseline `main run, failing test first`, candidate `no failing test first`.

| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |
|---|---:|---|---|---|---:|---:|---|
| resolved | 40 | 65.0% (50.0 to 80.0) | 67.5% (52.5 to 82.5) | +2.5% (-12.5 to +17.5) | -10% | 0.076 | block |
| not-confidently-wrong | 40 | 95.0% (87.5 to 100.0) | 95.0% (87.5 to 100.0) | +0.0% (-7.5 to +7.5) | -10% | 0.012 | pass |

Difference is candidate minus baseline, paired by item, with its 95% bootstrap interval. A suite passes when the whole interval sits above the margin after Holm's adjustment across the decided suites; an under-powered suite warns and is not decided.

**Reasons**

- resolved: cannot rule out a 10% drop: +2.5% (-12.5% to +17.5%) over 40 items, 4 worse and 5 better (p 0.076, Holm 0.076)
