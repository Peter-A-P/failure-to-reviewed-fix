"""The Workspace the hops use, backed by one task image and a host copy of its repository.

Reading happens on the host, from a copy of the image's repository taken once with docker
cp: localisation reads hundreds of files, and a container per read would turn seconds into
minutes. The copy is only ever read as text. Nothing in it is executed on the host, and
git is not run on it either, because a repository's own git configuration can name
commands for git to run.

Running happens in a fresh container from the task image for every call, with no network
(mend.sandbox.spec), the diff and the new files mounted read-only and applied inside, and
pytest writing JUnit XML to a second mount. The container is thrown away afterwards, so
every run starts from the broken commit and no run can leave anything behind for the next.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from mend.graph.workspace import TestReport, parse_junit
from mend.sandbox.runner import RunResult, run
from mend.sandbox.spec import DockerUnavailable, RunSpec, SandboxError

_IN = "/mend/in"
_OUT = "/mend/out"
_SKIP_DIRS = {".git", "__pycache__", ".tox", ".eggs", "node_modules", ".mypy_cache"}

# The SWE-bench images install each repository into a conda environment called testbed.
# Activated when present, so the same command works on a plain Python image in the tests.
_ACTIVATE = (
    "if [ -f /opt/miniconda3/bin/activate ]; then "
    ". /opt/miniconda3/bin/activate && conda activate testbed; fi"
)


def sandbox_script(test_paths: Sequence[str], *, has_diff: bool, workdir: str) -> str:
    """The shell script a run executes inside the container.

    Setup steps fail the run (set -e) because a diff that does not apply is not a test
    result. The test command itself does not: pytest exits non-zero when a test fails,
    which is the expected outcome half the time, and the verdict is read from the XML.
    xunit1 is asked for because it puts the file on every test case, which is how a test
    id names its file (mend.graph.workspace.parse_junit).
    """
    lines = ["set -e", _ACTIVATE, f"cd {shlex.quote(workdir)}"]
    if has_diff:
        lines.append(f"git apply --whitespace=nowarn {_IN}/patch.diff")
    lines.append(f"if [ -d {_IN}/files ]; then cp -r {_IN}/files/. .; fi")
    lines.append("set +e")
    pytest = [
        "python",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={_OUT}/report.xml",
        "-rA",
        *test_paths,
    ]
    lines.append(" ".join(shlex.quote(part) for part in pytest))
    lines.append("exit 0")
    return "\n".join(lines)


@dataclass
class DockerWorkspace:
    image: str
    checkout: Path
    workdir: str = "/testbed"
    timeout_s: int = 900
    runner: Callable[[RunSpec], RunResult] = run
    _files: tuple[str, ...] | None = field(default=None, init=False, repr=False)
    _cache: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def extract(cls, image: str, dest: Path, *, workdir: str = "/testbed") -> DockerWorkspace:
        """Copy the image's repository to dest on the host, once, without starting it."""
        dest.mkdir(parents=True, exist_ok=True)
        try:
            created = subprocess.run(
                ["docker", "create", image], capture_output=True, text=True, check=True
            )
        except FileNotFoundError as exc:
            raise DockerUnavailable("no docker client on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise SandboxError(f"could not create a container from {image}: {exc.stderr}") from exc
        container = created.stdout.strip()
        try:
            subprocess.run(
                ["docker", "cp", f"{container}:{workdir}/.", str(dest)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise SandboxError(f"could not copy {workdir} out of {image}: {exc.stderr}") from exc
        finally:
            subprocess.run(["docker", "rm", container], capture_output=True, check=False)
        return cls(image=image, checkout=dest, workdir=workdir)

    def files(self) -> tuple[str, ...]:
        if self._files is None:
            found = []
            for path in self.checkout.rglob("*"):
                rel = path.relative_to(self.checkout)
                if any(part in _SKIP_DIRS for part in rel.parts) or not path.is_file():
                    continue
                found.append(PurePosixPath(*rel.parts).as_posix())
            self._files = tuple(sorted(found))
        return self._files

    def read(self, path: str) -> str:
        if path not in self._cache:
            if path not in set(self.files()):
                raise KeyError(path)
            self._cache[path] = (self.checkout / path).read_text(encoding="utf-8", errors="replace")
        return self._cache[path]

    def run_tests(
        self,
        test_paths: Sequence[str],
        *,
        diff: str = "",
        new_files: Mapping[str, str] | None = None,
    ) -> TestReport:
        if not test_paths:
            return TestReport()
        with (
            tempfile.TemporaryDirectory(prefix="mend-in-") as tin,
            tempfile.TemporaryDirectory(prefix="mend-out-") as tout,
        ):
            in_dir, out_dir = Path(tin), Path(tout)
            if diff:
                (in_dir / "patch.diff").write_text(diff, encoding="utf-8", newline="\n")
            for rel, text in (new_files or {}).items():
                target = in_dir / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="\n")
            spec = RunSpec(
                image=self.image,
                command=(
                    "sh",
                    "-c",
                    sandbox_script(test_paths, has_diff=bool(diff), workdir=self.workdir),
                ),
                workdir=self.workdir,
                timeout_s=self.timeout_s,
                mounts=((in_dir, _IN, True), (out_dir, _OUT, False)),
            )
            result = self.runner(spec)
            report = out_dir / "report.xml"
            xml = report.read_text(encoding="utf-8") if report.exists() else ""
        return parse_junit(xml, output=result.stdout + result.stderr, timed_out=result.timed_out)
