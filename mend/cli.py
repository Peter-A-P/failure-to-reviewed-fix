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
from typing import Annotated

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
                    prompt="Are you ready?",
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
        typer.Option(help="Task image. Default: the harness's local name for the instance."),
    ] = None,
    work: Annotated[Path, typer.Option(help="Where the repository copy goes.")] = Path(
        "sandbox/work"
    ),
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
    from mend.sandbox.workspace import DockerWorkspace

    task = next((t for t in load_tasks(tasks) if t.instance_id == instance), None)
    if task is None:
        typer.echo(f"no task {instance} in {tasks}")
        raise typer.Exit(code=2)
    if not docker_available():
        typer.echo("no Docker daemon answered; the sandbox needs one")
        raise typer.Exit(code=2)

    workspace = DockerWorkspace.extract(
        image or f"sweb.eval.x86_64.{instance}:latest", work / instance
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


if __name__ == "__main__":  # pragma: no cover
    app()
