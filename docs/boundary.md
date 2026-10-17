# What this is built from

**Written 2026-09-13, at the start of the build.** Updated in the same commit as any
change to what the design draws on.

This project sits close to work done inside the Government of Newfoundland and Labrador.
It is built from public repositories and public sources only. This page lists them, says
what was taken from each, and names the places where this design deliberately differs from
anything an employer system does. It exists so that a reader does not have to take the
claim on trust, and so that a later commit that drifts has something to be measured
against.

## The short version

Nothing in this repository comes from a Government of Newfoundland and Labrador system.
No architecture, no prompts, no thresholds, no feature definitions, no code, and no
design borrowed from an internal system and renamed. The sources below are public, dated
and named. Where a design decision here happens to be a decision anyone would make, it is
recorded as such rather than claimed as original.

## What the design is built from

| Source | Public at | What was taken |
|---|---|---|
| SWE-bench and SWE-bench Verified | The dataset, its paper and its containerised harness (5.0.2), all public | The evaluation method: real issues from public Python repositories, judged by tests the system never sees. The harness runs the tests; this project does not reimplement it. Its Django and sympy log parsers are also used to read the sandbox's own test runs |
| The published agent literature on issue resolution | Papers and open repositories | The general shape of localise, edit, test. This shape is common knowledge in the field and is not anybody's private design |
| LangGraph | Public framework and documentation | Graph orchestration patterns, carried in through portfolio project 11 |
| OpenTelemetry | Public specification | The span and log shapes the capture stage reads. `mend/capture/otel_ingest.py` parses the standard OTLP JSON export and nothing else |
| JUnit XML | De facto public standard | The test-report shape the capture stage reads |
| Wilson score intervals; the percentile bootstrap; purity, completeness and the adjusted Rand index | Standard statistics, textbook definitions | Implemented in this repository from the published definitions, with the worked examples in `tests/test_cluster_metrics.py` as the check |
| Portfolio project 04, the Compliant AI Gateway | Peter's own, same portfolio | Every model call, the cost ledger, the spend caps, the route aliases |
| Portfolio project 03, the AI Release Gate | Peter's own, same portfolio | The evaluation discipline: graders are tests rather than judges, and every comparison carries an interval |
| Portfolio project 09, the Real-Time Risk Platform | Peter's own, same portfolio | Recorded chaos runs, used as a labelled capture set: logs and Prometheus metrics per run, the injected scenario as the label |
| Agentless (Xia et al., 2024) and SWE-agent (Yang et al., 2024) | Papers and open repositories | The published shape the hops follow: localise from the file listing before reading code, reproduce the issue with a test, then edit. Nothing of their prompts or code |
| Aider's search-and-replace edit format | Open-source repository and documentation | The idea that a model quotes the exact text to change rather than writing a unified diff. The tag syntax, the refusal messages and the diff construction in `mend/graph/parse.py` are this repository's |

## Where this design deliberately differs

Three decisions were taken to make this design its own, and each of them is enforced by a
test rather than by intention:

1. **A failing test comes first, or there is no patch.** The state machine in
   `mend/graph/machine.py` has no edge into `PATCHED` from anywhere except
   `TEST_FAILED_AS_EXPECTED`, and the transition re-checks that the evidence is still on
   the state when it arrives. `tests/test_machine.py` tries the shortcut by the two most
   convenient routes and asserts both are refused.
2. **The reviewer is a different vendor than the fixer.** Configured as gateway aliases in
   `config/mend.routes.yaml`, checked at start-up by `mend.gateway.check_roles`, and
   asserted against the shipped configuration by `tests/test_roles.py`. A same-vendor
   pairing does not start.
3. **Clustering is learned against maintainers' own duplicate links**, plus injected
   faults with causes known by construction, rather than against any internal taxonomy.
   The metrics are in `mend/cluster/metrics.py` and are computed on labelled sets whose
   ids are published.

## Data, and the terms it comes under

| Data | Terms | What this repository holds |
|---|---|---|
| SWE-bench Verified | MIT-licensed dataset; the underlying repositories keep their own open licences | The sampled subset ids, the seed and the sampling date. No dataset rows, no repository contents, no images |
| Public issue trackers | GitHub API terms | Issue ids and the duplicate labels derived from them. Issue text is cached locally for reproducibility and is not redistributed |
| Injected faults on two open-source test suites | The repositories' own open licences | The mutation definitions. The faults are local and are never proposed upstream |
| Project 09 chaos runs | Peter's own | Nothing raw. The captures stay in 09's working tree; the records `mend capture chaos09` derives from them go to `runs/`, which is not committed |

Nothing raw is committed. `.gitignore` keeps `data/raw/`, `data/swebench/`, `data/issues/`
and the sandbox working directories out of the repository.

## Hidden tests are never read

The benchmark's evaluation tests are used by its harness and by nothing else. The rule is
made mechanical rather than remembered: `mend.data.swebench.Task` has no field the hidden
tests, the gold patch or the test directives could be lifted into, so a prompt built from
a `Task` cannot contain them even by accident.
`tests/test_subset.py::test_the_task_type_cannot_carry_hidden_tests` loads a dataset row
carrying all three and asserts none of them survives into the object.

Harness 5.x adds a fourth place they live: each row's `eval_script`, which applies the
hidden test patch and runs the task's test command. `Task` has no field for it either, and
the same test asserts so. That is why the sandbox's per-repository test commands in
`mend/sandbox/runners.py` are written from each project's own documentation rather than
taken from the benchmark: the benchmark keeps them in the one field mend does not read.

The hidden tests' results come back as one bit per task, resolved or not, read from the
harness's report (`mend.sandbox.harness.verdicts`). The per-task test output the harness
writes under `logs/` names the hidden tests and is not read by mend or shown to any model;
when the harness was checked on this laptop, its setup log was read and its test output
was not.

## The subset is chosen before the run

`mend.data.swebench.write_subset` refuses to overwrite a committed subset file. There is
no filter, exclude or skip argument anywhere in that module, and a test scans its source
to keep it that way. Excluding hard tasks after seeing the results would make the headline
number meaningless, and the way to prevent it is to make it a visible act rather than a
convenience.

## If this starts to resemble an internal system

Stop and raise it. The substitute named in the portfolio plan takes this project's slot.
That has not happened and this page will say so if it does.
