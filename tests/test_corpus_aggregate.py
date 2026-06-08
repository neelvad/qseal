import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from snowprove.cli import main
from snowprove.corpus import (
    CorpusRunConfig,
    CorpusRunEnvironment,
    CorpusRunReport,
    CorpusTaskRun,
    OracleCallMetrics,
    StrategyRunResult,
    StrategyRunSummary,
    aggregate_corpus_runs,
    render_corpus_aggregate,
)
from snowprove.search import SearchResult


def test_aggregates_reward_and_task_stability() -> None:
    first, second = _reports()

    aggregate = aggregate_corpus_runs(
        (first, second),
        source_reports=("first.json", "second.json"),
    )

    assert aggregate.artifact_type == "corpus_run_aggregate"
    assert aggregate.run_count == 2
    assert aggregate.task_count == 2
    assert aggregate.winner_changed_task_count == 1
    assert aggregate.reward_class_changed_task_count == 1
    assert aggregate.uncertain_task_count == 1
    assert aggregate.uncertainty_adjusted_reward_class_changed_task_count == 0
    assert aggregate.path_changed_task_count == 1

    strategies = {item.strategy: item for item in aggregate.strategy_summaries}
    assert strategies["fixed_order"].mean_cumulative_reward == pytest.approx(0.11)
    assert strategies["fixed_order"].reward_standard_deviation == pytest.approx(0.01)
    assert strategies["greedy"].mean_benchmark_requests == 3

    tasks = {task.task_id: task for task in aggregate.tasks}
    assert tasks["winner-change"].winner_changed is True
    assert tasks["winner-change"].stable_winning_strategies == ()
    assert tasks["class-and-path-change"].reward_class_changed is True
    assert tasks["class-and-path-change"].path_changed_strategies == ("greedy",)
    assert tasks["class-and-path-change"].reward_class_counts == {
        "neutral": 1,
        "positive": 1,
    }
    assert (
        tasks["class-and-path-change"].uncertainty_adjusted_reward_class
        == "uncertain"
    )
    assert tasks["class-and-path-change"].uncertainty_reason is not None

    rendered = render_corpus_aggregate(aggregate)
    assert "Corpus: test-corpus v1 (2 runs)" in rendered
    assert "0 adjusted reward-class changes" in rendered
    assert "1 uncertain" in rendered
    assert "winner-change: winner" in rendered
    assert "paths:greedy" in rendered
    assert "class=uncertain" in rendered


def test_rejects_incompatible_reports() -> None:
    first, second = _reports()
    changed = second.model_copy(update={"corpus_fingerprint": "different"})

    with pytest.raises(ValueError, match="different corpus fingerprints"):
        aggregate_corpus_runs((first, changed))


def test_requires_two_reports() -> None:
    first, _ = _reports()

    with pytest.raises(ValueError, match="At least two"):
        aggregate_corpus_runs((first,))


def test_source_report_count_must_match() -> None:
    first, second = _reports()

    with pytest.raises(ValueError, match="source_reports must match"):
        aggregate_corpus_runs(
            (first, second),
            source_reports=("first.json",),
        )


def test_corpus_aggregate_cli_writes_artifact(tmp_path: Path) -> None:
    first, second = _reports()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    output_path = tmp_path / "aggregate.json"
    first_path.write_text(first.model_dump_json(indent=2))
    second_path.write_text(second.model_dump_json(indent=2))

    result = CliRunner().invoke(
        main,
        [
            "corpus",
            "aggregate",
            str(first_path),
            str(second_path),
            "--aggregate-file",
            str(output_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text())
    assert payload["artifact_type"] == "corpus_run_aggregate"
    assert payload["run_count"] == 2
    assert payload["source_reports"] == [str(first_path), str(second_path)]
    assert "Aggregate file written:" in result.output


def _reports() -> tuple[CorpusRunReport, CorpusRunReport]:
    first = _report(
        (
            _task(
                "winner-change",
                _completed("fixed_order", 0.1, ("fixed",)),
                _completed("greedy", 0.2, ("greedy",)),
            ),
            _task(
                "class-and-path-change",
                _completed("fixed_order", 0.1, ("same",)),
                _completed("greedy", 0.1, ("same",)),
            ),
        )
    )
    second = _report(
        (
            _task(
                "winner-change",
                _completed("fixed_order", 0.25, ("fixed",)),
                _completed("greedy", 0.2, ("greedy",)),
            ),
            _task(
                "class-and-path-change",
                _completed("fixed_order", -0.01, ("same",)),
                _completed("greedy", -0.01, ("changed",)),
            ),
        )
    )
    return first, second


def _report(tasks: tuple[CorpusTaskRun, ...]) -> CorpusRunReport:
    strategies = ("fixed_order", "greedy")
    summaries = []
    for strategy in strategies:
        results = [
            next(result for result in task.results if result.strategy == strategy)
            for task in tasks
        ]
        rewards = [
            result.search_result.cumulative_reward
            for result in results
            if result.search_result is not None
        ]
        summaries.append(
            StrategyRunSummary(
                strategy=strategy,
                run_count=len(results),
                completed_count=len(results),
                error_count=0,
                mean_cumulative_reward=sum(rewards) / len(rewards),
                total_explored_nodes=len(results),
                verification_requests=len(results),
                benchmark_requests=(2 if strategy == "fixed_order" else 3),
                verification_cache_misses=0,
                benchmark_cache_misses=0,
                total_elapsed_seconds=0.1,
            )
        )
    return CorpusRunReport(
        generated_at=datetime(2026, 6, 8, tzinfo=UTC),
        corpus_id="test-corpus",
        corpus_version="1",
        corpus_fingerprint="fingerprint",
        config=CorpusRunConfig(strategies=strategies),
        environment=CorpusRunEnvironment(
            python_version="test",
            duckdb_version="test",
            platform="test",
        ),
        tasks=tasks,
        strategy_summaries=tuple(summaries),
    )


def _task(task_id: str, *results: StrategyRunResult) -> CorpusTaskRun:
    return CorpusTaskRun(
        task_id=task_id,
        task_fingerprint=f"{task_id}-fingerprint",
        fixture_id="fixture",
        enabled_rules=("rule",),
        tags=(),
        results=results,
    )


def _completed(
    strategy,
    reward: float,
    action_ids: tuple[str, ...],
) -> StrategyRunResult:
    return StrategyRunResult(
        strategy=strategy,
        status="COMPLETED",
        elapsed_seconds=0.1,
        verification_calls=_calls(),
        benchmark_calls=_calls(),
        search_result=SearchResult(
            strategy=strategy,
            task_id="task",
            initial_sql="SELECT 1",
            final_sql="SELECT 1",
            action_ids=action_ids,
            cumulative_reward=reward,
            terminated=True,
            truncated=False,
            explored_nodes=1,
        ),
    )


def _calls() -> OracleCallMetrics:
    return OracleCallMetrics(requests=1, cache_hits=1, cache_misses=0)
