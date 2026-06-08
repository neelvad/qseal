from pathlib import Path

import click
from rich.console import Console

from snowprove.benchmark import BenchmarkStatus, benchmark_query_pair
from snowprove.candidates.bundle import load_candidate_metadata
from snowprove.constraints.loader import load_constraint_catalog
from snowprove.corpora import bundled_corpus_path
from snowprove.corpus import (
    CorpusRunConfig,
    load_corpus_run_report,
    load_task_corpus,
    render_corpus_summary,
    run_task_corpus,
    summarize_corpus_run,
    write_corpus_summary,
)
from snowprove.dbt.project import DbtProjectDiscoveryError, discover_compiled_sql_path
from snowprove.dbt.scan import scan_dbt_project
from snowprove.dialects import DEFAULT_DIALECT, SUPPORTED_DIALECTS
from snowprove.fixtures import DuckDbFixtureSpec, create_duckdb_fixture
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.report.json import (
    render_candidate_generation_json,
    render_candidate_run_json,
    render_candidate_verifications_json,
    render_dbt_scan_json,
    render_duckdb_benchmark_json,
    render_duckdb_fixture_json,
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
from snowprove.report.patch import apply_dbt_scan_patches, write_dbt_scan_patch_results
from snowprove.report.text import (
    render_candidate_verifications_report,
    render_dbt_scan_diff_report,
    render_dbt_scan_report,
    render_duckdb_benchmark_report,
    render_duckdb_fixture_report,
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
DialectChoice = click.Choice(SUPPORTED_DIALECTS, case_sensitive=False)
SearchStrategyChoice = click.Choice(
    ["fixed_order", "random", "greedy", "beam", "exhaustive"],
    case_sensitive=False,
)


@click.group()
def main() -> None:
    """Verified-safe SQL rewrites for a constrained SQL subset."""


@main.group(name="dbt")
def dbt_group() -> None:
    """dbt project workflows."""


@main.group(name="candidates")
def candidates_group() -> None:
    """Generate and verify candidate rewrites."""


@main.group(name="fixtures")
def fixtures_group() -> None:
    """Create reproducible benchmark data."""


@main.group(name="corpus")
def corpus_group() -> None:
    """Run reproducible rewrite-search tasks."""


@corpus_group.command(name="run")
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Corpus manifest. Defaults to the bundled duckdb-v1 corpus.",
)
@click.option(
    "--task",
    "task_ids",
    multiple=True,
    help="Only run a task ID. Can be passed more than once.",
)
@click.option(
    "--strategy",
    "strategies",
    multiple=True,
    type=SearchStrategyChoice,
    help="Only run a search strategy. Can be passed more than once.",
)
@click.option("--random-seed", type=int, default=42, show_default=True)
@click.option("--beam-width", type=click.IntRange(min=1), default=4, show_default=True)
@click.option("--max-nodes", type=click.IntRange(min=1), default=100, show_default=True)
@click.option("--warmups", type=click.IntRange(min=0), default=1, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
)
@click.option("--threads", type=click.IntRange(min=1), default=1, show_default=True)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="JSON report path. Defaults to OUTPUT_DIR/corpus-run.json.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_run(
    output_dir: Path,
    manifest_path: Path | None,
    task_ids: tuple[str, ...],
    strategies: tuple[str, ...],
    random_seed: int,
    beam_width: int,
    max_nodes: int,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    report_file: Path | None,
    output_format: str,
) -> None:
    """Execute search baselines over a task corpus."""
    manifest_path = manifest_path or bundled_corpus_path()
    report_file = report_file or output_dir / "corpus-run.json"
    config_values = {
        "task_ids": task_ids,
        "random_seed": random_seed,
        "beam_width": beam_width,
        "max_nodes": max_nodes,
        "warmups": warmups,
        "repetitions": repetitions,
        "timeout_seconds": timeout_seconds,
        "threads": threads,
    }
    if strategies:
        config_values["strategies"] = strategies

    try:
        report = run_task_corpus(
            load_task_corpus(manifest_path),
            output_dir,
            config=CorpusRunConfig(**config_values),
            report_path=report_file,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(report.model_dump_json(indent=2))
    else:
        console.print(
            f"Corpus: {report.corpus_id} v{report.corpus_version} "
            f"({len(report.tasks)} tasks)"
        )
        for summary in report.strategy_summaries:
            reward = (
                f"{summary.mean_cumulative_reward:.6f}"
                if summary.mean_cumulative_reward is not None
                else "n/a"
            )
            console.print(
                f"  {summary.strategy}: {summary.completed_count}/"
                f"{summary.run_count} completed, mean reward {reward}, "
                f"{summary.verification_requests} verifier requests, "
                f"{summary.benchmark_requests} benchmark requests, "
                f"{summary.benchmark_cache_misses} new benchmarks, "
                f"{summary.total_elapsed_seconds:.3f}s"
            )
    click.echo(f"Report file written: {report_file}", err=True)

    if any(summary.error_count for summary in report.strategy_summaries):
        raise click.exceptions.Exit(1)


@corpus_group.command(name="summarize")
@click.argument(
    "report_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--neutral-threshold",
    type=click.FloatRange(min=0),
    default=0.01,
    show_default=True,
    help="Maximum reward difference treated as equivalent.",
)
@click.option(
    "--summary-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the versioned JSON summary artifact to this file.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_summarize(
    report_path: Path,
    neutral_threshold: float,
    summary_file: Path | None,
    output_format: str,
) -> None:
    """Summarize strategy performance and task disagreement."""
    try:
        summary = summarize_corpus_run(
            load_corpus_run_report(report_path),
            source_report=str(report_path),
            neutral_threshold=neutral_threshold,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(summary.model_dump_json(indent=2))
    else:
        click.echo(render_corpus_summary(summary))

    if summary_file is not None:
        write_corpus_summary(summary, summary_file)
        click.echo(f"Summary file written: {summary_file}", err=True)


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


@main.command()
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("rewritten_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--database",
    "database_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="DuckDB database file. Defaults to an in-memory database.",
)
@click.option(
    "--setup",
    "setup_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SQL file executed once before plans, warmups, and measurements.",
)
@click.option(
    "--warmups",
    type=click.IntRange(min=0),
    default=2,
    show_default=True,
    help="Warmup executions per query.",
)
@click.option(
    "--repetitions",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="Measured executions per query.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=30.0,
    show_default=True,
    help="Per-query timeout in seconds.",
)
@click.option(
    "--threads",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="DuckDB worker threads.",
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
    help="Write a versioned JSON benchmark artifact to this file.",
)
def benchmark(
    original_path: Path,
    rewritten_path: Path,
    database_path: Path | None,
    setup_path: Path | None,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    output_format: str,
    report_file: Path | None,
) -> None:
    """Benchmark an original and rewritten query in DuckDB."""
    result = benchmark_query_pair(
        original_path.read_text(),
        rewritten_path.read_text(),
        database_path=database_path or ":memory:",
        setup_sql=setup_path.read_text() if setup_path is not None else None,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        threads=threads,
    ).model_copy(
        update={
            "inputs": {
                "original_path": str(original_path),
                "rewritten_path": str(rewritten_path),
                "setup_path": str(setup_path) if setup_path is not None else "",
            }
        }
    )
    json_report = render_duckdb_benchmark_json(result)

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(render_duckdb_benchmark_report(result))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Report file written: {report_file}", err=True)

    if result.status != BenchmarkStatus.COMPLETED:
        raise click.exceptions.Exit(1)


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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse model SQL.",
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
    dialect: str,
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
            dialect=dialect,
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
    selected_rules: tuple[str, ...],
    output_format: str,
    dialect: str,
) -> None:
    """Suggest verified-safe rewrites for one SQL query."""
    raw_sql = query_path.read_text()
    try:
        query = parse_select(raw_sql, dialect=dialect)
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
            click.echo(render_suggestions_json(suggestions, dialect=dialect))
        else:
            console.print(render_suggestions_report(suggestions))
        return

    suggestion = first_applicable_suggestion(suggestions)
    if output_format == "json":
        click.echo(render_suggestion_json(suggestion, dialect=dialect))
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
    """Generate candidate SQL files from Snowprove's rewrite rules."""
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
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used for verification.",
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
    dialect: str,
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
        dialect=dialect,
    )
    result = result.model_copy(
        update={
            "inputs": _verification_inputs(
                original_path,
                rewritten_path,
                schema_path,
                schema_format,
                dialect,
            )
        }
    )
    _print_verification(result, output_format, fail_on)


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
    dialect: str,
) -> dict[str, str]:
    return {
        "original_path": str(original_path),
        "rewritten_path": str(rewritten_path),
        "schema_path": str(schema_path),
        "schema_format": schema_format,
        "dialect": dialect,
    }


def _load_constraints(path: Path, schema_format: str):
    return load_constraint_catalog(path, schema_format)


def _verify_candidates(
    original_path: Path,
    original_sql: str,
    candidate_paths: list[Path],
    schema_path: Path,
    schema_format: str,
    constraints,
    *,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> list[VerificationResult]:
    backend = get_verifier_backend(
        verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
    )
    return [
        backend.verify(
            original_sql,
            candidate_path.read_text(),
            constraints,
            dialect=dialect,
        ).model_copy(
            update={
                "inputs": _verification_inputs(
                    original_path,
                    candidate_path,
                    schema_path,
                    schema_format,
                    dialect,
                )
            }
        )
        for candidate_path in candidate_paths
    ]


def _resolve_candidate_paths(
    candidate_paths: tuple[Path, ...],
    candidates_dir: Path | None,
) -> list[Path]:
    if candidate_paths and candidates_dir is not None:
        raise click.ClickException("Pass candidate paths or --candidates-dir, not both.")
    if candidates_dir is not None:
        paths = sorted(candidates_dir.glob("*.sql"))
        if not paths:
            raise click.ClickException(f"No .sql candidate files found in {candidates_dir}.")
        return paths
    if not candidate_paths:
        raise click.ClickException("Pass at least one candidate path or --candidates-dir.")
    return list(candidate_paths)


def _write_candidate_suggestions(
    suggestions: list[RewriteSuggestion],
    output_dir: Path,
    *,
    include_all: bool,
    force: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for index, suggestion in enumerate(_candidate_suggestions(suggestions, include_all), start=1):
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

    return generated, skipped


def _candidate_generation_payload(
    query_path: Path,
    output_dir: Path,
    generated: list[dict[str, str]],
    skipped: list[dict[str, str]],
    dialect: str,
) -> dict[str, object]:
    return {
        "original_path": str(query_path),
        "output_dir": str(output_dir),
        "dialect": dialect,
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "generated": generated,
        "skipped": skipped,
    }


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
