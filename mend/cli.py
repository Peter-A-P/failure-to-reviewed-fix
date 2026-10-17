"""The command line.

What is here is what can run today: ingestion, clustering with its metrics, the routing
curve and calibration, and the configuration checks. The hops that call models (localise,
test-first, patch, review) land with the graph wiring; `mend roles` already resolves and
checks the aliases they will use, because a configuration that would refuse to run should
refuse before the build depends on it and not during the first paid run.

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


if __name__ == "__main__":  # pragma: no cover
    app()
