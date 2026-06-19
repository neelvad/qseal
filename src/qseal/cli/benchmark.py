from pathlib import Path

import click
from rich.console import Console

from qseal.benchmark import (
    BenchmarkStatus,
    benchmark_query_pair,
)
from qseal.cli.types import (
    OutputFormat,
)
from qseal.report.json import (
    render_duckdb_benchmark_json,
    render_snowflake_benchmark_json,
)
from qseal.report.text import (
    render_duckdb_benchmark_report,
    render_snowflake_benchmark_report,
)

console = Console()


def _benchmark_snowflake_query_pair(*args, **kwargs):
    # Preserve the historical qseal.cli.benchmark_snowflake_query_pair patch point.
    import qseal.cli as cli

    return cli.benchmark_snowflake_query_pair(*args, **kwargs)


@click.command(name="benchmark")
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("rewritten_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--engine",
    type=click.Choice(("duckdb", "snowflake")),
    default="duckdb",
    show_default=True,
    help="Execution engine used for the benchmark.",
)
@click.option(
    "--database",
    "database_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="DuckDB database file. Defaults to an in-memory database.",
)
@click.option(
    "--setup",
    "setup_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SQL file executed once before plans, warmups, and measurements.",
)
@click.option(
    "--warmups",
    type=click.IntRange(min=0),
    default=2,
    show_default=True,
    help="Warmup executions per query.",
)
@click.option(
    "--repetitions",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="Measured executions per query.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
    help="Per-query timeout in seconds.",
)
@click.option(
    "--threads",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="DuckDB worker threads. Ignored by Snowflake.",
)
@click.option(
    "--minimum-duration-ms",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum duration for each timed execution batch.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write a versioned JSON benchmark artifact to this file.",
)
@click.option(
    "--query-tag",
    help=(
        "Snowflake query tag. Defaults to QSEAL_SNOWFLAKE_QUERY_TAG or "
        "qseal-tier3."
    ),
)
def benchmark(
    original_path: Path,
    rewritten_path: Path,
    engine: str,
    database_path: Path | None,
    setup_path: Path | None,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    minimum_duration_ms: float,
    output_format: str,
    report_file: Path | None,
    query_tag: str | None,
) -> None:
    """Benchmark an original and rewritten query.

    Snowflake mode requires snowflake-connector-python and QSEAL_SNOWFLAKE_*
    credentials.
    """
    if engine == "snowflake":
        result = _benchmark_snowflake_query_pair(
            original_path.read_text(),
            rewritten_path.read_text(),
            setup_sql=setup_path.read_text() if setup_path is not None else None,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            minimum_duration_ms=minimum_duration_ms,
            query_tag=query_tag,
        )
    else:
        result = benchmark_query_pair(
            original_path.read_text(),
            rewritten_path.read_text(),
            database_path=database_path or ":memory:",
            setup_sql=setup_path.read_text() if setup_path is not None else None,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            threads=threads,
            minimum_duration_ms=minimum_duration_ms,
        )

    result = result.model_copy(
        update={
            "inputs": {
                "original_path": str(original_path),
                "rewritten_path": str(rewritten_path),
                "setup_path": str(setup_path) if setup_path is not None else "",
                "engine": engine,
            }
        }
    )
    json_report = (
        render_snowflake_benchmark_json(result)
        if engine == "snowflake"
        else render_duckdb_benchmark_json(result)
    )

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(
            render_snowflake_benchmark_report(result)
            if engine == "snowflake"
            else render_duckdb_benchmark_report(result)
        )

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Report file written: {report_file}", err=True)

    if result.status != BenchmarkStatus.COMPLETED:
        raise click.exceptions.Exit(1)
