"""The command line.

Ingestion, clustering with its metrics, the routing curve and calibration, the
configuration checks, and the pipeline itself. `mend roles` resolves the four aliases and
calls nothing; `mend ping` makes one short paid call per role to prove the keys and the
vendor split end to end; `mend fix` runs one benchmark task through the whole graph in its
sandbox, and needs Docker.

Every command that reports a number prints it with its interval. There is no flag to turn
that off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from mend import __version__
from mend.capture.github_ingest import ingest_issues_json
from mend.capture.otel_ingest import ingest_otlp_json
from mend.capture.pytest_ingest import ingest_junit_xml
from mend.capture.schema import FailureRecord
from mend.cluster.agglomerate import ChannelWeights, cluster_by_fingerprint, cluster_records
from mend.cluster.metrics import evaluate
from mend.cluster.ticket import build_tickets

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Self-healing production AI: capture, cluster, propose, and know when not to.",
)
capture_app = typer.Typer(no_args_is_help=True, help="Turn failures into records.")
cluster_app = typer.Typer(no_args_is_help=True, help="Turn records into tickets, and measure it.")
app.add_typer(capture_app, name="capture")
app.add_typer(cluster_app, name="cluster")

CONFIG_DEFAULT = Path("config/boundary.yaml")


def _write_records(records: list[FailureRecord], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")


def _read_records(path: Path) -> list[FailureRecord]:
    return [
        FailureRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(f"mend {__version__}")


@capture_app.command("pytest")
def capture_pytest(
    report: Annotated[Path, typer.Argument(help="A JUnit XML report.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the records.")],
    repo: Annotated[str | None, typer.Option(help="Repository the run was against.")] = None,
    commit: Annotated[str | None, typer.Option(help="Commit the run was against.")] = None,
    marker: Annotated[
        list[str] | None,
        typer.Option("--marker", help="Path fragment marking in-project frames. Repeatable."),
    ] = None,
) -> None:
    """Ingest a pytest JUnit XML report."""
    records = ingest_junit_xml(
        report, repo=repo, commit=commit, project_markers=tuple(marker or ())
    )
    _write_records(records, out)
    typer.echo(f"{len(records)} records -> {out}")


@capture_app.command("otel")
def capture_otel(
    export: Annotated[Path, typer.Argument(help="An OTLP JSON export.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the records.")],
    cause_attribute: Annotated[
        str | None,
        typer.Option(help="Span attribute holding the true cause, for a labelled set."),
    ] = None,
) -> None:
    """Ingest error spans from an OpenTelemetry export."""
    records = ingest_otlp_json(export, true_cause_attribute=cause_attribute)
    _write_records(records, out)
    typer.echo(f"{len(records)} records -> {out}")


@capture_app.command("chaos09")
def capture_chaos09(
    campaign: Annotated[Path, typer.Argument(help="A 09 chaos-capture campaign directory.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the records.")],
) -> None:
    """Ingest project 09's chaos captures: log errors and metric departures, labelled by
    the injected scenario. Reads only run_id and scenario from each manifest."""
    from collections import Counter

    from mend.data.chaos09 import captures, ingest_capture

    runs = captures(campaign)
    records = [r for capture in runs for r in ingest_capture(capture)]
    _write_records(records, out)
    per = Counter(c.scenario for c in runs)
    typer.echo(f"{len(records)} records from {len(runs)} runs -> {out}")
    for scenario, n in sorted(per.items()):
        symptoms = sum(1 for r in records if r.true_cause == scenario)
        typer.echo(f"  {scenario}: {n} runs, {symptoms} symptoms")


@capture_app.command("issues")
def capture_issues(
    issues: Annotated[Path, typer.Argument(help="Cached issue JSON.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the records.")],
    repo: Annotated[str | None, typer.Option(help="Repository the issues belong to.")] = None,
) -> None:
    """Ingest GitHub issues that were fetched and cached earlier."""
    records = ingest_issues_json(issues, repo=repo)
    _write_records(records, out)
    typer.echo(f"{len(records)} records -> {out}")


@cluster_app.command("run")
def cluster_run(
    records_path: Annotated[Path, typer.Argument(help="Records written by mend capture.")],
    threshold: Annotated[float, typer.Option(help="Cut the tree at this distance.")] = 0.45,
    out: Annotated[Path | None, typer.Option("--out", help="Where to write the tickets.")] = None,
    fingerprint_only: Annotated[
        bool, typer.Option("--fingerprint-only", help="The Rule C baseline.")
    ] = False,
) -> None:
    """Cluster records into tickets."""
    records = _read_records(records_path)
    clustering = (
        cluster_by_fingerprint(records)
        if fingerprint_only
        else cluster_records(records, threshold=threshold)
    )
    tickets = build_tickets(records, clustering)

    typer.echo(
        f"{len(records)} records -> {clustering.n_clusters} tickets "
        f"({clustering.symptoms_per_cause:.2f} symptoms per ticket, "
        f"embedder {clustering.embedder})"
    )
    for ticket in tickets[:20]:
        typer.echo(f"  {ticket.ticket_id}  n={ticket.size:<4} {ticket.title()}")

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                [
                    {
                        "ticket_id": t.ticket_id,
                        "title": t.title(),
                        "size": t.size,
                        "member_ids": list(t.member_ids),
                        "suspect_files": list(t.suspect_files),
                        "exception_types": list(t.exception_types),
                    }
                    for t in tickets
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"tickets -> {out}")


@cluster_app.command("metrics")
def cluster_metrics(
    records_path: Annotated[Path, typer.Argument(help="Records carrying true_cause.")],
    threshold: Annotated[float, typer.Option(help="Cut the tree at this distance.")] = 0.45,
    fingerprint_only: Annotated[
        bool, typer.Option("--fingerprint-only", help="The Rule C baseline.")
    ] = False,
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples.")] = 2000,
) -> None:
    """Measure clustering against a labelled set: purity, completeness, ARI, with intervals."""
    records = _read_records(records_path)
    labelled = [r for r in records if r.true_cause]
    if not labelled:
        raise typer.BadParameter("no record in that file carries a true_cause")
    if len(labelled) != len(records):
        typer.echo(f"note: {len(records) - len(labelled)} unlabelled records ignored")

    clustering = (
        cluster_by_fingerprint(labelled)
        if fingerprint_only
        else cluster_records(labelled, threshold=threshold)
    )
    result = evaluate(
        clustering.labels, [r.true_cause or "" for r in labelled], resamples=resamples
    )

    typer.echo(
        f"records {result.n_records}, tickets {result.n_clusters}, causes {result.n_true_causes}"
    )
    typer.echo(f"symptoms per root cause  {result.ratio_interval.as_value()}")
    typer.echo(f"purity                   {result.purity_interval.as_percent()}")
    typer.echo(f"completeness             {result.completeness_interval.as_percent()}")
    typer.echo(f"adjusted Rand index      {result.ari_interval.as_value(3)}")


@cluster_app.command("crossval")
def cluster_crossval(
    records_path: Annotated[Path, typer.Argument(help="Labelled records, JSON lines.")],
    k: Annotated[int, typer.Option(help="Causes held out per fold.")] = 3,
    out: Annotated[Path | None, typer.Option(help="Write every fold's scores here.")] = None,
) -> None:
    """Every way of holding k causes out: each method tuned on the rest, scored on them.

    Compares record-level clustering, the fingerprint baseline and two-stage clustering,
    paired by fold. Prints the mean ARI with its spread across folds, which describes how
    much the answer depends on the causes held out and is not a confidence interval.
    """
    from collections.abc import Sequence

    from mend.cluster.crossval import Clusterer, leave_causes_out, paired, summarise
    from mend.cluster.incidents import cluster_two_stage, tune_two_stage
    from mend.cluster.tune import tune

    gaps = [10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0]
    thresholds = [i / 20 for i in range(1, 20)]

    def record_level(train: Sequence[FailureRecord]) -> Clusterer:
        chosen = tune(train).threshold
        return lambda test: cluster_records(test, threshold=chosen).labels

    def fingerprint_only(train: Sequence[FailureRecord]) -> Clusterer:
        return lambda test: cluster_by_fingerprint(test).labels

    def two_stage(train: Sequence[FailureRecord]) -> Clusterer:
        best, _ = tune_two_stage(train, gaps=gaps, thresholds=thresholds)
        return lambda test: (
            cluster_two_stage(test, gap_s=best.gap_s, threshold=best.threshold).labels
        )

    methods = {
        "record-level": record_level,
        "fingerprint": fingerprint_only,
        "two-stage": two_stage,
    }
    folds = leave_causes_out(_read_records(records_path), methods, k=k)
    for name in methods:
        typer.echo(f"{name:13} ARI {summarise(folds, name).as_value()}")
    difference, wins = paired(folds, "two-stage", "record-level")
    typer.echo(
        f"two-stage minus record-level {difference.as_value()}; "
        f"two-stage higher on {wins} of {len(folds)} folds"
    )
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([{"held_out": f.held_out, "ari": f.ari} for f in folds], indent=1),
            encoding="utf-8",
        )


@cluster_app.command("weights")
def cluster_weights(
    fingerprint: Annotated[float, typer.Option(help="Fingerprint channel weight.")] = 0.4,
    text: Annotated[float, typer.Option(help="Embedding channel weight.")] = 0.3,
    locality: Annotated[float, typer.Option(help="Code-locality channel weight.")] = 0.3,
) -> None:
    """Validate a set of channel weights without running a clustering."""
    weights = ChannelWeights(fingerprint=fingerprint, text=text, locality=locality)
    typer.echo(
        f"fingerprint {weights.fingerprint}, text {weights.text}, locality {weights.locality}"
    )


@app.command()
def roles(
    config: Annotated[Path, typer.Option(help="Gateway configuration.")] = CONFIG_DEFAULT,
) -> None:
    """Resolve the four role aliases and check the different-vendor rule.

    Makes no model call: Gateway.resolve answers from configuration. Exits non-zero when
    the fixer and the reviewer share a provider, so CI can assert the pairing.
    """
    from mend.gateway import PROJECT, SameVendorConfiguration, check_roles, resolve_roles

    try:
        from boundary import Gateway
    except ImportError:
        typer.echo("the gateway (project 04) is not installed; see docs/boundary.md")
        raise typer.Exit(code=2) from None

    with Gateway.from_config(config, project=PROJECT) as gateway:
        resolutions = resolve_roles(gateway)
        for resolution in resolutions.values():
            typer.echo(f"  {resolution}")
        try:
            check_roles(resolutions)
        except SameVendorConfiguration as error:
            typer.echo(f"REFUSED: {error}")
            raise typer.Exit(code=1) from error
    typer.echo("fixer and reviewer are on different vendors")


@app.command()
def ping(
    config: Annotated[Path, typer.Option(help="Gateway configuration.")] = CONFIG_DEFAULT,
) -> None:
    """One short call to each of the four roles, through the gateway, capped and ledgered.

    Proves the keys, the routes and the different-vendor split against what actually
    answers, for well under a cent. The four calls share one run id, so the per-issue cap
    covers them together.
    """
    from datetime import UTC, datetime

    from mend.gateway import Role
    from mend.graph.llm import GatewayClient, HopFailed

    client = GatewayClient.open(config)
    run_id = "ping-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    providers: dict[Role, str] = {}
    try:
        for role in Role:
            try:
                reply = client.ask(
                    role,
                    issue_id=run_id,
                    system="Reply with the single word: ready",
                    # The run id makes every ping a fresh request: an answer from the
                    # development cache would prove nothing about the keys.
                    prompt=f"Are you ready? ({run_id})",
                    max_tokens=2048 if role is Role.REVIEWER else 16,
                )
            except HopFailed as error:
                typer.echo(f"  {role.name.lower()}: FAILED: {error}")
                raise typer.Exit(code=1) from error
            providers[role] = reply.provider
            cost = f"US${reply.cost_usd:.5f}" if reply.cost_usd is not None else "uncosted"
            cached = ", cached" if reply.cached else ""
            typer.echo(
                f"  {role.name.lower()}: {reply.provider}/{reply.model} said "
                f"{reply.text.strip()[:40]!r} ({cost}, {reply.latency_ms:.0f} ms{cached})"
            )
    finally:
        client.close()
    if providers[Role.FIXER] == providers[Role.REVIEWER]:
        typer.echo("REFUSED: the fixer and the reviewer answered from the same vendor")
        raise typer.Exit(code=1)
    typer.echo(f"all four roles answered; fixer and reviewer on different vendors ({run_id})")


@app.command()
def fix(
    tasks: Annotated[Path, typer.Argument(help="SWE-bench JSON or JSONL export.")],
    instance: Annotated[str, typer.Option(help="The instance id to run.")],
    image: Annotated[
        str | None,
        typer.Option(help="Task image. Default: the one the dataset row names."),
    ] = None,
    work: Annotated[
        Path | None,
        typer.Option(help="Where the repository copy goes. Default: outside the repository."),
    ] = None,
    out: Annotated[Path, typer.Option(help="Run log, one JSON line per issue.")] = Path(
        "runs/fix.jsonl"
    ),
    config: Annotated[Path, typer.Option(help="Gateway configuration.")] = CONFIG_DEFAULT,
) -> None:
    """Run one benchmark task through the pipeline, in its sandbox. Needs Docker.

    The task is read through mend.data.swebench, which cannot carry the hidden tests, the
    gold patch or the test directives. Routing is uncalibrated until the validation split
    has run, so nothing auto-proposes.
    """
    from mend.data.swebench import load_tasks
    from mend.graph.context import Deps, Issue
    from mend.graph.graph import run_issue
    from mend.graph.llm import GatewayClient
    from mend.sandbox.runner import docker_available
    from mend.sandbox.runners import runner_for
    from mend.sandbox.workspace import DockerWorkspace

    task = next((t for t in load_tasks(tasks) if t.instance_id == instance), None)
    if task is None:
        typer.echo(f"no task {instance} in {tasks}")
        raise typer.Exit(code=2)
    if not docker_available():
        typer.echo("no Docker daemon answered; the sandbox needs one")
        raise typer.Exit(code=2)

    chosen = image or task.image
    if chosen is None:
        typer.echo(f"{instance} names no image; pass --image")
        raise typer.Exit(code=2)
    from mend.sandbox.batch import WORK_ROOT

    workspace = DockerWorkspace.extract(
        chosen, (work or WORK_ROOT) / instance, tests=runner_for(task.repo)
    )
    client = GatewayClient.open(config)
    try:
        record = run_issue(Issue.from_task(task), Deps(client=client, workspace=workspace))
    finally:
        client.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")
    state = record.state
    typer.echo(
        f"{instance}: {state.stage}" + (f" ({state.stop_reason})" if state.stop_reason else "")
    )
    if state.tier:
        typer.echo(f"  tier {state.tier}, score {state.score:.2f}")
    cost = f"US${record.cost_usd:.4f}" if record.cost_usd is not None else "uncosted"
    typer.echo(f"  {len(record.hops)} model calls, {cost}, {record.duration_s:.0f} s")


@app.command()
def score(
    runs: Annotated[Path, typer.Argument(help="The run log mend fix wrote.")],
    run_id: Annotated[str, typer.Option(help="A name for this scoring run.")],
    workers: Annotated[int, typer.Option(help="Harness workers; at most 3/4 of the cores.")] = 2,
    out_dir: Annotated[
        Path, typer.Option(help="Where predictions, report and outcomes go.")
    ] = Path("runs/score"),
) -> None:
    """Score a run with the official SWE-bench harness, on the hidden tests. Needs Docker
    and the bench extra.

    Submits every drafted patch, whatever its tier, as the source diff alone. A task the
    harness could not judge is reported and must be run again; it is never counted as
    unresolved.
    """
    from dataclasses import asdict

    from mend.eval.results import hit_rate, tier_table
    from mend.sandbox.harness import (
        HarnessIncomplete,
        evaluate,
        outcomes,
        predictions,
        read_runs,
        verdicts,
        write_predictions,
    )

    rows = read_runs(runs)
    preds = predictions(rows)
    target = (out_dir / run_id).resolve()
    target.mkdir(parents=True, exist_ok=True)
    predictions_path = target / "predictions.jsonl"
    write_predictions(preds, predictions_path)
    typer.echo(f"{len(rows)} tasks, {len(preds)} with a drafted patch -> {predictions_path}")

    judged: dict[str, bool | None] = {}
    if preds:
        report = evaluate(
            predictions_path.name,
            run_id=run_id,
            instance_ids=[p["instance_id"] for p in preds],
            workdir=target,
            max_workers=workers,
        )
        judged = verdicts(report)
    try:
        results = outcomes(rows, judged)
    except HarnessIncomplete as error:
        typer.echo(f"INCOMPLETE: {error}")
        raise typer.Exit(code=1) from error

    with (target / "outcomes.jsonl").open("w", encoding="utf-8") as handle:
        for outcome in results:
            handle.write(json.dumps(asdict(outcome)) + "\n")
    typer.echo(f"hit rate on hidden tests: {hit_rate(results).as_percent()}")
    for row in tier_table(results):
        if row.n == 0:
            continue
        wrong = (
            f", confidently wrong {row.confidently_wrong.as_percent()}"
            if row.confidently_wrong is not None and row.confidently_wrong.n
            else ""
        )
        typer.echo(f"  {row.tier}: {row.n} tasks, hit rate {row.hit_rate.as_percent()}{wrong}")


@app.command()
def report(
    outcomes: Annotated[Path, typer.Option(help="The main run's outcomes.")] = Path(
        "results/main/outcomes.jsonl"
    ),
    crossval: Annotated[Path, typer.Option(help="The clustering cross-validation folds.")] = Path(
        "results/chaos09/crossval.json"
    ),
    readme: Annotated[Path, typer.Option(help="The README to fill.")] = Path("README.md"),
) -> None:
    """Write the README's result tables from the committed results, between their markers.

    The only way the tables change. Rerun it after any new result and commit the README
    with the result files it was written from."""
    from mend.eval.report import (
        clustering_table,
        load_folds,
        load_outcomes,
        replace_section,
        resolution_table,
        review_table,
    )

    results = load_outcomes(outcomes)
    folds = load_folds(crossval)
    text = readme.read_text(encoding="utf-8")
    text = replace_section(text, "resolution", resolution_table(results))
    text = replace_section(text, "review", review_table(results))
    text = replace_section(
        text, "clustering", clustering_table(folds, label="09 chaos runs (8 faults, 373 symptoms)")
    )
    readme.write_text(text, encoding="utf-8", newline="\n")
    typer.echo(f"{readme}: tables written from {outcomes} and {crossval}")


@app.command()
def calibrate(
    run_dir: Annotated[
        Path, typer.Argument(help="A finished validation run, e.g. runs/validation.")
    ],
    target: Annotated[float, typer.Option(help="Confidently-wrong target.")] = 0.03,
    out: Annotated[Path, typer.Option(help="The thresholds file.")] = Path(
        "config/mend.thresholds.yaml"
    ),
) -> None:
    """Choose the routing thresholds on a validation run, write them with their provenance,
    and print the trade-off curve. Refuses to overwrite thresholds already chosen."""
    from datetime import UTC, datetime

    from mend.eval.calibration import calibration_rows, curve_table, write_thresholds
    from mend.eval.stats import wilson
    from mend.graph.route import calibrate as choose
    from mend.graph.route import routing_curve
    from mend.sandbox.batch import RunPaths, recorded_runs, recorded_verdicts

    paths = RunPaths(run_dir)
    rows = calibration_rows(recorded_runs(paths).values(), recorded_verdicts(paths))
    thresholds = choose(rows, target_confidently_wrong=target, split_name=run_dir.name)
    chosen = [
        r for r in rows if r.eligible and r.reviewer_agrees and r.score >= thresholds.auto_propose
    ]
    wrong = wilson(sum(1 for r in chosen if not r.resolved), len(chosen))
    write_thresholds(
        thresholds,
        out,
        {
            "run": run_dir.as_posix(),
            "tasks": len(rows),
            "auto_proposed_on_validation": len(chosen),
            "confidently_wrong_on_validation": wrong.as_percent(),
            "calibrated_at": datetime.now(UTC).date().isoformat(),
        },
    )
    typer.echo(
        f"auto-propose at {thresholds.auto_propose:.2f}, suggest at {thresholds.suggest:.2f}, "
        f"target {target:.0%}: {len(chosen)} would auto-propose, confidently wrong "
        f"{wrong.as_percent()} -> {out}"
    )
    typer.echo(curve_table(routing_curve(rows)))


@app.command()
def subset(
    tasks: Annotated[Path, typer.Argument(help="SWE-bench Verified, as JSON or JSONL.")],
    seed: Annotated[int, typer.Option(help="The seed. Recorded in both files.")],
    size: Annotated[int, typer.Option(help="Tasks drawn in all.")] = 150,
    validation: Annotated[int, typer.Option(help="Of those, the validation split.")] = 30,
    out_dir: Annotated[Path, typer.Option(help="Where the two subset files go.")] = Path(
        "data/subset"
    ),
) -> None:
    """Draw the benchmark subset once, stratified by repository, and split it into the
    validation split and the main run. Refuses to overwrite a subset already drawn."""
    from mend.data.swebench import sample, split_validation, write_subset

    all_tasks = load_tasks_or_exit(tasks)
    drawn = sample(
        all_tasks, size=size, seed=seed, source=f"SWE-bench Verified ({len(all_tasks)} tasks)"
    )
    val, main = split_validation(all_tasks, drawn, validation_size=validation)
    write_subset(val, out_dir / "validation.json")
    write_subset(main, out_dir / "main.json")
    typer.echo(f"seed {seed}: {len(val)} validation, {len(main)} main -> {out_dir}")
    for repo, n in main.per_repo.items():
        typer.echo(f"  {repo}: {val.per_repo.get(repo, 0)} validation, {n} main")


def load_tasks_or_exit(path: Path) -> list[Any]:
    from mend.data.swebench import load_tasks

    if not path.is_file():
        typer.echo(f"no dataset at {path}")
        raise typer.Exit(code=2)
    return load_tasks(path)


@app.command("run")
def run_split(
    split: Annotated[
        Path, typer.Argument(help="A committed subset file, e.g. data/subset/validation.json.")
    ],
    tasks: Annotated[Path, typer.Option(help="SWE-bench Verified, as JSON or JSONL.")] = Path(
        "data/swebench/verified.jsonl"
    ),
    name: Annotated[
        str | None, typer.Option(help="Run name. Default: the subset file's name.")
    ] = None,
    config: Annotated[Path, typer.Option(help="Gateway configuration.")] = CONFIG_DEFAULT,
    thresholds_path: Annotated[
        Path, typer.Option("--thresholds", help="Calibrated thresholds, when they exist.")
    ] = Path("config/mend.thresholds.yaml"),
) -> None:
    """Run a committed subset task by task: fix, score on the hidden tests, remove the
    image. Resumable: run it again after a crash and it carries on where it stopped.

    Routes with the calibrated thresholds when the file exists, and refuses to use them
    on the split they were calibrated on; with no file, routing is uncalibrated and
    nothing auto-proposes."""
    from dataclasses import asdict

    from mend.data.swebench import load_subset
    from mend.eval.calibration import load_thresholds
    from mend.eval.results import hit_rate, test_first_rate
    from mend.graph.context import Deps, Issue
    from mend.graph.graph import run_issue
    from mend.graph.llm import GatewayClient
    from mend.sandbox.batch import (
        WORK_ROOT,
        RunPaths,
        recorded_runs,
        recorded_verdicts,
        remove_task,
        run_subset,
        score_one,
    )
    from mend.sandbox.harness import HarnessIncomplete, outcomes
    from mend.sandbox.runner import docker_available
    from mend.sandbox.runners import runner_for
    from mend.sandbox.workspace import DockerWorkspace

    chosen = load_subset(split)
    by_id = {t.instance_id: t for t in load_tasks_or_exit(tasks)}
    run_name = name or split.stem
    paths = RunPaths(Path("runs") / run_name)
    thresholds = load_thresholds(thresholds_path) if thresholds_path.is_file() else None
    if thresholds is not None and thresholds.calibrated_on == run_name:
        typer.echo(
            f"the thresholds in {thresholds_path} were calibrated on {run_name}; routing the "
            "same split with them would report a target met by construction"
        )
        raise typer.Exit(code=2)
    typer.echo(
        f"routing: auto-propose at {thresholds.auto_propose:.2f}, calibrated on "
        f"{thresholds.calibrated_on}"
        if thresholds
        else "routing: uncalibrated, nothing auto-proposes"
    )
    if not docker_available():
        typer.echo("no Docker daemon answered; the sandbox and the harness need one")
        raise typer.Exit(code=2)

    client = GatewayClient.open(config)

    def fix_one(task: Any) -> dict[str, Any]:
        if not task.image:
            raise typer.BadParameter(f"{task.instance_id} names no image")
        workspace = DockerWorkspace.extract(
            task.image, WORK_ROOT / task.instance_id, tests=runner_for(task.repo)
        )
        record = run_issue(
            Issue.from_task(task),
            Deps(client=client, workspace=workspace, thresholds=thresholds),
        )
        loaded: dict[str, Any] = json.loads(record.to_json())
        return loaded

    try:
        run_subset(
            chosen.instance_ids,
            by_id,
            paths,
            fix=fix_one,
            score=lambda run: score_one(run, paths, name=run_name),
            cleanup=remove_task,
            echo=typer.echo,
        )
    finally:
        client.close()

    rows = list(recorded_runs(paths).values())
    try:
        results = outcomes(rows, recorded_verdicts(paths))
    except HarnessIncomplete as error:
        typer.echo(f"INCOMPLETE: {error}; run the same command again")
        raise typer.Exit(code=1) from error
    with (paths.root / "outcomes.jsonl").open("w", encoding="utf-8") as handle:
        for outcome in results:
            handle.write(json.dumps(asdict(outcome)) + "\n")
    typer.echo(f"{run_name}: {len(results)} tasks")
    typer.echo(f"  hit rate on hidden tests  {hit_rate(results).as_percent()}")
    typer.echo(f"  test-first rate           {test_first_rate(results).as_percent()}")


if __name__ == "__main__":  # pragma: no cover
    app()
