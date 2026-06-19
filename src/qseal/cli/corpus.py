from pathlib import Path

import click
from rich.console import Console

from qseal.cli.types import (
    OutputFormat,
    RewardModelChoice,
    SearchStrategyChoice,
)
from qseal.research.corpora import bundled_corpus_path
from qseal.research.corpus import (
    CorpusRunConfig,
    aggregate_corpus_runs,
    export_corpus_trajectories,
    inspect_corpus_aggregate,
    load_corpus_run_report,
    load_task_corpus,
    render_corpus_aggregate,
    render_corpus_aggregate_inspection,
    render_corpus_summary,
    render_corpus_trajectory_export,
    run_repeated_task_corpus,
    run_task_corpus,
    summarize_corpus_run,
    write_corpus_aggregate,
    write_corpus_summary,
)
from qseal.research.policy import (
    load_policy_model,
)

console = Console()

@click.group(name="corpus", hidden=True)
def corpus_group() -> None:
    """Experimental: run reproducible rewrite-search tasks."""


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
@click.option(
    "--reward-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum cumulative reward improvement required to prefer a longer path.",
)
@click.option(
    "--reward-model",
    type=RewardModelChoice,
    default="transition",
    show_default=True,
    help="Use paired transition timings or cached absolute SQL-state timings.",
)
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
    "--minimum-duration-ms",
    type=click.FloatRange(min=0),
    default=5.0,
    show_default=True,
    help="Minimum duration for each timed execution batch.",
)
@click.option(
    "--policy-model",
    "policy_model_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Baseline policy model JSON artifact for the policy_baseline strategy.",
)
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
    reward_margin: float,
    reward_model: str,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    minimum_duration_ms: float,
    policy_model_path: Path | None,
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
        "reward_margin": reward_margin,
        "reward_model": reward_model,
        "warmups": warmups,
        "repetitions": repetitions,
        "timeout_seconds": timeout_seconds,
        "threads": threads,
        "minimum_duration_ms": minimum_duration_ms,
    }
    if policy_model_path is not None:
        config_values["policy_model_path"] = str(policy_model_path)
        config_values["policy_model"] = load_policy_model(policy_model_path)
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
                f"{summary.low_confidence_steps} low-confidence steps, "
                f"{summary.total_elapsed_seconds:.3f}s"
            )
    click.echo(f"Report file written: {report_file}", err=True)

    if any(summary.error_count for summary in report.strategy_summaries):
        raise click.exceptions.Exit(1)


@corpus_group.command(name="repeat")
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--runs",
    type=click.IntRange(min=2),
    default=3,
    show_default=True,
    help="Number of independent corpus measurements.",
)
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
@click.option(
    "--reward-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum cumulative reward improvement required to prefer a longer path.",
)
@click.option(
    "--reward-model",
    type=RewardModelChoice,
    default="transition",
    show_default=True,
    help="Use paired transition timings or cached absolute SQL-state timings.",
)
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
    "--minimum-duration-ms",
    type=click.FloatRange(min=0),
    default=5.0,
    show_default=True,
    help="Minimum duration for each timed execution batch.",
)
@click.option(
    "--policy-model",
    "policy_model_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Baseline policy model JSON artifact for the policy_baseline strategy.",
)
@click.option(
    "--neutral-threshold",
    type=click.FloatRange(min=0),
    default=0.01,
    show_default=True,
    help="Maximum reward difference treated as equivalent.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_repeat(
    output_dir: Path,
    runs: int,
    manifest_path: Path | None,
    task_ids: tuple[str, ...],
    strategies: tuple[str, ...],
    random_seed: int,
    beam_width: int,
    max_nodes: int,
    reward_margin: float,
    reward_model: str,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    minimum_duration_ms: float,
    policy_model_path: Path | None,
    neutral_threshold: float,
    output_format: str,
) -> None:
    """Run independent corpus measurements and aggregate their stability."""
    manifest_path = manifest_path or bundled_corpus_path()
    config_values = {
        "task_ids": task_ids,
        "random_seed": random_seed,
        "beam_width": beam_width,
        "max_nodes": max_nodes,
        "reward_margin": reward_margin,
        "reward_model": reward_model,
        "warmups": warmups,
        "repetitions": repetitions,
        "timeout_seconds": timeout_seconds,
        "threads": threads,
        "minimum_duration_ms": minimum_duration_ms,
    }
    if policy_model_path is not None:
        config_values["policy_model_path"] = str(policy_model_path)
        config_values["policy_model"] = load_policy_model(policy_model_path)
    if strategies:
        config_values["strategies"] = strategies

    click.echo(
        f"Running {runs} independent corpus measurements in {output_dir}...",
        err=True,
    )
    try:
        aggregate = run_repeated_task_corpus(
            load_task_corpus(manifest_path),
            output_dir,
            runs=runs,
            config=CorpusRunConfig(**config_values),
            neutral_threshold=neutral_threshold,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(aggregate.model_dump_json(indent=2))
    else:
        click.echo(render_corpus_aggregate(aggregate))
    click.echo(
        f"Aggregate file written: {output_dir / 'corpus-aggregate.json'}",
        err=True,
    )


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


@corpus_group.command(name="aggregate")
@click.argument(
    "report_paths",
    nargs=-1,
    required=True,
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
    "--aggregate-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the versioned JSON aggregate artifact to this file.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_aggregate(
    report_paths: tuple[Path, ...],
    neutral_threshold: float,
    aggregate_file: Path | None,
    output_format: str,
) -> None:
    """Aggregate repeated compatible corpus runs."""
    try:
        aggregate = aggregate_corpus_runs(
            tuple(load_corpus_run_report(path) for path in report_paths),
            source_reports=tuple(str(path) for path in report_paths),
            neutral_threshold=neutral_threshold,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(aggregate.model_dump_json(indent=2))
    else:
        click.echo(render_corpus_aggregate(aggregate))

    if aggregate_file is not None:
        write_corpus_aggregate(aggregate, aggregate_file)
        click.echo(f"Aggregate file written: {aggregate_file}", err=True)


@corpus_group.command(name="inspect-aggregate")
@click.argument(
    "aggregate_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--task",
    "task_id",
    help="Inspect one task ID. Defaults to every unstable task.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_inspect_aggregate(
    aggregate_path: Path,
    task_id: str | None,
    output_format: str,
) -> None:
    """Inspect task paths and timings across an aggregate's source runs."""
    try:
        inspection = inspect_corpus_aggregate(
            aggregate_path,
            task_id=task_id,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(inspection.model_dump_json(indent=2))
    else:
        click.echo(render_corpus_aggregate_inspection(inspection))


@corpus_group.command(name="export-trajectories")
@click.argument(
    "report_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Corpus manifest. Defaults to the bundled duckdb-v1 corpus.",
)
@click.option(
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write JSONL trajectory records to this path.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def corpus_export_trajectories(
    report_path: Path,
    manifest_path: Path | None,
    output_path: Path,
    output_format: str,
) -> None:
    """Export search paths as labeled JSONL trajectory rows."""
    manifest_path = manifest_path or bundled_corpus_path()
    try:
        export = export_corpus_trajectories(
            load_corpus_run_report(report_path),
            load_task_corpus(manifest_path),
            output_path,
            source_report=str(report_path),
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(export.model_dump_json(indent=2))
    else:
        click.echo(render_corpus_trajectory_export(export))
