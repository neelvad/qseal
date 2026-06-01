from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.yaml_loader import load_constraints
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.text import render_suggestion_report, render_verification_report
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin
from snowprove.rewrites.predicate_pushdown import PredicatePushdown
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
def suggest(query_path: Path, schema_path: Path) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql)
        constraints = load_constraints(schema_path)
        suggestion = _first_applicable_suggestion(
            [
                RemoveUnusedLeftJoin().apply(query, constraints),
                RemoveRedundantDistinct().apply(query, constraints),
                PredicatePushdown().apply(query, constraints),
            ]
        )
    except UnsupportedSqlError as error:
        suggestion = RewriteSuggestion(
            rule_name=RemoveRedundantDistinct.rule_name,
            status=VerificationStatus.UNSUPPORTED,
            original_sql=raw_sql.strip(),
            reason=str(error),
        )

    console.print(render_suggestion_report(suggestion))


def _first_applicable_suggestion(suggestions: list[RewriteSuggestion]) -> RewriteSuggestion:
    for suggestion in suggestions:
        if suggestion.status != VerificationStatus.NOT_APPLICABLE:
            return suggestion
    return suggestions[0]


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
