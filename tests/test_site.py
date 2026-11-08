"""The website: its numbers are the committed results', and the built page carries the menu,
the architecture page and every diagram.

The page types no measured number. `mend site` writes them from the result files, so a
result that changes without the site being rewritten fails here, in CI, rather than leaving
a stale number on the public page.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from mend import site

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def at_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def test_the_committed_numbers_are_the_results() -> None:
    values_text, data_text = site.render(*site.build())
    assert (ROOT / site.VALUES).read_text(encoding="utf-8") == values_text, "run `mend site`"
    assert (ROOT / site.DATA).read_text(encoding="utf-8") == data_text, "run `mend site`"


def test_the_headline_matches_the_readme() -> None:
    values = json.loads((ROOT / site.VALUES).read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{values['hit_pct']} ({values['hit_range']}, n = {values['tasks']})" in readme
    assert f"{values['wrong_pct']} ({values['wrong_range']}, n = {values['auto_count']})" in readme


def test_the_page_asks_for_no_number_it_is_not_given() -> None:
    values = json.loads((ROOT / site.VALUES).read_text(encoding="utf-8"))
    for page in (ROOT / "web").glob("*.html"):
        asked = set(re.findall(r"\{\{(\w+)\}\}", page.read_text(encoding="utf-8")))
        assert asked - {"architecture_sections"} <= set(values), page.name


def test_the_built_site_has_the_menu_the_architecture_page_and_every_diagram(
    tmp_path: Path,
) -> None:
    out = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "tools/site.py",
            "build",
            "--web",
            "web",
            "--values",
            str(site.VALUES),
            "--docs",
            "docs",
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    index = (out / "index.html").read_text(encoding="utf-8")
    architecture = (out / "architecture.html").read_text(encoding="utf-8")
    assert 'class="tabs"' in index and 'href="architecture.html"' in index
    for diagram in (ROOT / "docs" / "architecture").glob("*.svg"):
        assert f"architecture/{diagram.name}" in architecture
        assert (out / "architecture" / diagram.name).is_file()
    assert "{{" not in index and "{{" not in architecture


def test_the_script_only_looks_for_elements_the_page_has() -> None:
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([\w-]+)"', page))
    for wanted in re.findall(r'(?:byId|clear\(byId)\("([\w-]+)"\)', script):
        assert wanted in ids, wanted
    for wanted in re.findall(r'(?:bars|pairedBars|legend)\("([\w-]+)"', script):
        assert wanted in ids, wanted
