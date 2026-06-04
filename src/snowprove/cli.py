from pathlib import Path

import click
from rich.console import Console

from snowprove.constraints.loader import load_constraint_catalog
from snowprove.dbt.project import DbtProjectDiscoveryError, discover_compiled_sql_path
from snowprove.dbt.scan import scan_dbt_project
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.json import (
    render_candidate_generation_json,
    render_candidate_verifications_json,
    render_dbt_scan_json,
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
from snowprove.report.patch import apply_dbt_scan_patches, write_dbt_scan_patch_results
from snowprove.report.text import (
    render_candidate_verifications_report,
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
from snowprove.verifier.backends import get_verifier_backend
from snowprove.verifier.model import VerificationResult

console = Console()

OutputFormat = click.Choice(["text", "json"], case_sensitive=False)
SchemaFormat = click.Choice(["auto", "snowprove", "dbt"], case_sensitive=False)
RuleChoice = click.Choice(rule_names(), case_sensitive=False)
FailOn = click.Choice(["none", "findings"], case_sensitive=False)
CheckFailOn = click.Choice(["none", "unproven"], case_sensitive=False)
VerifierChoice = click.Choice(["builtin", "external", "sqlsolver"], case_sensitive=False)


@click.group()
def main() -> None:
    """Verified-safe SQL rewrites for a constrained Snowflake SQL subset."""


@main.group(name="dbt")
def dbt_group() -> None:
    """dbt project workflows."""


@main.group(name="candidates")
def candidates_group() -> None:
    """Generate and verify candidate rewrites."""


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
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write a versioned JSON scan artifact to this file.",
)
@click.option(
    "--compiled-dir",
    "compiled_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing compiled dbt SQL files to scan instead of models/ SQL.",
)
@click.option(
    "--write-patches",
    "patch_dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Write unified diff patch files for proven rewrites to this directory.",
)
@click.option(
    "--apply-patches",
    is_flag=True,
    help="Apply proven rewrites directly to model SQL files.",
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
    report_file: Path | None,
    compiled_path: Path | None,
    patch_dir: Path | None,
    apply_patches: bool,
    use_compiled: bool,
) -> None:
    """Scan dbt model SQL files for verified rewrite opportunities."""
    if show_diff and output_format == "json":
        raise click.ClickException("--diff is only supported with --format text.")
    if patch_dir is not None and output_format == "json":
        raise click.ClickException("--write-patches is only supported with --format text.")
    if apply_patches and output_format == "json":
        raise click.ClickException("--apply-patches is only supported with --format text.")
    if apply_patches and show_all:
        raise click.ClickException("--apply-patches cannot be used with --all.")
    if apply_patches and patch_dir is not None:
        raise click.ClickException("--apply-patches and --write-patches cannot be used together.")
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

    patch_results = ()
    if patch_dir is not None:
        patch_results = write_dbt_scan_patch_results(result, patch_dir)

    json_report = render_dbt_scan_json(result, patch_results=patch_results)

    if output_format == "json":
        click.echo(json_report)
    elif show_diff:
        click.echo(render_dbt_scan_diff_report(result))
    else:
        console.print(render_dbt_scan_report(result))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Report file written: {report_file}", err=True)

    if patch_dir is not None:
        console.print(f"Patch files written: {len(patch_results)}")
        for patch in patch_results:
            console.print(f"  {patch.path}")

    if apply_patches:
        applied = apply_dbt_scan_patches(result)
        applied_count = sum(1 for item in applied if item.applied)
        skipped = tuple(item for item in applied if not item.applied)
        console.print(f"Patches applied: {applied_count}")
        for item in applied:
            if item.applied:
                console.print(f"  {item.path} ({item.rule_name})")
            else:
                console.print(f"  skipped {item.path} ({item.rule_name}): {item.reason}")
        if skipped:
            raise click.ClickException("Some proven rewrites could not be applied.")

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


@candidates_group.command(name="generate")
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
    "--out",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where candidate SQL files will be written.",
)
@click.option(
    "--all",
    "include_all",
    is_flag=True,
    help="Write every rule result that contains rewritten SQL, not only proven rewrites.",
)
@click.option(
    "--rule",
    "selected_rules",
    multiple=True,
    type=RuleChoice,
    help="Only run a specific rewrite rule. Can be passed more than once.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing candidate files.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
def candidates_generate(
    query_path: Path,
    schema_path: Path,
    schema_format: str,
    output_dir: Path,
    include_all: bool,
    selected_rules: tuple[str, ...],
    force: bool,
    output_format: str,
) -> None:
    """Generate candidate SQL files from Snowprove's rewrite rules."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql)
        constraints = _load_constraints(schema_path, schema_format)
        suggestions = suggest_rewrites(query, constraints, rules=select_rules(selected_rules))
    except (UnsupportedSqlError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    visible = _candidate_suggestions(suggestions, include_all)

    for index, suggestion in enumerate(visible, start=1):
        if suggestion.rewritten_sql is None:
            skipped.append(
                {
                    "rule_name": suggestion.rule_name,
                    "status": suggestion.status.value,
                    "reason": suggestion.reason or "No rewritten SQL was produced.",
                }
            )
            continue

        candidate_path = output_dir / f"{index:03d}_{_safe_filename(suggestion.rule_name)}.sql"
        if candidate_path.exists() and not force:
            raise click.ClickException(
                f"Candidate file already exists: {candidate_path}. Use --force to overwrite."
            )

        candidate_path.write_text(f"{suggestion.rewritten_sql.strip()}\n")
        generated.append(
            {
                "path": str(candidate_path),
                "rule_name": suggestion.rule_name,
                "status": suggestion.status.value,
            }
        )

    if output_format == "json":
        click.echo(
            render_candidate_generation_json(
                original_path=str(query_path),
                output_dir=str(output_dir),
                generated=generated,
                skipped=skipped,
            )
        )
        return

    console.print(f"Candidates generated: {len(generated)}")
    console.print(f"Skipped: {len(skipped)}")
    for item in generated:
        console.print(f"  {item['path']} ({item['rule_name']}, {item['status']})")
    for item in skipped:
        console.print(f"  skipped {item['rule_name']} ({item['status']}): {item['reason']}")


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
@click.option(
    "--fail-on",
    type=CheckFailOn,
    default="none",
    show_default=True,
    help="Exit nonzero when the verification does not satisfy the selected policy.",
)
@click.option(
    "--verifier",
    type=VerifierChoice,
    default="builtin",
    show_default=True,
    help="Verifier backend.",
)
@click.option(
    "--solver-command",
    help="External verifier command to use with --verifier external.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    help="External verifier timeout in seconds.",
)
def check(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
    output_format: str,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
) -> None:
    """Check whether two supported SQL queries are equivalent."""
    original_sql = original_path.read_text()
    rewritten_sql = rewritten_path.read_text()

    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    result = get_verifier_backend(
        verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
    ).verify(
        original_sql,
        rewritten_sql,
        constraints,
    )
    result = result.model_copy(
        update={
            "inputs": _verification_inputs(
                original_path,
                rewritten_path,
                schema_path,
                schema_format,
            )
        }
    )
    _print_verification(result, output_format, fail_on)


@candidates_group.command(name="check")
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument(
    "candidate_paths",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
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
@click.option(
    "--fail-on",
    type=CheckFailOn,
    default="none",
    show_default=True,
    help="Exit nonzero when any candidate verification does not satisfy the selected policy.",
)
@click.option(
    "--verifier",
    type=VerifierChoice,
    default="builtin",
    show_default=True,
    help="Verifier backend.",
)
@click.option(
    "--solver-command",
    help="External verifier command to use with --verifier external.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    help="External verifier timeout in seconds.",
)
def candidates_check(
    original_path: Path,
    candidate_paths: tuple[Path, ...],
    schema_path: Path,
    schema_format: str,
    output_format: str,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
) -> None:
    """Check generated candidate SQL files against one original query."""
    original_sql = original_path.read_text()

    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    backend = get_verifier_backend(
        verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
    )
    results = [
        backend.verify(original_sql, candidate_path.read_text(), constraints).model_copy(
            update={
                "inputs": _verification_inputs(
                    original_path,
                    candidate_path,
                    schema_path,
                    schema_format,
                )
            }
        )
        for candidate_path in candidate_paths
    ]

    if output_format == "json":
        click.echo(render_candidate_verifications_json(results))
    else:
        console.print(render_candidate_verifications_report(results))

    if fail_on == "unproven" and any(
        result.status != VerificationStatus.PROVEN_EQUIVALENT for result in results
    ):
        raise click.exceptions.Exit(1)


def _print_verification(result: VerificationResult, output_format: str, fail_on: str) -> None:
    if output_format == "json":
        click.echo(render_verification_json(result))
    else:
        console.print(render_verification_report(result))

    if fail_on == "unproven" and result.status != VerificationStatus.PROVEN_EQUIVALENT:
        raise click.exceptions.Exit(1)


def _verification_inputs(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
) -> dict[str, str]:
    return {
        "original_path": str(original_path),
        "rewritten_path": str(rewritten_path),
        "schema_path": str(schema_path),
        "schema_format": schema_format,
    }


def _load_constraints(path: Path, schema_format: str):
    return load_constraint_catalog(path, schema_format)


def _candidate_suggestions(
    suggestions: list[RewriteSuggestion],
    include_all: bool,
) -> list[RewriteSuggestion]:
    if include_all:
        return [
            suggestion
            for suggestion in suggestions
            if suggestion.status != VerificationStatus.NOT_APPLICABLE
        ]
    return [
        suggestion
        for suggestion in suggestions
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    ]


def _safe_filename(value: str) -> str:
    return "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value
    )
