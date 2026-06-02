from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.dbt_loader import load_dbt_constraints
from snowprove.constraints.yaml_loader import load_constraints
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.json import (
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
from snowprove.report.text import (
    render_suggestion_report,
    render_suggestions_report,
    render_verification_report,
)
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.registry import first_applicable_suggestion, suggest_rewrites
from snowprove.verifier.check import check_equivalence
from snowprove.verifier.model import VerificationResult

console = Console()

OutputFormat = click.Choice(["text", "json"], case_sensitive=False)
SchemaFormat = click.Choice(["snowprove", "dbt"], case_sensitive=False)


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
@click.option(
    "--schema-format",
    type=SchemaFormat,
    default="snowprove",
    show_default=True,
    help="Schema constraint format.",
)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show every applicable rewrite result instead of only the first.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
def suggest(
    query_path: Path,
    schema_path: Path,
    schema_format: str,
    show_all: bool,
    output_format: str,
) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql)
        constraints = _load_constraints(schema_path, schema_format)
        suggestions = suggest_rewrites(query, constraints)
    except UnsupportedSqlError as error:
        suggestions = [
            RewriteSuggestion(
                rule_name=RemoveRedundantDistinct.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=raw_sql.strip(),
                reason=str(error),
            )
        ]

    if show_all:
        if output_format == "json":
            click.echo(render_suggestions_json(suggestions))
        else:
            console.print(render_suggestions_report(suggestions))
        return

    suggestion = first_applicable_suggestion(suggestions)
    if output_format == "json":
        click.echo(render_suggestion_json(suggestion))
    else:
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
@click.option(
    "--schema-format",
    type=SchemaFormat,
    default="snowprove",
    show_default=True,
    help="Schema constraint format.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
def check(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
    output_format: str,
) -> None:
    """Check whether two supported SQL queries are equivalent."""
    original_sql = original_path.read_text()
    rewritten_sql = rewritten_path.read_text()

    try:
        original = parse_select(original_sql)
    except UnsupportedSqlError as error:
        result = VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=original_sql.strip(),
            rewritten_sql=rewritten_sql.strip(),
            reason=f"Original query unsupported: {error}",
        )
        _print_verification(result, output_format)
        return

    try:
        rewritten = parse_select(rewritten_sql)
    except UnsupportedSqlError as error:
        result = VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=original_sql.strip(),
            rewritten_sql=rewritten_sql.strip(),
            reason=f"Rewritten query unsupported: {error}",
        )
        _print_verification(result, output_format)
        return

    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    result = check_equivalence(original, rewritten, constraints)
    _print_verification(result, output_format)


def _print_verification(result: VerificationResult, output_format: str) -> None:
    if output_format == "json":
        click.echo(render_verification_json(result))
    else:
        console.print(render_verification_report(result))


def _load_constraints(path: Path, schema_format: str):
    if schema_format == "dbt":
        return load_dbt_constraints(path)
    return load_constraints(path)
