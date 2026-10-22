"""The duplicate-link clustering set: issues maintainers closed as duplicates of another.

PLAN.md section 2.2. The truth is the maintainers' own judgement: an issue labelled a
duplicate in its tracker, linked to the issue it duplicates. Every duplicate and the issue
it points to form one group, and the clustering is asked to recover the groups from the
issues' text and tracebacks alone.

Three large Python repositories, each with a duplicate label:

- pandas-dev/pandas, "Duplicate Report";
- matplotlib/matplotlib, "status: duplicate";
- numpy/numpy, "50 - Duplicate".

The link to the original is read in this order, and the rule that found it is recorded:

1. GitHub's own "marked as duplicate" event, which names the original.
2. The latest comment by a maintainer (owner, member or collaborator) that says
   "duplicate" or "dup" and refers to exactly one issue, as #123, gh-123 or a link.
3. The latest comment by anyone that does the same.

A labelled issue with no link by these rules is left out, and how many were is reported.
Chains are followed to their root (a duplicate of a duplicate joins the original's group),
and a link to a pull request rather than an issue is dropped.

Issue text is cached locally and never committed or redistributed (PLAN.md section 3). The
committed file is the links: repository, issue, original, and the rule that found it.

Frames in a user's traceback come from an installed copy of the library, under
site-packages, which the general parser rightly treats as outside any project. For this
set the project is the library itself, so a frame counts as in the project when its path,
normalised, starts with the library's package directory.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mend.capture.github_ingest import record_from_issue
from mend.capture.schema import FailureRecord

MAINTAINERS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


@dataclass(frozen=True, slots=True)
class Tracker:
    repo: str
    label: str
    package: str
    since: int


TRACKERS = (
    Tracker("pandas-dev/pandas", "Duplicate Report", "pandas", 2011),
    Tracker("matplotlib/matplotlib", "status: duplicate", "matplotlib", 2011),
    Tracker("numpy/numpy", "50 - Duplicate", "numpy", 2011),
)

_MENTIONS_DUPLICATE = re.compile(r"\bdup(?:licate)?s?\b|\bduplicated\b", re.IGNORECASE)


def references(text: str, repo: str) -> set[int]:
    """Issue numbers a comment refers to in this repository."""
    owner_repo = re.escape(repo)
    found = {int(n) for n in re.findall(r"(?<![\w/])#(\d+)\b", text)}
    found |= {int(n) for n in re.findall(r"\bgh-(\d+)\b", text, flags=re.IGNORECASE)}
    found |= {
        int(n)
        for n in re.findall(rf"github\.com/{owner_repo}/(?:issues|pull)/(\d+)", text, re.IGNORECASE)
    }
    return found


@dataclass(frozen=True, slots=True)
class Link:
    repo: str
    issue: int
    original: int
    rule: str


def link_for(issue: Mapping[str, Any], repo: str) -> Link | None:
    """The original this labelled issue duplicates, by the rules in the module docstring."""
    number = int(issue["number"])
    for event in reversed(issue.get("timelineItems", {}).get("nodes", [])):
        canonical = (event or {}).get("canonical") or {}
        if canonical.get("__typename") == "Issue" and canonical.get("number") != number:
            return Link(repo, number, int(canonical["number"]), "event")
    comments = [c for c in issue.get("comments", {}).get("nodes", []) if c]
    maintainers = [c for c in comments if c.get("authorAssociation") in MAINTAINERS]
    for rule, pool in (("maintainer-comment", maintainers), ("comment", comments)):
        for comment in reversed(pool):
            body = str(comment.get("body") or "")
            if not _MENTIONS_DUPLICATE.search(body):
                continue
            refs = references(body, repo) - {number}
            if len(refs) == 1:
                return Link(repo, number, refs.pop(), rule)
    return None


_ISSUE_FIELDS = "number title body createdAt"

SEARCH = (
    "query($q: String!, $after: String) { rateLimit { remaining } "
    "search(query: $q, type: ISSUE, first: 50, after: $after) { issueCount "
    "pageInfo { hasNextPage endCursor } nodes { ... on Issue { " + _ISSUE_FIELDS + " "
    "timelineItems(itemTypes: [MARKED_AS_DUPLICATE_EVENT], last: 5) { nodes { "
    "... on MarkedAsDuplicateEvent { canonical { __typename "
    "... on Issue { number } ... on PullRequest { number } } } } } "
    "comments(last: 30) { nodes { authorAssociation body } } } } } }"
)

GraphQL = Callable[[str, Mapping[str, Any]], dict[str, Any]]


def gh_graphql(query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
    """One GraphQL call through the GitHub CLI, so no token passes through this code."""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    done = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", check=True, timeout=120
    )
    payload: dict[str, Any] = json.loads(done.stdout)
    return payload


def labelled_issues(tracker: Tracker, graphql: GraphQL = gh_graphql) -> Iterator[dict[str, Any]]:
    """Every closed issue with the duplicate label, year by year (search stops at 1000)."""
    for year in range(tracker.since, date.today().year + 1):
        q = (
            f'repo:{tracker.repo} is:issue is:closed label:"{tracker.label}" '
            f"created:{year}-01-01..{year}-12-31"
        )
        after: str | None = None
        while True:
            data = graphql(SEARCH, {"q": q, "after": after})["data"]["search"]
            yield from (n for n in data["nodes"] if n)
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]


def fetch_issues(
    repo: str, numbers: Sequence[int], graphql: GraphQL = gh_graphql
) -> dict[int, dict[str, Any] | None]:
    """Issues by number, fifty to a call; a pull request or a missing number is None."""
    owner, name = repo.split("/")
    out: dict[int, dict[str, Any] | None] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        fields = " ".join(
            f"i{n}: issueOrPullRequest(number: {n}) {{ __typename ... on Issue {{ {_ISSUE_FIELDS} }} }}"
            for n in chunk
        )
        query = f'query {{ repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'
        try:
            repo_data = graphql(query, {})["data"]["repository"]
        except subprocess.CalledProcessError:
            # One unreadable number fails the whole call; fall back to one at a time.
            for n in chunk:
                single = f'query {{ repository(owner: "{owner}", name: "{name}") {{ i{n}: issueOrPullRequest(number: {n}) {{ __typename ... on Issue {{ {_ISSUE_FIELDS} }} }} }} }}'
                try:
                    node = graphql(single, {})["data"]["repository"][f"i{n}"]
                except subprocess.CalledProcessError:
                    node = None
                out[n] = node if node and node.get("__typename") == "Issue" else None
            continue
        for n in chunk:
            node = repo_data.get(f"i{n}")
            out[n] = node if node and node.get("__typename") == "Issue" else None
    return out


def root_of(issue: int, links: Mapping[int, int]) -> int:
    """Follow duplicate-of links to the end; a cycle stops at its smallest member."""
    seen = [issue]
    while seen[-1] in links:
        nxt = links[seen[-1]]
        if nxt in seen:
            return min(seen[seen.index(nxt) :])
        seen.append(nxt)
    return seen[-1]


@dataclass(frozen=True, slots=True)
class Mined:
    tracker: Tracker
    labelled: int
    links: tuple[Link, ...]
    groups: dict[int, tuple[int, ...]]
    issues: dict[int, dict[str, Any]]


def mine(tracker: Tracker, graphql: GraphQL = gh_graphql) -> Mined:
    labelled = {int(i["number"]): i for i in labelled_issues(tracker, graphql)}
    links = [link for i in labelled.values() if (link := link_for(i, tracker.repo)) is not None]
    originals = sorted({k.original for k in links} - set(labelled))
    fetched = fetch_issues(tracker.repo, originals, graphql)
    issues: dict[int, dict[str, Any]] = dict(labelled)
    issues.update({n: node for n, node in fetched.items() if node is not None})
    usable = [k for k in links if k.original in issues]
    edges = {k.issue: k.original for k in usable}
    groups: dict[int, list[int]] = {}
    for member in sorted(set(edges) | set(edges.values())):
        groups.setdefault(root_of(member, edges), []).append(member)
    kept = {root: tuple(m) for root, m in groups.items() if len(m) >= 2}
    return Mined(tracker, len(labelled), tuple(usable), kept, issues)


def records(mined: Mined) -> list[FailureRecord]:
    """One record per issue in a group, labelled by the group's root."""
    package = mined.tracker.package + "/"
    out = []
    for root, members in sorted(mined.groups.items()):
        for number in members:
            record = record_from_issue(
                mined.issues[number],
                repo=mined.tracker.repo,
                true_cause=f"{mined.tracker.repo}#{root}",
            )
            frames = tuple(
                f.model_copy(update={"in_project": f.file.startswith(package)})
                for f in record.frames
            )
            out.append(record.model_copy(update={"frames": frames}))
    return out


def write_links(path: Path, mined: Sequence[Mined]) -> None:
    payload = {
        "source": "GitHub issue trackers, duplicate labels; see mend/data/duplicates.py",
        "trackers": [
            {
                **asdict(m.tracker),
                "labelled": m.labelled,
                "linked": len(m.links),
                "groups": len(m.groups),
                "issues_in_groups": sum(len(v) for v in m.groups.values()),
                "rules": {
                    rule: sum(1 for k in m.links if k.rule == rule)
                    for rule in ("event", "maintainer-comment", "comment")
                },
            }
            for m in mined
        ],
        "groups": [
            {"repo": m.tracker.repo, "original": root, "members": list(members)}
            for m in mined
            for root, members in sorted(m.groups.items())
        ],
        "links": [asdict(k) for m in mined for k in m.links],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def save_cache(path: Path, mined: Mined) -> None:
    """The fetched issues and links, for re-running without the API. Never committed:
    data/issues/ is ignored, because issue text is not this repository's to redistribute."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tracker": asdict(mined.tracker),
        "labelled": mined.labelled,
        "links": [asdict(k) for k in mined.links],
        "issues": {str(n): i for n, i in mined.issues.items()},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_cache(path: Path) -> Mined:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tracker = Tracker(**payload["tracker"])
    links = tuple(Link(**k) for k in payload["links"])
    edges = {k.issue: k.original for k in links}
    groups: dict[int, list[int]] = {}
    for member in sorted(set(edges) | set(edges.values())):
        groups.setdefault(root_of(member, edges), []).append(member)
    return Mined(
        tracker,
        int(payload["labelled"]),
        links,
        {root: tuple(m) for root, m in groups.items() if len(m) >= 2},
        {int(n): i for n, i in payload["issues"].items()},
    )
