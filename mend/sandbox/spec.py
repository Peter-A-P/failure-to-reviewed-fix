"""What a sandboxed run is allowed to do, as a value rather than as a habit.

Every command this project runs on behalf of a model runs in a container, and the
constraints on that container are built here and asserted by tests. The reason to make the
specification a value with its own tests, rather than a string of docker flags assembled
at the call site, is that the constraints are the security property: a run that quietly
loses --network none is a model-authored test executing with the laptop's network and the
laptop's credentials, and nothing downstream would notice.

The default is the strict one and the unsafe options have to be spelled out. There is no
way to build a spec with network access except to pass network=Network.BRIDGE by name,
and tests/test_sandbox_spec.py asserts that the default refuses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Network(StrEnum):
    """Container networking. NONE is the default everywhere in this package.

    BRIDGE exists for exactly one job: building the task image, which has to fetch the
    repository and install its dependencies. Nothing a model wrote ever runs under it.
    """

    NONE = "none"
    BRIDGE = "bridge"


class SandboxError(Exception):
    """The sandbox could not run, or was asked to run something it will not."""


# Deadlines for the docker commands that are not a test run (a test run has its own,
# RunSpec.timeout_s). Each is generous for its job; their point is that a command that will
# never return is turned into an error. On 2026-10-17 a docker pull waited ten hours on a
# Docker Desktop engine that had stopped answering, and the run waited with it.
QUICK_S = 120  # inspect, rm, create
PULL_S = 1800  # one attempt at a multi-gigabyte image
COPY_S = 900  # a repository out of an image
BUILD_S = 1800  # the harness image, once
HARNESS_S = 5400  # one harness run, image work and tests included


class DockerUnavailable(SandboxError):
    """No usable Docker daemon. Distinguished from a failed run on purpose.

    A run that could not start is not a task that failed, and counting one as the other
    would quietly turn an unconfigured laptop into a low hit rate.
    """


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One command, and the box it runs in.

    Defaults are the strict ones:

    - network NONE. A generated test that reaches the internet can pass for reasons that
      have nothing to do with the bug, and a generated patch that reaches the internet is
      a generated patch nobody should run at all.
    - a wall-clock timeout, because an infinite loop in a generated test is not an
      unusual outcome, it is a weekly one.
    - memory and process limits, because the other common outcome is a fork bomb or an
      allocation the laptop cannot survive.
    - read_only false, because the test run writes; the workspace is a per-task copy that
      is thrown away, which is the actual containment.
    """

    image: str
    command: tuple[str, ...]
    workdir: str = "/testbed"
    network: Network = Network.NONE
    timeout_s: int = 900
    memory_mb: int = 4096
    pids_limit: int = 512
    cpus: float = 2.0
    env: dict[str, str] = field(default_factory=dict)
    mounts: tuple[tuple[Path, str, bool], ...] = ()

    def __post_init__(self) -> None:
        if not self.image:
            raise ValueError("a run needs an image")
        if not self.command:
            raise ValueError("a run needs a command")
        if self.timeout_s <= 0:
            raise ValueError("a run needs a positive timeout")
        if self.memory_mb < 256:
            raise ValueError("a run needs at least 256 MB")
        if self.pids_limit < 16:
            raise ValueError("a run needs at least 16 processes")

    @property
    def is_isolated(self) -> bool:
        """Whether this run is cut off from the network. Read by the runner, and by tests."""
        return self.network is Network.NONE

    def docker_args(self) -> list[str]:
        """The full docker run argument list, including the image and the command.

        Assembled in one place so that the tests can read the constraints back off a spec
        rather than trusting that every call site remembered them.
        """
        args = [
            "run",
            "--rm",
            f"--network={self.network.value}",
            f"--workdir={self.workdir}",
            f"--memory={self.memory_mb}m",
            # Without this, a container under memory pressure swaps instead of failing,
            # and a 900-second timeout becomes a 900-second thrash.
            f"--memory-swap={self.memory_mb}m",
            f"--pids-limit={self.pids_limit}",
            f"--cpus={self.cpus}",
            # No new privileges: a setuid binary inside the image cannot escalate.
            "--security-opt=no-new-privileges",
        ]
        for key, value in sorted(self.env.items()):
            args.append(f"--env={key}={value}")
        for source, target, read_only in self.mounts:
            suffix = ":ro" if read_only else ""
            args.append(f"--volume={source.as_posix()}:{target}{suffix}")
        args.append(self.image)
        args.extend(self.command)
        return args


def pytest_spec(
    image: str,
    test_ids: tuple[str, ...],
    *,
    workdir: str = "/testbed",
    timeout_s: int = 900,
) -> RunSpec:
    """A run of specific tests, reporting JUnit XML to a fixed path inside the container.

    JUnit XML rather than parsing pytest's console output, so that the same ingester reads
    a sandbox run and a CI run (mend.capture.pytest_ingest). -p no:cacheprovider because a
    cache directory written into the task workspace turns up in the diff.
    """
    command = (
        "python",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--junitxml=/tmp/mend-report.xml",
        "-rA",
        *test_ids,
    )
    return RunSpec(image=image, command=command, workdir=workdir, timeout_s=timeout_s)
