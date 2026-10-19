"""Running a committed subset task by task: fix, score, clean up, and resume after a crash.

The build laptop has room for a handful of task images at a time, not 150, so each task
goes all the way through before the next starts: its image is pulled, mend runs on it, the
harness scores the drafted patch while the image is still there, and then the image and
the repository copy are removed. Two append-only logs make the run resumable: the run log
(one RunRecord per task, as mend fix writes) and the verdict log (one harness verdict per
task). A crash costs at most the task it happened on.

Resuming never re-runs a task that has a record. A task that was fixed but not judged is
scored again from its record, which pulls the image again but spends nothing on models: a
second attempt at the fix would be a second draw, and keeping whichever came out better is
exactly the selection the rules forbid.

The order of tasks is the subset file's order. There is no argument for choosing which
tasks run (mend.data.swebench has the reasons).
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mend.data.swebench import Task
from mend.sandbox.harness import evaluate, predictions, verdicts, write_predictions
from mend.sandbox.spec import QUICK_S, SandboxError
from mend.sandbox.workspace import remove_tree

# Outside the OneDrive-synced repository: a task's repository copy is thousands of files,
# and a synced folder would upload every one of them and then lock them during cleanup.
WORK_ROOT = Path(tempfile.gettempdir()) / "mend-work"


@dataclass(frozen=True, slots=True)
class RunPaths:
    root: Path

    @property
    def runs(self) -> Path:
        return self.root / "fix.jsonl"

    @property
    def verdicts(self) -> Path:
        return self.root / "verdicts.jsonl"

    def score_dir(self, instance_id: str) -> Path:
        return self.root / "score" / instance_id


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def recorded_runs(paths: RunPaths) -> dict[str, dict[str, Any]]:
    return {str(r["issue"]["issue_id"]): r for r in _read_jsonl(paths.runs)}


def recorded_verdicts(paths: RunPaths) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for row in _read_jsonl(paths.verdicts):
        out[str(row["instance_id"])] = row["resolved"]
    return out


def score_one(run: Mapping[str, Any], paths: RunPaths, *, name: str) -> bool | None:
    """The harness's verdict on one task's drafted patch, while its image is still local."""
    instance_id = str(run["issue"]["issue_id"])
    target = paths.score_dir(instance_id).resolve()
    target.mkdir(parents=True, exist_ok=True)
    write_predictions(predictions([run]), target / "predictions.jsonl")
    report = evaluate(
        "predictions.jsonl",
        run_id=f"{name}-{instance_id}",
        instance_ids=[instance_id],
        workdir=target,
        max_workers=1,
    )
    return verdicts(report).get(instance_id)


def remove_task(task: Task, work_root: Path = WORK_ROOT) -> None:
    """The task's image and repository copy. Failures here are not fatal: a leftover image
    costs disk, not correctness, and the next task should still run."""
    with contextlib.suppress(OSError):
        remove_tree(work_root / task.instance_id)
    if task.image:
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(
                ["docker", "image", "rm", "-f", task.image],
                capture_output=True,
                check=False,
                timeout=QUICK_S,
            )
        trim_docker_disk()


# The run stops before a task when the host disk has less than this free. Docker Desktop's
# data disk on Windows keeps space a removed image used (2026-10-19: 19 GB allocated while
# Docker held 3 GB), so removing images bounds what Docker holds but not what the host
# loses, and a run that filled the laptop's disk would break far more than the run.
MIN_FREE_BYTES = 10 * 1024**3


class DiskLow(SandboxError):
    """Too little free disk to start another task. Stops the run cleanly; resumable."""


def free_bytes(path: Path = WORK_ROOT) -> int:
    probe = path if path.exists() else path.parent
    return shutil.disk_usage(probe).free


def trim_docker_disk() -> None:
    """Ask Docker's VM to trim its filesystems, so freed blocks can be handed back or
    reused. Best effort: a failure here costs disk, not correctness."""
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--privileged",
                "--pid=host",
                "alpine:3.20",
                "nsenter",
                "-t",
                "1",
                "-m",
                "--",
                "fstrim",
                "-a",
            ],
            capture_output=True,
            check=False,
            timeout=QUICK_S,
        )


def run_subset(
    instance_ids: Sequence[str],
    tasks: Mapping[str, Task],
    paths: RunPaths,
    *,
    fix: Callable[[Task], dict[str, Any]],
    score: Callable[[Mapping[str, Any]], bool | None],
    cleanup: Callable[[Task], None],
    echo: Callable[[str], None] = print,
    disk_free: Callable[[], int] = free_bytes,
    min_free: int = MIN_FREE_BYTES,
) -> None:
    """Every task in order, each fixed, scored and cleaned up before the next.

    A task with no drafted patch gets the verdict False without a harness run: there was
    nothing to judge. A verdict of None (the harness could not judge) is written as None
    and the task is scored again on the next resume.
    """
    runs = recorded_runs(paths)
    judged = recorded_verdicts(paths)
    for i, instance_id in enumerate(instance_ids, start=1):
        if judged.get(instance_id) is not None:
            continue
        free = disk_free()
        if free < min_free:
            raise DiskLow(
                f"{free / 1024**3:.1f} GB free, below the {min_free / 1024**3:.0f} GB floor; "
                f"stopped before {instance_id}. Free some space or compact Docker's data disk, "
                "then run the same command again."
            )
        task = tasks[instance_id]
        try:
            run = runs.get(instance_id)
            if run is None:
                run = fix(task)
                _append(paths.runs, run)
                runs[instance_id] = run
            drafted = bool(predictions([run]))
            verdict = score(run) if drafted else False
            _append(paths.verdicts, {"instance_id": instance_id, "resolved": verdict})
            state = run.get("state") or {}
            echo(
                f"[{i}/{len(instance_ids)}] {instance_id}: {state.get('stage')}"
                + (f" ({state.get('stop_reason')})" if state.get("stop_reason") else "")
                + (f", tier {state.get('tier')}" if state.get("tier") else "")
                + f", resolved {verdict}"
                + f" [{disk_free() / 1024**3:.1f} GB free]"
            )
        finally:
            cleanup(task)
