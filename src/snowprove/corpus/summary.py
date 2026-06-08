from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from snowprove.corpus.runner import CorpusRunReport, SearchStrategy

RewardClass = Literal["positive", "neutral", "negative", "error"]


class TaskSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture_id: str
    reward_class: RewardClass
    completed_strategies: tuple[SearchStrategy, ...] = Field(default_factory=tuple)
    error_strategies: tuple[SearchStrategy, ...] = Field(default_factory=tuple)
    winning_strategies: tuple[SearchStrategy, ...] = Field(default_factory=tuple)
    best_reward: float | None = None
    reward_spread: float | None = None
    unique_path_count: int = 0
    path_disagreement: bool = False
    reward_disagreement: bool = False
    trivial: bool = False


class RankedStrategySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int
    strategy: SearchStrategy
    wins: int
    completed_count: int
    error_count: int
    mean_cumulative_reward: float | None
    mean_explored_nodes: float | None
    verification_cache_misses: int
    benchmark_cache_misses: int
    total_elapsed_seconds: float


class CorpusSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_search_summary"] = "corpus_search_summary"
    source_report: str
    corpus_id: str
    corpus_version: str
    corpus_fingerprint: str
    neutral_threshold: float
    task_count: int
    completed_task_count: int
    error_task_count: int
    positive_task_count: int
    neutral_task_count: int
    negative_task_count: int
    path_disagreement_count: int
    reward_disagreement_count: int
    trivial_task_count: int
    strategy_rankings: tuple[RankedStrategySummary, ...]
    tasks: tuple[TaskSummary, ...]


def load_corpus_run_report(path: Path) -> CorpusRunReport:
    try:
        return CorpusRunReport.model_validate_json(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"Could not load corpus run report {path}: {error}") from error


def summarize_corpus_run(
    report: CorpusRunReport,
    *,
    source_report: str = "",
    neutral_threshold: float = 0.01,
) -> CorpusSummary:
    if neutral_threshold < 0:
        raise ValueError("neutral_threshold must be zero or greater.")

    tasks = tuple(
        _summarize_task(task, neutral_threshold)
        for task in report.tasks
    )
    wins = {
        strategy: sum(
            strategy in task.winning_strategies
            for task in tasks
        )
        for strategy in report.config.strategies
    }
    rankings = sorted(
        (
            RankedStrategySummary(
                rank=0,
                strategy=summary.strategy,
                wins=wins[summary.strategy],
                completed_count=summary.completed_count,
                error_count=summary.error_count,
                mean_cumulative_reward=summary.mean_cumulative_reward,
                mean_explored_nodes=(
                    summary.total_explored_nodes / summary.completed_count
                    if summary.completed_count
                    else None
                ),
                verification_cache_misses=summary.verification_cache_misses,
                benchmark_cache_misses=summary.benchmark_cache_misses,
                total_elapsed_seconds=summary.total_elapsed_seconds,
            )
            for summary in report.strategy_summaries
        ),
        key=lambda item: (
            -item.wins,
            -(
                item.mean_cumulative_reward
                if item.mean_cumulative_reward is not None
                else float("-inf")
            ),
            item.benchmark_cache_misses,
            item.strategy,
        ),
    )
    ranked = tuple(
        item.model_copy(update={"rank": index})
        for index, item in enumerate(rankings, start=1)
    )
    return CorpusSummary(
        source_report=source_report,
        corpus_id=report.corpus_id,
        corpus_version=report.corpus_version,
        corpus_fingerprint=report.corpus_fingerprint,
        neutral_threshold=neutral_threshold,
        task_count=len(tasks),
        completed_task_count=sum(bool(task.completed_strategies) for task in tasks),
        error_task_count=sum(bool(task.error_strategies) for task in tasks),
        positive_task_count=sum(task.reward_class == "positive" for task in tasks),
        neutral_task_count=sum(task.reward_class == "neutral" for task in tasks),
        negative_task_count=sum(task.reward_class == "negative" for task in tasks),
        path_disagreement_count=sum(task.path_disagreement for task in tasks),
        reward_disagreement_count=sum(task.reward_disagreement for task in tasks),
        trivial_task_count=sum(task.trivial for task in tasks),
        strategy_rankings=ranked,
        tasks=tasks,
    )


def render_corpus_summary(summary: CorpusSummary) -> str:
    lines = [
        f"Corpus: {summary.corpus_id} v{summary.corpus_version}",
        (
            f"Tasks: {summary.task_count} total, "
            f"{summary.completed_task_count} completed, "
            f"{summary.error_task_count} with errors"
        ),
        (
            f"Rewards: {summary.positive_task_count} positive, "
            f"{summary.neutral_task_count} neutral, "
            f"{summary.negative_task_count} negative"
        ),
        (
            f"Signals: {summary.path_disagreement_count} path disagreements, "
            f"{summary.reward_disagreement_count} reward disagreements, "
            f"{summary.trivial_task_count} trivial tasks"
        ),
        "",
        "Strategy ranking:",
        (
            f"{'RANK':>4} {'STRATEGY':<12} {'WINS':>4} {'MEAN REWARD':>11} "
            f"{'MEAN NODES':>10} {'VERIFY':>7} {'BENCH':>5} {'SECONDS':>8}"
        ),
    ]
    for item in summary.strategy_rankings:
        reward = (
            f"{item.mean_cumulative_reward:.6f}"
            if item.mean_cumulative_reward is not None
            else "n/a"
        )
        nodes = (
            f"{item.mean_explored_nodes:.2f}"
            if item.mean_explored_nodes is not None
            else "n/a"
        )
        lines.append(
            f"{item.rank:>4} {item.strategy:<12} {item.wins:>4} "
            f"{reward:>11} {nodes:>10} "
            f"{item.verification_cache_misses:>7} "
            f"{item.benchmark_cache_misses:>5} "
            f"{item.total_elapsed_seconds:>8.3f}"
        )

    notable = tuple(
        task
        for task in summary.tasks
        if task.path_disagreement
        or task.reward_disagreement
        or task.error_strategies
    )
    lines.extend(["", "Notable tasks:"])
    if not notable:
        lines.append("  none")
    for task in notable:
        winners = ", ".join(task.winning_strategies) or "none"
        signals = []
        if task.path_disagreement:
            signals.append("path")
        if task.reward_disagreement:
            signals.append("reward")
        if task.error_strategies:
            signals.append(f"errors:{','.join(task.error_strategies)}")
        lines.append(
            f"  {task.task_id}: {task.reward_class}, winners={winners}, "
            f"signals={','.join(signals)}"
        )
    return "\n".join(lines)


def write_corpus_summary(summary: CorpusSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(summary.model_dump(mode='json'), indent=2, sort_keys=True)}\n"
    )


def _summarize_task(task, neutral_threshold: float) -> TaskSummary:
    completed = tuple(
        result
        for result in task.results
        if result.status == "COMPLETED" and result.search_result is not None
    )
    errors = tuple(
        result.strategy
        for result in task.results
        if result.status == "ERROR"
    )
    if not completed:
        return TaskSummary(
            task_id=task.task_id,
            fixture_id=task.fixture_id,
            reward_class="error",
            error_strategies=errors,
        )

    rewards = tuple(
        result.search_result.cumulative_reward
        for result in completed
        if result.search_result is not None
    )
    best_reward = max(rewards)
    worst_reward = min(rewards)
    winners = tuple(
        result.strategy
        for result in completed
        if result.search_result is not None
        and best_reward - result.search_result.cumulative_reward <= neutral_threshold
    )
    paths = {
        result.search_result.action_ids
        for result in completed
        if result.search_result is not None
    }
    reward_spread = best_reward - worst_reward
    if best_reward > neutral_threshold:
        reward_class: RewardClass = "positive"
    elif best_reward < -neutral_threshold:
        reward_class = "negative"
    else:
        reward_class = "neutral"

    return TaskSummary(
        task_id=task.task_id,
        fixture_id=task.fixture_id,
        reward_class=reward_class,
        completed_strategies=tuple(result.strategy for result in completed),
        error_strategies=errors,
        winning_strategies=winners,
        best_reward=best_reward,
        reward_spread=reward_spread,
        unique_path_count=len(paths),
        path_disagreement=len(paths) > 1,
        reward_disagreement=reward_spread > neutral_threshold,
        trivial=(
            len(completed) > 1
            and len(paths) == 1
            and reward_spread <= neutral_threshold
            and not errors
        ),
    )
