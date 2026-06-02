from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.loader import load_constraint_catalog
from snowprove.dbt.project import DbtProjectDiscoveryError, discover_compiled_sql_path
from snowprove.dbt.scan import scan_dbt_project
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.json import (
    render_dbt_scan_json,
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
from snowprove.report.text import (
    render_dbt_scan_diff_report,
    render_dbt_scan_report,
    render_suggestion_report,
    render_suggestions_report,
    render_verification_report,
)
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.registry import (
    first_applicable_suggestion,
    rule_names,
    select_rules,
    suggest_rewrites,
)
from snowprove.verifier.check import check_equivalence
from snowprove.verifier.model import VerificationResult

console = Console()

OutputFormat = click.Choice(["text", "json"], case_sensitive=False)
SchemaFormat = click.Choice(["auto", "snowprove", "dbt"], case_sensitive=False)
RuleChoice = click.Choice(rule_names(), case_sensitive=False)
FailOn = click.Choice(["none", "findings"], case_sensitive=False)


@click.group()
def main() -> None:
    """Verified-safe SQL rewrites for a constrained Snowflake SQL subset."""


@main.group(name="dbt")
def dbt_group() -> None:
    """dbt project workflows."""


@dbt_group.command(name="scan")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show unknown and unsupported scan results in addition to proven rewrites.",
)
@click.option(
    "--rule",
    "selected_rules",
    multiple=True,
    type=RuleChoice,
    help="Only run a specific rewrite rule. Can be passed more than once.",
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
    "--diff",
    "show_diff",
    is_flag=True,
    help="Print unified diffs for proven rewrites instead of the normal scan report.",
)
@click.option(
    "--fail-on",
    type=FailOn,
    default="none",
    show_default=True,
    help="Exit nonzero only for the selected proven-result policy.",
)
@click.option(
    "--compiled-dir",
    "compiled_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing compiled dbt SQL files to scan instead of models/ SQL.",
)
@click.option(
    "--use-compiled",
    is_flag=True,
    help="Auto-discover and scan compiled SQL under target/compiled/.",
)
def dbt_scan(
    project_path: Path,
    show_all: bool,
    selected_rules: tuple[str, ...],
    output_format: str,
    show_diff: bool,
    fail_on: str,
    compiled_path: Path | None,
    use_compiled: bool,
) -> None:
    """Scan dbt model SQL files for verified rewrite opportunities."""
    if show_diff and output_format == "json":
        raise click.ClickException("--diff is only supported with --format text.")
    if compiled_path is not None and use_compiled:
        raise click.ClickException("--compiled-dir and --use-compiled cannot be used together.")

    try:
        if use_compiled:
            compiled_path = discover_compiled_sql_path(project_path)
        result = scan_dbt_project(
            project_path,
            rules=select_rules(selected_rules),
            include_all=show_all,
            compiled_path=compiled_path,
        )
    except DbtProjectDiscoveryError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(render_dbt_scan_json(result))
    elif show_diff:
        click.echo(render_dbt_scan_diff_report(result))
    else:
        console.print(render_dbt_scan_report(result))

    if fail_on == "findings" and result.has_proven_findings():
        raise click.exceptions.Exit(1)


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
    default="auto",
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
    "--rule",
    "selected_rules",
    multiple=True,
    type=RuleChoice,
    help="Only run a specific rewrite rule. Can be passed more than once.",
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
    selected_rules: tuple[str, ...],
    output_format: str,
) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql)
        constraints = _load_constraints(schema_path, schema_format)
        suggestions = suggest_rewrites(query, constraints, rules=select_rules(selected_rules))
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
    default="auto",
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
    return load_constraint_catalog(path, schema_format)
