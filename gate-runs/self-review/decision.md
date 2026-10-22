## Gate: PASS

Spec `mend-self-review` (57d050c0f85c7724).

Baseline `different-vendor reviewer`, candidate `the fixer's own model reviewing`.

| Suite | Paired items | Baseline | Candidate | Difference | Margin | Holm p | Verdict |
|---|---:|---|---|---|---:|---:|---|
| verdict-right | 104 | 67.3% (57.7 to 76.0) | 76.0% (67.3 to 83.7) | +8.7% (-1.0 to +18.3) | -10% | 0.001 | pass |
| not-confidently-wrong | 104 | 95.2% (90.4 to 99.0) | 92.3% (86.5 to 97.1) | -2.9% (-7.7 to +1.0) | -10% | 0.002 | pass |

Difference is candidate minus baseline, paired by item, with its 95% bootstrap interval. A suite passes when the whole interval sits above the margin after Holm's adjustment across the decided suites; an under-powered suite warns and is not decided.

**Reasons**

- pass: 2 of 2 suites decided, none inferior
