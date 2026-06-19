from pathlib import Path

import click
from rich.console import Console

from qseal.candidates.bundle import load_candidate_metadata
from qseal.candidates.evidence import build_candidate_evidence
from qseal.cli.common import (
    _candidate_generation_payload,
    _load_constraints,
    _resolve_candidate_paths,
    _verify_candidates,
    _write_candidate_suggestions,
)
from qseal.cli.types import (
    CheckFailOn,
    DialectChoice,
    OutputFormat,
    RuleChoice,
    SchemaFormat,
    VerifierChoice,
)
from qseal.dialects import DEFAULT_DIALECT
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.report.json import (
    render_candidate_evidence_json,
    render_candidate_generation_json,
    render_candidate_run_json,
    render_candidate_verifications_json,
)
from qseal.report.text import (
    render_candidate_evidence_report,
    render_candidate_verifications_report,
)
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.registry import (
    select_rules,
    suggest_rewrites,
)

console = Console()

@click.group(name="candidates")
def candidates_group() -> None:
    """Generate and verify candidate rewrites."""


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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse and render the query.",
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
    dialect: str,
) -> None:
    """Generate candidate SQL files from QuerySeal's rewrite rules."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql, dialect=dialect)
        constraints = _load_constraints(schema_path, schema_format)
        suggestions = suggest_rewrites(query, constraints, rules=select_rules(selected_rules))
    except (UnsupportedSqlError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    generated, skipped = _write_candidate_suggestions(
        suggestions,
        output_dir,
        include_all=include_all,
        force=force,
    )

    if output_format == "json":
        click.echo(
            render_candidate_generation_json(
                original_path=str(query_path),
                output_dir=str(output_dir),
                generated=generated,
                skipped=skipped,
                dialect=dialect,
            )
        )
        return

    console.print(f"Candidates generated: {len(generated)}")
    console.print(f"Skipped: {len(skipped)}")
    for item in generated:
        console.print(f"  {item['path']} ({item['rule_name']}, {item['status']})")
    for item in skipped:
        console.print(f"  skipped {item['rule_name']} ({item['status']}): {item['reason']}")


@candidates_group.command(name="run")
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
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write a versioned JSON candidate-run artifact to this file.",
)
@click.option(
    "--fail-on",
    type=CheckFailOn,
    default="none",
    show_default=True,
    help="Exit nonzero when candidate verification does not satisfy the selected policy.",
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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used for generation and verification.",
)
def candidates_run(
    query_path: Path,
    schema_path: Path,
    schema_format: str,
    output_dir: Path,
    include_all: bool,
    selected_rules: tuple[str, ...],
    force: bool,
    output_format: str,
    report_file: Path | None,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> None:
    """Generate candidate SQL files and verify them in one command."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql, dialect=dialect)
        constraints = _load_constraints(schema_path, schema_format)
        suggestions = suggest_rewrites(query, constraints, rules=select_rules(selected_rules))
    except (UnsupportedSqlError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    generated, skipped = _write_candidate_suggestions(
        suggestions,
        output_dir,
        include_all=include_all,
        force=force,
    )
    candidate_paths = [Path(item["path"]) for item in generated]
    results = _verify_candidates(
        query_path,
        raw_sql,
        candidate_paths,
        schema_path,
        schema_format,
        constraints,
        verifier=verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
        dialect=dialect,
    )
    generation = _candidate_generation_payload(
        query_path,
        output_dir,
        generated,
        skipped,
        dialect,
    )
    json_report = render_candidate_run_json(
        generation=generation,
        verifications=results,
        dialect=dialect,
    )

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(f"Candidates generated: {len(generated)}")
        console.print(f"Skipped: {len(skipped)}")
        for item in generated:
            console.print(f"  {item['path']} ({item['rule_name']}, {item['status']})")
        for item in skipped:
            console.print(f"  skipped {item['rule_name']} ({item['status']}): {item['reason']}")
        console.print("")
        console.print(render_candidate_verifications_report(results))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Report file written: {report_file}", err=True)

    if fail_on == "unproven" and (
        not results
        or any(result.status != VerificationStatus.PROVEN_EQUIVALENT for result in results)
    ):
        raise click.exceptions.Exit(1)


@candidates_group.command(name="check")
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument(
    "candidate_paths",
    nargs=-1,
    required=False,
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
    "--candidates-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing candidate .sql files to verify.",
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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used for verification.",
)
def candidates_check(
    original_path: Path,
    candidate_paths: tuple[Path, ...],
    schema_path: Path,
    schema_format: str,
    output_format: str,
    candidates_dir: Path | None,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> None:
    """Check generated candidate SQL files against one original query."""
    original_sql = original_path.read_text()
    resolved_candidate_paths = _resolve_candidate_paths(candidate_paths, candidates_dir)

    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    results = _verify_candidates(
        original_path,
        original_sql,
        resolved_candidate_paths,
        schema_path,
        schema_format,
        constraints,
        verifier=verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
        dialect=dialect,
    )
    metadata_by_path = load_candidate_metadata(candidates_dir)

    if output_format == "json":
        click.echo(
            render_candidate_verifications_json(
                results,
                metadata_by_path=metadata_by_path,
                dialect=dialect,
            )
        )
    else:
        console.print(render_candidate_verifications_report(results))

    if fail_on == "unproven" and any(
        result.status != VerificationStatus.PROVEN_EQUIVALENT for result in results
    ):
        raise click.exceptions.Exit(1)


@candidates_group.command(name="evidence")
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument(
    "candidate_paths",
    nargs=-1,
    required=False,
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
    "--candidates-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing candidate .sql files to verify and benchmark.",
)
@click.option(
    "--rows",
    type=click.IntRange(min=1),
    default=100_000,
    show_default=True,
    help="Synthetic DuckDB rows per referenced table.",
)
@click.option("--warmups", type=click.IntRange(min=0), default=1, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--benchmark-timeout",
    "benchmark_timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
    help="Per-query benchmark timeout in seconds.",
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
    help="Write a versioned candidate evidence artifact to this file.",
)
@click.option(
    "--fail-on",
    type=CheckFailOn,
    default="none",
    show_default=True,
    help="Exit nonzero when any candidate is not proven.",
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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used for verification and DuckDB benchmark transpilation.",
)
def candidates_evidence(
    original_path: Path,
    candidate_paths: tuple[Path, ...],
    schema_path: Path,
    schema_format: str,
    candidates_dir: Path | None,
    rows: int,
    warmups: int,
    repetitions: int,
    benchmark_timeout_seconds: float,
    output_format: str,
    report_file: Path | None,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> None:
    """Verify candidates, then benchmark only the proven candidates on DuckDB."""
    original_sql = original_path.read_text()
    resolved_candidate_paths = _resolve_candidate_paths(candidate_paths, candidates_dir)

    try:
        constraints = _load_constraints(schema_path, schema_format)
        verifications = _verify_candidates(
            original_path,
            original_sql,
            resolved_candidate_paths,
            schema_path,
            schema_format,
            constraints,
            verifier=verifier,
            solver_command=solver_command,
            timeout_seconds=timeout_seconds,
            dialect=dialect,
        )
        evidence = build_candidate_evidence(
            original_path,
            resolved_candidate_paths,
            verifications,
            constraints,
            schema_path=schema_path,
            schema_format=schema_format,
            dialect=dialect,
            rows=rows,
            warmups=warmups,
            repetitions=repetitions,
            benchmark_timeout_seconds=benchmark_timeout_seconds,
            candidate_metadata=load_candidate_metadata(candidates_dir),
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    json_report = render_candidate_evidence_json(evidence)
    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(render_candidate_evidence_report(evidence))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Evidence report written: {report_file}", err=True)

    if fail_on == "unproven" and any(not row.proven for row in evidence.results):
        raise click.exceptions.Exit(1)
