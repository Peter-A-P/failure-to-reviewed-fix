# Working notes for Claude Code

This repository is From Failure to Reviewed Fix, in Minutes (renamed 2026-09-20; was
Self-Healing Production AI, and nothing here heals itself: every change is human-gated),
package `mend`: failure capture and
clustering, test-first patch drafting, adversarial review by a different vendor's model,
and calibrated confidence routing to a human-approved pull request. Built July 2027. The
plan is in [PLAN.md](PLAN.md).

## Read first

- [README.md](README.md): what this is and the current result tables.
- [PLAN.md](PLAN.md): the design. Do not deviate from it silently; if something in it turns
  out wrong, change the plan in the same commit as the code and say why in the commit
  message.
- `docs/boundary.md` once it exists: what this design is built from, with sources.

## Engineering standard

- Python 3.13. Typed throughout; `mypy --strict` and `ruff` clean in CI.
- Tests that fail meaningfully: no merge path, no patch without a failed test first,
  reviewer on a different provider than the fixer, spend cap before the first call,
  sandbox without network, clustering metrics on labelled fixtures.
- `pyproject.toml` with pinned major versions and a comment saying why for each pin.
- Docs ship in the same commit as the change.
- Never commit credentials, GitHub tokens, or anything from `.env`.

## Rules specific to this repository

- **Public repositories and public sources only.** No internal architecture, prompts,
  thresholds or code from anywhere, and no design borrowed from an employer system. If a
  design starts to resemble one, stop and raise it. `docs/boundary.md` lists the sources.
- **Nothing merges.** No merge path exists; a test asserts it. Draft pull requests and
  comments only, and only in repositories this workflow is installed in.
- **Failing test first, or no patch.** The graph's state machine enforces it.
- **The reviewer is a different vendor** than the fixer, by gateway alias; a configuration
  test asserts it.
- **Every model call goes through the 04 gateway** with a spend cap per issue enforced
  before the first call.
- **Hidden tests are never read.** The benchmark's evaluation tests are used only by the
  harness, never shown to any model or used to tune anything.
- **Report the hit rate as it falls.** No cherry-picked subsets, no excluding hard tasks
  after the fact; the subset is sampled before the first run and its ids committed.
- **Every reported number carries a confidence interval.**
- **Plain punctuation** in everything written here: no em-dashes or other typographic
  dashes, straight quotes only.

## What goes in the README

The README opens with the one-liner, the results tables and the honest limitation, before
any installation instructions. The report command fills the tables; do not hand-edit them.
Record one approach that was tried and rejected, with the evidence, once the work has
produced it.
