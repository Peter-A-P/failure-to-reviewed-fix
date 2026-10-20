"""The sandbox refuses network access from task containers.

One of the tests PLAN.md section 4 names. It runs without Docker, and that is the point:
the guarantee is a property of the specification and of the runner's refusal, so it can be
asserted on every commit rather than only on a machine with a working daemon. The one test
that does need Docker is marked and skipped when there is none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mend.sandbox.runner import docker_available, run
from mend.sandbox.spec import Network, RunSpec, SandboxError, pytest_spec

IMAGE = "mend/task:demo"


def test_the_default_is_no_network() -> None:
    spec = RunSpec(image=IMAGE, command=("python", "-c", "print(1)"))
    assert spec.network is Network.NONE
    assert spec.is_isolated
    assert "--network=none" in spec.docker_args()


def test_the_runner_refuses_a_networked_spec() -> None:
    """The refusal, not the default, is what stops this from being lost in a refactor."""
    spec = RunSpec(image=IMAGE, command=("pip", "install", "requests"), network=Network.BRIDGE)
    with pytest.raises(SandboxError, match="no network"):
        run(spec)


def test_network_requires_an_explicit_keyword() -> None:
    """allow_network is keyword-only, so it cannot be reached by argument order."""
    spec = RunSpec(image=IMAGE, command=("true",), network=Network.BRIDGE)
    with pytest.raises(TypeError):
        run(spec, True)  # type: ignore[misc]


def test_limits_are_on_every_run() -> None:
    args = RunSpec(image=IMAGE, command=("pytest",)).docker_args()
    joined = " ".join(args)
    assert "--memory=4096m" in joined
    # Without a matching swap limit, a container under memory pressure swaps rather than
    # failing, and the timeout becomes a long thrash.
    assert "--memory-swap=4096m" in joined
    assert "--pids-limit=512" in joined
    assert "--security-opt=no-new-privileges" in joined
    assert "--rm" in args


def test_a_spec_must_be_runnable() -> None:
    with pytest.raises(ValueError, match="image"):
        RunSpec(image="", command=("true",))
    with pytest.raises(ValueError, match="command"):
        RunSpec(image=IMAGE, command=())
    with pytest.raises(ValueError, match="timeout"):
        RunSpec(image=IMAGE, command=("true",), timeout_s=0)
    with pytest.raises(ValueError, match="256 MB"):
        RunSpec(image=IMAGE, command=("true",), memory_mb=16)


def test_read_only_mounts_are_marked() -> None:
    spec = RunSpec(
        image=IMAGE,
        command=("true",),
        mounts=((Path("/host/patch"), "/patch", True), (Path("/host/work"), "/work", False)),
    )
    joined = " ".join(spec.docker_args())
    assert "/patch:ro" in joined
    assert "/work:ro" not in joined


def test_the_command_comes_after_the_image() -> None:
    """Docker argument order: everything before the image is a flag, everything after is
    the command. Getting this wrong silently turns the command into flags."""
    spec = RunSpec(image=IMAGE, command=("python", "-m", "pytest"))
    args = spec.docker_args()
    image_at = args.index(IMAGE)
    assert args[image_at + 1 :] == ["python", "-m", "pytest"]
    assert all(not a.startswith("--") for a in args[image_at:])


def test_a_pytest_run_asks_for_junit_xml() -> None:
    """So that a sandbox run and a CI run are read by the same ingester."""
    spec = pytest_spec(IMAGE, ("tests/test_bug.py::test_reported",))
    assert "--junitxml=/tmp/mend-report.xml" in spec.command
    assert "no:cacheprovider" in spec.command
    assert spec.is_isolated


def test_the_environment_is_not_inherited() -> None:
    """Only what a spec names reaches the container, so the laptop's keys never do."""
    spec = RunSpec(image=IMAGE, command=("true",), env={"PYTHONHASHSEED": "0"})
    env_args = [a for a in spec.docker_args() if a.startswith("--env=")]
    assert env_args == ["--env=PYTHONHASHSEED=0"]


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="no Docker daemon on this machine")
def test_a_container_really_has_no_network() -> None:
    """The property, checked against a real daemon rather than against the flag list.

    Skipped where there is no Docker, which includes the current build laptop; it runs in
    CI and on any machine with a daemon.
    """
    spec = RunSpec(
        image="python:3.13-alpine",
        command=(
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=5)",
        ),
        workdir="/",
        timeout_s=60,
    )
    result = run(spec)
    assert not result.ok, "a task container reached the network"


def test_container_output_is_read_as_utf8_whatever_the_host_code_page() -> None:
    """A test printing characters the Windows code page cannot decode once left stdout as
    None and crashed the run; the runner now decodes UTF-8 and replaces what it cannot."""
    import inspect

    from mend.sandbox import runner

    source = inspect.getsource(runner.run)
    assert 'encoding="utf-8"' in source and 'errors="replace"' in source
