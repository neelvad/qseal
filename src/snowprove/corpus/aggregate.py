from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from snowprove.corpus.runner import CorpusRunReport, SearchStrategy
from snowprove.corpus.summary import RewardClass, summarize_corpus_run

AggregateRewardClass = Literal["positive", "neutral", "negative", "error", "uncertain"]


class AggregateStrategySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: SearchStrategy
    run_count: int
    mean_cumulative_reward: float | None
    reward_standard_deviation: float | None
    minimum_cumulative_reward: float | None
    maximum_cumulative_reward: float | None
    mean_wins: float
    win_standard_deviation: float
    mean_benchmark_requests: float
    mean_elapsed_seconds: float


class AggregateTaskSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    run_count: int
    reward_class_counts: dict[RewardClass, int]
    uncertainty_adjusted_reward_class: AggregateRewardClass = "uncertain"
    uncertainty_band: float = 0.0
    uncertainty_reason: str | None = None
    stable_winning_strategies: tuple[SearchStrategy, ...] = Field(default_factory=tuple)
    winner_changed: bool
    reward_class_changed: bool
    path_changed_strategies: tuple[SearchStrategy, ...] = Field(default_factory=tuple)
    maximum_strategy_reward_standard_deviation: float


class CorpusRunAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_run_aggregate"] = "corpus_run_aggregate"
    source_reports: tuple[str, ...]
    corpus_id: str
    corpus_version: str
    corpus_fingerprint: str
    run_count: int
    neutral_threshold: float
    task_count: int
    winner_changed_task_count: int
    reward_class_changed_task_count: int
    uncertainty_adjusted_reward_class_changed_task_count: int = 0
    uncertain_task_count: int = 0
    path_changed_task_count: int
    strategy_summaries: tuple[AggregateStrategySummary, ...]
    tasks: tuple[AggregateTaskSummary, ...]


def aggregate_corpus_runs(
    reports: tuple[CorpusRunReport, ...],
    *,
    source_reports: tuple[str, ...] = (),
    neutral_threshold: float = 0.01,
) -> CorpusRunAggregate:
    if len(reports) < 2:
        raise ValueError("At least two corpus run reports are required.")
    if source_reports and len(source_reports) != len(reports):
        raise ValueError("source_reports must match the number of reports.")
    if neutral_threshold < 0:
        raise ValueError("neutral_threshold must be zero or greater.")
    _validate_compatible_reports(reports)

    summaries = tuple(
        summarize_corpus_run(report, neutral_threshold=neutral_threshold)
        for report in reports
    )
    strategies = reports[0].config.strategies
    task_ids = tuple(task.task_id for task in reports[0].tasks)
    strategy_summaries = tuple(
        _aggregate_strategy(strategy, reports, summaries)
        for strategy in strategies
    )
    effective_neutral_threshold = summaries[0].neutral_threshold
    task_summaries = tuple(
        _aggregate_task(
            task_id,
            strategies,
            reports,
            summaries,
            effective_neutral_threshold,
        )
        for task_id in task_ids
    )
    first = reports[0]
    return CorpusRunAggregate(
        source_reports=source_reports,
        corpus_id=first.corpus_id,
        corpus_version=first.corpus_version,
        corpus_fingerprint=first.corpus_fingerprint,
        run_count=len(reports),
        neutral_threshold=neutral_threshold,
        task_count=len(task_summaries),
        winner_changed_task_count=sum(task.winner_changed for task in task_summaries),
        reward_class_changed_task_count=sum(
            task.reward_class_changed for task in task_summaries
        ),
        uncertainty_adjusted_reward_class_changed_task_count=sum(
            task.reward_class_changed
            and task.uncertainty_adjusted_reward_class != "uncertain"
            for task in task_summaries
        ),
        uncertain_task_count=sum(
            task.uncertainty_adjusted_reward_class == "uncertain"
            for task in task_summaries
        ),
        path_changed_task_count=sum(
            bool(task.path_changed_strategies) for task in task_summaries
        ),
        strategy_summaries=strategy_summaries,
        tasks=task_summaries,
    )


def render_corpus_aggregate(aggregate: CorpusRunAggregate) -> str:
    lines = [
        (
            f"Corpus: {aggregate.corpus_id} v{aggregate.corpus_version} "
            f"({aggregate.run_count} runs)"
        ),
        (
            f"Stability: {aggregate.winner_changed_task_count} winner changes, "
            f"{aggregate.reward_class_changed_task_count} reward-class changes, "
            f"{aggregate.uncertainty_adjusted_reward_class_changed_task_count} "
            f"adjusted reward-class changes, {aggregate.uncertain_task_count} uncertain, "
            f"{aggregate.path_changed_task_count} path changes"
        ),
        "",
        "Strategy stability:",
        (
            f"{'STRATEGY':<12} {'MEAN REWARD':>11} {'STDDEV':>9} "
            f"{'MIN':>9} {'MAX':>9} {'MEAN WINS':>10} {'BREQ':>7}"
        ),
    ]
    for item in aggregate.strategy_summaries:
        mean_reward = _format_optional(item.mean_cumulative_reward)
        reward_stddev = _format_optional(item.reward_standard_deviation)
        minimum = _format_optional(item.minimum_cumulative_reward)
        maximum = _format_optional(item.maximum_cumulative_reward)
        lines.append(
            f"{item.strategy:<12} {mean_reward:>11} "
            f"{reward_stddev:>9} {minimum:>9} {maximum:>9} "
            f"{item.mean_wins:>10.2f} {item.mean_benchmark_requests:>7.2f}"
        )

    unstable = tuple(
        task
        for task in aggregate.tasks
        if task.winner_changed
        or task.reward_class_changed
        or task.path_changed_strategies
    )
    lines.extend(["", "Unstable tasks:"])
    if not unstable:
        lines.append("  none")
    for task in unstable:
        signals = []
        if task.winner_changed:
            signals.append("winner")
        if task.reward_class_changed:
            signals.append("reward-class")
        if task.path_changed_strategies:
            signals.append(f"paths:{','.join(task.path_changed_strategies)}")
        lines.append(
            f"  {task.task_id}: {','.join(signals)}, "
            f"class={task.uncertainty_adjusted_reward_class}, "
            f"max reward stddev={task.maximum_strategy_reward_standard_deviation:.6f}"
        )
        if task.uncertainty_reason:
            lines.append(f"    {task.uncertainty_reason}")
    return "\n".join(lines)


def write_corpus_aggregate(aggregate: CorpusRunAggregate, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(aggregate.model_dump(mode='json'), indent=2, sort_keys=True)}\n"
    )


def _aggregate_strategy(
    strategy: SearchStrategy,
    reports: tuple[CorpusRunReport, ...],
    summaries,
) -> AggregateStrategySummary:
    run_summaries = tuple(
        next(item for item in report.strategy_summaries if item.strategy == strategy)
        for report in reports
    )
    rewards = tuple(
        item.mean_cumulative_reward
        for item in run_summaries
        if item.mean_cumulative_reward is not None
    )
    wins = tuple(
        next(item for item in summary.strategy_rankings if item.strategy == strategy).wins
        for summary in summaries
    )
    return AggregateStrategySummary(
        strategy=strategy,
        run_count=len(reports),
        mean_cumulative_reward=statistics.mean(rewards) if rewards else None,
        reward_standard_deviation=statistics.pstdev(rewards) if rewards else None,
        minimum_cumulative_reward=min(rewards) if rewards else None,
        maximum_cumulative_reward=max(rewards) if rewards else None,
        mean_wins=statistics.mean(wins),
        win_standard_deviation=statistics.pstdev(wins),
        mean_benchmark_requests=statistics.mean(
            item.benchmark_requests for item in run_summaries
        ),
        mean_elapsed_seconds=statistics.mean(
            item.total_elapsed_seconds for item in run_summaries
        ),
    )


def _aggregate_task(
    task_id: str,
    strategies: tuple[SearchStrategy, ...],
    reports: tuple[CorpusRunReport, ...],
    summaries,
    neutral_threshold: float,
) -> AggregateTaskSummary:
    task_summaries = tuple(
        next(task for task in summary.tasks if task.task_id == task_id)
        for summary in summaries
    )
    winner_sets = tuple(frozenset(task.winning_strategies) for task in task_summaries)
    stable_winners = set(winner_sets[0])
    for winners in winner_sets[1:]:
        stable_winners.intersection_update(winners)

    report_tasks = tuple(
        next(task for task in report.tasks if task.task_id == task_id)
        for report in reports
    )
    path_changed = []
    reward_stddevs = []
    for strategy in strategies:
        results = tuple(
            next(result for result in task.results if result.strategy == strategy)
            for task in report_tasks
        )
        completed = tuple(
            result.search_result
            for result in results
            if result.status == "COMPLETED" and result.search_result is not None
        )
        if len({result.action_ids for result in completed}) > 1:
            path_changed.append(strategy)
        rewards = tuple(result.cumulative_reward for result in completed)
        if rewards:
            reward_stddevs.append(statistics.pstdev(rewards))

    class_counts = Counter(task.reward_class for task in task_summaries)
    best_rewards = tuple(
        task.best_reward
        for task in task_summaries
        if task.best_reward is not None
    )
    uncertainty_band = max(
        neutral_threshold,
        max(reward_stddevs, default=0.0),
    )
    adjusted_class, uncertainty_reason = _uncertainty_adjusted_class(
        class_counts,
        best_rewards,
        neutral_threshold,
        uncertainty_band,
    )
    return AggregateTaskSummary(
        task_id=task_id,
        run_count=len(reports),
        reward_class_counts=dict(sorted(class_counts.items())),
        uncertainty_adjusted_reward_class=adjusted_class,
        uncertainty_band=uncertainty_band,
        uncertainty_reason=uncertainty_reason,
        stable_winning_strategies=tuple(
            strategy for strategy in strategies if strategy in stable_winners
        ),
        winner_changed=len(set(winner_sets)) > 1,
        reward_class_changed=len(class_counts) > 1,
        path_changed_strategies=tuple(path_changed),
        maximum_strategy_reward_standard_deviation=max(reward_stddevs, default=0.0),
    )


def _uncertainty_adjusted_class(
    class_counts: Counter[RewardClass],
    best_rewards: tuple[float, ...],
    neutral_threshold: float,
    uncertainty_band: float,
) -> tuple[AggregateRewardClass, str | None]:
    if not best_rewards or "error" in class_counts:
        return "error", None

    classes = set(class_counts)
    non_error_classes = classes - {"error"}
    if len(non_error_classes) == 1:
        return next(iter(non_error_classes)), None

    if _overlaps_neutral_boundary(
        best_rewards,
        neutral_threshold,
        uncertainty_band,
    ):
        return (
            "uncertain",
            (
                "Observed best rewards overlap the neutral threshold within "
                f"the uncertainty band ({uncertainty_band:.6f})."
            ),
        )
    return (
        "uncertain",
        "Reward classes changed across runs outside the simple uncertainty band.",
    )


def _overlaps_neutral_boundary(
    rewards: tuple[float, ...],
    neutral_threshold: float,
    uncertainty_band: float,
) -> bool:
    for reward in rewards:
        lower = reward - uncertainty_band
        upper = reward + uncertainty_band
        if lower <= neutral_threshold <= upper:
            return True
        if lower <= -neutral_threshold <= upper:
            return True
    return False


def _validate_compatible_reports(reports: tuple[CorpusRunReport, ...]) -> None:
    first = reports[0]
    first_tasks = tuple(
        (task.task_id, task.task_fingerprint)
        for task in first.tasks
    )
    for report in reports[1:]:
        if report.corpus_fingerprint != first.corpus_fingerprint:
            raise ValueError("Corpus reports have different corpus fingerprints.")
        if report.config != first.config:
            raise ValueError("Corpus reports have different run configurations.")
        if report.environment != first.environment:
            raise ValueError("Corpus reports have different runtime environments.")
        tasks = tuple((task.task_id, task.task_fingerprint) for task in report.tasks)
        if tasks != first_tasks:
            raise ValueError("Corpus reports have different task sets.")


def _format_optional(value: float | None) -> str:
    return f"{value:.6f}" if value is not None else "n/a"
