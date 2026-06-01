from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.yaml_loader import load_constraints
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.text import render_suggestion_report, render_verification_report
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.verifier.check import check_equivalence

console = Console()


@click.group()
def main() -> None:
    """Verified-safe SQL rewrites for a constrained Snowflake SQL subset."""


@main.command()
@click.argument("query_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML file containing trusted schema constraints.",
)
def suggest(query_path: Path, schema_path: Path) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    try:
        query = parse_select(query_path.read_text())
        constraints = load_constraints(schema_path)
        suggestion = RemoveRedundantDistinct().apply(query, constraints)
    except UnsupportedSqlError as error:
        raise click.ClickException(str(error)) from error

    console.print(render_suggestion_report(suggestion))


@main.command()
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("rewritten_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML file containing trusted schema constraints.",
)
def check(original_path: Path, rewritten_path: Path, schema_path: Path) -> None:
    """Check whether two supported SQL queries are equivalent."""
    try:
        original = parse_select(original_path.read_text())
        rewritten = parse_select(rewritten_path.read_text())
        constraints = load_constraints(schema_path)
    except UnsupportedSqlError as error:
        raise click.ClickException(str(error)) from error

    result = check_equivalence(original, rewritten, constraints)
    console.print(render_verification_report(result))
