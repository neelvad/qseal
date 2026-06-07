import math

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)
from snowprove.cache import JsonFileCache, content_hash
from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.environment import (
    CachedPerformanceEvaluator,
    CachedVerifier,
    EnvironmentTask,
    JsonlTrajectoryRecorder,
    RewriteEnvironment,
    load_trajectory,
)
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.model import VerificationResult


def _task() -> EnvironmentTask:
    return EnvironmentTask(
        task_id="cached-distinct",
        sql="SELECT DISTINCT user_id FROM users",
        constraints=ConstraintCatalog(
            tables={"users": TableConstraints(unique=[("user_id",)])}
        ),
        metadata={"fixture_fingerprint": "fixture-1"},
    )


def test_content_hash_is_stable_across_mapping_order() -> None:
    assert content_hash({"a": 1, "b": {"x": 2, "y": 3}}) == content_hash(
        {"b": {"y": 3, "x": 2}, "a": 1}
    )


def test_cached_verifier_avoids_repeated_delegate_calls(tmp_path) -> None:
    delegate = _CountingVerifier()
    verifier = CachedVerifier(
        delegate,
        JsonFileCache(tmp_path / "cache"),
        namespace="test-verifier-v1",
    )
    constraints = _task().constraints

    first = verifier.verify(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        constraints,
        dialect="duckdb",
    )
    second = verifier.verify(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        constraints,
        dialect="duckdb",
    )

    assert first == second
    assert delegate.calls == 1
    assert verifier.misses == 1
    assert verifier.hits == 1
    assert len(tuple((tmp_path / "cache" / "verification").rglob("*.json"))) == 1


def test_cached_benchmark_avoids_repeated_delegate_calls(tmp_path) -> None:
    delegate = _CountingPerformanceEvaluator(speedup=2)
    evaluator = CachedPerformanceEvaluator(
        delegate,
        JsonFileCache(tmp_path / "cache"),
        namespace="test-benchmark-v1",
        context={"fixture_fingerprint": "fixture-1"},
    )

    first = evaluator.evaluate("SELECT DISTINCT user_id FROM users", "SELECT user_id FROM users")
    second = evaluator.evaluate("SELECT DISTINCT user_id FROM users", "SELECT user_id FROM users")

    assert first == second
    assert delegate.calls == 1
    assert evaluator.misses == 1
    assert evaluator.hits == 1
    assert len(tuple((tmp_path / "cache" / "benchmark").rglob("*.json"))) == 1


def test_environment_reuses_cached_oracles_across_episodes(tmp_path) -> None:
    verifier_delegate = _CountingVerifier()
    benchmark_delegate = _CountingPerformanceEvaluator(speedup=2)
    cache = JsonFileCache(tmp_path / "cache")
    verifier = CachedVerifier(
        verifier_delegate,
        cache,
        namespace="test-verifier-v1",
    )
    evaluator = CachedPerformanceEvaluator(
        benchmark_delegate,
        cache,
        namespace="test-benchmark-v1",
        context={"fixture_fingerprint": "fixture-1"},
    )
    environment = RewriteEnvironment(
        verifier=verifier,
        performance_evaluator=evaluator,
    )

    for _ in range(2):
        observation = environment.reset(_task())
        transition = environment.step(observation.actions[0].action_id)
        assert transition.reward == math.log(2)

    assert verifier_delegate.calls == 1
    assert benchmark_delegate.calls == 1
    assert verifier.hits == 1
    assert evaluator.hits == 1


def test_jsonl_recorder_writes_auditable_transitions(tmp_path) -> None:
    trajectory_path = tmp_path / "trajectories.jsonl"
    environment = RewriteEnvironment(
        trajectory_recorder=JsonlTrajectoryRecorder(trajectory_path)
    )
    task = _task()

    for _ in range(2):
        observation = environment.reset(task)
        environment.step(observation.actions[0].action_id)

    records = load_trajectory(trajectory_path)
    assert len(records) == 2
    assert all(record.task_id == task.task_id for record in records)
    assert all(record.step_index == 0 for record in records)
    assert all(
        record.action_id == "remove_redundant_distinct::query:distinct"
        for record in records
    )
    assert all(record.state_sql == task.sql for record in records)
    assert all(record.proposed_sql == "SELECT user_id\nFROM users;" for record in records)
    assert all(record.next_state_sql == "SELECT user_id\nFROM users;" for record in records)
    assert all(record.terminated is True for record in records)
    assert all(record.verification["status"] == "PROVEN_EQUIVALENT" for record in records)
    assert all(record.task_metadata == task.metadata for record in records)


def test_jsonl_recorder_preserves_rejected_proposal_and_unchanged_state(tmp_path) -> None:
    trajectory_path = tmp_path / "rejected.jsonl"
    environment = RewriteEnvironment(
        verifier=_RejectingVerifier(),
        trajectory_recorder=JsonlTrajectoryRecorder(trajectory_path),
    )
    task = _task()
    observation = environment.reset(task)

    environment.step(observation.actions[0].action_id)

    record = load_trajectory(trajectory_path)[0]
    assert record.state_sql == task.sql
    assert record.proposed_sql == "SELECT user_id\nFROM users;"
    assert record.next_state_sql == task.sql
    assert record.verification["status"] == "NOT_EQUIVALENT"
    assert record.terminated is True


class _CountingVerifier:
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, original_sql, rewritten_sql, constraints, dialect="duckdb"):
        del constraints, dialect
        self.calls += 1
        return VerificationResult(
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=original_sql,
            rewritten_sql=rewritten_sql,
            rule_name=self.name,
        )


class _RejectingVerifier:
    name = "rejecting"

    def verify(self, original_sql, rewritten_sql, constraints, dialect="duckdb"):
        del constraints, dialect
        return VerificationResult(
            status=VerificationStatus.NOT_EQUIVALENT,
            original_sql=original_sql,
            rewritten_sql=rewritten_sql,
            rule_name=self.name,
        )


class _CountingPerformanceEvaluator:
    def __init__(self, speedup: float) -> None:
        self.speedup = speedup
        self.calls = 0

    def cache_context(self):
        return {"evaluator": "counting", "speedup": self.speedup}

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        self.calls += 1
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
