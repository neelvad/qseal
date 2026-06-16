from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qseal.benchmark.model import BenchmarkResult
from qseal.corpus.aggregate import AggregateTaskSummary, CorpusRunAggregate
from qseal.corpus.runner import CorpusRunReport, SearchStrategy
from qseal.corpus.summary import RewardClass, load_corpus_run_report, summarize_corpus_run


class InspectedStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    reward: float
    original_median_ms: float | None = None
    rewritten_median_ms: float | None = None
    original_executions_per_sample: int | None = None
    rewritten_executions_per_sample: int | None = None
    speedup: float | None = None
    timing_confident: bool | None = None
    confidence_reason: str | None = None


class InspectedStrategyRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: SearchStrategy
    status: Literal["COMPLETED", "ERROR"]
    cumulative_reward: float | None = None
    action_ids: tuple[str, ...] = Field(default_factory=tuple)
    steps: tuple[InspectedStep, ...] = Field(default_factory=tuple)
    error: str | None = None


class InspectedTaskRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_index: int
    source_report: str
    reward_class: RewardClass
    winning_strategies: tuple[SearchStrategy, ...]
    strategies: tuple[InspectedStrategyRun, ...]


class InspectedTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: AggregateTaskSummary
    runs: tuple[InspectedTaskRun, ...]


class CorpusAggregateInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_aggregate_inspection"] = (
        "corpus_aggregate_inspection"
    )
    aggregate_path: str
    corpus_id: str
    corpus_version: str
    run_count: int
    task_count: int
    tasks: tuple[InspectedTask, ...]


def inspect_corpus_aggregate(
    aggregate_path: Path,
    *,
    task_id: str | None = None,
) -> CorpusAggregateInspection:
    aggregate_path = aggregate_path.resolve()
    aggregate = CorpusRunAggregate.model_validate_json(aggregate_path.read_text())
    reports, report_paths = _load_source_reports(aggregate, aggregate_path.parent)
    selected = _selected_tasks(aggregate, task_id)
    benchmark_indexes = tuple(_load_benchmark_index(path) for path in report_paths)

    tasks = tuple(
        _inspect_task(
            summary,
            reports,
            report_paths,
            benchmark_indexes,
            aggregate.neutral_threshold,
        )
        for summary in selected
    )
    return CorpusAggregateInspection(
        aggregate_path=str(aggregate_path),
        corpus_id=aggregate.corpus_id,
        corpus_version=aggregate.corpus_version,
        run_count=aggregate.run_count,
        task_count=len(tasks),
        tasks=tasks,
    )


def render_corpus_aggregate_inspection(
    inspection: CorpusAggregateInspection,
) -> str:
    lines = [
        (
            f"Corpus: {inspection.corpus_id} v{inspection.corpus_version} "
            f"({inspection.run_count} runs)"
        ),
        f"Inspected tasks: {inspection.task_count}",
    ]
    if not inspection.tasks:
        lines.extend(["", "No unstable tasks."])
        return "\n".join(lines)

    for task in inspection.tasks:
        summary = task.summary
        signals = []
        if summary.winner_changed:
            signals.append("winner")
        if summary.reward_class_changed:
            signals.append("reward-class")
        if summary.path_changed_strategies:
            signals.append(f"paths:{','.join(summary.path_changed_strategies)}")
        lines.extend(
            [
                "",
                f"Task: {summary.task_id}",
                f"Signals: {', '.join(signals) if signals else 'stable'}",
                (
                    "Reward classes: "
                    + ", ".join(
                        f"{name}={count}"
                        for name, count in summary.reward_class_counts.items()
                    )
                ),
                (
                    "Adjusted class: "
                    f"{summary.uncertainty_adjusted_reward_class} "
                    f"(band={summary.uncertainty_band:.6f})"
                ),
            ]
        )
        if summary.uncertainty_reason:
            lines.append(f"Reason: {summary.uncertainty_reason}")
        for run in task.runs:
            winners = ",".join(run.winning_strategies) or "none"
            lines.append(
                f"  Run {run.run_index:03d}: class={run.reward_class}, "
                f"winners={winners}"
            )
            for strategy in run.strategies:
                path = " -> ".join(strategy.action_ids) or "(unchanged)"
                reward = (
                    f"{strategy.cumulative_reward:.6f}"
                    if strategy.cumulative_reward is not None
                    else "n/a"
                )
                lines.append(
                    f"    {strategy.strategy:<12} reward={reward:>9} path={path}"
                )
                for step in strategy.steps:
                    timing = _render_step_timing(step)
                    lines.append(
                        f"      {step.action_id}: reward={step.reward:.6f}, {timing}"
                    )
    return "\n".join(lines)


def _inspect_task(
    aggregate_task: AggregateTaskSummary,
    reports: tuple[CorpusRunReport, ...],
    report_paths: tuple[Path, ...],
    benchmark_indexes: tuple[dict[tuple[str, str, str], BenchmarkResult], ...],
    neutral_threshold: float,
) -> InspectedTask:
    runs = []
    for index, (report, report_path, benchmarks) in enumerate(
        zip(reports, report_paths, benchmark_indexes, strict=True),
        start=1,
    ):
        task = next(item for item in report.tasks if item.task_id == aggregate_task.task_id)
        task_summary = next(
            item
            for item in summarize_corpus_run(
                report,
                neutral_threshold=neutral_threshold,
            ).tasks
            if item.task_id == aggregate_task.task_id
        )
        strategies = []
        for result in task.results:
            if result.search_result is None:
                strategies.append(
                    InspectedStrategyRun(
                        strategy=result.strategy,
                        status=result.status,
                        error=result.error,
                    )
                )
                continue
            steps = tuple(
                _inspect_step(step, task.fixture_id, benchmarks)
                for step in result.search_result.steps
            )
            strategies.append(
                InspectedStrategyRun(
                    strategy=result.strategy,
                    status=result.status,
                    cumulative_reward=result.search_result.cumulative_reward,
                    action_ids=result.search_result.action_ids,
                    steps=steps,
                    error=result.error,
                )
            )
        runs.append(
            InspectedTaskRun(
                run_index=index,
                source_report=str(report_path),
                reward_class=task_summary.reward_class,
                winning_strategies=task_summary.winning_strategies,
                strategies=tuple(strategies),
            )
        )
    return InspectedTask(summary=aggregate_task, runs=tuple(runs))


def _inspect_step(step, fixture_id: str, benchmarks) -> InspectedStep:
    benchmark = benchmarks.get(
        (
            _normalize_sql(step.state_sql),
            _normalize_sql(step.proposed_sql),
            fixture_id,
        )
    )
    return InspectedStep(
        action_id=step.action_id,
        reward=step.reward,
        original_median_ms=(
            step.original_median_ms
            if step.original_median_ms is not None
            else benchmark.original.median_ms if benchmark else None
        ),
        rewritten_median_ms=(
            step.rewritten_median_ms
            if step.rewritten_median_ms is not None
            else benchmark.rewritten.median_ms if benchmark else None
        ),
        original_executions_per_sample=(
            step.original_executions_per_sample
            if step.original_executions_per_sample is not None
            else benchmark.original.executions_per_sample if benchmark else None
        ),
        rewritten_executions_per_sample=(
            step.rewritten_executions_per_sample
            if step.rewritten_executions_per_sample is not None
            else benchmark.rewritten.executions_per_sample if benchmark else None
        ),
        speedup=(
            step.speedup
            if step.speedup is not None
            else benchmark.speedup if benchmark else None
        ),
        timing_confident=(
            benchmark.timing_confident if benchmark else step.timing_confident
        ),
        confidence_reason=(
            benchmark.confidence_reason if benchmark else step.confidence_reason
        ),
    )


def _load_source_reports(
    aggregate: CorpusRunAggregate,
    aggregate_dir: Path,
) -> tuple[tuple[CorpusRunReport, ...], tuple[Path, ...]]:
    if not aggregate.source_reports:
        raise ValueError("Aggregate artifact does not include source_reports.")
    paths = tuple(
        path if path.is_absolute() else (aggregate_dir / path).resolve()
        for path in map(Path, aggregate.source_reports)
    )
    missing = tuple(path for path in paths if not path.is_file())
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise ValueError(f"Aggregate source reports do not exist: {rendered}.")
    reports = tuple(load_corpus_run_report(path) for path in paths)
    incompatible = tuple(
        path
        for report, path in zip(reports, paths, strict=True)
        if report.corpus_fingerprint != aggregate.corpus_fingerprint
    )
    if incompatible:
        rendered = ", ".join(str(path) for path in incompatible)
        raise ValueError(
            f"Aggregate source reports have incompatible fingerprints: {rendered}."
        )
    return reports, paths


def _selected_tasks(
    aggregate: CorpusRunAggregate,
    task_id: str | None,
) -> tuple[AggregateTaskSummary, ...]:
    if task_id is not None:
        selected = tuple(task for task in aggregate.tasks if task.task_id == task_id)
        if not selected:
            raise ValueError(f"Aggregate does not contain task: {task_id}.")
        return selected
    return tuple(
        task
        for task in aggregate.tasks
        if task.winner_changed
        or task.reward_class_changed
        or task.path_changed_strategies
    )


def _load_benchmark_index(
    report_path: Path,
) -> dict[tuple[str, str, str], BenchmarkResult]:
    index = {}
    cache_root = report_path.parent / "cache" / "benchmark"
    if not cache_root.is_dir():
        return index
    for path in cache_root.glob("*/*.json"):
        benchmark = BenchmarkResult.model_validate_json(path.read_text())
        fixture_id = Path(benchmark.environment.database_path).stem
        index[
            (
                _normalize_sql(benchmark.original.sql),
                _normalize_sql(benchmark.rewritten.sql),
                fixture_id,
            )
        ] = benchmark
    return index


def _render_step_timing(step: InspectedStep) -> str:
    if step.original_median_ms is None or step.rewritten_median_ms is None:
        return "benchmark unavailable"
    confidence = "confident" if step.timing_confident else "low-confidence"
    speedup = f"{step.speedup:.6f}x" if step.speedup is not None else "n/a"
    return (
        f"{step.original_median_ms:.6f}->{step.rewritten_median_ms:.6f} ms, "
        f"speedup={speedup}, batches="
        f"{step.original_executions_per_sample}/"
        f"{step.rewritten_executions_per_sample}, {confidence}"
    )


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.strip().removesuffix(";").split())
