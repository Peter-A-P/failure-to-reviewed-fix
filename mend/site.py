"""The website's numbers, written from the committed results and from nothing else.

`mend site` writes two files from the same result files `mend report` reads:
data/site/values.json, strings for the {{tokens}} in web/*.html, and web/data.json, the
series the page's charts draw. The page types no measured number, and tests/test_site.py
fails if either file has fallen behind the results.

Every number is formatted here, once. The page displays; it computes nothing.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

from mend.cluster.crossval import Spread, paired, summarise
from mend.eval import ablation, confident_wrong
from mend.eval.report import load_folds, load_kfold, load_outcomes
from mend.eval.results import (
    IssueOutcome,
    confidently_wrong_rate,
    cost_per_attempted,
    cost_per_resolved,
    hit_rate,
    minutes_per_issue,
    reviewer_value,
    test_first_rate,
    tier_table,
)
from mend.eval.stats import Interval, wilson
from mend.graph.route import Tier

VALUES = Path("data/site/values.json")
DATA = Path("web/data.json")

MAIN_OUTCOMES = Path("results/main/outcomes.jsonl")
MAIN_RUN = Path("results/main/fix.jsonl")
MAIN_VERDICTS = Path("results/main/verdicts.jsonl")
CHAOS = Path("results/chaos09/crossval.json")
FAULTS = Path("results/faults")
DUPLICATES = Path("results/duplicates")
WRONG = Path("results/main/false-positives.yaml")
SELF_REVIEW = Path("results/ablation-self-review")
NO_TEST = Path("results/ablation-no-test-first")
ABLATION_SPLIT = Path("data/subset/ablation.json")
LIVE = Path("results/live")
GATE = Path("gate-runs/ledger.jsonl")

# The live run the page walks through step by step: 03's planted Holm bug.
FOLLOW = "ai-release-gate-41237394546"
PULL_REQUESTS = {
    "ai-release-gate": "https://github.com/Peter-A-P/ai-release-gate/pull/2",
    "compliant-ai-gateway": "https://github.com/Peter-A-P/compliant-ai-gateway/pull/1",
}

_TIER_NAMES = {
    Tier.AUTO_PROPOSE: "Offer a pull request",
    Tier.SUGGEST: "Suggest",
    Tier.QUIET: "Stay quiet",
}


def interval(value: Interval) -> dict[str, Any]:
    return {"est": value.estimate, "low": value.low, "high": value.high, "n": value.n}


def spread(value: Spread) -> dict[str, Any]:
    return {"est": value.mean, "low": value.low, "high": value.high, "n": value.n_folds}


def triple(values: Sequence[float]) -> dict[str, float]:
    est, low, high = values
    return {"est": float(est), "low": float(low), "high": float(high)}


def pct(value: float, places: int = 1) -> str:
    return f"{value * 100:.{places}f}%"


def pct_range(value: Interval, places: int = 1) -> str:
    return f"{value.low * 100:.{places}f}% to {value.high * 100:.{places}f}%"


def money(value: float, places: int = 2) -> str:
    return f"US${value:.{places}f}"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _verdicts(path: Path) -> dict[str, bool]:
    return {str(r["instance_id"]): bool(r["resolved"]) for r in _jsonl(path)}


def _records(path: Path) -> dict[str, dict[str, Any]]:
    return {str(r["issue"]["issue_id"]): r for r in _jsonl(path)}


# --------------------------------------------------------------------------- the benchmark


def resolution(outcomes: Sequence[IssueOutcome]) -> tuple[dict[str, str], dict[str, Any]]:
    hit = hit_rate(outcomes)
    wrong = confidently_wrong_rate(outcomes)
    per_resolved = cost_per_resolved(outcomes)
    per_attempted = cost_per_attempted(outcomes)
    minutes = minutes_per_issue(outcomes)
    first = test_first_rate(outcomes)
    quiet = [o for o in outcomes if o.tier is Tier.QUIET]
    rows = tier_table(outcomes)
    auto = next(r for r in rows if r.tier is Tier.AUTO_PROPOSE)
    values = {
        "tasks": str(len(outcomes)),
        "resolved": str(sum(o.resolved for o in outcomes)),
        "hit_pct": pct(hit.estimate),
        "hit_range": pct_range(hit),
        "wrong_pct": pct(wrong.estimate),
        "wrong_range": pct_range(wrong),
        "wrong_count": str(round(wrong.estimate * wrong.n)),
        "auto_count": str(wrong.n),
        "auto_hit_pct": pct(auto.hit_rate.estimate),
        "auto_hit_range": pct_range(auto.hit_rate),
        "auto_right": str(round(auto.hit_rate.estimate * auto.n)),
        "cost_resolved": money(per_resolved.estimate),
        "cost_resolved_range": f"{money(per_resolved.low)} to {money(per_resolved.high)}",
        "cost_attempted": money(per_attempted.estimate),
        "minutes": f"{minutes.estimate:.1f}",
        "test_first_pct": pct(first.estimate),
        "test_first_count": str(round(first.estimate * first.n)),
        "quiet_count": str(len(quiet)),
        "quiet_right": str(sum(o.resolved for o in quiet)),
    }
    data = {
        "tiers": [
            {
                "tier": _TIER_NAMES[r.tier],
                "n": r.n,
                "hit": interval(r.hit_rate),
                "wrong": None if r.confidently_wrong is None else interval(r.confidently_wrong),
                "cost_attempted": interval(r.cost_per_attempted),
                "cost_resolved": interval(r.cost_per_resolved),
            }
            for r in rows
        ],
        "all": {
            "n": len(outcomes),
            "hit": interval(hit),
            "wrong": interval(wrong),
            "cost_attempted": interval(per_attempted),
            "cost_resolved": interval(per_resolved),
        },
    }
    return values, data


def review(outcomes: Sequence[IssueOutcome]) -> tuple[dict[str, str], dict[str, Any]]:
    value = reviewer_value(outcomes)
    passed = _verdicts(MAIN_VERDICTS)
    main = _records(MAIN_RUN)
    same = _jsonl(SELF_REVIEW / "self-review.jsonl")
    reviewed = [r for r in main.values() if (r.get("state") or {}).get("review") is not None]
    arms = [
        ("A different company's model", ablation.review_numbers(reviewed, passed)),
        ("The fixer's own company's model", ablation.review_numbers(same, passed)),
    ]
    values = {
        "reviewed": str(value.n_reviewed),
        "wrong_objected_pct": pct(value.fixer_wrong_when_disagreed.estimate),
        "wrong_agreed_pct": pct(value.fixer_wrong_when_agreed.estimate),
        "objected_count": str(value.n_disagreed),
        "agreed_count": str(value.n_reviewed - value.n_disagreed),
        "same_wrong_auto_pct": pct(arms[1][1]["wrong_auto"].estimate),
    }
    data = {
        "split": [
            {"label": "The reviewer objected", "value": interval(value.fixer_wrong_when_disagreed)},
            {"label": "The reviewer agreed", "value": interval(value.fixer_wrong_when_agreed)},
        ],
        "arms": [
            {
                "label": name,
                "caught": interval(n["caught"]),
                "false_alarm": interval(n["false_alarm"]),
                "wrong_auto": interval(n["wrong_auto"]),
            }
            for name, n in arms
        ],
    }
    return values, data


def test_first() -> tuple[dict[str, str], dict[str, Any]]:
    passed = _verdicts(MAIN_VERDICTS)
    main = _records(MAIN_RUN)
    ids = set(json.loads(ABLATION_SPLIT.read_text(encoding="utf-8"))["instance_ids"])
    with_test = ablation.first_test_numbers(
        [r for i, r in sorted(main.items()) if i in ids], passed
    )
    without = ablation.first_test_numbers(
        _jsonl(NO_TEST / "fix.jsonl"), _verdicts(NO_TEST / "verdicts.jsonl")
    )
    values = {
        "ablation_tasks": str(with_test["resolved"].n),
        "with_test_resolved": str(round(with_test["resolved"].estimate * with_test["resolved"].n)),
        "without_test_resolved": str(round(without["resolved"].estimate * without["resolved"].n)),
        "with_test_cost": money(with_test["cost"], 3),
        "without_test_cost": money(without["cost"], 3),
    }
    data = {
        "arms": [
            {
                "label": "Failing test first",
                "resolved": interval(with_test["resolved"]),
                "cost": with_test["cost"],
            },
            {
                "label": "No failing test first",
                "resolved": interval(without["resolved"]),
                "cost": without["cost"],
            },
        ]
    }
    return values, data


def gate() -> dict[str, str]:
    """The release gate's verdicts on the two ablations, by suite."""
    latest: dict[str, Mapping[str, Any]] = {}
    for line in GATE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            latest[str(record.get("spec_name") or record.get("spec", {}).get("name"))] = record
    margin = latest["mend-no-test-first"]
    suites = {s["suite"]: s for s in margin["suites"]}
    resolved = suites["resolved"]
    return {
        "gate_test_diff": f"{resolved['difference'] * 100:+.1f}",
        "gate_test_range": f"{resolved['lo'] * 100:+.1f} to {resolved['hi'] * 100:+.1f}",
    }


def wrong_cases() -> tuple[dict[str, str], dict[str, Any]]:
    passed = _verdicts(MAIN_VERDICTS)
    cases = confident_wrong.wrong_auto_proposals(_records(MAIN_RUN).values(), passed)
    ids = [str(r["issue"]["issue_id"]) for r in cases]
    classified = confident_wrong.read(WRONG, ids)
    if classified is None:
        raise SystemExit(f"{WRONG}: not every case has a cause yet")
    counts = confident_wrong.tabulate(classified)
    n = len(classified)
    values = {
        "wrong_underspecified": str(counts[confident_wrong.Cause.ISSUE_UNDERSPECIFIED]),
        "wrong_location": str(counts[confident_wrong.Cause.WRONG_LOCATION]),
    }
    data = {
        "causes": [
            {
                "cause": c.value.replace("_", " "),
                "meaning": confident_wrong.MEANING[c],
                "count": counts[c],
                "share": interval(wilson(counts[c], n)),
            }
            for c in confident_wrong.Cause
        ],
        "cases": [
            {
                "task": item.issue_id,
                "cause": item.cause.value.replace("_", " "),
                "why": item.note.strip(),
            }
            for item in sorted(classified, key=lambda x: x.issue_id)
        ],
    }
    return values, data


# --------------------------------------------------------------------------- clustering


def clustering() -> tuple[dict[str, str], dict[str, Any]]:
    folds = load_folds(CHAOS)
    methods = [
        ("record-level", "One record at a time"),
        ("fingerprint", "Fingerprint only"),
        ("two-stage", "Incidents first, then signatures"),
    ]
    _, wins = paired(folds, "two-stage", "record-level")
    chaos = [{"label": name, "value": spread(summarise(folds, key))} for key, name in methods]
    sets = []
    for path, name in (
        (FAULTS / "kfold.json", "Injected faults"),
        (DUPLICATES / "kfold.json", "Duplicate reports"),
        (DUPLICATES / "kfold-st.json", "Duplicate reports, trained text encoder"),
    ):
        payload = load_kfold(path)
        pooled = payload["pooled"]["record-level"]
        sets.append(
            {
                "label": name,
                "causes": pooled["n_true_causes"],
                "symptoms": pooled["n_records"],
                "ari": triple(pooled["ari"]),
                "purity": triple(pooled["purity"]),
                "completeness": triple(pooled["completeness"]),
            }
        )
    two = summarise(folds, "two-stage")
    record = summarise(folds, "record-level")
    values = {
        "ari_two_stage": f"{two.mean:.3f}",
        "ari_record": f"{record.mean:.3f}",
        "chaos_folds": str(len(folds)),
        "chaos_wins": str(wins),
        "faults_completeness": pct(sets[0]["completeness"]["est"], 0),
        "duplicates_ari_hash": f"{sets[1]['ari']['est']:.3f}",
        "duplicates_ari_encoder": f"{sets[2]['ari']['est']:.3f}",
    }
    values["chaos_symptoms"] = str(len(_jsonl(Path("results/chaos09/records.jsonl"))))
    return values, {"chaos": chaos, "sets": sets}


# --------------------------------------------------------------------------- live


def _junit(path: Path) -> tuple[int, str]:
    """How many tests the sandbox ran, and the day it ran them."""
    root = ElementTree.parse(path).getroot()
    stamp = next((s.get("timestamp") for s in root.iter("testsuite") if s.get("timestamp")), "")
    return sum(1 for _ in root.iter("testcase")), (stamp or "")[:10]


def _markers(repo: str) -> tuple[str, ...]:
    caller = yaml.safe_load(Path(f"action/{repo}.yml").read_text(encoding="utf-8"))
    return tuple(str(caller["jobs"]["suggest"]["with"]["markers"]).split())


def live() -> tuple[dict[str, str], dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for folder in sorted(LIVE.iterdir(), key=lambda p: p.name.rsplit("-", 1)[1]):
        repo, run_id = folder.name.rsplit("-", 1)
        total, stamp = _junit(folder / "report.xml")
        captured, tickets = capture(
            folder / "report.xml", repo=f"Peter-A-P/{repo}", commit="", markers=_markers(repo)
        )
        record = _jsonl(folder / "runs.jsonl")[0] if (folder / "runs.jsonl").is_file() else None
        if record is None:
            outcome, cost, posted, at = "ran no tests", 0.0, False, stamp
        else:
            state = record["state"]
            tier = state.get("tier")
            outcome = (
                {"auto_propose": "would offer a pull request", "suggest": "suggestion"}.get(
                    tier, ""
                )
                if tier in ("auto_propose", "suggest")
                else "stopped: " + str(state.get("stop_reason") or "no patch").split(": ", 1)[-1]
            )
            cost = float(record["cost_usd"])
            posted = tier in ("auto_propose", "suggest")
            spent = json.loads((folder / "spent.json").read_text(encoding="utf-8"))
            at = next(
                str(i["at"])[:10]
                for i in spent["issues"]
                if str(i["issue_id"]).startswith(f"live-{run_id}-")
            )
        runs.append(
            {
                "repo": repo,
                "run": f"https://github.com/Peter-A-P/{repo}/actions/runs/{run_id}",
                "pull_request": PULL_REQUESTS[repo],
                "date": at,
                "tests": total,
                "failures": len(captured),
                "tickets": len(tickets),
                "outcome": outcome,
                "cost": cost,
                "posted": posted,
            }
        )
    values = {
        "live_runs": str(len(runs)),
        "live_comments": str(sum(r["posted"] for r in runs)),
        "live_cost": money(sum(r["cost"] for r in runs)),
    }
    return values, {"runs": runs}


def follow() -> tuple[dict[str, str], dict[str, Any]]:
    folder = LIVE / FOLLOW
    repo, run_id = FOLLOW.rsplit("-", 1)
    record = _jsonl(folder / "runs.jsonl")[0]
    state = record["state"]
    records, tickets = capture(
        folder / "report.xml", repo=f"Peter-A-P/{repo}", commit="", markers=_markers(repo)
    )
    failing = sorted({r.test_id or r.title for r in records if (r.test_id or r.title)})
    review_state = state["review"]
    hops = [
        {
            "role": h["role"].removeprefix("mend-"),
            "provider": h["provider"],
            "model": h["model"],
            "cost": h["cost_usd"],
            "seconds": round(h["latency_ms"] / 1000, 1),
        }
        for h in record["hops"]
    ]
    data = {
        "repo": repo,
        "pull_request": PULL_REQUESTS[repo],
        "run": f"https://github.com/Peter-A-P/{repo}/actions/runs/{run_id}",
        "failing": failing,
        "tickets": [{"title": t.title(), "size": t.size} for t in tickets],
        "ticket": record["issue"]["title"],
        "suspects": list(state.get("suspect_files") or []),
        "test_id": state["test"]["test_id"],
        "test_source": state["test"]["source"],
        "test_output": "\n".join(str(state["test"]["output"]).splitlines()[:14]),
        "diff": state["patch"]["diff"],
        "suite": list(state["patch"]["suite_files"]),
        "reviewer": review_state["reviewer_provider"],
        "fixer": review_state["fixer_provider"],
        "agrees": bool(review_state["agrees"]),
        "objection": review_state.get("objection") or "",
        "tier": state["tier"],
        "score": round(float(state["score"]), 2),
        "cost": record["cost_usd"],
        "seconds": round(float(record["duration_s"])),
        "hops": hops,
    }
    values = {
        "follow_failures": str(len(records)),
        "follow_tickets": str(len(tickets)),
        "follow_cost": money(float(record["cost_usd"])),
        "follow_seconds": str(round(float(record["duration_s"]))),
    }
    return values, data


def capture(
    junit: Path, *, repo: str, commit: str, markers: Sequence[str]
) -> tuple[list[Any], list[Any]]:
    from mend.live.run import capture as run_capture

    return run_capture(junit, repo=repo, commit=commit, markers=markers)


# --------------------------------------------------------------------------- engineering


def engineering() -> dict[str, str]:
    tests = 0
    for path in Path("tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tests += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        )
    lines = sum(
        1
        for path in Path("mend").rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    return {"test_functions": str(tests), "code_lines": f"{round(lines, -2):,}"}


# --------------------------------------------------------------------------- the files


def build() -> tuple[dict[str, str], dict[str, Any]]:
    outcomes = load_outcomes(MAIN_OUTCOMES)
    values: dict[str, str] = {}
    data: dict[str, Any] = {}
    for key, (v, d) in {
        "resolution": resolution(outcomes),
        "review": review(outcomes),
        "test_first": test_first(),
        "wrong": wrong_cases(),
        "clustering": clustering(),
        "live": live(),
        "follow": follow(),
    }.items():
        values.update(v)
        data[key] = d
    values.update(gate())
    values.update(engineering())
    dates = [
        r["date"] for r in data["live"]["runs"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"])
    ]
    values["results_date"] = max(dates)
    return values, data


def render(values: Mapping[str, str], data: Mapping[str, Any]) -> tuple[str, str]:
    """The two files' text. values carries a version that changes whenever the data does,
    so a browser holding an old stylesheet or script fetches the new one."""
    data_text = json.dumps(data, indent=1, ensure_ascii=True) + "\n"
    version = hashlib.sha256(data_text.encode("utf-8")).hexdigest()[:10]
    values_text = json.dumps({**values, "version": version}, indent=1, sort_keys=True) + "\n"
    return values_text, data_text


def write() -> tuple[Path, Path]:
    values_text, data_text = render(*build())
    VALUES.parent.mkdir(parents=True, exist_ok=True)
    VALUES.write_text(values_text, encoding="utf-8", newline="\n")
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(data_text, encoding="utf-8", newline="\n")
    return VALUES, DATA
