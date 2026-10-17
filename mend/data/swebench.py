"""The benchmark subset: sampled once, stratified by repository, committed as ids.

This module exists to make one rule mechanical rather than a good intention: report the
hit rate as it falls, on a subset chosen before the first run, with no excluding hard
tasks afterwards (PLAN.md section 2.1 and the repository rules).

The mechanism is a subset file holding the sampled ids and the seed and date that produced
them. sample() writes it once and refuses to overwrite it; load() reads it back and is
what every run uses. There is no filter argument, no exclude list and no "skip failures"
flag anywhere in this file, and adding one would be a visible change to a file whose whole
purpose is that it has none.

Stratified by repository because SWE-bench Verified is dominated by a handful of large
projects, and an unstratified sample of 120 would be mostly django. Stratification here
means proportional allocation with a floor, so that every repository present in the full
set is present in the subset: a run that covers every repository can be cut short and
still say something, which is the mitigation in PLAN.md section 8 for a slow sandbox.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class Task:
    """One benchmark instance, as much of it as this project reads.

    Deliberately does not carry the hidden tests, the gold patch, or the test directives.
    Those exist in the dataset and are the harness's business; a Task object that held
    them could be passed to a model by accident, and the honest hit rate depends on that
    being impossible rather than unlikely (PLAN.md section 2.1, and the repository rule
    that hidden tests are never read).
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    environment_setup_commit: str | None = None
    # The harness's prebuilt image for the broken commit (harness 5.x names it in the row).
    # The environment, not the evaluation: the hidden tests are applied by the harness's
    # eval_script, which is not read here.
    image: str | None = None

    @property
    def repo_key(self) -> str:
        """The stratum: owner/name, which is what the dataset's repo field already is."""
        return self.repo


@dataclass(frozen=True, slots=True)
class Subset:
    """A sampled subset, with everything needed to say it was not chosen after the fact."""

    instance_ids: tuple[str, ...]
    seed: int
    sampled_at: str
    source: str
    per_repo: Mapping[str, int]

    def __len__(self) -> int:
        return len(self.instance_ids)


def load_tasks(path: Path) -> list[Task]:
    """Tasks from a JSON or JSON Lines export of the dataset.

    Unknown keys are ignored rather than rejected: the dataset carries fields this project
    must not read, and the way to not read them is to not lift them off the page.
    """
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, object]]
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload["instances"]

    return [
        Task(
            instance_id=str(row["instance_id"]),
            repo=str(row["repo"]),
            base_commit=str(row["base_commit"]),
            problem_statement=str(row.get("problem_statement", "")),
            environment_setup_commit=(
                str(row["environment_setup_commit"])
                if row.get("environment_setup_commit")
                else None
            ),
            image=str(row["image"]) if row.get("image") else None,
        )
        for row in rows
    ]


def allocate(counts: Mapping[str, int], size: int, *, floor: int = 1) -> dict[str, int]:
    """How many tasks to take from each repository.

    Proportional allocation with a floor of one per repository, then the remainder given
    to the largest repositories by fractional part. The floor is what guarantees coverage;
    the largest-remainder step is what stops the floor from quietly making the sample
    uniform when there are many small repositories.
    """
    if size <= 0:
        raise ValueError("a subset needs a positive size")
    total = sum(counts.values())
    if size > total:
        raise ValueError(f"cannot sample {size} tasks from {total}")
    if floor * len(counts) > size:
        raise ValueError(
            f"a floor of {floor} across {len(counts)} repositories needs at least "
            f"{floor * len(counts)} tasks, not {size}"
        )

    exact = {repo: size * n / total for repo, n in counts.items()}
    allocation = {repo: max(floor, math.floor(value)) for repo, value in exact.items()}

    # Never allocate more than a repository has.
    for repo in allocation:
        allocation[repo] = min(allocation[repo], counts[repo])

    # Hand out or claw back the difference, largest fractional part first.
    order = sorted(exact, key=lambda r: (-(exact[r] - math.floor(exact[r])), r))
    while sum(allocation.values()) < size:
        moved = False
        for repo in order:
            if sum(allocation.values()) >= size:
                break
            if allocation[repo] < counts[repo]:
                allocation[repo] += 1
                moved = True
        if not moved:  # pragma: no cover - guarded by the size check above
            break
    while sum(allocation.values()) > size:
        for repo in reversed(order):
            if sum(allocation.values()) <= size:
                break
            if allocation[repo] > floor:
                allocation[repo] -= 1

    return allocation


def sample(
    tasks: Sequence[Task],
    *,
    size: int,
    seed: int,
    source: str,
    floor: int = 1,
) -> Subset:
    """Draw a stratified subset. Deterministic in (tasks, size, seed).

    Deterministic and seeded so that the sample can be redrawn and checked by anyone who
    has the dataset, which is the difference between "we sampled before the run" as a
    claim and as a fact.
    """
    if not tasks:
        raise ValueError("no tasks to sample from")

    by_repo: dict[str, list[Task]] = {}
    for task in tasks:
        by_repo.setdefault(task.repo_key, []).append(task)
    for group in by_repo.values():
        group.sort(key=lambda t: t.instance_id)

    allocation = allocate({repo: len(group) for repo, group in by_repo.items()}, size, floor=floor)

    rng = np.random.default_rng(seed)
    chosen: list[str] = []
    for repo in sorted(by_repo):
        group = by_repo[repo]
        take = allocation[repo]
        indices = rng.permutation(len(group))[:take]
        chosen.extend(group[int(i)].instance_id for i in sorted(indices))

    return Subset(
        instance_ids=tuple(sorted(chosen)),
        seed=seed,
        sampled_at=datetime.now(UTC).date().isoformat(),
        source=source,
        per_repo=dict(sorted(allocation.items())),
    )


def write_subset(subset: Subset, path: Path) -> None:
    """Write the subset file, refusing to overwrite an existing one.

    The refusal is the point. Resampling after seeing the results, even innocently, is the
    thing this file exists to prevent, so replacing a committed subset has to be a
    deliberate act: delete the file in a commit that says why.
    """
    if path.exists():
        raise FileExistsError(
            f"{path} already holds a committed subset. Resampling after a run would make "
            "the hit rate meaningless; delete it in a commit that says why, or write "
            "elsewhere."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instance_ids": list(subset.instance_ids),
        "seed": subset.seed,
        "sampled_at": subset.sampled_at,
        "source": subset.source,
        "per_repo": dict(subset.per_repo),
        "n": len(subset),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_subset(path: Path) -> Subset:
    """Read the committed subset. Every run starts here."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Subset(
        instance_ids=tuple(payload["instance_ids"]),
        seed=int(payload["seed"]),
        sampled_at=str(payload["sampled_at"]),
        source=str(payload["source"]),
        per_repo=dict(payload.get("per_repo", {})),
    )
