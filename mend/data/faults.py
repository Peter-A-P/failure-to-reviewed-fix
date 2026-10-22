"""The injected-fault clustering set: one fault, many failing tests, labels by construction.

PLAN.md section 2.2. Two open-source libraries with fast, thorough test suites are checked
out at a pinned tag. One small mutation at a time is made to the library's source: a
comparison flipped, a condition negated, a constant changed, a return value dropped, the
operators of classic mutation testing. The suite is then run, and every test that failed
with the mutation and passed without it is a symptom whose cause is known exactly, because
it was put there.

This is the set that tests traceback-level clustering, the case PLAN.md section 2.2 was
designed for and 09's chaos runs did not exercise (docs/rejected.md, "What this does not
show"). A fault in a helper used everywhere fails tests in many files, through many call
paths, with many exception types: the diversity that splits one bug into several tickets.

Rules that keep the labels honest:

- Sites are chosen by a seeded shuffle of every candidate site, not by hand, and the order
  is deterministic in the checkout and the seed.
- A fault is kept when between MIN_FAILING and MAX_FAILING tests fail that passed on the
  clean checkout, and nothing errored at collection. One failing test is not a cluster;
  a fault that breaks import fails everything identically and tests nothing.
- At most PER_FAULT symptoms per fault are kept, drawn with the seed, so a fault that
  breaks three hundred tests cannot outweigh twenty others in a pairwise metric.
- Nothing about a symptom says which run it came from. Every record gets the same capture
  time and a record id that does not contain the fault, because each fault ran in its own
  process and an ingestion timestamp or a run name would be the label leaking in.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mend.capture.pytest_ingest import ingest_junit_xml
from mend.capture.schema import FailureRecord, Source

MIN_FAILING = 2
MAX_FAILING = 400
PER_FAULT = 25
CAPTURED_AT = datetime(2026, 10, 21, tzinfo=UTC)
TIMEOUT_S = 300


@dataclass(frozen=True, slots=True)
class Suite:
    """A library and how to run its tests. Pinned by tag; the clone is verified by commit."""

    name: str
    url: str
    tag: str
    commit: str
    package: str
    tests: str = "tests"
    requirements: tuple[str, ...] = ()


SUITES = {
    "click": Suite(
        name="click",
        url="https://github.com/pallets/click.git",
        tag="8.1.7",
        commit="874ca2bc1c30d93a4ac6e36a15ed685eafe89097",
        package="src/click",
        requirements=("pytest==8.2.2", "pytest-xdist==3.6.1"),
    ),
    "marshmallow": Suite(
        name="marshmallow",
        url="https://github.com/marshmallow-code/marshmallow.git",
        tag="3.21.3",
        commit="b9646e326c511c11fc07aef4aa0004c14a5d454c",
        package="src/marshmallow",
        requirements=("pytest==8.2.2", "pytest-xdist==3.6.1", "pytz", "simplejson"),
    ),
}


@dataclass(frozen=True, slots=True)
class Mutation:
    """One change at one site. before and after are the exact source text replaced."""

    file: str
    line: int
    col: int
    end_line: int
    end_col: int
    operator: str
    before: str
    after: str

    @property
    def fault_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.file}:{self.line}:{self.col}:{self.operator}".encode()
        ).hexdigest()
        return digest[:8]


_COMPARE_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}
_BINOP_SWAP: dict[type[ast.operator], type[ast.operator]] = {ast.Add: ast.Sub, ast.Sub: ast.Add}
_BOOL_SWAP: dict[type[ast.boolop], type[ast.boolop]] = {ast.And: ast.Or, ast.Or: ast.And}


def _mutants(node: ast.AST) -> Iterator[tuple[str, ast.expr, str]]:
    """(operator name, node replaced, replacement source) for each mutation of a node."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        swap = _COMPARE_SWAP.get(type(node.ops[0]))
        if swap is not None:
            mutated = ast.Compare(node.left, [swap()], node.comparators)
            yield "compare", node, ast.unparse(mutated)
    elif isinstance(node, ast.BinOp):
        swap_op = _BINOP_SWAP.get(type(node.op))
        if swap_op is not None:
            yield "arithmetic", node, ast.unparse(ast.BinOp(node.left, swap_op(), node.right))
    elif isinstance(node, ast.BoolOp):
        swap_bool = _BOOL_SWAP.get(type(node.op))
        if swap_bool is not None:
            yield "boolean", node, ast.unparse(ast.BoolOp(swap_bool(), node.values))
    elif isinstance(node, ast.If | ast.While):
        yield "negate", node.test, f"not ({ast.unparse(node.test)})"
    elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
        yield "constant", node, repr(not node.value)
    elif isinstance(node, ast.Constant) and type(node.value) is int and node.value in (0, 1):
        yield "constant", node, repr(1 - node.value)
    elif isinstance(node, ast.Return) and node.value is not None:
        if not (isinstance(node.value, ast.Constant) and node.value.value is None):
            yield "return-none", node.value, "None"


def _offset(lines: Sequence[str], line: int, col: int) -> int:
    """A character offset into the joined text from ast's (1-based line, UTF-8 byte col)."""
    before = sum(len(x) for x in lines[: line - 1])
    return before + len(lines[line - 1].encode("utf-8")[:col].decode("utf-8"))


def candidates(checkout: Path, package: str) -> list[Mutation]:
    """Every mutation site in the package's source, in a fixed order."""
    out: list[Mutation] = []
    for path in sorted((checkout / package).rglob("*.py")):
        rel = path.relative_to(checkout).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        for node in ast.walk(ast.parse(source)):
            for operator, target, after in _mutants(node):
                if target.end_lineno is None or target.end_col_offset is None:
                    continue
                start = _offset(lines, target.lineno, target.col_offset)
                end = _offset(lines, target.end_lineno, target.end_col_offset)
                out.append(
                    Mutation(
                        file=rel,
                        line=target.lineno,
                        col=target.col_offset,
                        end_line=target.end_lineno,
                        end_col=target.end_col_offset,
                        operator=operator,
                        before=source[start:end],
                        after=after,
                    )
                )
    out.sort(key=lambda m: (m.file, m.line, m.col, m.operator, m.after))
    return out


def apply(source: str, mutation: Mutation) -> str:
    """The source with one mutation made. Refuses if the site no longer holds `before`."""
    lines = source.splitlines(keepends=True)
    start = _offset(lines, mutation.line, mutation.col)
    end = _offset(lines, mutation.end_line, mutation.end_col)
    if source[start:end] != mutation.before:
        raise ValueError(f"{mutation.file}:{mutation.line} does not hold the text to mutate")
    mutated = source[:start] + mutation.after + source[end:]
    ast.parse(mutated)
    return mutated


@dataclass(frozen=True, slots=True)
class SuiteRun:
    """What one run of the suite produced: the JUnit report, or why there is none."""

    xml: str | None
    timed_out: bool = False


Runner = Callable[[Path, Path], SuiteRun]


def pytest_runner(python: Path, *, workers: int = 4, timeout_s: int = TIMEOUT_S) -> Runner:
    """Run the suite with the given interpreter, native tracebacks, JUnit XML, spread over
    a few worker processes (a sequential run of one suite is two minutes on the laptop)."""

    def run(checkout: Path, report: Path) -> SuiteRun:
        report.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--tb=native",
                    "-n",
                    str(workers),
                    f"--junitxml={report}",
                    "tests",
                ],
                cwd=checkout,
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SuiteRun(None, timed_out=True)
        if not report.is_file():
            return SuiteRun(None)
        return SuiteRun(report.read_text(encoding="utf-8"))

    return run


def scrub(text: str, checkout: Path, home: Path | None = None) -> str:
    """A report with this machine taken out of it.

    The checkout's absolute path goes, so a frame says src/click/core.py; then the home
    folder becomes ~, so the interpreter's and the virtual environment's frames name no
    user. Both slash directions, because a Windows traceback uses one and pytest the other.
    """
    home = home or Path.home()
    out = text
    root = str(checkout.resolve())
    for form in {root, root.replace("\\", "/")}:
        # With its separator only: the environment beside the checkout shares its prefix.
        out = out.replace(form + ("/" if "/" in form else "\\"), "")
    for form in {str(home), str(home).replace("\\", "/")}:
        out = out.replace(form, "~")
    return out


def _records(xml: str, checkout: Path, suite: Suite, report: Path) -> list[FailureRecord]:
    """The failures in a report, scrubbed, with frames in the project being the library's
    source and its tests and nothing installed beside them."""
    report.write_text(scrub(xml, checkout), encoding="utf-8")
    return ingest_junit_xml(
        report, repo=suite.name, project_markers=(f"{suite.package}/", f"{suite.tests}/")
    )


@dataclass(frozen=True, slots=True)
class Fault:
    """A kept mutation, with how many tests it failed and how many symptoms were kept."""

    suite: str
    mutation: Mutation
    failing: int
    kept: int

    @property
    def cause(self) -> str:
        return f"{self.suite}:{self.mutation.fault_id}"


def prepare(suite: Suite, root: Path) -> tuple[Path, Path]:
    """Clone the suite at its tag into root, check the commit, and make its environment.
    Returns (checkout, python). Idempotent: an existing checkout at the right commit and
    an existing environment are reused."""
    checkout = root / suite.name
    if not checkout.is_dir():
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--branch", suite.tag, suite.url, str(checkout)],
            check=True,
            capture_output=True,
            timeout=600,
        )
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()
    if head != suite.commit:
        raise RuntimeError(f"{suite.name} at {suite.tag} is {head}, not the pinned {suite.commit}")
    venv = root / f"{suite.name}-venv"
    python = venv / (
        "Scripts/python.exe" if (venv / "Scripts").exists() or _windows() else "bin/python"
    )
    if not python.is_file():
        subprocess.run(["uv", "venv", "-q", "--python", "3.13", str(venv)], check=True, timeout=600)
        python = venv / ("Scripts/python.exe" if _windows() else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "-q",
            "--python",
            str(python),
            "-e",
            str(checkout),
            *suite.requirements,
        ],
        check=True,
        timeout=1200,
    )
    return checkout, python


def _windows() -> bool:
    import os

    return os.name == "nt"


def build(
    suite: Suite,
    checkout: Path,
    runner: Runner,
    *,
    faults: int,
    seed: int,
    work: Path,
    echo: Callable[[str], None] = print,
    max_tries: int = 400,
) -> tuple[list[Fault], list[FailureRecord]]:
    """Mutate, run, keep, until `faults` faults are kept or `max_tries` sites were tried."""
    work.mkdir(parents=True, exist_ok=True)
    clean = runner(checkout, work / "clean.xml")
    if clean.xml is None:
        raise RuntimeError(f"{suite.name}: the clean suite produced no report")
    baseline = {r.test_id for r in _records(clean.xml, checkout, suite, work / "clean.xml")}

    sites = candidates(checkout, suite.package)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(sites))
    kept: list[Fault] = []
    records: list[FailureRecord] = []
    for tries, index in enumerate(order, start=1):
        if len(kept) >= faults or tries > max_tries:
            break
        mutation = sites[int(index)]
        path = checkout / mutation.file
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(apply(original, mutation), encoding="utf-8", newline="")
            result = runner(checkout, work / "mutant.xml")
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if result.xml is None:
            echo(f"  {mutation.file}:{mutation.line} {mutation.operator}: no report, skipped")
            continue
        found = [
            r
            for r in _records(result.xml, checkout, suite, work / "mutant.xml")
            if r.test_id not in baseline
        ]
        errored = any(r.exception_type == "CollectionError" for r in found)
        if errored or not MIN_FAILING <= len(found) <= MAX_FAILING:
            continue
        fault = Fault(suite.name, mutation, failing=len(found), kept=min(len(found), PER_FAULT))
        pick = sorted(found, key=lambda r: r.record_id)
        if len(pick) > PER_FAULT:
            chosen = rng.choice(len(pick), size=PER_FAULT, replace=False)
            pick = [pick[int(i)] for i in sorted(chosen)]
        for record in pick:
            neutral = hashlib.sha256(f"{fault.cause}|{record.record_id}".encode()).hexdigest()
            records.append(
                record.model_copy(
                    update={
                        "record_id": f"{suite.name}:{neutral[:12]}",
                        "captured_at": CAPTURED_AT,
                        "source": Source.INJECTED,
                        "true_cause": fault.cause,
                    }
                )
            )
        kept.append(fault)
        echo(
            f"  kept {fault.cause}: {mutation.file}:{mutation.line} {mutation.operator}, "
            f"{len(found)} tests failed"
        )
    return kept, records


def write_manifest(
    path: Path, suites: dict[str, Suite], faults: Sequence[Fault], seed: int
) -> None:
    payload = {
        "seed": seed,
        "rules": {
            "min_failing": MIN_FAILING,
            "max_failing": MAX_FAILING,
            "symptoms_per_fault": PER_FAULT,
        },
        "suites": {name: asdict(s) for name, s in suites.items()},
        "faults": [
            {"cause": f.cause, "failing": f.failing, "kept": f.kept, **asdict(f.mutation)}
            for f in faults
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
