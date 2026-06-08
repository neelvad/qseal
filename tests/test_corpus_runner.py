import json
from pathlib import Path
from shutil import copytree

import pytest
import yaml

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
    QueryBenchmarkResult,
)
from snowprove.corpora import bundled_corpus_path
from snowprove.corpus import CorpusRunConfig, load_task_corpus, run_task_corpus


def test_runs_selected_tasks_and_strategies_with_comparison_summary(
    tmp_path: Path,
) -> None:
    corpus = _tiny_corpus(tmp_path)
    report_path = tmp_path / "run" / "report.json"
    config = CorpusRunConfig(
        task_ids=("distinct-and-not-null",),
        strategies=("fixed_order", "greedy", "beam", "exhaustive"),
        beam_width=2,
        max_nodes=20,
    )

    report = run_task_corpus(
        corpus,
        tmp_path / "run",
        config=config,
        performance_evaluator_factory=_evaluator_factory,
        report_path=report_path,
    )

    assert report.artifact_type == "corpus_search_run"
    assert report.corpus_fingerprint == corpus.fingerprint
    assert len(report.tasks) == 1
    task = report.tasks[0]
    assert task.task_id == "distinct-and-not-null"
    assert [result.strategy for result in task.results] == list(config.strategies)
    assert all(result.status == "COMPLETED" for result in task.results)
    assert all(result.search_result is not None for result in task.results)
    assert all(
        result.verification_calls.requests > 0 for result in task.results
    )
    assert all(result.benchmark_calls.requests > 0 for result in task.results)

    summaries = {summary.strategy: summary for summary in report.strategy_summaries}
    assert summaries["fixed_order"].completed_count == 1
    assert summaries["fixed_order"].error_count == 0
    assert summaries["fixed_order"].mean_cumulative_reward == pytest.approx(
        2 * 0.6931471805599453
    )
    assert summaries["exhaustive"].total_explored_nodes > 0
    assert summaries["fixed_order"].benchmark_requests > 0
    assert summaries["exhaustive"].benchmark_requests > 0
    assert task.verification_executions > 0
    assert task.benchmark_executions > 0
    assert sum(
        result.verification_calls.cache_misses for result in task.results
    ) == task.verification_executions
    assert sum(
        result.benchmark_calls.cache_misses for result in task.results
    ) == task.benchmark_executions

    payload = json.loads(report_path.read_text())
    assert payload["artifact_type"] == "corpus_search_run"
    assert payload["tasks"][0]["task_id"] == "distinct-and-not-null"
    assert payload["strategy_summaries"][0]["strategy"] == "fixed_order"


def test_reuses_strategy_cache_on_repeated_run(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    config = CorpusRunConfig(
        task_ids=("redundant-distinct-users",),
        strategies=("fixed_order",),
    )
    output_dir = tmp_path / "run"

    first = run_task_corpus(
        corpus,
        output_dir,
        config=config,
        performance_evaluator_factory=_evaluator_factory,
    )
    second = run_task_corpus(
        corpus,
        output_dir,
        config=config,
        performance_evaluator_factory=_evaluator_factory,
    )

    first_result = first.tasks[0].results[0]
    second_result = second.tasks[0].results[0]
    assert first_result.verification_calls.cache_misses == 1
    assert first_result.benchmark_calls.cache_misses == 1
    assert second_result.verification_calls.cache_misses == 0
    assert second_result.benchmark_calls.cache_misses == 0
    assert second_result.verification_calls.cache_hits == 1
    assert second_result.benchmark_calls.cache_hits == 1


def test_strategies_share_identical_transition_rewards(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    evaluator = _ChangingPerformanceEvaluator()

    def evaluator_factory(task, database_path, fixture_manifest):
        del task, database_path, fixture_manifest
        return evaluator

    report = run_task_corpus(
        corpus,
        tmp_path / "run",
        config=CorpusRunConfig(
            task_ids=("redundant-distinct-users",),
            strategies=("fixed_order", "random", "greedy", "beam", "exhaustive"),
        ),
        performance_evaluator_factory=evaluator_factory,
    )

    task = report.tasks[0]
    rewards = {
        result.search_result.cumulative_reward
        for result in task.results
        if result.search_result is not None
    }
    assert len(rewards) == 1
    assert next(iter(rewards)) == pytest.approx(0.6931471805599453)
    assert evaluator.calls == 1
    assert task.benchmark_executions == 1
    assert task.verification_executions == 1
    assert task.results[0].benchmark_calls.cache_misses == 1
    assert all(
        result.benchmark_calls.cache_misses == 0
        for result in task.results[1:]
    )
    assert all(
        result.benchmark_calls.cache_hits == 1
        for result in task.results[1:]
    )


def test_state_reward_model_uses_endpoint_tie_policy(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    report = run_task_corpus(
        corpus,
        tmp_path / "run",
        config=CorpusRunConfig(
            task_ids=("distinct-and-not-null",),
            strategies=("greedy",),
            reward_model="state",
            reward_margin=0.05,
        ),
        performance_evaluator_factory=_state_runtime_evaluator_factory,
    )

    strategy_result = report.tasks[0].results[0]
    result = strategy_result.search_result
    assert result is not None, strategy_result.error
    assert result.tie_policy == "endpoint"
    assert result.final_sql == "SELECT user_id\nFROM users;"
    assert result.action_ids == (
        "remove_redundant_distinct::query:distinct",
        "remove_redundant_not_null_filter::predicate:0",
    )


def test_strategy_errors_are_recorded_without_aborting_report(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)

    report = run_task_corpus(
        corpus,
        tmp_path / "run",
        config=CorpusRunConfig(
            task_ids=("redundant-distinct-users",),
            strategies=("fixed_order", "random"),
        ),
        performance_evaluator_factory=_failing_evaluator_factory,
    )

    assert [result.status for result in report.tasks[0].results] == [
        "ERROR",
        "ERROR",
    ]
    assert all(
        "RuntimeError: benchmark failed" in (result.error or "")
        for result in report.tasks[0].results
    )
    assert [summary.error_count for summary in report.strategy_summaries] == [1, 1]


def test_rejects_unknown_task_selection(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)

    with pytest.raises(ValueError, match="Unknown corpus tasks: missing"):
        run_task_corpus(
            corpus,
            tmp_path / "run",
            config=CorpusRunConfig(task_ids=("missing",)),
            performance_evaluator_factory=_evaluator_factory,
        )


def test_run_config_rejects_duplicate_strategies() -> None:
    with pytest.raises(ValueError, match="Duplicate strategies"):
        CorpusRunConfig(strategies=("greedy", "greedy"))


def test_run_config_requires_policy_model_for_policy_strategy() -> None:
    with pytest.raises(ValueError, match="requires a policy model"):
        CorpusRunConfig(strategies=("policy_baseline",))
    with pytest.raises(ValueError, match="requires a policy model"):
        CorpusRunConfig(strategies=("policy_baseline_abstain",))


def test_run_config_can_reload_policy_strategy_report_config() -> None:
    config = CorpusRunConfig(
        strategies=("policy_baseline", "policy_baseline_abstain"),
        policy_model_path="/tmp/policy.json",
    )

    assert config.policy_model is None
    assert config.policy_model_path == "/tmp/policy.json"


def _tiny_corpus(tmp_path: Path):
    copied_root = copytree(
        bundled_corpus_path().parent,
        tmp_path / "tiny-corpus",
    )
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    for fixture in payload["fixtures"]:
        fixture["spec"].update(
            {
                "user_rows": 20,
                "order_rows": 50,
                "event_rows": 30,
            }
        )
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return load_task_corpus(manifest_path)


def _evaluator_factory(task, database_path, fixture_manifest):
    del task, database_path, fixture_manifest
    return _FixedPerformanceEvaluator(speedup=2.0)


def _failing_evaluator_factory(task, database_path, fixture_manifest):
    del task, database_path, fixture_manifest
    return _FailingPerformanceEvaluator()


def _state_runtime_evaluator_factory(task, database_path, fixture_manifest):
    del task, database_path, fixture_manifest
    return _StateRuntimePerformanceEvaluator(
        {
            "SELECT DISTINCT user_id\nFROM users\nWHERE user_id IS NOT NULL;": 2.0,
            "SELECT user_id\nFROM users\nWHERE user_id IS NOT NULL;": 1.0,
            "SELECT DISTINCT user_id\nFROM users;": 1.5,
            "SELECT user_id\nFROM users;": 0.98,
        }
    )


class _FixedPerformanceEvaluator:
    def __init__(self, speedup: float) -> None:
        self.speedup = speedup

    def cache_context(self):
        return {"evaluator": "fixed", "speedup": self.speedup}

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        environment = BenchmarkEnvironment(
            duckdb_version="test",
            python_version="test",
            platform="test",
            database_path="fixture.duckdb",
            threads=1,
            warmups=0,
            repetitions=1,
            timeout_seconds=1,
        )
        return BenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            original=QueryBenchmark(
                status=BenchmarkStatus.COMPLETED,
                sql=original_sql,
                timings_ms=(self.speedup,),
                median_ms=self.speedup,
                row_count=1,
            ),
            rewritten=QueryBenchmark(
                status=BenchmarkStatus.COMPLETED,
                sql=rewritten_sql,
                timings_ms=(1.0,),
                median_ms=1.0,
                row_count=1,
            ),
            environment=environment,
            speedup=self.speedup,
            row_counts_match=True,
        )


class _FailingPerformanceEvaluator:
    def cache_context(self):
        return {"evaluator": "failing"}

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        del original_sql, rewritten_sql
        raise RuntimeError("benchmark failed")


class _StateRuntimePerformanceEvaluator:
    supports_query_benchmark = True
    supports_interleaved_query_benchmark = True

    def __init__(self, runtimes: dict[str, float]) -> None:
        self.runtimes = runtimes

    def cache_context(self):
        return {"evaluator": "state-runtime", "runtimes": self.runtimes}

    def evaluate_query_pair(
        self,
        original_sql: str,
        rewritten_sql: str,
    ) -> tuple[QueryBenchmarkResult, QueryBenchmarkResult]:
        return self._result(original_sql), self._result(rewritten_sql)

    def _result(self, sql: str) -> QueryBenchmarkResult:
        runtime = self.runtimes[sql.strip()]
        environment = BenchmarkEnvironment(
            duckdb_version="test",
            python_version="test",
            platform="test",
            database_path="fixture.duckdb",
            threads=1,
            warmups=0,
            repetitions=1,
            timeout_seconds=1,
        )
        return QueryBenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            query=QueryBenchmark(
                status=BenchmarkStatus.COMPLETED,
                sql=sql.strip(),
                timings_ms=(runtime,),
                median_ms=runtime,
                row_count=1,
            ),
            environment=environment,
        )


class _ChangingPerformanceEvaluator(_FixedPerformanceEvaluator):
    def __init__(self) -> None:
        super().__init__(speedup=2.0)
        self.calls = 0

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        self.calls += 1
        self.speedup = float(self.calls + 1)
        return super().evaluate(original_sql, rewritten_sql)
