"""Where the live workflow may act: the repository it runs in, if that is one listed here.

Two conditions, both required. The target must be the repository GitHub Actions says the
job is running in, so a workflow installed in one repository cannot be pointed at another
by an input. And it must be on this list, so installing the workflow somewhere new is a
reviewed change to this file rather than a copy of a YAML file.
"""

from __future__ import annotations

# PLAN.md section 2.7: the portfolio's own public repositories, chosen by Peter on
# 2026-10-31. Project 03's release gate and project 04's gateway.
REPOSITORIES = frozenset({"Peter-A-P/ai-release-gate", "Peter-A-P/compliant-ai-gateway"})


class OutOfScope(Exception):
    """The workflow was asked to act somewhere it may not."""


def check(target: str, *, running_in: str | None) -> str:
    """target, if the live workflow may act on it; OutOfScope otherwise."""
    if not running_in:
        raise OutOfScope("not running in GitHub Actions: GITHUB_REPOSITORY is unset")
    if target.casefold() != running_in.casefold():
        raise OutOfScope(f"asked to act on {target} from a workflow running in {running_in}")
    allowed = {r.casefold(): r for r in REPOSITORIES}
    if target.casefold() not in allowed:
        raise OutOfScope(f"{target} is not one of {sorted(REPOSITORIES)}")
    return allowed[target.casefold()]
