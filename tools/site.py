"""Build and check a portfolio project site. Standard library only, Python 3.11+.

    python site.py build --web web --values data/site/values.json --docs docs --out dist
    python site.py check dist

build   Fills every {{token}} in web/*.html from a JSON object of strings, refusing a token
        nothing supplies and naming any value no page uses. architecture.html also gets
        {{architecture_sections}}, rendered from docs/architecture.md (one "## " section per
        diagram, the image first, "Where it lives:" set small), and the SVGs are copied to
        dist/architecture/. Every other file in web/ is copied as it is.

check   Reads a built site and fails on what has shipped wrong before: an unfilled token,
        inline script or style (the CSP refuses them, so they break only in production), an
        off-site script, stylesheet, font or image, typographic dashes or curly quotes, an
        image without alt text, a link to an anchor that is not there, missing link-preview
        tags or card, a "How this was built" section that is not in the first person, and
        stock AI phrasing. Warnings do not fail; errors do.

The values file is written by the project's report command, from the same run that writes the
README's tables. Never type a measured number into it by hand.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path

TOKEN = re.compile(r"\{\{(\w+)\}\}")


# ------------------------------------------------------------------------------- build


def fill(template: str, values: dict[str, str], name: str) -> tuple[str, set[str]]:
    used = set(TOKEN.findall(template))
    missing = used - set(values)
    if missing:
        raise SystemExit(f"{name} asks for {sorted(missing)}, which nothing supplies")
    return TOKEN.sub(lambda m: values[m.group(1)], template), used


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def architecture_sections(docs: Path) -> str:
    document = (docs / "architecture.md").read_text(encoding="utf-8")
    out: list[str] = []
    for section in re.split(r"^## ", document, flags=re.M)[1:]:
        title, _, body = section.partition("\n")
        blocks = [b.strip() for b in body.strip().split("\n\n") if b.strip()]
        image = re.fullmatch(r"!\[(.*)\]\(architecture/([^)]+\.svg)\)", blocks[0], re.S) if blocks else None
        if image is None:
            raise SystemExit(f"docs/architecture.md: {title.strip()!r} does not open with a diagram")
        alt, name = image.groups()
        svg = (docs / "architecture" / name).read_text(encoding="utf-8")
        size = re.search(r'width="(\d+(?:\.\d+)?)" height="(\d+(?:\.\d+)?)"', svg)
        dims = f' width="{size.group(1)}" height="{size.group(2)}"' if size else ""
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        paragraphs = []
        for block in blocks[1:]:
            text = " ".join(line.strip() for line in block.splitlines())
            where = ' class="where"' if text.startswith("Where it lives:") else ""
            paragraphs.append(f"      <p{where}>{inline(text)}</p>")
        out.append(
            f'  <section class="section" id="{slug}">\n'
            f"    <h2>{inline(title.strip())}</h2>\n"
            f'    <figure class="arch-figure"><a href="architecture/{name}">'
            f'<img src="architecture/{name}"{dims} alt="{html.escape(" ".join(alt.split()))}"></a></figure>\n'
            '    <div class="prose">\n' + "\n".join(paragraphs) + "\n    </div>\n  </section>\n"
        )
    return "\n".join(out)


def build(web: Path, values_path: Path, docs: Path, out: Path) -> None:
    values = json.loads(values_path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or not all(isinstance(v, str) for v in values.values()):
        raise SystemExit(f"{values_path} must be one JSON object of strings")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=shutil.ignore_patterns("*.html"))
    used_anywhere: set[str] = set()
    for page in sorted(web.glob("*.html")):
        page_values = dict(values)
        if "{{architecture_sections}}" in page.read_text(encoding="utf-8"):
            page_values["architecture_sections"] = architecture_sections(docs)
            (out / "architecture").mkdir(exist_ok=True)
            for svg in (docs / "architecture").glob("*.svg"):
                shutil.copy2(svg, out / "architecture" / svg.name)
        text, used = fill(page.read_text(encoding="utf-8"), page_values, page.name)
        used_anywhere |= used
        (out / page.name).write_text(text, encoding="utf-8", newline="\n")
    unused = set(values) - used_anywhere
    if unused:
        raise SystemExit(f"{sorted(unused)} are supplied and no page uses them")
    print(f"built {out} from {web}")


# ------------------------------------------------------------------------------- check

# Stock phrasing that reads as machine-written. A hit is a warning: read the sentence, and run
# the humanizer over the page if there are several.
TELLS = [
    r"\bdelve", r"\bseamless", r"\bleverag", r"\brobust\b", r"\bcutting-edge", r"\bgame.?chang",
    r"\btestament\b", r"\bpivotal\b", r"\bcrucial\b", r"\blandscape\b", r"\bunlock", r"\bempower",
    r"\belevat", r"\bharness", r"\bstreamlin", r"\bnot just\b", r"\bisn't just\b", r"\bmore than just\b",
    r"\bin today's\b", r"\bever-evolving\b", r"\bit's worth noting\b", r"\bimportantly\b",
    r"\bat its core\b", r"\bthe real \w+ is\b", r"\bhere's the thing\b", r"\bboasts?\b",
    r"\bstate-of-the-art\b", r"\bworld-class\b", r"\bpowerful\b", r"\binnovative\b",
    r"\bjourney\b", r"\brealm\b", r"\btapestry\b", r"\bnavigat(e|ing) the\b", r"\bdeep dive\b",
]
TYPOGRAPHIC = {"—": "em dash", "–": "en dash", "‘": "curly quote", "’": "curly quote",
               "“": "curly quote", "”": "curly quote", "…": "ellipsis character"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.anchors: list[str] = []
        self.problems: list[str] = []
        self.meta: dict[str, str] = {}
        self.text: list[str] = []
        self.title = ""
        self.lang = ""
        self._in: list[str] = []
        self.built: list[str] = []
        self._in_built = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        self._in.append(tag)
        if tag == "html":
            self.lang = a.get("lang", "")
        if "id" in a:
            self.ids.add(a["id"])
            if a["id"] == "built":
                self._in_built = len(self._in)
        if "style" in a:
            self.problems.append(f"inline style on <{tag}> (the CSP refuses it)")
        for k in a:
            if k.startswith("on"):
                self.problems.append(f"inline handler {k} on <{tag}> (the CSP refuses it)")
        if tag == "style":
            self.problems.append("<style> block (the CSP refuses it; use style.css)")
        if tag == "script" and not a.get("src"):
            self.problems.append("inline <script> (the CSP refuses it; use app.js)")
        for attr in ("src", "href"):
            url = a.get(attr, "")
            if tag in ("script", "img", "link", "source", "video", "audio", "iframe") and re.match(r"(https?:)?//", url):
                if not (tag == "link" and a.get("rel") == "canonical"):
                    self.problems.append(f"off-site {tag} {attr}={url} (the page makes no outside request)")
        if tag == "img" and "alt" not in a:
            self.problems.append(f"<img src={a.get('src')}> has no alt text")
        if tag == "a" and a.get("href", "").startswith("#") and len(a["href"]) > 1:
            self.anchors.append(a["href"][1:])
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if self._in_built and len(self._in) == self._in_built and tag == "section":
            self._in_built = 0
        while self._in and self._in.pop() != tag:
            pass

    def handle_data(self, data: str) -> None:
        current = self._in[-1] if self._in else ""
        if current in ("script", "style", "code", "pre"):
            return
        if current == "title":
            self.title += data
        self.text.append(data)
        if self._in_built and current == "p":
            self.built.append(data)


def png_size(path: Path) -> tuple[int, int] | None:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def check(site: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    pages = sorted(site.glob("*.html"))
    if not pages:
        raise SystemExit(f"no pages in {site}")
    for page in pages:
        raw = page.read_text(encoding="utf-8")
        name = page.name
        for token in sorted(set(TOKEN.findall(raw))):
            errors.append(f"{name}: unfilled {{{{{token}}}}}")
        p = Page()
        p.feed(raw)
        errors += [f"{name}: {x}" for x in p.problems]
        if not p.lang:
            errors.append(f"{name}: <html> has no lang")
        if 'name="viewport"' not in raw:
            errors.append(f"{name}: no viewport meta")
        if "description" not in p.meta:
            errors.append(f"{name}: no meta description")
        for anchor in p.anchors:
            if anchor not in p.ids:
                errors.append(f"{name}: link to #{anchor}, which is not on the page")
        text = " ".join(p.text)
        for ch, label in TYPOGRAPHIC.items():
            n = text.count(ch)
            if n:
                errors.append(f"{name}: {n} x {label}; plain punctuation only")
        if re.search(r"\s-\s", text):
            warnings.append(f"{name}: ' - ' used as a dash; rewrite the sentence or use a colon, comma or full stop")
        lowered = text.lower()
        for pattern in TELLS:
            hits = re.findall(pattern, lowered)
            if hits:
                warnings.append(f"{name}: stock phrasing /{pattern}/ x{len(hits)}")
        if name == "index.html":
            if ":" not in p.title:
                warnings.append("index.html: <title> is not 'Project name: what it does for the reader'")
            for key in ("og:title", "og:description", "og:image", "og:image:alt", "twitter:card"):
                if key not in p.meta:
                    errors.append(f"index.html: no {key} meta")
            og = site / "og.png"
            if not og.exists():
                errors.append("og.png is missing (1200 x 630 link-preview card)")
            elif png_size(og) != (1200, 630):
                errors.append(f"og.png is {png_size(og)}, not 1200 x 630")
            if "architecture.html" not in raw:
                errors.append("index.html does not link to architecture.html")
            if "built" not in p.ids:
                errors.append("index.html has no section#built (How this was built)")
            elif p.built:
                first = " ".join(p.built).strip()
                if not re.match(r"I\b", first):
                    errors.append("How this was built: the first paragraph must open in the first person ('I ...')")
                if "Peter Parker's" in first or "Peter's" in first:
                    errors.append("How this was built: written about Peter in the third person; write it as 'I'")
            description = p.meta.get("description", "")
            if not 50 <= len(description) <= 300:
                warnings.append(f"index.html: meta description is {len(description)} characters; aim for 50 to 300")
    for name in ("style.css", "app.js", "favicon.svg", "staticwebapp.config.json", "fonts/LICENSE.txt"):
        if not (site / name).exists():
            warnings.append(f"{name} is missing")
    css = site / "style.css"
    if css.exists():
        sheet = css.read_text(encoding="utf-8")
        if "prefers-color-scheme: dark" not in sheet:
            errors.append("style.css has no dark mode")
        if re.search(r"@import|fonts\.googleapis|https?://", sheet):
            errors.append("style.css loads something off-site")
    js = site / "app.js"
    if js.exists():
        script = js.read_text(encoding="utf-8")
        if re.search(r"\.innerHTML\s*=|insertAdjacentHTML|document\.write", script):
            warnings.append("app.js writes HTML; data must reach the page through textContent")
        if re.search(r"#[0-9a-fA-F]{6}\b", script):
            warnings.append("app.js has a hex colour; colours live in style.css")
    total = sum(f.stat().st_size for f in site.rglob("*") if f.is_file() and f.suffix != ".mp4")
    if total > 3_000_000:
        warnings.append(f"site is {total / 1e6:.1f} MB without video; check images and data")
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")
    print(f"{len(pages)} pages, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--web", type=Path, default=Path("web"))
    b.add_argument("--values", type=Path, required=True)
    b.add_argument("--docs", type=Path, default=Path("docs"))
    b.add_argument("--out", type=Path, default=Path("dist"))
    c = sub.add_parser("check")
    c.add_argument("site", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args.web, args.values, args.docs, args.out)
    else:
        sys.exit(check(args.site))


if __name__ == "__main__":
    main()
