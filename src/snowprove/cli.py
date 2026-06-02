from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.yaml_loader import load_constraints
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
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
    "--all",
    "show_all",
    is_flag=True,
    help="Show every applicable rewrite result instead of only the first.",
)
def suggest(query_path: Path, schema_path: Path, show_all: bool) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql)
        constraints = load_constraints(schema_path)
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
        console.print(render_suggestions_report(suggestions))
    else:
        console.print(render_suggestion_report(first_applicable_suggestion(suggestions)))


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
        console.print(render_verification_report(result))
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
        console.print(render_verification_report(result))
        return

    try:
        constraints = load_constraints(schema_path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    result = check_equivalence(original, rewritten, constraints)
    console.print(render_verification_report(result))
