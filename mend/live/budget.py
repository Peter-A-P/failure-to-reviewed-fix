"""The live workflow's running total, kept beside the gateway's ledger.

The gateway caps spend per issue and per month (config/live.caps.yaml). A demonstration
budget is neither: it is a total, and a new month must not refill it. So mend live keeps
the total of every issue it has run in this repository, refuses to start one once the
total has reached the cap, and adds each issue's cost when it finishes. The file travels
with the ledger in the workflow's cache.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# US$3 across the two repositories (Peter, 2026-10-31), half each. config/live.caps.yaml
# holds the same number as the gateway's monthly cap, and a test asserts the two agree.
TOTAL_USD = 1.50


class BudgetSpent(Exception):
    """The live budget for this repository is used up."""


@dataclass(frozen=True, slots=True)
class Budget:
    path: Path
    cap_usd: float = TOTAL_USD

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"total_usd": 0.0, "issues": []}
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return data

    @property
    def spent_usd(self) -> float:
        return float(self._load()["total_usd"])

    def check(self) -> float:
        """What is left, or BudgetSpent if nothing is."""
        left = self.cap_usd - self.spent_usd
        if left <= 0:
            raise BudgetSpent(
                f"US${self.spent_usd:.2f} of the US${self.cap_usd:.2f} live budget is spent"
            )
        return left

    def add(self, issue_id: str, cost_usd: float | None, *, run_url: str = "") -> float:
        """Record one issue's cost and return the new total. An issue whose cost is
        unknown is recorded at the per-issue cap, the most it could have spent."""
        data = self._load()
        cost = 1.00 if cost_usd is None else float(cost_usd)
        data["total_usd"] = round(float(data["total_usd"]) + cost, 6)
        data["issues"].append(
            {
                "issue_id": issue_id,
                "cost_usd": cost,
                "cost_known": cost_usd is not None,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "run": run_url,
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        return float(data["total_usd"])
