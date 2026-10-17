"""The workspace: JUnit reports, related tests, and the Docker plumbing without a daemon."""

from __future__ import annotations

from pathlib import Path

from mend.graph.localise import terms
from mend.graph.workspace import module_name, parse_junit, related_tests, source_files
from mend.sandbox.runner import RunResult
from mend.sandbox.runners import PYTEST
from mend.sandbox.spec import RunSpec
from mend.sandbox.workspace import DockerWorkspace, sandbox_script
from tests.fakes import ScriptedWorkspace, report

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
<testcase classname="tests.test_x" name="test_ok" file="tests/test_x.py" line="1"/>
<testcase classname="tests.test_x" name="test_bad" file="tests/test_x.py" line="5">
  <failure message="assert 1 == 2">AssertionError</failure></testcase>
<testcase classname="" name="tests/test_y.py" file="tests/test_y.py">
  <error message="collection failure">ImportError: nope</error></testcase>
<testcase classname="tests.test_x" name="test_skip" file="tests/test_x.py" line="9">
  <skipped message="later"/></testcase>
</testsuite></testsuites>"""


def test_junit_is_read_by_outcome_with_file_based_ids() -> None:
    r = parse_junit(JUNIT)
    assert r.passed == {"tests/test_x.py::test_ok"}
    assert r.failed == {"tests/test_x.py::test_bad"}
    assert r.errored == {"tests/test_y.py::tests/test_y.py"}
    assert r.skipped == {"tests/test_x.py::test_skip"}
    assert r.ran and not r.failed_cleanly  # the collection error spoils it


def test_a_clean_failure_is_a_demonstration_and_an_error_is_not() -> None:
    assert report(failed=["t::a"]).failed_cleanly
    assert not report(failed=["t::a"], errored=["t::b"]).failed_cleanly
    assert not report(passed=["t::a"]).failed_cleanly


def test_an_empty_report_did_not_run() -> None:
    r = parse_junit("", output="Killed", timed_out=True)
    assert not r.ran and r.timed_out and r.output == "Killed"


def test_module_names() -> None:
    assert module_name("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name("src/pkg/__init__.py") == "pkg"


def ws(contents: dict[str, str]) -> ScriptedWorkspace:
    return ScriptedWorkspace(contents, lambda _run: report())


def test_related_tests_by_name_then_by_import() -> None:
    w = ws(
        {
            "pkg/parser.py": "",
            "tests/test_parser.py": "",
            "tests/test_api.py": "from pkg.parser import parse\n",
            "tests/test_other.py": "import json\n",
        }
    )
    assert related_tests(w, ["pkg/parser.py"]) == ("tests/test_parser.py", "tests/test_api.py")


def test_source_files_exclude_tests_and_docs() -> None:
    w = ws({"pkg/a.py": "", "tests/test_a.py": "", "docs/conf.py": "", "README.md": ""})
    assert source_files(w) == ("pkg/a.py",)


def test_terms_pick_identifiers_not_prose() -> None:
    found = terms("Calling `QuerySet.bulk_create` with ignore_conflicts fails in ModelAdmin")
    assert "bulk_create" in found and "ignore_conflicts" in found and "ModelAdmin" in found
    assert "Calling" not in found and "with" not in found


def test_the_script_applies_the_diff_then_runs_pytest_and_never_fails_on_a_red_test() -> None:
    script = sandbox_script(PYTEST.command(["tests/test_a.py"]), has_diff=True, workdir="/testbed")
    lines = script.splitlines()
    assert lines[0] == "set -e"
    assert any(line.startswith("git apply") for line in lines)
    assert "junit_family=xunit1" in script
    assert lines.index("set +e") < next(i for i, line in enumerate(lines) if "pytest" in line)
    assert lines[-1] == "exit 0"


def test_a_docker_run_is_isolated_and_reads_the_report_from_its_mount(tmp_path: Path) -> None:
    """The plumbing, with a runner that plays the container: it checks the spec, finds the
    mounted inputs and writes the JUnit report where pytest would."""
    checkout = tmp_path / "repo"
    (checkout / "pkg").mkdir(parents=True)
    (checkout / "pkg" / "a.py").write_text("x = 1\n")
    (checkout / ".git").mkdir()
    (checkout / ".git" / "config").write_text("[core]\n")
    seen: list[RunSpec] = []

    def runner(spec: RunSpec) -> RunResult:
        seen.append(spec)
        assert spec.is_isolated
        mounts = {target: (source, ro) for source, target, ro in spec.mounts}
        in_dir, in_ro = mounts["/mend/in"]
        out_dir, out_ro = mounts["/mend/out"]
        assert in_ro and not out_ro
        assert (in_dir / "patch.diff").read_text() == "diff --git a/pkg/a.py b/pkg/a.py\n"
        assert (in_dir / "files" / "tests" / "test_new.py").read_text() == "def test(): pass\n"
        (out_dir / "report.xml").write_text(JUNIT)
        return RunResult(1, "out", "", False, 0.1, ())

    w = DockerWorkspace(image="sweb.eval.x86_64.demo", checkout=checkout, execute=runner)
    assert w.files() == ("pkg/a.py",)  # .git is never listed
    r = w.run_tests(
        ["tests/test_new.py"],
        diff="diff --git a/pkg/a.py b/pkg/a.py\n",
        new_files={"tests/test_new.py": "def test(): pass\n"},
    )
    assert r.failed == {"tests/test_x.py::test_bad"}
    assert len(seen) == 1 and seen[0].command[:2] == ("bash", "-c")


def test_unpacking_keeps_regular_files_and_drops_links_and_escapes(tmp_path: Path) -> None:
    """Django's tree holds symlinks Windows cannot create; the host copy is only read, so
    links are skipped, and nothing may land outside the destination."""
    import io
    import tarfile

    from mend.sandbox.workspace import unpack_regular_files

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in (
            ("./pkg/a.py", b"x = 1\n"),
            ("./.gitignore", b"*.pyc\n"),
            ("../evil.py", b"!"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("./docs/link.png")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../elsewhere.png"
        tar.addfile(link)
    buffer.seek(0)
    dest = tmp_path / "copy"
    assert unpack_regular_files(buffer, dest) == 2
    assert (dest / "pkg" / "a.py").read_text() == "x = 1\n"
    assert (dest / ".gitignore").exists()
    assert not (dest / "docs" / "link.png").exists()
    assert not (tmp_path / "evil.py").exists()
