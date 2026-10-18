"""Scoring a run with the official SWE-bench harness, and nothing else.

The pipeline's run log says what mend did with each task; whether that fixed the issue is
decided by the benchmark's hidden tests, run by the benchmark's own harness, in its own
containers. This module is the hand-off: it writes the drafted patches in the harness's
predictions format, runs the harness as a separate process, and reads back one verdict per
task. It never reads the hidden tests itself; the harness applies them, and only its
resolved or not comes back.

Three rules, each because getting it wrong would change the headline number:

- What is submitted is the source diff only. The test mend wrote is evidence for a person
  reviewing the change, not part of the fix, and the harness's own test patch may add a
  file at the same path, which would make the hidden tests fail to apply.
- Every drafted patch is scored, whatever tier it was routed to. Stay-quiet precision and
  the routing curve need to know whether the patches mend declined to propose were wrong.
- A task the harness could not judge (an infrastructure error, a container that never
  finished) is not counted as unresolved. outcomes() refuses to produce a table until those
  tasks have been run again, because counting them as failures would make the hit rate
  depend on the laptop.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from mend.eval.results import IssueOutcome
from mend.graph.route import Tier
from mend.sandbox.runner import docker_available
from mend.sandbox.spec import BUILD_S, HARNESS_S, QUICK_S, DockerUnavailable, SandboxError

MODEL_NAME = "mend"
DATASET = "SWE-bench/SWE-bench_Verified"


class HarnessIncomplete(SandboxError):
    """Some submitted tasks have no verdict yet. Run them again; do not count them."""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(
            f"{len(self.missing)} submitted tasks have no harness verdict "
            f"({', '.join(self.missing[:5])}{'...' if len(self.missing) > 5 else ''}); "
            "run them again rather than counting them as unresolved"
        )


def read_runs(path: Path) -> list[dict[str, Any]]:
    """The run log mend fix writes: one RunRecord as JSON per line.

    A task run twice keeps its last record, so a rerun after a crash replaces the first
    attempt rather than counting the task twice.
    """
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[str(row["issue"]["issue_id"])] = row
    return list(latest.values())


def _diff(run: Mapping[str, Any]) -> str:
    patch = (run.get("state") or {}).get("patch") or {}
    return str(patch.get("diff") or "")


def predictions(runs: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The harness's input: one row per task with a drafted patch."""
    return [
        {
            "instance_id": str(run["issue"]["issue_id"]),
            "model_name_or_path": MODEL_NAME,
            "model_patch": _diff(run),
        }
        for run in runs
        if _diff(run)
    ]


def write_predictions(rows: Sequence[Mapping[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


# The harness runs in a Linux container of its own, driving the host's Docker through its
# socket. On a Windows host the harness writes its eval script and the patch with CRLF line
# endings, bash in the task container cannot run the script, and even the benchmark's gold
# patch scores as unresolved (checked 2026-10-17 on pallets__flask-5014). Inside Linux the
# same version writes LF and the gold patch resolves. The version is pinned in the image
# tag so a report always says which harness judged it.
HARNESS_VERSION = "5.0.2"
# The docker client is copied in because the harness shells out to it to remove each task
# container when the task is done; without it the containers are left behind.
_DOCKERFILE = (
    "FROM python:3.12-slim\n"
    "COPY --from=docker:27.5.1-cli /usr/local/bin/docker /usr/local/bin/docker\n"
    f"RUN pip install --no-cache-dir swebench=={HARNESS_VERSION}\n"
    "WORKDIR /work\n"
)
# The tag carries the harness version and a hash of the recipe, so changing either builds
# a new image instead of reusing a stale one under the same name.
HARNESS_IMAGE = (
    f"mend-harness:swebench-{HARNESS_VERSION}-"
    + hashlib.sha256(_DOCKERFILE.encode()).hexdigest()[:8]
)
# Where the harness container sees the scoring directory, and a named volume so the
# dataset is downloaded once rather than on every run.
_WORK = "/work"
_HF_CACHE = "mend-hf-cache:/root/.cache/huggingface"


def ensure_harness_image() -> None:
    """Build the harness image once. Building needs the network; nothing in it is model-
    written, and the task containers it starts are the harness's, with the harness's rules."""
    present = subprocess.run(
        ["docker", "image", "inspect", HARNESS_IMAGE],
        capture_output=True,
        check=False,
        timeout=QUICK_S,
    )
    if present.returncode == 0:
        return
    built = subprocess.run(
        ["docker", "build", "-t", HARNESS_IMAGE, "-"],
        input=_DOCKERFILE,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=BUILD_S,
    )
    if built.returncode != 0:
        raise SandboxError(f"could not build {HARNESS_IMAGE}: {built.stderr[-2000:]}")


def harness_command(
    predictions_name: str,
    *,
    run_id: str,
    instance_ids: Sequence[str],
    workdir: Path,
    max_workers: int = 2,
    timeout_s: int = 1800,
    dataset: str = DATASET,
) -> list[str]:
    """docker run of the harness, with workdir mounted as its working directory.

    predictions_name is a file inside workdir, or "gold" for the benchmark's own patches,
    which is how the harness is checked on a new machine before anything is scored."""
    predictions = predictions_name if predictions_name == "gold" else f"{_WORK}/{predictions_name}"
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{workdir.resolve().as_posix()}:{_WORK}",
        "-v",
        _HF_CACHE,
        "-w",
        _WORK,
        HARNESS_IMAGE,
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset,
        "--split",
        "test",
        "--predictions_path",
        predictions,
        "--run_id",
        run_id,
        "--max_workers",
        str(max_workers),
        "--timeout",
        str(timeout_s),
        "--report_dir",
        _WORK,
        "--instance_ids",
        *instance_ids,
    ]


def evaluate(
    predictions_name: str,
    *,
    run_id: str,
    instance_ids: Sequence[str],
    workdir: Path,
    max_workers: int = 2,
    timeout_s: int = 1800,
) -> Path:
    """Run the harness and return its report file, written into workdir with its per-task
    logs under workdir/logs/run_evaluation."""
    if not instance_ids:
        raise ValueError("nothing to score: no task has a drafted patch")
    if not docker_available():
        raise DockerUnavailable("the harness needs a running Docker daemon")
    ensure_harness_image()
    command = harness_command(
        predictions_name,
        run_id=run_id,
        instance_ids=instance_ids,
        workdir=workdir,
        max_workers=max_workers,
        timeout_s=timeout_s,
    )
    try:
        done = subprocess.run(command, check=False, timeout=HARNESS_S)
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"the harness did not finish within {HARNESS_S} s") from exc
    model = "gold" if predictions_name == "gold" else MODEL_NAME
    report = workdir / f"{model}.{run_id}.json"
    if done.returncode != 0 or not report.is_file():
        raise SandboxError(f"the harness exited {done.returncode} and wrote no report at {report}")
    return report


def verdicts(report_path: Path) -> dict[str, bool | None]:
    """resolved True, unresolved False, and None where the harness could not judge.

    Infrastructure failures the harness classifies are None even when it also lists them
    as unresolved: a test environment that broke says nothing about the patch.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    out: dict[str, bool | None] = {}
    for instance in report.get("unresolved_ids", []):
        out[instance] = False
    for instance in report.get("resolved_ids", []):
        out[instance] = True
    for key in ("error_ids", "incomplete_ids", "infra_failure_ids"):
        for instance in report.get(key, []):
            out[instance] = None
    return out


def outcomes(
    runs: Iterable[Mapping[str, Any]], judged: Mapping[str, bool | None]
) -> list[IssueOutcome]:
    """One IssueOutcome per task, resolved by the harness and by nothing else.

    A task with no drafted patch is unresolved without being submitted: there was nothing
    to judge. A task with a patch and no verdict raises HarnessIncomplete.
    """
    rows = list(runs)
    missing = [
        str(run["issue"]["issue_id"])
        for run in rows
        if _diff(run) and judged.get(str(run["issue"]["issue_id"])) is None
    ]
    if missing:
        raise HarnessIncomplete(missing)

    out = []
    for run in rows:
        issue_id = str(run["issue"]["issue_id"])
        state = run.get("state") or {}
        test = state.get("test") or {}
        review = state.get("review")
        drafted = bool(_diff(run))
        out.append(
            IssueOutcome(
                issue_id=issue_id,
                tier=Tier(state["tier"]) if state.get("tier") else Tier.QUIET,
                score=float(state.get("score") or 0.0),
                test_written=bool(test),
                test_failed_first=bool(test.get("ran") and test.get("failed_on_broken_commit")),
                patch_drafted=drafted,
                reviewer_agreed=bool(review["agrees"]) if review else None,
                resolved=bool(judged.get(issue_id)) if drafted else False,
                cost_usd=run.get("cost_usd"),
                duration_s=run.get("duration_s"),
                stop_reason=state.get("stop_reason"),
            )
        )
    return out
