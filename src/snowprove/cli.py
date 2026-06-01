from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.yaml_loader import load_constraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.report.text import render_suggestion_report
from snowprove.rewrites.distinct import RemoveRedundantDistinct

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
    query = parse_select(query_path.read_text())
    constraints = load_constraints(schema_path)
    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    console.print(render_suggestion_report(suggestion))
