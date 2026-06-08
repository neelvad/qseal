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
    load_corpus_run_report,
    render_corpus_summary,
    summarize_corpus_run,
)
from snowprove.search import SearchResult


def test_summarizes_strategy_rankings_and_task_disagreement() -> None:
    summary = summarize_corpus_run(_report(), source_report="run.json")

    assert summary.artifact_type == "corpus_search_summary"
    assert summary.task_count == 3
    assert summary.completed_task_count == 3
    assert summary.error_task_count == 1
    assert summary.positive_task_count == 1
    assert summary.neutral_task_count == 1
    assert summary.negative_task_count == 1
    assert summary.path_disagreement_count == 1
    assert summary.reward_disagreement_count == 1
    assert summary.trivial_task_count == 1

    assert [ranking.strategy for ranking in summary.strategy_rankings] == [
        "greedy",
        "fixed_order",
    ]
    assert [ranking.wins for ranking in summary.strategy_rankings] == [3, 1]
    assert summary.strategy_rankings[0].mean_explored_nodes == pytest.approx(2)
    assert summary.strategy_rankings[0].benchmark_requests == 6

    tasks = {task.task_id: task for task in summary.tasks}
    assert tasks["different-paths"].winning_strategies == ("greedy",)
    assert tasks["different-paths"].path_disagreement is True
    assert tasks["different-paths"].reward_disagreement is True
    assert tasks["trivial"].trivial is True
    assert tasks["partial-error"].reward_class == "negative"
    assert tasks["partial-error"].error_strategies == ("fixed_order",)

    rendered = render_corpus_summary(summary)
    assert "Strategy ranking:" in rendered
    assert "different-paths: positive, winners=greedy" in rendered
    assert "errors:fixed_order" in rendered


def test_neutral_threshold_controls_ties_and_disagreement() -> None:
    summary = summarize_corpus_run(_report(), neutral_threshold=0.2)
    task = summary.tasks[0]

    assert task.winning_strategies == ("fixed_order", "greedy")
    assert task.reward_disagreement is False


def test_run_reward_margin_sets_minimum_summary_threshold() -> None:
    report = _report().model_copy(
        update={
            "config": CorpusRunConfig(
                strategies=("fixed_order", "greedy"),
                reward_margin=0.2,
            )
        }
    )

    summary = summarize_corpus_run(report, neutral_threshold=0.01)

    assert summary.neutral_threshold == 0.2
    assert summary.reward_margin == 0.2
    assert summary.tasks[0].winning_strategies == ("fixed_order", "greedy")


def test_single_strategy_task_is_not_classified_as_trivial() -> None:
    report = _report().model_copy(
        update={
            "tasks": (
                _task(
                    "single",
                    _completed("fixed_order", 0.0, (), explored_nodes=0),
                ),
            ),
            "strategy_summaries": (_report().strategy_summaries[0],),
            "config": CorpusRunConfig(strategies=("fixed_order",)),
        }
    )

    summary = summarize_corpus_run(report)

    assert summary.tasks[0].trivial is False


def test_rejects_negative_neutral_threshold() -> None:
    with pytest.raises(ValueError, match="zero or greater"):
        summarize_corpus_run(_report(), neutral_threshold=-0.1)


def test_load_rejects_non_corpus_report(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"artifact_type": "verification"}))

    with pytest.raises(ValueError, match="Could not load corpus run report"):
        load_corpus_run_report(path)


def test_corpus_summarize_cli_writes_json_artifact(tmp_path: Path) -> None:
    report_path = tmp_path / "run.json"
    summary_path = tmp_path / "summary.json"
    report_path.write_text(_report().model_dump_json(indent=2))

    result = CliRunner().invoke(
        main,
        [
            "corpus",
            "summarize",
            str(report_path),
            "--summary-file",
            str(summary_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(summary_path.read_text())
    assert payload["artifact_type"] == "corpus_search_summary"
    assert payload["source_report"] == str(report_path)
    assert payload["strategy_rankings"][0]["strategy"] == "greedy"
    assert "Summary file written:" in result.output


def _report() -> CorpusRunReport:
    tasks = (
        _task(
            "different-paths",
            _completed("fixed_order", 0.2, ("first",), explored_nodes=1),
            _completed("greedy", 0.3, ("second",), explored_nodes=2),
        ),
        _task(
            "trivial",
            _completed("fixed_order", 0.0, (), explored_nodes=0),
            _completed("greedy", 0.0, (), explored_nodes=2),
        ),
        _task(
            "partial-error",
            _error("fixed_order"),
            _completed("greedy", -0.2, ("harmful",), explored_nodes=2),
        ),
    )
    return CorpusRunReport(
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
        corpus_id="test-corpus",
        corpus_version="1",
        corpus_fingerprint="abc123",
        config=CorpusRunConfig(strategies=("fixed_order", "greedy")),
        environment=CorpusRunEnvironment(
            python_version="test",
            duckdb_version="test",
            platform="test",
        ),
        tasks=tasks,
        strategy_summaries=(
            StrategyRunSummary(
                strategy="fixed_order",
                run_count=3,
                completed_count=2,
                error_count=1,
                mean_cumulative_reward=0.1,
                total_explored_nodes=1,
                verification_requests=2,
                benchmark_requests=2,
                verification_cache_misses=2,
                benchmark_cache_misses=2,
                total_elapsed_seconds=0.3,
            ),
            StrategyRunSummary(
                strategy="greedy",
                run_count=3,
                completed_count=3,
                error_count=0,
                mean_cumulative_reward=1 / 30,
                total_explored_nodes=6,
                verification_requests=6,
                benchmark_requests=6,
                verification_cache_misses=6,
                benchmark_cache_misses=6,
                total_elapsed_seconds=0.6,
            ),
        ),
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
    *,
    explored_nodes: int,
) -> StrategyRunResult:
    return StrategyRunResult(
        strategy=strategy,
        status="COMPLETED",
        elapsed_seconds=0.1,
        verification_calls=_calls(1),
        benchmark_calls=_calls(1),
        search_result=SearchResult(
            strategy=strategy,
            task_id="task",
            initial_sql="SELECT 1",
            final_sql="SELECT 1",
            action_ids=action_ids,
            cumulative_reward=reward,
            terminated=True,
            truncated=False,
            explored_nodes=explored_nodes,
        ),
    )


def _error(strategy) -> StrategyRunResult:
    return StrategyRunResult(
        strategy=strategy,
        status="ERROR",
        elapsed_seconds=0.1,
        verification_calls=_calls(0),
        benchmark_calls=_calls(0),
        error="RuntimeError: failed",
    )


def _calls(misses: int) -> OracleCallMetrics:
    return OracleCallMetrics(
        requests=misses,
        cache_hits=0,
        cache_misses=misses,
    )
