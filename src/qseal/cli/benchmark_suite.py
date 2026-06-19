from pathlib import Path

import click
from rich.console import Console

from qseal.benchmark import (
    run_snowflake_dbt_demo_suite,
    run_snowflake_family_suite,
)
from qseal.cli.types import (
    OutputFormat,
)
from qseal.report.json import (
    render_snowflake_family_suite_json,
)
from qseal.report.text import (
    render_snowflake_family_suite_report,
)

console = Console()

@click.group(name="benchmark-suite")
def benchmark_suite_group() -> None:
    """Run repeatable benchmark suites."""


@benchmark_suite_group.command(name="snowflake-family")
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--scale",
    "scales",
    multiple=True,
    type=click.IntRange(min=1),
    default=(1_000_000,),
    show_default=True,
    help="User-table row scale. May be repeated; order tables use 2x this value.",
)
@click.option(
    "--mode",
    "modes",
    multiple=True,
    type=click.Choice(("aggregate", "materialized"), case_sensitive=False),
    default=("aggregate",),
    show_default=True,
    help="Benchmark query shape. May be repeated.",
)
@click.option("--runs", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--warmups", type=click.IntRange(min=0), default=1, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
    help="Per-query timeout in seconds.",
)
@click.option(
    "--minimum-duration-ms",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum duration for each timed execution batch.",
)
@click.option(
    "--materialized-limit",
    type=click.IntRange(min=1),
    default=10_000,
    show_default=True,
    help="Rows returned by each bounded materialized-output query.",
)
@click.option(
    "--query-tag-prefix",
    default="qseal-tier3-family",
    show_default=True,
    help="Prefix for Snowflake query tags; case/run identifiers are appended.",
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
    help="Write the suite JSON artifact here. Defaults to OUTPUT_DIR/snowflake-family-suite.json.",
)
@click.option(
    "--allow-existing",
    is_flag=True,
    help="Allow writing into a non-empty output directory.",
)
def snowflake_family_benchmark_suite(
    output_dir: Path,
    scales: tuple[int, ...],
    modes: tuple[str, ...],
    runs: int,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
    materialized_limit: int,
    query_tag_prefix: str,
    output_format: str,
    report_file: Path | None,
    allow_existing: bool,
) -> None:
    """Run the repeatable Snowflake Tier-3 rewrite-family benchmark suite.

    Requires snowflake-connector-python and QSEAL_SNOWFLAKE_* credentials.
    """
    if output_dir.exists() and any(output_dir.iterdir()) and not allow_existing:
        raise click.ClickException(
            f"Output directory is not empty: {output_dir}. "
            "Pass --allow-existing to append/overwrite suite files."
        )

    try:
        report = run_snowflake_family_suite(
            output_dir,
            scales=scales,
            modes=modes,
            runs=runs,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            minimum_duration_ms=minimum_duration_ms,
            materialized_limit=materialized_limit,
            query_tag_prefix=query_tag_prefix,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    json_report = render_snowflake_family_suite_json(report)
    report_path = report_file or output_dir / "snowflake-family-suite.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(f"{json_report}\n")

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(render_snowflake_family_suite_report(report))
    click.echo(f"Suite report written: {report_path}", err=True)

    if report.completed_count != report.result_count:
        raise click.exceptions.Exit(1)


@benchmark_suite_group.command(name="snowflake-dbt-demo")
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--scale",
    "scales",
    multiple=True,
    type=click.IntRange(min=1),
    default=(1_000_000,),
    show_default=True,
    help="dim_users row scale. The stg_orders table uses 2x this value.",
)
@click.option(
    "--mode",
    "modes",
    multiple=True,
    type=click.Choice(("aggregate", "materialized"), case_sensitive=False),
    default=("materialized",),
    show_default=True,
    help="Benchmark query shape. May be repeated.",
)
@click.option("--runs", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--warmups", type=click.IntRange(min=0), default=1, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
    help="Per-query timeout in seconds.",
)
@click.option(
    "--minimum-duration-ms",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum duration for each timed execution batch.",
)
@click.option(
    "--materialized-limit",
    type=click.IntRange(min=1),
    default=10_000,
    show_default=True,
    help="Rows returned by each bounded materialized-output query.",
)
@click.option(
    "--query-tag-prefix",
    default="qseal-tier3-dbt-demo",
    show_default=True,
    help="Prefix for Snowflake query tags; case/run identifiers are appended.",
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
    help=(
        "Write the suite JSON artifact here. Defaults to "
        "OUTPUT_DIR/snowflake-dbt-demo-suite.json."
    ),
)
@click.option(
    "--allow-existing",
    is_flag=True,
    help="Allow writing into a non-empty output directory.",
)
def snowflake_dbt_demo_benchmark_suite(
    output_dir: Path,
    scales: tuple[int, ...],
    modes: tuple[str, ...],
    runs: int,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
    materialized_limit: int,
    query_tag_prefix: str,
    output_format: str,
    report_file: Path | None,
    allow_existing: bool,
) -> None:
    """Run the Snowflake Tier-3 dbt join-elimination demo benchmark.

    Requires snowflake-connector-python and QSEAL_SNOWFLAKE_* credentials.
    """
    if output_dir.exists() and any(output_dir.iterdir()) and not allow_existing:
        raise click.ClickException(
            f"Output directory is not empty: {output_dir}. "
            "Pass --allow-existing to append/overwrite suite files."
        )

    try:
        report = run_snowflake_dbt_demo_suite(
            output_dir,
            scales=scales,
            modes=modes,
            runs=runs,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            minimum_duration_ms=minimum_duration_ms,
            materialized_limit=materialized_limit,
            query_tag_prefix=query_tag_prefix,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    json_report = render_snowflake_family_suite_json(report)
    report_path = report_file or output_dir / "snowflake-dbt-demo-suite.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(f"{json_report}\n")

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(render_snowflake_family_suite_report(report))
    click.echo(f"Suite report written: {report_path}", err=True)

    if report.completed_count != report.result_count:
        raise click.exceptions.Exit(1)
