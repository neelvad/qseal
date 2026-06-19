from pathlib import Path

import click
from rich.console import Console

from qseal.cli.types import (
    OutputFormat,
)
from qseal.fixtures import DuckDbFixtureSpec, create_duckdb_fixture
from qseal.report.json import (
    render_duckdb_fixture_json,
)
from qseal.report.text import (
    render_duckdb_fixture_report,
)

console = Console()

@click.group(name="fixtures")
def fixtures_group() -> None:
    """Create reproducible benchmark data."""


@fixtures_group.command(name="create")
@click.argument("database_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Manifest output path. Defaults beside the database.",
)
@click.option("--seed", type=int, default=1, show_default=True)
@click.option("--users", "user_rows", type=click.IntRange(min=1), default=10_000, show_default=True)
@click.option(
    "--orders",
    "order_rows",
    type=click.IntRange(min=1),
    default=100_000,
    show_default=True,
)
@click.option(
    "--events",
    "event_rows",
    type=click.IntRange(min=1),
    default=50_000,
    show_default=True,
)
@click.option(
    "--active-fraction",
    type=click.FloatRange(min=0, max=1),
    default=0.2,
    show_default=True,
)
@click.option(
    "--null-fraction",
    type=click.FloatRange(min=0, max=1),
    default=0.1,
    show_default=True,
)
@click.option(
    "--duplicate-fraction",
    type=click.FloatRange(min=0, max=1, max_open=True),
    default=0.25,
    show_default=True,
)
@click.option(
    "--skew-fraction",
    type=click.FloatRange(min=0, max=1),
    default=0.8,
    show_default=True,
)
@click.option(
    "--segments",
    "segment_count",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
)
@click.option("--force", is_flag=True, help="Replace existing database and manifest files.")
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
def fixtures_create(
    database_path: Path,
    manifest_path: Path | None,
    seed: int,
    user_rows: int,
    order_rows: int,
    event_rows: int,
    active_fraction: float,
    null_fraction: float,
    duplicate_fraction: float,
    skew_fraction: float,
    segment_count: int,
    force: bool,
    output_format: str,
) -> None:
    """Create one seeded DuckDB benchmark fixture."""
    try:
        manifest = create_duckdb_fixture(
            database_path,
            manifest_path=manifest_path,
            force=force,
            spec=DuckDbFixtureSpec(
                seed=seed,
                user_rows=user_rows,
                order_rows=order_rows,
                event_rows=event_rows,
                active_fraction=active_fraction,
                null_fraction=null_fraction,
                duplicate_fraction=duplicate_fraction,
                skew_fraction=skew_fraction,
                segment_count=segment_count,
            ),
        )
    except (FileExistsError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(render_duckdb_fixture_json(manifest))
    else:
        console.print(render_duckdb_fixture_report(manifest))
