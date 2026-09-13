"""Normalising failure text so that two reports of one bug look alike.

Every channel in the clustering stage reads normalised text. The substitutions below are
the ones that change between two runs of the same failure and carry no information about
which bug it is: addresses, temporary paths, identifiers, timestamps, and the numbers
inside an assertion message. They are applied in a fixed order, most specific first,
because a memory address is also a hexadecimal number and a uuid is also a hex string.

What is deliberately *not* normalised: quoted strings from the code under test, exception
type names, and function names. Those are the signal. An over-eager normaliser collapses
"KeyError: 'user_id'" and "KeyError: 'account_id'" into one bug, and the completeness
metric will not notice because it only punishes splitting.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# (pattern, replacement), applied in order. Order matters: see the module docstring.
_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Object repr addresses: <foo.Bar object at 0x7f3c8a1b2d50>
    (re.compile(r"0x[0-9a-fA-F]{6,16}"), "<ADDR>"),
    # UUIDs, including the trace and span ids that appear in log lines.
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<UUID>",
    ),
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "<HEX>"),
    # ISO-8601 timestamps, with or without a zone.
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        "<TIME>",
    ),
    # Temporary directories, which differ on every run of the same test.
    (
        re.compile(r"(?:/tmp|/var/folders|C:\\Users\\[^\\]+\\AppData\\Local\\Temp)[^\s'\"]*"),
        "<TMP>",
    ),
    # pytest's own per-run temporary path.
    (re.compile(r"\bpytest-of-[^\s'\"]*"), "<TMP>"),
    # Windows and POSIX absolute paths become their last two segments, which is the part
    # that identifies the module rather than the machine.
    (re.compile(r"(?:[A-Za-z]:)?[\/](?:[\w.\-]+[\/])+([\w.\-]+[\/][\w.\-]+\.py)"), r"\1"),
    # Bare numbers, last, once the structured forms above have had their turn.
    (re.compile(r"(?<![\w<])\d+(?:\.\d+)?(?![\w>])"), "<N>"),
)

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalise_text(text: str | None) -> str:
    """Apply every substitution and tidy the whitespace. None becomes the empty string."""
    if not text:
        return ""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    for pattern, replacement in _SUBSTITUTIONS:
        out = pattern.sub(replacement, out)
    out = _WHITESPACE.sub(" ", out)
    out = _BLANK_LINES.sub("\n\n", out)
    return "\n".join(line.rstrip() for line in out.split("\n")).strip()


def normalise_message(message: str | None) -> str:
    """The one-line form used in a fingerprint.

    Beyond the shared substitutions this truncates, because a fingerprint built from a
    500-character assertion diff is a fingerprint that matches nothing but itself.
    """
    flat = " ".join(normalise_text(message).split())
    return flat[:200]


# The standard library, whose path carries a Python version that differs between the
# sandbox and the laptop. Stripped for the same reason as the markers below: a frame that
# compares unequal because of the interpreter version is noise.
_STDLIB_PREFIX = re.compile(r"^.*/lib/python\d+(?:\.\d+)*/")


def normalise_path(path: str) -> str:
    """A repository-relative, forward-slashed path.

    Strips the common prefixes an environment adds (/testbed is the SWE-bench harness's
    checkout root, site-packages is an installed copy of the same code, lib/pythonX.Y is
    the standard library) so that the same file captured in two environments compares
    equal.

    A path matching none of them is returned as it came, minus any leading ./. Truncating
    an unrecognised path to its last segments would be the more aggressive choice and the
    wrong one: it would collapse pkg/a/mod.py and pkg/b/mod.py, which are two files.
    """
    p = path.replace("\\", "/")
    for marker in ("/testbed/", "/site-packages/", "/dist-packages/", "/src/"):
        idx = p.find(marker)
        if idx != -1:
            return p[idx + len(marker) :].lstrip("./")
    return _STDLIB_PREFIX.sub("", p).lstrip("./")


def shared_prefix_ratio(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard overlap of two sets of locations, used by the locality channel.

    Jaccard rather than a prefix match because two symptoms of one bug often enter the
    faulty function from different call sites: they share the deep frames and disagree
    about the shallow ones.
    """
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0
