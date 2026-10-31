"""The sandbox for a live repository: an image with its code and dependencies, then runs
from that image with no network.

The benchmark tasks come with images. A live repository does not, so one is built from the
checkout of the failing commit: a plain Python image, the repository copied in, and its
own install command run. The build is the one step with network access, and it runs
nothing a model wrote: only the repository's code as it was pushed, and its locked
dependencies. Every test run after that, the full suite to capture the failures and each
of the pipeline's runs of a generated test or patch, goes through mend.sandbox with the
network off, exactly as on the benchmark.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from xml.etree import ElementTree

from mend.sandbox.runner import RunResult, run
from mend.sandbox.runners import JUNIT_PATH
from mend.sandbox.spec import BUILD_S, RunSpec, SandboxError

WORKDIR = "/repo"

# Pinned so a rebuild next month installs with the same resolver; the version the build
# laptop ran, which reads the lock files of both repositories.
UV_IMAGE = "ghcr.io/astral-sh/uv:0.12.13"
PYTHON_IMAGE = "python:3.13-slim"


def dockerfile(install: str) -> str:
    """The image: git for applying diffs, uv for the install, the repository at /repo and
    its environment outside it, so the host copy the hops read holds only the code."""
    return "\n".join(
        [
            f"FROM {PYTHON_IMAGE}",
            "RUN apt-get update && apt-get install -y --no-install-recommends git "
            "&& rm -rf /var/lib/apt/lists/*",
            f"COPY --from={UV_IMAGE} /uv /uvx /usr/local/bin/",
            "ENV UV_PROJECT_ENVIRONMENT=/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never",
            f"WORKDIR {WORKDIR}",
            "COPY . /repo",
            f"RUN {install}",
            "ENV PATH=/venv/bin:$PATH VIRTUAL_ENV=/venv",
            "",
        ]
    )


# The repository's own .dockerignore is written for its own image and may leave the tests
# out (04's does), so the build uses this one instead: BuildKit reads <Dockerfile>.dockerignore
# beside the Dockerfile in place of the context's. It keeps secrets, local state and the
# environment out, and the tests in.
IGNORE = "\n".join(
    (
        ".git/",
        ".env",
        ".env.*",
        "CLAUDE.local.md",
        "*.sqlite",
        "*.sqlite-*",
        ".venv/",
        "**/__pycache__",
        "",
    )
)


def build(
    checkout: Path,
    install: str,
    tag: str,
    *,
    execute: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> str:
    """Build the image for checkout and return its tag."""
    with tempfile.TemporaryDirectory(prefix="mend-image-") as tmp:
        path = Path(tmp) / "Dockerfile"
        path.write_text(dockerfile(install), encoding="utf-8", newline="\n")
        (Path(tmp) / "Dockerfile.dockerignore").write_text(IGNORE, encoding="utf-8", newline="\n")
        command = ["docker", "build", "-q", "-f", str(path), "-t", tag, str(checkout)]
        env = {**os.environ, "DOCKER_BUILDKIT": "1"}
        if execute is None:
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=BUILD_S,
                env=env,
            )
        else:
            done = execute(command)
    if done.returncode != 0:
        raise SandboxError(f"could not build the image for {checkout}: {done.stderr[-2000:]}")
    return tag


def suite_command(paths: Sequence[str]) -> str:
    """The whole suite, or the named paths of it, writing the JUnit XML capture reads."""
    parts = [
        "python",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={JUNIT_PATH}",
        "-q",
        *paths,
    ]
    return " ".join(shlex.quote(p) for p in parts)


def run_suite(
    image: str,
    out_dir: Path,
    *,
    paths: Sequence[str] = (),
    timeout_s: int = 1800,
    execute: Callable[[RunSpec], RunResult] = run,
) -> Path:
    """Run the suite in the sandbox and return the JUnit XML it wrote."""
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = RunSpec(
        image=image,
        command=("bash", "-c", f"cd {WORKDIR} && {suite_command(paths)}; exit 0"),
        workdir=WORKDIR,
        timeout_s=timeout_s,
        mounts=((out_dir, "/mend/out", False),),
    )
    result = execute(spec)
    report = out_dir / "report.xml"
    if not report.is_file():
        tail = ((result.stdout or "") + (result.stderr or ""))[-2000:]
        raise SandboxError(f"the suite wrote no JUnit report: {tail}")
    return report


def collected(report: Path) -> int:
    """How many tests the report says ran. Zero is not a pass: it is a sandbox that did not
    see the suite, which is what an image built without the tests looks like."""
    return sum(1 for _ in ElementTree.parse(report).getroot().iter("testcase"))
