from pathlib import Path

import click
from rich.console import Console

from qseal.cli.common import (
    _load_constraints,
)
from qseal.cli.types import (
    DialectChoice,
    OutputFormat,
    RuleChoice,
    SchemaFormat,
)
from qseal.dialects import DEFAULT_DIALECT
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.report.json import (
    render_rewrite_chain_json,
    render_suggestion_json,
    render_suggestions_json,
)
from qseal.report.text import (
    render_rewrite_chain_report,
    render_suggestion_report,
    render_suggestions_report,
)
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.rewrites.chain import suggest_rewrite_chain
from qseal.rewrites.distinct import RemoveRedundantDistinct
from qseal.rewrites.registry import (
    first_applicable_suggestion,
    select_rules,
    suggest_rewrites,
)
from qseal.rewrites.subtree import suggest_subtree_rewrites

console = Console()

@click.command(name="suggest")
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
    "--chain",
    "show_chain",
    is_flag=True,
    help="Repeatedly apply verified rewrites until a fixed point is reached.",
)
@click.option(
    "--max-steps",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Maximum verified rewrite steps when --chain is enabled.",
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
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse and render the query.",
)
def suggest(
    query_path: Path,
    schema_path: Path,
    schema_format: str,
    show_all: bool,
    show_chain: bool,
    max_steps: int,
    selected_rules: tuple[str, ...],
    output_format: str,
    dialect: str,
) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    constraints = _load_constraints(schema_path, schema_format)
    rules = select_rules(selected_rules)
    if show_chain:
        if show_all:
            raise click.ClickException("--chain cannot be combined with --all.")
        chain = suggest_rewrite_chain(
            raw_sql,
            constraints,
            rules=rules,
            dialect=dialect,
            max_steps=max_steps,
        )
        if output_format == "json":
            click.echo(render_rewrite_chain_json(chain, dialect=dialect))
        else:
            console.print(render_rewrite_chain_report(chain))
        return

    try:
        query = parse_select(raw_sql, dialect=dialect)
        suggestions = suggest_rewrites(query, constraints, rules=rules)
    except UnsupportedSqlError as error:
        suggestions = suggest_subtree_rewrites(
            raw_sql,
            constraints,
            rules=rules,
            dialect=dialect,
        ) or [
            RewriteSuggestion(
                rule_name=RemoveRedundantDistinct.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=raw_sql.strip(),
                reason=str(error),
            )
        ]

    if show_all:
        if output_format == "json":
            click.echo(render_suggestions_json(suggestions, dialect=dialect))
        else:
            console.print(render_suggestions_report(suggestions))
        return

    suggestion = first_applicable_suggestion(suggestions)
    if output_format == "json":
        click.echo(render_suggestion_json(suggestion, dialect=dialect))
    else:
        console.print(render_suggestion_report(suggestion))
