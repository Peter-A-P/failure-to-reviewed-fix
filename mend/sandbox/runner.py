"""Running a RunSpec, and refusing to run one that is not what it claims to be.

The runner is thin on purpose: it shells out to the docker client rather than using a
Python SDK, because the argument list is then exactly what a person can paste into a
terminal to reproduce a run, and that is worth more here than a typed API.

The one piece of logic it does have is the check in run(): a spec that is not isolated is
refused unless the caller passes allow_network, which only the image build does. That is
the "sandbox refuses network access from task containers" test in PLAN.md section 4.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass

from mend.sandbox.spec import DockerUnavailable, RunSpec, SandboxError


@dataclass(frozen=True, slots=True)
class RunResult:
    """What came back. timed_out is kept separate from a non-zero exit code.

    Separate because they mean different things to the stage above: a test that fails is
    evidence about the bug, and a test that ran for fifteen minutes and was killed is
    evidence about the test.
    """

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    args: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def docker_available() -> bool:
    """Whether there is a docker client on PATH that answers.

    Checks the daemon, not just the binary: Docker Desktop installed and not running is
    the common case on a laptop, and it fails at the first run rather than at the first
    command otherwise.
    """
    if shutil.which("docker") is None:
        return False
    # Three tries a few seconds apart: Docker Desktop busy unpacking a multi-gigabyte image
    # can miss one 30-second deadline and answer the next, and a validation run stopped at
    # task 8 of 30 on exactly that (2026-10-17).
    for attempt in range(3):
        try:
            done = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            done = None
        if done is not None and done.returncode == 0:
            return True
        if attempt < 2:
            time.sleep(10)
    return False


def run(spec: RunSpec, *, allow_network: bool = False) -> RunResult:
    """Run the spec, refusing an un-isolated one unless the caller insisted.

    allow_network is keyword-only and defaults to False, so the unsafe case cannot be
    reached by accident or by argument order. The only legitimate caller is the image
    build, which has to fetch a repository and install dependencies.
    """
    if not spec.is_isolated and not allow_network:
        raise SandboxError(
            f"refusing to run with network {spec.network.value}: task containers have no "
            "network (PLAN.md section 4). Pass allow_network=True only to build an image."
        )
    if not docker_available():
        raise DockerUnavailable(
            "no Docker daemon answered. The sandbox needs one; see docs/sandbox.md."
        )

    args = ["docker", *spec.docker_args()]
    started = time.monotonic()
    try:
        done = subprocess.run(
            args,
            capture_output=True,
            text=True,
            # UTF-8, never the Windows code page: a test printing a character cp1252
            # cannot decode left stdout as None and crashed the run (2026-10-20).
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        return RunResult(
            exit_code=124,
            stdout=_text(expired.stdout),
            stderr=_text(expired.stderr),
            timed_out=True,
            duration_s=time.monotonic() - started,
            args=tuple(args),
        )
    return RunResult(
        exit_code=done.returncode,
        stdout=done.stdout,
        stderr=done.stderr,
        timed_out=False,
        duration_s=time.monotonic() - started,
        args=tuple(args),
    )


def _text(raw: str | bytes | None) -> str:
    """TimeoutExpired carries whatever was captured before the kill, as str or bytes."""
    if raw is None:
        return ""
    return raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
