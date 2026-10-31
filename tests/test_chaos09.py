"""Reading 09's chaos captures: what becomes a symptom, and what must not.

The captures are built here in the shape 09's docs/chaos-capture.md describes, small enough
to read, with one property each test cares about. The real campaign stays in 09's working
tree and is not needed to run these.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mend.capture.schema import Source
from mend.data.chaos09 import captures, ingest_campaign, log_records, metric_records

T0 = 1_792_251_300.0  # traffic begins
STEPS = 120


def series(
    name: str, values: list[float], job: str = "scorer", start: float = T0 - 10
) -> dict[str, Any]:
    return {
        "metric": {"__name__": name, "job": job},
        "values": [[start + i, str(v)] for i, v in enumerate(values)],
    }


def counter(rate: list[float]) -> list[float]:
    total, out = 0.0, []
    for r in rate:
        total += r
        out.append(total)
    return out


def steady_traffic() -> list[float]:
    # Nothing for ten seconds, then a thousand records a second.
    return counter([0.0] * 10 + [1000.0] * (STEPS - 10))


def write_run(
    root: Path,
    run_id: str,
    scenario: str,
    families: dict[str, list[dict[str, Any]]],
    logs: list[dict[str, Any]] | None = None,
    manifest_extra: dict[str, Any] | None = None,
) -> Path:
    run = root / run_id
    (run / "logs").mkdir(parents=True)
    (run / "prometheus").mkdir()
    manifest = {"run_id": run_id, "scenario": scenario, **(manifest_extra or {})}
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "logs" / "harness.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in (logs or []))
    )
    (run / "logs" / "broker.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-10-17T15:43:41.816635205Z",
                "service": "broker",
                "severity": "INFO",
                "message": "segments removed",
            }
        )
        + "\n"
    )
    all_series = {
        "redpanda_kafka_records_produced_total": [
            series("redpanda_kafka_records_produced_total", steady_traffic(), "broker")
        ]
    }
    all_series.update(families)
    (run / "prometheus" / "series.json").write_text(json.dumps(all_series))
    (run / "prometheus" / "metadata.json").write_text(
        json.dumps({"verdict_queue_depth": [{"type": "gauge", "help": "records waiting"}]})
    )
    return run


def gauge_with_step(level: float, *, from_s: int, to_s: int, to_level: float) -> list[float]:
    """A steady gauge that moves to another level between two seconds of traffic."""
    out = []
    for i in range(STEPS):
        second = i - 10
        out.append(to_level if from_s <= second < to_s else level + (i % 3) * 0.01 * level)
    return out


def titles(records: list[Any]) -> set[str]:
    return {r.title for r in records}


def test_a_sustained_rise_is_one_symptom_with_the_label(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        "r1",
        "scorer-stall",
        {
            "verdict_queue_depth": [
                series(
                    "verdict_queue_depth", gauge_with_step(50, from_s=12, to_s=40, to_level=5000)
                )
            ],
        },
    )
    (capture,) = captures(tmp_path)
    records = metric_records(capture)
    assert titles(records) == {"scorer: verdict_queue_depth rose"}
    (record,) = records
    assert record.source is Source.CHAOS
    assert record.true_cause == "scorer-stall"
    assert record.exception_type == "MetricDeparture"
    assert any("12 s after traffic began" in line for line in record.logs)


def test_a_counter_whose_rate_stops_is_read_as_a_fall(tmp_path: Path) -> None:
    rate = [0.0] * 10 + [1000.0] * 20 + [0.0] * 30 + [1000.0] * (STEPS - 60)
    write_run(
        tmp_path,
        "r1",
        "pause",
        {
            "verdict_batch_records_count": [series("verdict_batch_records_count", counter(rate))],
        },
    )
    assert titles(metric_records(captures(tmp_path)[0])) == {
        "scorer: verdict_batch_records_count fell"
    }


def test_a_two_second_blip_is_not_a_symptom(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        "r1",
        "none",
        {
            "verdict_queue_depth": [
                series(
                    "verdict_queue_depth", gauge_with_step(50, from_s=30, to_s=32, to_level=5000)
                )
            ],
        },
    )
    assert metric_records(captures(tmp_path)[0]) == []


def test_a_gauge_that_only_climbs_is_judged_by_its_rate(tmp_path: Path) -> None:
    """A committed offset rises in every run. Its level departing is not a symptom; its
    rate changing would be."""
    offsets = counter([0.0] * 10 + [1000.0] * (STEPS - 10))
    write_run(
        tmp_path,
        "r1",
        "none",
        {
            "redpanda_kafka_consumer_group_committed_offset": [
                series("redpanda_kafka_consumer_group_committed_offset", offsets, "broker")
            ],
        },
    )
    assert metric_records(captures(tmp_path)[0]) == []


def test_a_counter_that_first_appears_mid_run_rose_from_zero(tmp_path: Path) -> None:
    """09 exports dead letters only once there is one, so the baseline has no samples."""
    dead = {
        "metric": {"__name__": "verdict_dead_letters_total", "job": "scorer"},
        "values": [[T0 + 20 + i, str(2.0 * i)] for i in range(30)],
    }
    write_run(tmp_path, "r1", "poison", {"verdict_dead_letters_total": [dead]})
    assert titles(metric_records(captures(tmp_path)[0])) == {
        "scorer: verdict_dead_letters_total rose"
    }


def test_monitoring_and_build_series_are_never_symptoms(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        "r1",
        "throttle",
        {
            name: [series(name, gauge_with_step(0.01, from_s=12, to_s=60, to_level=5.0))]
            for name in (
                "scrape_duration_seconds",
                "up",
                "redpanda_application_build",
                "verdict_commit_seconds_created",
            )
        },
    )
    assert metric_records(captures(tmp_path)[0]) == []


def test_the_end_of_the_stream_is_not_a_symptom(tmp_path: Path) -> None:
    rate = [0.0] * 10 + [1000.0] * 90 + [0.0] * (STEPS - 100)
    write_run(
        tmp_path,
        "r1",
        "none",
        {
            "verdict_batch_records_count": [series("verdict_batch_records_count", counter(rate))],
        },
    )
    assert metric_records(captures(tmp_path)[0]) == []


def test_only_run_id_and_scenario_are_read_from_the_manifest(tmp_path: Path) -> None:
    """The injection times and 09's own report are the answer. Garbage in them changes
    nothing, which is what not reading them looks like from outside."""
    families = {
        "verdict_queue_depth": [
            series("verdict_queue_depth", gauge_with_step(50, from_s=12, to_s=40, to_level=5000))
        ]
    }
    a, b = tmp_path / "a", tmp_path / "b"
    write_run(a, "r1", "pause", families)
    write_run(
        b,
        "r1",
        "pause",
        families,
        manifest_extra={
            "injection_start_utc": "not a time",
            "injection_end_utc": None,
            "fault": {"seconds": -1},
            "harness_report": {"decided_once": "nonsense"},
        },
    )
    assert ingest_campaign(a) == ingest_campaign(b)


def test_a_run_still_being_recorded_is_skipped(tmp_path: Path) -> None:
    write_run(tmp_path, "r1", "pause", {})
    (tmp_path / "r2" / "logs").mkdir(parents=True)
    assert [c.run_id for c in captures(tmp_path)] == ["r1"]


TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "C:\\Users\\someone\\POCs\\09-realtime-risk-platform\\verdict\\scoring\\consumer.py", line 338, in _take\n'
    "    served = self.decider.take(event)\n"
    "verdict.features.engine.LateEventError: event evt-1 arrived after the engine reached 10:00"
)


def late(i: int) -> dict[str, Any]:
    return {
        "ts": f"2026-10-17T15:40:0{i % 10}.310515+00:00",
        "service": "scorer",
        "severity": "ERROR",
        "exception_type": "verdict.features.engine.LateEventError",
        "message": f"verdict.features.engine.LateEventError: event evt-{i} arrived after the engine reached 10:00",
        "traceback": TRACEBACK,
    }


def test_log_errors_become_symptoms_capped_per_shape_with_the_count(tmp_path: Path) -> None:
    rows = [late(i) for i in range(40)]
    rows.insert(
        1,
        {
            "ts": "2026-10-17T15:40:08+00:00",
            "service": "scorer",
            "severity": "ERROR",
            "message": "During handling of the above exception, another exception occurred:",
        },
    )
    write_run(tmp_path, "r1", "out-of-order", {}, logs=rows)
    records = log_records(captures(tmp_path)[0])
    assert len(records) == 3
    record = records[0]
    assert record.exception_type == "verdict.features.engine.LateEventError"
    assert record.message is not None and record.message.startswith("event evt-")
    assert "seen 40 times in this run" in record.logs
    assert record.frames[0].file == "verdict/scoring/consumer.py"
    assert record.frames[0].in_project
    assert record.true_cause == "out-of-order"
    assert record.traceback_text is not None
    assert 'File "verdict\\scoring\\consumer.py"' in record.traceback_text
    assert "someone" not in record.traceback_text


def test_info_lines_are_not_symptoms(tmp_path: Path) -> None:
    write_run(tmp_path, "r1", "none", {})
    assert log_records(captures(tmp_path)[0]) == []


def test_record_ids_are_stable_across_ingestions(tmp_path: Path) -> None:
    write_run(tmp_path, "r1", "out-of-order", {}, logs=[late(i) for i in range(5)])
    first = [r.record_id for r in ingest_campaign(tmp_path)]
    second = [r.record_id for r in ingest_campaign(tmp_path)]
    assert first == second and len(set(first)) == len(first)
