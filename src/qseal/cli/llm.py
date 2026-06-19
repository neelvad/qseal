import json
from pathlib import Path

import click
from rich.console import Console

from qseal.candidates.benchmarking import benchmark_proven
from qseal.candidates.explain import explain_proven
from qseal.candidates.generation import generate_candidates
from qseal.candidates.verification import merge_reports, verify_bundles
from qseal.cli.types import (
    DialectChoice,
)
from qseal.constraints.model import ConstraintCatalog
from qseal.dbt.project import (
    discover_dbt_project,
)
from qseal.dbt.scan import _load_project_constraints
from qseal.dialects import DEFAULT_DIALECT
from qseal.verifier.backends.qed import QedBackend
from qseal.verifier.backends.sqlsolver import SqlSolverBackend
from qseal.verifier.backends.verieql import VeriEqlBackend

console = Console()

@click.group(name="llm")
def llm_group() -> None:
    """LLM-generated candidate pipeline: generate, verify, benchmark, explain."""


@llm_group.command(name="generate")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where candidate bundles are written.",
)
@click.option("--dialect", type=DialectChoice, default=DEFAULT_DIALECT, show_default=True)
@click.option(
    "--model",
    "model_id",
    envvar="QSEAL_LLM_MODEL",
    help=(
        "Anthropic model id for actual generation. Can also be set with "
        "QSEAL_LLM_MODEL. Required unless --dry-run is used."
    ),
)
@click.option("--limit", type=click.IntRange(min=1), help="Only process the first N targets.")
@click.option("--max-candidates", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--use-batches",
    is_flag=True,
    help="Submit via the Anthropic Batches API (half price, for full runs).",
)
@click.option("--dry-run", is_flag=True, help="Print prompts without calling the API.")
def llm_generate(
    project_path: Path,
    out_dir: Path,
    dialect: str,
    model_id: str | None,
    limit: int | None,
    max_candidates: int,
    use_batches: bool,
    dry_run: bool,
) -> None:
    """Generate premise-targeted LLM rewrite candidates for a dbt project."""
    if not dry_run and not model_id:
        raise click.ClickException(
            "LLM generation requires --model or QSEAL_LLM_MODEL. "
            "Use --dry-run to inspect prompts without a model."
        )
    summary = generate_candidates(
        project_path,
        out_dir,
        dialect=dialect,
        model_id=model_id,
        limit=limit,
        max_candidates=max_candidates,
        use_batches=use_batches,
        dry_run=dry_run,
        log=lambda message: click.echo(message, err=True),
    )
    click.echo(json.dumps(summary, indent=2))


@llm_group.command(name="verify")
@click.argument("bundles_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="dbt project for constraints (else BUNDLES_DIR/constraints.json).",
)
@click.option(
    "--constraints",
    "constraints_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Constraint catalog JSON (else BUNDLES_DIR/constraints.json).",
)
@click.option("--dialect", type=DialectChoice, default=DEFAULT_DIALECT, show_default=True)
@click.option("--qed", is_flag=True, help="Run the QED prover (QSEAL_QED_* env vars).")
@click.option("--solver-command", help="SQLSolver command (typically in the x86 container).")
@click.option("--solver-timeout", type=int, default=60, show_default=True)
@click.option(
    "--verieql-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="VeriEQL checkout for refutation and cross-checks.",
)
@click.option("--only", help="Comma-separated model names (for sharded runs).")
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the verification report JSON here.",
)
def llm_verify(
    bundles_dir: Path,
    project_path: Path | None,
    constraints_path: Path | None,
    dialect: str,
    qed: bool,
    solver_command: str | None,
    solver_timeout: int,
    verieql_dir: Path | None,
    only: str | None,
    report_file: Path | None,
) -> None:
    """Verify candidate bundles through the prover/refuter cascade."""
    constraints = _bundle_constraints(bundles_dir, project_path, constraints_path)
    result = verify_bundles(
        bundles_dir,
        constraints,
        dialect=dialect,
        solver=(
            SqlSolverBackend(solver_command=solver_command, timeout_seconds=solver_timeout)
            if solver_command
            else None
        ),
        qed=QedBackend(timeout_seconds=solver_timeout) if qed else None,
        refuter=VeriEqlBackend(verieql_dir=verieql_dir) if verieql_dir else None,
        only=set(only.split(",")) if only else None,
        report_file=report_file,
        log=lambda message: click.echo(message, err=True),
    )
    click.echo(
        json.dumps({"candidates": result["candidate_count"], **result["buckets"]}, indent=2)
    )
    for alarm in result["alarms"]:
        click.echo(f"ALARM: proven candidate refuted: {alarm}")
    if result["alarms"]:
        raise click.exceptions.Exit(1)


@llm_group.command(name="merge")
@click.argument("reports", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the merged report JSON here.",
)
def llm_merge(reports: tuple[Path, ...], report_file: Path | None) -> None:
    """Merge per-prover verification reports into the best verdict per candidate."""
    if len(reports) < 2:
        raise click.ClickException("merge requires at least two report files.")
    result = merge_reports(list(reports), report_file)
    click.echo(
        json.dumps({"candidates": result["candidate_count"], **result["buckets"]}, indent=2)
    )
    for conflict in result["conflicts"]:
        click.echo(f"ALARM: prover/refuter conflict on {conflict}")
    if result["conflicts"]:
        raise click.exceptions.Exit(1)


def _bundle_constraints(
    bundles_dir: Path,
    project_path: Path | None,
    constraints_path: Path | None,
) -> ConstraintCatalog:
    if project_path is not None:
        project = discover_dbt_project(project_path)
        return _load_project_constraints(project.schema_yml_files)
    path = constraints_path or (bundles_dir / "constraints.json")
    if not path.exists():
        raise click.ClickException(
            "provide --project or a constraints snapshot (constraints.json)."
        )
    return ConstraintCatalog.model_validate_json(path.read_text())


@llm_group.command(name="benchmark")
@click.argument("report_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("bundles_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--report-file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the benchmark report JSON here.",
)
@click.option("--rows", default="100000,1000000", show_default=True, help="Comma-separated scales.")
@click.option("--dialect", type=DialectChoice, default=DEFAULT_DIALECT, show_default=True)
@click.option("--warmups", type=click.IntRange(min=0), default=1, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=1), default=3, show_default=True)
@click.option("--timeout", type=click.FloatRange(min=0, min_open=True), default=30.0,
              show_default=True)
@click.option("--only", help="Comma-separated model names.")
def llm_benchmark(
    report_path: Path,
    bundles_dir: Path,
    report_file: Path,
    rows: str,
    dialect: str,
    warmups: int,
    repetitions: int,
    timeout: float,
    only: str | None,
) -> None:
    """Tier-1: DuckDB micro-benchmarks for the proven rewrites in a report."""
    result = benchmark_proven(
        report_path,
        bundles_dir,
        rows=[int(float(scale)) for scale in rows.split(",")],
        dialect=dialect,
        warmups=warmups,
        repetitions=repetitions,
        timeout=timeout,
        only=set(only.split(",")) if only else None,
        report_file=report_file,
        log=lambda message: click.echo(message, err=True),
    )
    click.echo(
        json.dumps({"measurements": result["measurement_count"], **result["outcomes"]}, indent=2)
    )


@llm_group.command(name="explain")
@click.argument("report_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("bundles_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--report-file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the EXPLAIN-diff report JSON here.",
)
@click.option("--dialect", type=DialectChoice, default=DEFAULT_DIALECT, show_default=True)
@click.option("--only", help="Comma-separated model names.")
def llm_explain(
    report_path: Path,
    bundles_dir: Path,
    report_file: Path,
    dialect: str,
    only: str | None,
) -> None:
    """Tier-2: Snowflake EXPLAIN plan diffs for the proven rewrites in a report.

    Requires SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD.
    """
    result = explain_proven(
        report_path,
        bundles_dir,
        dialect=dialect,
        only=set(only.split(",")) if only else None,
        report_file=report_file,
        log=lambda message: click.echo(message, err=True),
    )
    click.echo(json.dumps({"pairs": result["pair_count"], **result["verdicts"]}, indent=2))
