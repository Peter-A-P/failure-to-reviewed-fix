# Self-Healing Production AI

When a production system fails, this captures the failure with full context, drafts the
fix, has a second AI review it adversarially, and hands an engineer a ready-to-approve pull
request. Triage in minutes instead of days, engineers back on new work, and nothing changes
without a person saying yes.

**Status: planning.** Nothing has run yet. The plan is in [PLAN.md](PLAN.md): a
three-week build in July 2027, measured against real open-source issues with hidden tests.

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

## What this does not do

- It does not merge. There is no merge path in the code, and a test asserts it.
- It does not patch without proof. A failing test that demonstrates the bug comes first,
  or the system stops and says why.
- It does not chase a leaderboard. The hit rate on hidden tests is what it is; the
  confidently-wrong analysis matters more.
- It is Python only in this version, because the benchmark and the sandbox are.

## How it works

See [PLAN.md](PLAN.md). Failures arrive as test results, traces and logs and become
structured records. Clustering by fingerprint, failure-text embeddings and code locality
turns many symptoms into one ticket, measured against maintainers' own duplicate links,
injected faults with known causes, and recorded chaos runs. For each ticket the system
localises the fault, writes a test that must fail on the broken commit, drafts a patch that
must pass it and the existing suite, and sends the result to a reviewer model from a
different vendor whose job is to break it. A routing score with thresholds calibrated
against a stated false-positive target decides whether to open a draft pull request,
leave a suggestion, or stay quiet. Every model call goes through the portfolio gateway
with a spend cap per issue; every comparison runs through the release gate with intervals.

## Part of a portfolio

One of fifteen projects built over twelve months. It calls models through the Compliant AI
Gateway, is measured with the AI Release Gate, uses the failure traces from the Real-Time
Risk Platform's chaos runs, and inherits its agent patterns from Overload.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command and the benchmark's containers, and that reproducibility is
the evidence that matters.
