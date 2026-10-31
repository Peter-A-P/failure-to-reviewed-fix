"""Project 09's chaos captures, as failure records with the injected fault as the label.

Each capture is one run of 09's streaming platform with one fault injected (or none, for
the controls), recorded as an operator would have seen it: the services' logs and every
Prometheus series at a one-second scrape (09's docs/chaos-capture.md). This turns a run
into symptoms, the third labelled set in PLAN.md section 2.2.

Two kinds of symptom, because 09 logs very little and most faults show only in metrics:

- A log record at WARNING or above becomes a record directly, its traceback parsed into
  frames. Records that repeat within a run (one per late event, say) are kept up to
  _MAX_PER_KEY times per message shape, with the count noted, so that one noisy fault does
  not outweigh every other symptom in the set by sheer volume.
- A metric that leaves its own steady level and stays out becomes a record naming the
  metric and the direction. The steady level is the run's first seconds of traffic, and
  the start of traffic is read off the metrics (the first record the broker accepted), not
  off the manifest.

The manifest holds the answer, so this reads exactly two fields from it: run_id, to name
the records, and scenario, which goes into true_cause and nowhere else. The injection
times, the fault parameters and 09's own summary of the run are never read; a detector
that knew when the fault began would find it by construction.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from mend.capture.normalise import normalise_message
from mend.capture.schema import FailureRecord, Frame, Source
from mend.capture.traceback_parse import parse_exception, parse_frames

# 09's own package, which is what makes a frame "in project".
PROJECT_MARKERS = ("/verdict/",)

_LOG_SEVERITIES = {"WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"}
_MAX_PER_KEY = 3
_CHAINED = re.compile(
    r"^(During handling of the above exception|The above exception was the direct cause)"
)

# 09's protocol (docs/chaos-capture.md): the fault starts at about the tenth second of
# traffic, and 90,000 transactions go out at 1,000 a second. The steady level is taken
# from seconds 1 to 7 of traffic, before any fault can have begun, and the search for a
# departure stops when sending does, so the end of the stream is not read as a symptom.
BASELINE_FROM_S = 1.0
BASELINE_TO_S = 7.0
SEND_S = 90.0

# A departure: more than _DEVIATIONS scales from the steady median, for at least
# _SUSTAIN_S consecutive seconds. The scale is the median absolute deviation, floored at a
# tenth of the median, so that a metric that sat perfectly still in the baseline does not
# turn every wobble afterwards into a symptom.
_DEVIATIONS = 6.0
_SUSTAIN_S = 3
_RELATIVE_FLOOR = 0.10
_ABSOLUTE_FLOOR = 1e-9

# Series that describe the build, the clock or the monitoring rather than the system's
# behaviour. Prometheus's own scrape timings follow the load on the capture machine, which
# 09 shares with other projects' jobs, so they are a symptom of the host, not of the fault.
_SKIP_SUFFIXES = ("_created", "_bucket")
_SKIP_FRAGMENTS = ("_build", "fips_mode", "uptime", "_info")
_SKIP_PREFIXES = ("scrape_", "up", "prometheus_")
# Where traffic starts: the broker's count of accepted records, or failing that the
# scorer's count of records it batched.
_TRAFFIC_COUNTERS = ("redpanda_kafka_records_produced_total", "verdict_batch_records_count")


@dataclass(frozen=True, slots=True)
class Capture:
    run_id: str
    scenario: str
    path: Path


def captures(root: Path) -> list[Capture]:
    """Every complete run under a campaign directory, in run order.

    A run directory without a manifest is a run still being recorded, and is skipped
    rather than read half-written.
    """
    out = []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = run_dir / "manifest.json"
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        out.append(
            Capture(run_id=str(data["run_id"]), scenario=str(data["scenario"]), path=run_dir)
        )
    return out


def ingest_campaign(root: Path) -> list[FailureRecord]:
    records: list[FailureRecord] = []
    for capture in captures(root):
        records.extend(ingest_capture(capture))
    return records


def ingest_capture(capture: Capture) -> list[FailureRecord]:
    return log_records(capture) + metric_records(capture)


# -- logs ----------------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _relative(frame: Frame) -> Frame:
    """09's frames carry the capture machine's checkout path; keep only from verdict/ on,
    so a frame compares equal across machines."""
    path = frame.file.replace("\\", "/")
    idx = path.find("/verdict/")
    if idx == -1:
        return frame
    return frame.model_copy(update={"file": path[idx + 1 :]})


_CHECKOUT = re.compile(r'(File ")[^"]*?[\\/](verdict[\\/])')


def scrub(traceback: str) -> str:
    """The traceback with the capture machine's checkout path taken out of every frame,
    for the same reason as _relative, and so that a committed record names no user."""
    return _CHECKOUT.sub(r"\1\2", traceback)


def _when(raw: Any) -> datetime:
    """09 writes UTC ISO times, the broker's with nanoseconds, which datetime refuses."""
    text = str(raw).replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def log_records(capture: Capture) -> list[FailureRecord]:
    rows: list[dict[str, Any]] = []
    for name in ("harness.jsonl", "broker.jsonl"):
        rows.extend(_read_jsonl(capture.path / "logs" / name))

    kept: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        if str(row.get("severity", "")).upper() not in _LOG_SEVERITIES:
            continue
        message = str(row.get("message", ""))
        traceback = row.get("traceback")
        exc_type = row.get("exception_type")
        if not exc_type and not traceback and _CHAINED.match(message):
            continue  # the separator between two tracebacks, which says nothing itself
        key = (str(row.get("service", "")), str(exc_type or ""), normalise_message(message))
        counts[key] = counts.get(key, 0) + 1
        if len(kept.setdefault(key, [])) < _MAX_PER_KEY:
            kept[key].append(row)

    records = []
    for key, group in kept.items():
        for i, row in enumerate(group):
            records.append(_log_record(capture, row, i, counts[key]))
    return records


def _log_record(capture: Capture, row: Mapping[str, Any], index: int, seen: int) -> FailureRecord:
    service = str(row.get("service", "unknown"))
    message = str(row.get("message", ""))
    traceback = row.get("traceback") if isinstance(row.get("traceback"), str) else None
    exc_type = row.get("exception_type") if isinstance(row.get("exception_type"), str) else None
    if traceback and not exc_type:
        exc_type, _ = parse_exception(traceback)
    # 09 prefixes the message with the exception's dotted name; the type is already its own
    # field, so the message keeps only what follows.
    if exc_type and message.startswith(f"{exc_type}: "):
        message = message[len(exc_type) + 2 :]
    frames = (
        tuple(_relative(f) for f in parse_frames(traceback, project_markers=PROJECT_MARKERS))
        if traceback
        else ()
    )
    context = [f"{k}: {row[k]}" for k in ("client", "facility") if row.get(k)]
    if seen > 1:
        context.append(f"seen {seen} times in this run")
    key = normalise_message(f"{service}\x00{exc_type}\x00{message}")
    return FailureRecord(
        record_id=f"chaos09:{capture.run_id}:log:{hashlib.sha256(key.encode()).hexdigest()[:12]}:{index}",
        source=Source.CHAOS,
        captured_at=_when(row.get("ts")),
        exception_type=exc_type,
        message=message or None,
        frames=frames,
        # The frames above are read from the full paths, which is how the marker finds 09's
        # package; only the stored text is scrubbed.
        traceback_text=scrub(traceback) if traceback else None,
        env=f"chaos09:{capture.run_id}",
        logs=tuple(context),
        title=f"{service}: {exc_type or message[:80]}",
        true_cause=capture.scenario,
    )


# -- metrics -------------------------------------------------------------------------------


def _skip(name: str) -> bool:
    return (
        name.endswith(_SKIP_SUFFIXES)
        or any(f in name for f in _SKIP_FRAGMENTS)
        or name == "up"
        or name.startswith(_SKIP_PREFIXES[0])
        or name.startswith(_SKIP_PREFIXES[2])
    )


def _only_climbs(points: Mapping[float, float], start: float) -> bool:
    """A gauge that rose through the whole baseline without ever falling, such as a
    committed offset or a last-seen timestamp. Its level always departs from the baseline,
    in every run, faulted or not; its rate is what can change."""
    base = [
        points[t] for t in sorted(points) if start + BASELINE_FROM_S <= t <= start + BASELINE_TO_S
    ]
    steps = [b - a for a, b in pairwise(base)]
    return len(steps) >= 2 and all(d >= 0 for d in steps) and sum(steps) > 0


def _is_counter(name: str, kind: str) -> bool:
    return kind == "counter" or name.endswith(("_total", "_count", "_sum"))


def _family(series: Sequence[Mapping[str, Any]]) -> dict[float, float]:
    """One value per timestamp, summed over the family's label sets."""
    total: dict[float, float] = {}
    for one in series:
        for stamp, value in one.get("values", []):
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if v != v:  # NaN, which Prometheus writes for an empty histogram quantile
                continue
            total[round(float(stamp), 3)] = total.get(round(float(stamp), 3), 0.0) + v
    return total


def _increments(points: Mapping[float, float]) -> dict[float, float]:
    """Per-second increase of a counter, with a reset read as a fresh start."""
    stamps = sorted(points)
    out = {}
    for a, b in pairwise(stamps):
        step = b - a
        if step <= 0:
            continue
        delta = points[b] - points[a]
        out[b] = (delta if delta >= 0 else points[b]) / step
    return out


def traffic_start(series: Mapping[str, Sequence[Mapping[str, Any]]]) -> float | None:
    for name in _TRAFFIC_COUNTERS:
        rate = _increments(_family(series.get(name, [])))
        for stamp in sorted(rate):
            if rate[stamp] > 0:
                return stamp
    return None


@dataclass(frozen=True, slots=True)
class Departure:
    metric: str
    direction: str
    onset: float
    seconds: int
    steady: float
    extreme: float


def departure(
    name: str, values: Mapping[float, float], start: float, *, absent_is_zero: bool = False
) -> Departure | None:
    """The first sustained departure from the steady level, or None.

    Only the first: a metric that rises and then falls back past its steady level during
    recovery is one symptom, not two, and the direction that matters is the one it went
    first.
    """
    base = [v for t, v in values.items() if start + BASELINE_FROM_S <= t <= start + BASELINE_TO_S]
    if len(base) < 3:
        if not absent_is_zero:
            return None
        # A labelled counter is only exported once it first counts something, so one that
        # is missing from the baseline had counted nothing there: dead letters, say.
        base = [0.0] * int(BASELINE_TO_S - BASELINE_FROM_S + 1)
    centre = median(base)
    spread = median(abs(v - centre) for v in base) * 1.4826
    scale = max(spread, _RELATIVE_FLOOR * abs(centre), _ABSOLUTE_FLOOR)
    window = sorted(
        (t, v) for t, v in values.items() if start + BASELINE_TO_S < t <= start + SEND_S
    )
    run: list[tuple[float, float]] = []
    run_sign = 0
    for stamp, value in window:
        z = (value - centre) / scale
        sign = 1 if z > _DEVIATIONS else -1 if z < -_DEVIATIONS else 0
        if sign != 0 and (not run or sign == run_sign):
            run.append((stamp, value))
            run_sign = sign
        else:
            run, run_sign = ([(stamp, value)], sign) if sign != 0 else ([], 0)
        if len(run) >= _SUSTAIN_S:
            # Extend to the end of the departure, for its length and its extreme.
            rest = [
                (t, v)
                for t, v in window
                if t > run[-1][0] and ((v - centre) / scale) * run_sign > _DEVIATIONS
            ]
            stretch = run + _contiguous(run[-1][0], rest)
            pick = max if run_sign > 0 else min
            return Departure(
                metric=name,
                direction="rose" if run_sign > 0 else "fell",
                onset=run[0][0],
                seconds=len(stretch),
                steady=centre,
                extreme=pick(v for _, v in stretch),
            )
    return None


def _contiguous(
    after: float, rest: Iterable[tuple[float, float]], step: float = 1.5
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    last = after
    for stamp, value in rest:
        if stamp - last > step:
            break
        out.append((stamp, value))
        last = stamp
    return out


def metric_records(capture: Capture) -> list[FailureRecord]:
    prom = capture.path / "prometheus"
    series_path = prom / "series.json"
    if not series_path.is_file():
        return []
    series: dict[str, list[dict[str, Any]]] = json.loads(series_path.read_text(encoding="utf-8"))
    metadata_path = prom / "metadata.json"
    metadata: dict[str, list[dict[str, Any]]] = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    )
    start = traffic_start(series)
    if start is None:
        return []

    records = []
    for name in sorted(series):
        if _skip(name):
            continue
        base_name = re.sub(r"_(total|count|sum)$", "", name)
        meta = (metadata.get(name) or metadata.get(base_name) or [{}])[0]
        kind = str(meta.get("type", ""))
        points = _family(series[name])
        counter = _is_counter(name, kind) or _only_climbs(points, start)
        values = _increments(points) if counter else points
        found = departure(name, values, start, absent_is_zero=counter)
        if found is None:
            continue
        job = next(
            (
                str(s.get("metric", {}).get("job"))
                for s in series[name]
                if s.get("metric", {}).get("job")
            ),
            "unknown",
        )
        records.append(
            _metric_record(
                capture, found, job, str(meta.get("help", "")), counter=counter, start=start
            )
        )
    return records


def _metric_record(
    capture: Capture, d: Departure, job: str, help_text: str, *, counter: bool, start: float
) -> FailureRecord:
    what = "rate" if counter else "level"
    return FailureRecord(
        record_id=f"chaos09:{capture.run_id}:metric:{d.metric}",
        source=Source.CHAOS,
        captured_at=datetime.fromtimestamp(d.onset, tz=UTC),
        exception_type="MetricDeparture",
        message=f"{d.metric} {what} {d.direction} from its steady level",
        env=f"chaos09:{capture.run_id}",
        logs=tuple(
            line
            for line in (
                f"job: {job}",
                f"help: {help_text}" if help_text else "",
                f"{d.direction} {d.onset - start:.0f} s after traffic began, for {d.seconds} s",
                f"steady {d.steady:.4g}, reached {d.extreme:.4g}",
            )
            if line
        ),
        title=f"{job}: {d.metric} {d.direction}",
        true_cause=capture.scenario,
    )
