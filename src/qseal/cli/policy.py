from pathlib import Path

import click
from rich.console import Console

from qseal.cli.common import (
    _select_policy_holdout_tasks,
    _strategy_wins,
    _unknown_preference_group_options,
)
from qseal.cli.types import (
    OutputFormat,
    PolicyLabelGroupChoice,
    RewardModelChoice,
)
from qseal.corpora import bundled_corpus_path
from qseal.corpus import (
    CorpusRunConfig,
    load_task_corpus,
    run_task_corpus,
)
from qseal.policy import (
    PolicyDataFilter,
    PolicyHoldoutEvaluation,
    compare_policy_holdouts,
    evaluate_baseline_policy,
    inspect_baseline_policy,
    inspect_policy_labels,
    load_baseline_policy,
    render_baseline_policy_evaluation,
    render_baseline_policy_inspection,
    render_baseline_policy_training,
    render_linear_policy_training,
    render_policy_holdout_comparison,
    render_policy_holdout_evaluation,
    render_policy_label_inspection,
    train_baseline_policy,
    train_linear_policy,
    write_baseline_policy,
    write_policy_model,
)

console = Console()

@click.group(name="policy")
def policy_group() -> None:
    """Train and evaluate simple rewrite action policies."""


@policy_group.command(name="train-baseline")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--model-file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the baseline policy model JSON artifact to this file.",
)
@click.option("--include-task", "include_tasks", multiple=True)
@click.option("--exclude-task", "exclude_tasks", multiple=True)
@click.option("--include-fixture", "include_fixtures", multiple=True)
@click.option("--exclude-fixture", "exclude_fixtures", multiple=True)
@click.option("--include-tag", "include_tags", multiple=True)
@click.option("--exclude-tag", "exclude_tags", multiple=True)
@click.option(
    "--stop-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum observed suffix reward required before a rewrite beats no-op.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_train_baseline(
    trajectory_path: Path,
    model_file: Path,
    include_tasks: tuple[str, ...],
    exclude_tasks: tuple[str, ...],
    include_fixtures: tuple[str, ...],
    exclude_fixtures: tuple[str, ...],
    include_tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    stop_margin: float,
    output_format: str,
) -> None:
    """Train a simple feature-mean action ranker from trajectory JSONL."""
    model = train_baseline_policy(
        trajectory_path,
        source_trajectories=str(trajectory_path),
        data_filter=PolicyDataFilter(
            include_tasks=include_tasks,
            exclude_tasks=exclude_tasks,
            include_fixtures=include_fixtures,
            exclude_fixtures=exclude_fixtures,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        ),
        stop_margin=stop_margin,
    )
    write_baseline_policy(model, model_file)

    if output_format == "json":
        click.echo(model.model_dump_json(indent=2))
    else:
        click.echo(render_baseline_policy_training(model))
    click.echo(f"Model file written: {model_file}", err=True)


@policy_group.command(name="train-ranker")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--model-file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the linear policy model JSON artifact to this file.",
)
@click.option("--include-task", "include_tasks", multiple=True)
@click.option("--exclude-task", "exclude_tasks", multiple=True)
@click.option("--include-fixture", "include_fixtures", multiple=True)
@click.option("--exclude-fixture", "exclude_fixtures", multiple=True)
@click.option("--include-tag", "include_tags", multiple=True)
@click.option("--exclude-tag", "exclude_tags", multiple=True)
@click.option("--epochs", type=click.IntRange(min=1), default=20, show_default=True)
@click.option(
    "--learning-rate",
    type=click.FloatRange(min=0, min_open=True),
    default=1.0,
    show_default=True,
)
@click.option(
    "--training-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Skip ranker training preferences whose known reward gap is below this margin.",
)
@click.option(
    "--stop-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum observed suffix reward required before a rewrite beats no-op.",
)
@click.option(
    "--unknown-preference-scale",
    type=click.FloatRange(min=0),
    default=1.0,
    show_default=True,
    help="Training scale for preferences whose alternative reward was not observed.",
)
@click.option(
    "--unknown-preference-group-by",
    multiple=True,
    help=(
        "Grouping dimension for unknown preference scale overrides. "
        "Defaults to action_set and table when group scales are supplied."
    ),
)
@click.option(
    "--unknown-preference-group-scale",
    nargs=2,
    multiple=True,
    metavar="GROUP SCALE",
    help=(
        "Override unknown preference scale for a group key from "
        "`policy inspect-labels`."
    ),
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_train_ranker(
    trajectory_path: Path,
    model_file: Path,
    include_tasks: tuple[str, ...],
    exclude_tasks: tuple[str, ...],
    include_fixtures: tuple[str, ...],
    exclude_fixtures: tuple[str, ...],
    include_tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    epochs: int,
    learning_rate: float,
    training_margin: float,
    stop_margin: float,
    unknown_preference_scale: float,
    unknown_preference_group_by: tuple[str, ...],
    unknown_preference_group_scale: tuple[tuple[str, str], ...],
    output_format: str,
) -> None:
    """Train a small linear action ranker from trajectory oracle labels."""
    group_by, group_scales = _unknown_preference_group_options(
        unknown_preference_group_by,
        unknown_preference_group_scale,
    )
    model = train_linear_policy(
        trajectory_path,
        source_trajectories=str(trajectory_path),
        data_filter=PolicyDataFilter(
            include_tasks=include_tasks,
            exclude_tasks=exclude_tasks,
            include_fixtures=include_fixtures,
            exclude_fixtures=exclude_fixtures,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        ),
        stop_margin=stop_margin,
        epochs=epochs,
        learning_rate=learning_rate,
        training_margin=training_margin,
        unknown_preference_scale=unknown_preference_scale,
        unknown_preference_group_by=group_by,
        unknown_preference_group_scales=group_scales,
    )
    write_policy_model(model, model_file)

    if output_format == "json":
        click.echo(model.model_dump_json(indent=2))
    else:
        click.echo(render_linear_policy_training(model))
    click.echo(f"Model file written: {model_file}", err=True)


@policy_group.command(name="evaluate-baseline")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--model-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Baseline policy model JSON artifact.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the evaluation JSON artifact to this file.",
)
@click.option("--include-task", "include_tasks", multiple=True)
@click.option("--exclude-task", "exclude_tasks", multiple=True)
@click.option("--include-fixture", "include_fixtures", multiple=True)
@click.option("--exclude-fixture", "exclude_fixtures", multiple=True)
@click.option("--include-tag", "include_tags", multiple=True)
@click.option("--exclude-tag", "exclude_tags", multiple=True)
@click.option(
    "--reward-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Reward gap tolerated when computing adjusted offline accuracy.",
)
@click.option(
    "--stop-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum observed suffix reward required before a rewrite beats no-op.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_evaluate_baseline(
    trajectory_path: Path,
    model_file: Path,
    report_file: Path | None,
    include_tasks: tuple[str, ...],
    exclude_tasks: tuple[str, ...],
    include_fixtures: tuple[str, ...],
    exclude_fixtures: tuple[str, ...],
    include_tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    reward_margin: float,
    stop_margin: float,
    output_format: str,
) -> None:
    """Evaluate a baseline policy model against trajectory oracle labels."""
    evaluation = evaluate_baseline_policy(
        trajectory_path,
        load_baseline_policy(model_file),
        source_trajectories=str(trajectory_path),
        model_path=str(model_file),
        data_filter=PolicyDataFilter(
            include_tasks=include_tasks,
            exclude_tasks=exclude_tasks,
            include_fixtures=include_fixtures,
            exclude_fixtures=exclude_fixtures,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        ),
        reward_margin=reward_margin,
        stop_margin=stop_margin,
    )
    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(evaluation.model_dump_json(indent=2))

    if output_format == "json":
        click.echo(evaluation.model_dump_json(indent=2))
    else:
        click.echo(render_baseline_policy_evaluation(evaluation))
    if report_file is not None:
        click.echo(f"Evaluation file written: {report_file}", err=True)


@policy_group.command(name="inspect-baseline")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--model-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Baseline policy model JSON artifact.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the inspection JSON artifact to this file.",
)
@click.option("--include-task", "include_tasks", multiple=True)
@click.option("--exclude-task", "exclude_tasks", multiple=True)
@click.option("--include-fixture", "include_fixtures", multiple=True)
@click.option("--exclude-fixture", "exclude_fixtures", multiple=True)
@click.option("--include-tag", "include_tags", multiple=True)
@click.option("--exclude-tag", "exclude_tags", multiple=True)
@click.option(
    "--reward-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Reward gap tolerated when classifying acceptable predictions.",
)
@click.option(
    "--stop-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum observed suffix reward required before a rewrite beats no-op.",
)
@click.option(
    "--mode",
    type=click.Choice(("misses", "unacceptable", "all")),
    default="misses",
    show_default=True,
    help="Which prediction rows to show.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    help="Limit text output rows. JSON reports always include every selected row.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_inspect_baseline(
    trajectory_path: Path,
    model_file: Path,
    report_file: Path | None,
    include_tasks: tuple[str, ...],
    exclude_tasks: tuple[str, ...],
    include_fixtures: tuple[str, ...],
    exclude_fixtures: tuple[str, ...],
    include_tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    reward_margin: float,
    stop_margin: float,
    mode: str,
    limit: int | None,
    output_format: str,
) -> None:
    """Inspect per-state baseline policy predictions and misses."""
    inspection = inspect_baseline_policy(
        trajectory_path,
        load_baseline_policy(model_file),
        source_trajectories=str(trajectory_path),
        model_path=str(model_file),
        data_filter=PolicyDataFilter(
            include_tasks=include_tasks,
            exclude_tasks=exclude_tasks,
            include_fixtures=include_fixtures,
            exclude_fixtures=exclude_fixtures,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        ),
        reward_margin=reward_margin,
        stop_margin=stop_margin,
        mode=mode,
    )
    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(inspection.model_dump_json(indent=2))

    if output_format == "json":
        click.echo(inspection.model_dump_json(indent=2))
    else:
        click.echo(render_baseline_policy_inspection(inspection, limit=limit))
    if report_file is not None:
        click.echo(f"Inspection file written: {report_file}", err=True)


@policy_group.command(name="inspect-labels")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the label inspection JSON artifact to this file.",
)
@click.option("--train-include-task", "train_include_tasks", multiple=True)
@click.option("--train-exclude-task", "train_exclude_tasks", multiple=True)
@click.option("--train-include-fixture", "train_include_fixtures", multiple=True)
@click.option("--train-exclude-fixture", "train_exclude_fixtures", multiple=True)
@click.option("--train-include-tag", "train_include_tags", multiple=True)
@click.option("--train-exclude-tag", "train_exclude_tags", multiple=True)
@click.option("--holdout-include-task", "holdout_include_tasks", multiple=True)
@click.option("--holdout-exclude-task", "holdout_exclude_tasks", multiple=True)
@click.option("--holdout-include-fixture", "holdout_include_fixtures", multiple=True)
@click.option("--holdout-exclude-fixture", "holdout_exclude_fixtures", multiple=True)
@click.option("--holdout-include-tag", "holdout_include_tags", multiple=True)
@click.option("--holdout-exclude-tag", "holdout_exclude_tags", multiple=True)
@click.option(
    "--group-by",
    "group_by",
    multiple=True,
    type=PolicyLabelGroupChoice,
    help=(
        "Preference grouping dimension. Defaults to action_set and table. "
        "Can be passed more than once."
    ),
)
@click.option(
    "--reward-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Skip known preference gaps below this margin.",
)
@click.option(
    "--stop-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Minimum observed suffix reward required before a rewrite beats no-op.",
)
@click.option(
    "--examples-per-group",
    type=click.IntRange(min=0),
    default=3,
    show_default=True,
    help="Number of example preferences retained per group.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    help="Limit text output groups. JSON reports always include every group.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_inspect_labels(
    trajectory_path: Path,
    report_file: Path | None,
    train_include_tasks: tuple[str, ...],
    train_exclude_tasks: tuple[str, ...],
    train_include_fixtures: tuple[str, ...],
    train_exclude_fixtures: tuple[str, ...],
    train_include_tags: tuple[str, ...],
    train_exclude_tags: tuple[str, ...],
    holdout_include_tasks: tuple[str, ...],
    holdout_exclude_tasks: tuple[str, ...],
    holdout_include_fixtures: tuple[str, ...],
    holdout_exclude_fixtures: tuple[str, ...],
    holdout_include_tags: tuple[str, ...],
    holdout_exclude_tags: tuple[str, ...],
    group_by: tuple[str, ...],
    reward_margin: float,
    stop_margin: float,
    examples_per_group: int,
    limit: int | None,
    output_format: str,
) -> None:
    """Compare train and holdout oracle preference labels from trajectories."""
    inspection = inspect_policy_labels(
        trajectory_path,
        source_trajectories=str(trajectory_path),
        train_filter=PolicyDataFilter(
            include_tasks=train_include_tasks,
            exclude_tasks=train_exclude_tasks,
            include_fixtures=train_include_fixtures,
            exclude_fixtures=train_exclude_fixtures,
            include_tags=train_include_tags,
            exclude_tags=train_exclude_tags,
        ),
        holdout_filter=PolicyDataFilter(
            include_tasks=holdout_include_tasks,
            exclude_tasks=holdout_exclude_tasks,
            include_fixtures=holdout_include_fixtures,
            exclude_fixtures=holdout_exclude_fixtures,
            include_tags=holdout_include_tags,
            exclude_tags=holdout_exclude_tags,
        ),
        group_by=group_by or ("action_set", "table"),
        reward_margin=reward_margin,
        stop_margin=stop_margin,
        examples_per_group=examples_per_group,
    )
    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(inspection.model_dump_json(indent=2))

    if output_format == "json":
        click.echo(inspection.model_dump_json(indent=2))
    else:
        click.echo(render_policy_label_inspection(inspection, limit=limit))
    if report_file is not None:
        click.echo(f"Label inspection file written: {report_file}", err=True)


@policy_group.command(name="holdout-evaluate")
@click.argument(
    "trajectory_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Corpus manifest. Defaults to the bundled duckdb-v1 corpus.",
)
@click.option("--include-task", "include_tasks", multiple=True)
@click.option("--include-fixture", "include_fixtures", multiple=True)
@click.option("--include-tag", "include_tags", multiple=True)
@click.option(
    "--policy-kind",
    type=click.Choice(("baseline", "ranker")),
    default="baseline",
    show_default=True,
    help="Policy model family trained for policy_baseline_abstain.",
)
@click.option("--epochs", type=click.IntRange(min=1), default=20, show_default=True)
@click.option(
    "--learning-rate",
    type=click.FloatRange(min=0, min_open=True),
    default=1.0,
    show_default=True,
)
@click.option(
    "--training-margin",
    type=click.FloatRange(min=0),
    default=0.0,
    show_default=True,
    help="Skip ranker training preferences whose known reward gap is below this margin.",
)
@click.option(
    "--unknown-preference-scale",
    type=click.FloatRange(min=0),
    default=1.0,
    show_default=True,
    help="Training scale for preferences whose alternative reward was not observed.",
)
@click.option(
    "--unknown-preference-group-by",
    multiple=True,
    help=(
        "Grouping dimension for unknown preference scale overrides. "
        "Defaults to action_set and table when group scales are supplied."
    ),
)
@click.option(
    "--unknown-preference-group-scale",
    nargs=2,
    multiple=True,
    metavar="GROUP SCALE",
    help=(
        "Override unknown preference scale for a group key from "
        "`policy inspect-labels`."
    ),
)
@click.option("--reward-margin", type=click.FloatRange(min=0), default=0.05, show_default=True)
@click.option(
    "--label-margin",
    type=click.FloatRange(min=0),
    default=None,
    help=(
        "Reward gap tolerated for offline adjusted accuracy. "
        "Defaults to --reward-margin."
    ),
)
@click.option(
    "--reward-model",
    type=RewardModelChoice,
    default="transition",
    show_default=True,
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
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_holdout_evaluate(
    trajectory_path: Path,
    output_dir: Path,
    manifest_path: Path | None,
    include_tasks: tuple[str, ...],
    include_fixtures: tuple[str, ...],
    include_tags: tuple[str, ...],
    policy_kind: str,
    epochs: int,
    learning_rate: float,
    training_margin: float,
    unknown_preference_scale: float,
    unknown_preference_group_by: tuple[str, ...],
    unknown_preference_group_scale: tuple[tuple[str, str], ...],
    reward_margin: float,
    label_margin: float | None,
    reward_model: str,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    minimum_duration_ms: float,
    output_format: str,
) -> None:
    """Train excluding a held-out split and compare policy search on that split."""
    if not (include_tasks or include_fixtures or include_tags):
        raise click.ClickException(
            "At least one holdout include filter is required: "
            "--include-task, --include-fixture, or --include-tag."
        )
    if output_dir.exists():
        raise click.ClickException(f"Output directory already exists: {output_dir}")
    group_by, group_scales = _unknown_preference_group_options(
        unknown_preference_group_by,
        unknown_preference_group_scale,
    )

    manifest_path = manifest_path or bundled_corpus_path()
    corpus = load_task_corpus(manifest_path)
    holdout_filter = PolicyDataFilter(
        include_tasks=include_tasks,
        include_fixtures=include_fixtures,
        include_tags=include_tags,
    )
    train_filter = PolicyDataFilter(
        exclude_tasks=include_tasks,
        exclude_fixtures=include_fixtures,
        exclude_tags=include_tags,
    )
    heldout_task_ids = _select_policy_holdout_tasks(corpus, holdout_filter)
    if not heldout_task_ids:
        raise click.ClickException("Holdout filters selected no corpus tasks.")

    output_dir.mkdir(parents=True)
    model_path = output_dir / "policy.json"
    evaluation_path = output_dir / "offline-evaluation.json"
    corpus_report_path = output_dir / "corpus-run" / "corpus-run.json"
    holdout_report_path = output_dir / "holdout-evaluation.json"

    if policy_kind == "ranker":
        model = train_linear_policy(
            trajectory_path,
            source_trajectories=str(trajectory_path),
            data_filter=train_filter,
            stop_margin=reward_margin,
            epochs=epochs,
            learning_rate=learning_rate,
            training_margin=training_margin,
            unknown_preference_scale=unknown_preference_scale,
            unknown_preference_group_by=group_by,
            unknown_preference_group_scales=group_scales,
        )
    else:
        model = train_baseline_policy(
            trajectory_path,
            source_trajectories=str(trajectory_path),
            data_filter=train_filter,
            stop_margin=reward_margin,
        )
    write_policy_model(model, model_path)
    offline_evaluation = evaluate_baseline_policy(
        trajectory_path,
        model,
        source_trajectories=str(trajectory_path),
        model_path=str(model_path),
        data_filter=holdout_filter,
        reward_margin=label_margin if label_margin is not None else reward_margin,
        stop_margin=reward_margin,
    )
    evaluation_path.write_text(offline_evaluation.model_dump_json(indent=2))
    corpus_report = run_task_corpus(
        corpus,
        corpus_report_path.parent,
        config=CorpusRunConfig(
            strategies=("greedy", "policy_baseline_abstain"),
            task_ids=heldout_task_ids,
            reward_margin=reward_margin,
            reward_model=reward_model,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            threads=threads,
            minimum_duration_ms=minimum_duration_ms,
            policy_model_path=str(model_path),
            policy_model=model,
        ),
        report_path=corpus_report_path,
    )
    holdout = PolicyHoldoutEvaluation(
        generated_at=model.generated_at,
        source_trajectories=str(trajectory_path),
        train_filter=train_filter,
        holdout_filter=holdout_filter,
        trained_state_count=model.labeled_state_count,
        heldout_state_count=offline_evaluation.labeled_state_count,
        offline_evaluation=offline_evaluation,
        corpus_report_path=str(corpus_report_path),
        heldout_task_ids=heldout_task_ids,
        strategy_rewards={
            summary.strategy: summary.mean_cumulative_reward
            for summary in corpus_report.strategy_summaries
        },
        strategy_wins=_strategy_wins(corpus_report),
        strategy_benchmark_requests={
            summary.strategy: summary.benchmark_requests
            for summary in corpus_report.strategy_summaries
        },
        strategy_verifier_requests={
            summary.strategy: summary.verification_requests
            for summary in corpus_report.strategy_summaries
        },
    )
    holdout_report_path.write_text(holdout.model_dump_json(indent=2))

    if output_format == "json":
        click.echo(holdout.model_dump_json(indent=2))
    else:
        click.echo(render_policy_holdout_evaluation(holdout))
    click.echo(f"Holdout evaluation file written: {holdout_report_path}", err=True)


@policy_group.command(name="compare-holdouts")
@click.argument(
    "holdout_paths",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Label for a holdout artifact. Must be supplied once per path if used.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the comparison JSON artifact to this file.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
)
def policy_compare_holdouts(
    holdout_paths: tuple[Path, ...],
    labels: tuple[str, ...],
    report_file: Path | None,
    output_format: str,
) -> None:
    """Compare policy holdout evaluation artifacts."""
    try:
        comparison = compare_policy_holdouts(
            holdout_paths,
            labels=labels,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(comparison.model_dump_json(indent=2))

    if output_format == "json":
        click.echo(comparison.model_dump_json(indent=2))
    else:
        click.echo(render_policy_holdout_comparison(comparison))
    if report_file is not None:
        click.echo(f"Holdout comparison file written: {report_file}", err=True)
